"""Parsery HTML stron IBO — wyłącznie stdlib (html.parser), zero zależności.

Oparte na realnej strukturze z 2026-09:
- Historia odczytów: tabela z id kończącym się na 'GridView_DXMainTable',
  wiersze <tr> z id zawierającym 'DXDataRow', kolumny Data | Odczyt | Status.
- Niezapłacone płatności:
  * tabela z id zawierającym 'gvNaleznosci_DXMainTable':
    [checkbox] | Nr dokumentu | Termin płatności | Kwota | Pozostało do zapłaty
  * panel podsumowania: span'y o id kończącym się na _XSaldo, _XNadplata,
    _XSaldoOpis ('(niedopłata)' / '(nadpłata)').
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from html.parser import HTMLParser
from typing import Any

_LOGGER = logging.getLogger(__name__)

DATE_FMT = "%d.%m.%Y"


class _PageParser(HTMLParser):
    """Zbiera: tabele (id -> wiersze (row_id, [teksty komórek])),
    span'y [(klasy, tekst)] i [(id, tekst)], id wszystkich elementów."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: dict[str | None, list[tuple[str, list[str]]]] = {}
        self.table_stack: list[str | None] = []
        self.row_stack: list[tuple[str, list[str]]] = []
        self.cell_stack: list[list[str]] = []
        self.spans: list[tuple[str, str]] = []  # (klasy, tekst)
        self.spans_by_id: dict[str, str] = {}
        self.ids: set[str] = set()
        self._span_stack: list[tuple[str | None, str, list[str]]] = []

    # -- pomocnicze ---------------------------------------------------------
    def _open_span(self, attrs: dict) -> None:
        self._span_stack.append(
            (attrs.get("id"), attrs.get("class") or "", [])
        )

    def _close_span(self) -> None:
        if not self._span_stack:
            return
        sid, cls, parts = self._span_stack.pop()
        text = "".join(parts).strip()
        if cls:
            self.spans.append((cls, text))
        if sid:
            self.spans_by_id[sid] = text

    # -- HTMLParser ---------------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "table":
            tid = a.get("id")
            self.table_stack.append(tid)
            self.tables.setdefault(tid, [])
        elif tag == "tr" and self.table_stack:
            self.row_stack.append((a.get("id") or "", []))
        elif tag == "td":
            self.cell_stack.append([])
        elif tag == "span":
            self._open_span(a)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "span":
            self._open_span(a)
            self._close_span()

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self.cell_stack:
            text = "".join(self.cell_stack.pop()).strip()
            if self.row_stack:
                self.row_stack[-1][1].append(text)
        elif tag == "tr" and self.row_stack:
            row_id, cells = self.row_stack.pop()
            if self.table_stack:
                self.tables[self.table_stack[-1]].append((row_id, cells))
        elif tag == "table" and self.table_stack:
            self.table_stack.pop()
        elif tag == "span":
            self._close_span()

    def handle_data(self, data: str) -> None:
        if self.cell_stack:
            self.cell_stack[-1].append(data)
        if self._span_stack:
            self._span_stack[-1][2].append(data)


def _parse_html(html: str) -> _PageParser:
    p = _PageParser()
    try:
        p.feed(html)
        p.close()
    except Exception as err:  # zniekształcony HTML nie powinien wywalać HA
        raise IboParseError(f"Nie udało się sparsować HTML: {err}") from err
    return p


def _parse_amount(text: str) -> float | None:
    """'348,15' / '348,15 zł' / '348.15' -> 348.15"""
    cleaned = text.replace("\xa0", " ").strip().lower().removesuffix("zł").strip()
    cleaned = cleaned.replace(" ", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_date(text: str) -> date | None:
    try:
        return datetime.strptime(text.strip(), DATE_FMT).date()
    except ValueError:
        return None


def _find_table(page: _PageParser, id_contains: str) -> list[tuple[str, list[str]]] | None:
    for tid, rows in page.tables.items():
        if tid and id_contains in tid:
            return rows
    return None


def _data_rows(rows: list[tuple[str, list[str]]]) -> list[list[str]]:
    return [cells for row_id, cells in rows if "DXDataRow" in row_id]


def parse_readings(html: str) -> dict[str, Any]:
    """Historia odczytów -> {'readings': [{date, value, type}], ...}."""
    page = _parse_html(html)
    rows = _find_table(page, "GridView_DXMainTable")
    if rows is None:
        raise IboParseError("Nie znaleziono tabeli historii odczytów")

    readings: list[dict[str, Any]] = []
    for cells in _data_rows(rows):
        if len(cells) < 3:
            continue
        d = _parse_date(cells[0])
        if d is None:
            continue
        value = _parse_amount(cells[1])
        if value is None:
            _LOGGER.debug("Pomijam wiersz odczytu: %s", cells)
            continue
        readings.append(
            {"date": d.isoformat(), "value": value, "type": cells[2]}
        )

    if not readings:
        raise IboParseError("Tabela historii odczytów bez wierszy danych")

    last = readings[0]  # tabela posortowana od najnowszego
    previous = readings[1] if len(readings) > 1 else None
    usage = round(last["value"] - previous["value"], 2) if previous else None
    return {
        "readings": readings,
        "last_reading_date": last["date"],
        "last_reading_value": last["value"],
        "last_reading_type": last["type"],
        "previous_reading_value": previous["value"] if previous else None,
        "usage_since_previous": usage,
    }


def parse_payments(html: str) -> dict[str, Any]:
    """Niezapłacone płatności -> saldo, nadpłata, lista dokumentów."""
    page = _parse_html(html)

    saldo_el = next(
        (t for sid, t in page.spans_by_id.items() if sid.endswith("_XSaldo")),
        None,
    )
    if saldo_el is None:
        raise IboParseError("Nie znaleziono panelu salda (XSaldo)")
    nadplata_el = next(
        (t for sid, t in page.spans_by_id.items() if sid.endswith("_XNadplata")),
        None,
    )
    opis_el = next(
        (t for sid, t in page.spans_by_id.items() if sid.endswith("_XSaldoOpis")),
        None,
    )

    saldo = _parse_amount(saldo_el)
    nadplata = _parse_amount(nadplata_el) if nadplata_el else None
    opis = opis_el or ""
    # '(nadpłata)' = ujemne saldo (nadpłata na koncie)
    if "nadpłata" in opis.lower() and saldo is not None:
        saldo = -abs(saldo)

    documents: list[dict[str, Any]] = []
    rows = _find_table(page, "gvNaleznosci_DXMainTable")
    if rows is not None:
        for cells in _data_rows(rows):
            nonempty = [c for c in cells if c]
            if len(nonempty) < 4:
                continue
            nr, termin, kwota, pozostalo = nonempty[:4]
            d = _parse_date(termin)
            documents.append(
                {
                    "number": nr,
                    "due_date": d.isoformat() if d else termin,
                    "amount": _parse_amount(kwota),
                    "remaining": _parse_amount(pozostalo),
                    "overdue": bool(d and d < date.today()),
                }
            )

    overdue = [doc for doc in documents if doc["overdue"]]
    min_due = min((doc["due_date"] for doc in documents), default=None)
    return {
        "balance": saldo,
        "overpayment": nadplata,
        "balance_description": opis,
        "document_count": len(documents),
        "documents": documents,
        "overdue_count": len(overdue),
        "min_due_date": min_due,
    }


def is_login_page(html: str) -> bool:
    """True = to strona logowania (brak danych), a nie strona z danymi."""
    page = _parse_html(html)
    has_data_table = any(
        tid and ("DXMainTable" in tid) for tid in page.tables
    )
    return "btLogin" in page.ids and not has_data_table


def has_wrong_credentials_error(html: str) -> bool:
    """True = serwer IBO zwrócił komunikat o błędnych danych logowania."""
    import re

    for cls, text in _parse_html(html).spans:
        classes = cls.split()
        if "dxbs-edit-error-text" in classes and "d-none" not in classes:
            low = text.lower()
            if "identyfikator" in low or "hasło" in low:
                return True
    for m in re.finditer(r"errorText'\s*:\s*'([^']{4,})", html):
        low = m.group(1).lower()
        if ("identyfikator" in low or "hasło" in low) and "wymagane" not in low:
            return True
    return False


class IboParseError(Exception):
    """Nie udało się sparsować strony IBO."""

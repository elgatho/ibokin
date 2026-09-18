"""Klient HTTP IBO — logowanie ASP.NET/DevExpress + pobieranie stron.

Klon działającego flow logowania (zweryfikowany na produkcji 2026-09):
GET Login.aspx?ReturnUrl=%2fclient%2f -> ekstrakcja tokenów -> POST z polami
$State DevExpress (rawValue) -> sesja w cookies.
"""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import quote

import aiohttp

from .const import (
    BASE_URL,
    LOGIN_URL,
    LOGIN_USER_AGENT,
    REQUEST_TIMEOUT,
    URL_HISTORIA,
    URL_NIEZAPLACONE,
    URL_STREFA,
)
from .parsers import (
    has_wrong_credentials_error,
    is_login_page,
    parse_payments,
    parse_readings,
)

_LOGGER = logging.getLogger(__name__)

VIEWSTATE_RE = re.compile(r'id="__VIEWSTATE" value="([^"]+)"')
VIEWSTATEGENERATOR_RE = re.compile(r'id="__VIEWSTATEGENERATOR" value="([^"]+)"')
EVENTVALIDATION_RE = re.compile(r'id="__EVENTVALIDATION" value="([^"]+)"')
DXSCRIPT_RE = re.compile(r"DXScript=([^\"]+)")
DXCSS_RE = re.compile(r"DXCss=([^\"]+)")

LOGIN_MARKERS = ("btLogin", "Logowanie")


class IboAuthError(Exception):
    """Błędny numer klienta lub hasło (serwer odrzucił logowanie)."""


class IboConnectionError(Exception):
    """Błąd sieciowy / Cloudflare / nieoczekiwana odpowiedź."""


def _dx_username_state(username: str) -> str:
    inner = json.dumps(
        {"rawValue": username, "validationState": ""}, separators=(",", ":")
    )
    return inner.replace('"', "&quot;")


def _encode_pairs(pairs: list[tuple[str, str]]) -> bytes:
    return "&".join(
        f"{quote(str(k), safe='')}={quote(str(v), safe='')}" for k, v in pairs
    ).encode("ascii")


class IboClient:
    """Sesyjny klient IBO. Jeden klient = jedna konfiguracja (nr klienta)."""

    def __init__(
        self, session: aiohttp.ClientSession, username: str, password: str
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._logged_in = False

    async def verify_credentials(self) -> None:
        """Weryfikacja logowania (config flow). Podnosi IboAuthError przy złych danych."""
        await self.login()
        # Potwierdzenie sesji: pobierz strefę klienta (przy złych danych rzuci
        # IboAuthError, przy problemach sieciowych IboConnectionError)
        await self._get_authenticated(URL_STREFA)

    async def login(self) -> None:
        headers = {
            "User-Agent": LOGIN_USER_AGENT,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            ),
            "Accept-Language": "pl-PL,pl;q=0.9",
            "Referer": LOGIN_URL,
            "Origin": BASE_URL,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        try:
            async with self._session.get(
                LOGIN_URL, headers=headers,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                page = await resp.text()
        except aiohttp.ClientError as err:
            raise IboConnectionError(f"GET login: {err}") from err

        viewstate = _extract(page, VIEWSTATE_RE)
        viewstategenerator = _extract(page, VIEWSTATEGENERATOR_RE)
        eventvalidation = _extract(page, EVENTVALIDATION_RE)
        dxscript = _extract(page, DXSCRIPT_RE)
        dxcss = _extract(page, DXCSS_RE)
        if not viewstate:
            raise IboConnectionError(
                "Brak __VIEWSTATE na stronie logowania (zmiana strony / Cloudflare)"
            )

        pairs: list[tuple[str, str]] = [
            ("__EVENTTARGET", ""),
            ("__EVENTARGUMENT", ""),
            ("__VIEWSTATE", viewstate),
            ("__VIEWSTATEGENERATOR", viewstategenerator),
            ("__EVENTVALIDATION", eventvalidation),
            ("tbUserName$State", _dx_username_state(self._username)),
            ("tbUserName", self._username),
            ("tbPassword$State", "{&quot;validationState&quot;:&quot;&quot;}"),
            ("tbPassword", self._password),
            ("cbShowPassword", "U"),
            ("btLogin", "Zaloguj"),
            ("DXScript", dxscript),
            ("DXCss", dxcss),
        ]
        try:
            async with self._session.post(
                LOGIN_URL, data=_encode_pairs(pairs), headers=headers,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                body = await resp.text()
                final_url = str(resp.url)
        except aiohttp.ClientError as err:
            raise IboConnectionError(f"POST login: {err}") from err

        if "Login.aspx" in final_url:
            if has_wrong_credentials_error(body):
                raise IboAuthError("Błędny numer klienta lub hasło")
            raise IboConnectionError(
                "Logowanie nie przeszło (bez komunikatu o danych) — spróbuj ponownie"
            )
        self._logged_in = True
        _LOGGER.debug("IBO: logowanie OK (user=%s)", self._username)

    async def _get_authenticated(self, url: str) -> str:
        """GET strony chronionej; przy przekierowaniu na login — relogin i retry."""
        headers = {"User-Agent": LOGIN_USER_AGENT, "Accept-Language": "pl-PL,pl;q=0.9"}
        for attempt in (1, 2):
            try:
                async with self._session.get(
                    url, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                ) as resp:
                    body = await resp.text()
                    final_url = str(resp.url)
            except aiohttp.ClientError as err:
                raise IboConnectionError(f"GET {url}: {err}") from err

            if "Login.aspx" in final_url or is_login_page(body):
                if attempt == 1:
                    _LOGGER.info("IBO: sesja wygasła — ponowne logowanie")
                    await self.login()
                    continue
                raise IboAuthError(
                    "Sesja wygasła i ponowne logowanie nie powiodło się"
                )
            return body
        raise IboConnectionError("Nie udało się pobrać strony po reloginie")

    async def async_get_payments(self) -> dict:
        html = await self._get_authenticated(URL_NIEZAPLACONE)
        return parse_payments(html)

    async def async_get_readings(self, meter_id: str) -> dict:
        html = await self._get_authenticated(URL_HISTORIA.format(meter_id=meter_id))
        return parse_readings(html)

    async def async_fetch_all(self, meter_id: str) -> dict:
        payments = await self.async_get_payments()
        readings = await self.async_get_readings(meter_id)
        return {"payments": payments, "readings": readings}


def _extract(html: str, regex: re.Pattern) -> str:
    m = regex.search(html)
    return m.group(1) if m else ""

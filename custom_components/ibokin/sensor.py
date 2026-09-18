"""Sensor IBOKIN: saldo niezapłaconych płatności + ostatni odczyt."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER

ATTR_DOCUMENTS = "documents"
ATTR_READINGS = "readings"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            IboBalanceSensor(coordinator, entry, "balance"),
            IboReadingSensor(coordinator, entry, "last_reading"),
        ]
    )


class IboEntity(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry: ConfigEntry, sensor_key: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._sensor_key = sensor_key
        self._attr_unique_id = f"{entry.entry_id}_{sensor_key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="IBOKIN — IBO Niepołomice",
            manufacturer=MANUFACTURER,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def data(self) -> dict[str, Any] | None:
        return self.coordinator.data


class IboBalanceSensor(IboEntity):
    """Saldo niezapłaconych płatności (suma)."""

    _attr_translation_key = "balance"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:cash-multiple"

    @property
    def native_value(self) -> float | None:
        if self.data and self.data.get("payments"):
            return self.data["payments"].get("balance")
        return None

    @property
    def native_unit_of_measurement(self) -> str:
        return "PLN"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not self.data or not self.data.get("payments"):
            return {}
        p = self.data["payments"]
        return {
            "nadplata": p.get("overpayment"),
            "opis_salda": p.get("balance_description"),
            "liczba_dokumentow": p.get("document_count"),
            "przeterminowane": p.get("overdue_count"),
            "najblizszy_termin": p.get("min_due_date"),
            ATTR_DOCUMENTS: p.get("documents"),
        }


class IboReadingSensor(IboEntity):
    """Ostatni odczyt wodomierza."""

    _attr_translation_key = "last_reading"
    _attr_device_class = SensorDeviceClass.WATER
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:water-pump"

    @property
    def native_value(self) -> float | None:
        if self.data and self.data.get("readings"):
            return self.data["readings"].get("last_reading_value")
        return None

    @property
    def native_unit_of_measurement(self) -> str:
        return "m³"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if not self.data or not self.data.get("readings"):
            return {}
        r = self.data["readings"]
        return {
            "data_odczytu": r.get("last_reading_date"),
            "typ_odczytu": r.get("last_reading_type"),
            "poprzedni_odczyt": r.get("previous_reading_value"),
            "zuzycie_od_poprzedniego": r.get("usage_since_previous"),
            ATTR_READINGS: r.get("readings"),
        }

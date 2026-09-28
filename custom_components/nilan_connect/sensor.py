"""Measurements of the unit, its alarm codes, and its heat recovery efficiency."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfRatio
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from nilan_connect import Key, PointKey

from .data import NilanConfigEntry, NilanData
from .entity import NilanEntity, NilanEntityDescription, NilanPointEntity, describe
from .units import ha_unit

PARALLEL_UPDATES = 0

EFFICIENCY = "efficiency"
"""The heat recovery efficiency, which no point holds: it is worked out from three."""


@dataclass(frozen=True, kw_only=True)
class NilanSensorDescription(NilanEntityDescription, SensorEntityDescription):
    """A sensor of one point."""


def _reading(
    point: Key[Any], device_class: SensorDeviceClass | None
) -> NilanSensorDescription:
    return NilanSensorDescription(
        key=str(point),
        translation_key=str(point),
        point=point,
        device_class=device_class,
        state_class=SensorStateClass.MEASUREMENT,
    )


def _code(point: Key[Any]) -> NilanSensorDescription:
    # A code is a number without an order, which has no statistics.
    return NilanSensorDescription(
        key=str(point),
        translation_key=str(point),
        point=point,
        entity_registry_enabled_default=False,
    )


SENSORS: tuple[NilanSensorDescription, ...] = (
    _code(PointKey.ALARM_1_CODE),
    _code(PointKey.ALARM_2_CODE),
    _code(PointKey.ALARM_3_CODE),
    _code(PointKey.ALARM_1_INFO),
    _code(PointKey.ALARM_2_INFO),
    _code(PointKey.ALARM_3_INFO),
    _reading(PointKey.CO2_LEVEL, SensorDeviceClass.CO2),
    _reading(PointKey.FAN_DUTYCYCLE_EXTRACT, None),
    _reading(PointKey.FAN_DUTYCYCLE_SUPPLY, None),
    _reading(PointKey.FAN_LEVEL_CURRENT, None),
    _reading(PointKey.FILTER_REPLACE_TIME_AGO, SensorDeviceClass.DURATION),
    _reading(PointKey.FILTER_REPLACE_TIME_REMAIN, SensorDeviceClass.DURATION),
    _reading(PointKey.HUMIDITY, SensorDeviceClass.HUMIDITY),
    _reading(PointKey.HUMIDITY_AVG, SensorDeviceClass.HUMIDITY),
    _reading(PointKey.HUMIDITY_HIGH_LEVEL, None),
    _reading(PointKey.HUMIDITY_HIGH_LEVEL_TIME, SensorDeviceClass.DURATION),
    _reading(PointKey.TEMP_EXHAUST, SensorDeviceClass.TEMPERATURE),
    _reading(PointKey.TEMP_EXTRACT, SensorDeviceClass.TEMPERATURE),
    _reading(PointKey.TEMP_OUTSIDE, SensorDeviceClass.TEMPERATURE),
    _reading(PointKey.TEMP_SUPPLY, SensorDeviceClass.TEMPERATURE),
    _reading(PointKey.VOC_LEVEL, SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS_PARTS),
)

EFFICIENCY_FROM: tuple[Key[float], Key[float], Key[float]] = (
    PointKey.TEMP_SUPPLY,
    PointKey.TEMP_OUTSIDE,
    PointKey.TEMP_EXTRACT,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NilanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a sensor for every described point the unit has, and its efficiency when it has
    the temperatures it is worked out from."""
    data = entry.runtime_data
    sensors: list[SensorEntity] = [
        NilanSensor(data, description) for description in describe(data, SENSORS)
    ]
    if all(data.client.has(key) for key in EFFICIENCY_FROM):
        sensors.append(NilanEfficiency(data))
    async_add_entities(sensors)


class NilanSensor(NilanPointEntity, SensorEntity):
    """The value of one point."""

    def __init__(self, data: NilanData, description: NilanSensorDescription) -> None:
        self._attr_native_unit_of_measurement = ha_unit(data.client, description.point)
        super().__init__(data, description)

    def _show(self) -> None:
        value = self._current(self._key)
        self._attr_native_value = (
            value if isinstance(value, int | float) and not isinstance(value, bool) else None
        )


class NilanEfficiency(NilanEntity, SensorEntity):
    """The supply side's temperature ratio of the heat recovery, in percent:
    (supply - outdoor) / (extract - outdoor).

    Worked out again whenever one of the three temperatures changes; unknown while the extract
    and outdoor air are equally warm.
    """

    _attr_translation_key = EFFICIENCY
    _attr_native_unit_of_measurement = UnitOfRatio.PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, data: NilanData) -> None:
        super().__init__(data, EFFICIENCY)

    def _watched(self) -> tuple[Key[Any], ...]:
        return EFFICIENCY_FROM

    def _show(self) -> None:
        supply, outside, extract = (self._current(key) for key in EFFICIENCY_FROM)
        if supply is None or outside is None or extract is None or extract == outside:
            self._attr_native_value = None
        else:
            self._attr_native_value = (supply - outside) / (extract - outside) * 100

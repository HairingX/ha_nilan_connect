"""Measurements of the unit, its codes and states, and its heat recovery efficiency."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import IntEnum
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfRatio
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from nilan_connect import Key, PointKey

from .data import NilanConfigEntry, NilanData
from .entity import NilanEntity, NilanEntityDescription, NilanPointEntity, describe, state_name
from .units import ha_unit

PARALLEL_UPDATES = 0

EFFICIENCY = "efficiency"
"""The heat recovery efficiency, which no point holds: it is worked out from three."""


@dataclass(frozen=True, kw_only=True)
class NilanSensorDescription(NilanEntityDescription, SensorEntityDescription):
    """A sensor of one point."""


def _reading(
    point: Key[Any], device_class: SensorDeviceClass | None = None, *, enabled: bool = True
) -> NilanSensorDescription:
    return NilanSensorDescription(
        key=str(point),
        translation_key=str(point),
        point=point,
        device_class=device_class,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=enabled,
    )


def _temperature(point: Key[float], *, enabled: bool = True) -> NilanSensorDescription:
    return _reading(point, SensorDeviceClass.TEMPERATURE, enabled=enabled)


def _code(point: Key[Any]) -> NilanSensorDescription:
    # A code is a number without an order, which has no statistics.
    return NilanSensorDescription(
        key=str(point),
        translation_key=str(point),
        point=point,
        entity_registry_enabled_default=False,
    )


def _state(point: Key[Any], *, diagnostic: bool = False) -> NilanSensorDescription:
    """A state of the unit, shown by its name; its options are the states the unit's point has."""
    return NilanSensorDescription(
        key=str(point),
        translation_key=str(point),
        point=point,
        device_class=SensorDeviceClass.ENUM,
        entity_category=EntityCategory.DIAGNOSTIC if diagnostic else None,
    )


SENSORS: tuple[NilanSensorDescription, ...] = (
    _code(PointKey.ALARM_1_CODE),
    _code(PointKey.ALARM_2_CODE),
    _code(PointKey.ALARM_3_CODE),
    _code(PointKey.ALARM_1_INFO),
    _code(PointKey.ALARM_2_INFO),
    _code(PointKey.ALARM_3_INFO),
    _code(PointKey.ALARM_BITS),
    _code(PointKey.ALARM_BITS_HIGH),
    _code(PointKey.STATE_CODE),
    _state(PointKey.ALARM_1),
    _state(PointKey.ALARM_2),
    _state(PointKey.ALARM_3),
    _state(PointKey.OPERATION_STATE),
    _state(PointKey.OPERATION_MODE_CURRENT),
    _state(PointKey.HEAT_PUMP_STATE),
    _state(PointKey.DAMPER_TEST_STATE, diagnostic=True),
    _state(PointKey.DAMPER_TEST_DAY, diagnostic=True),
    NilanSensorDescription(
        key=str(PointKey.DAMPER_TEST_LAST_DATE),
        translation_key=str(PointKey.DAMPER_TEST_LAST_DATE),
        point=PointKey.DAMPER_TEST_LAST_DATE,
        device_class=SensorDeviceClass.DATE,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    _reading(PointKey.CO2_LEVEL, SensorDeviceClass.CO2),
    _reading(PointKey.FAN_DUTYCYCLE_EXTRACT),
    _reading(PointKey.FAN_DUTYCYCLE_SUPPLY),
    _reading(PointKey.FAN_LEVEL_CURRENT),
    _reading(PointKey.FAN_LEVEL_SUPPLY),
    _reading(PointKey.FAN_LEVEL_EXTRACT),
    _reading(PointKey.FAN_RPM_SUPPLY),
    _reading(PointKey.FAN_RPM_EXTRACT),
    _reading(PointKey.ROTOR_SPEED),
    _reading(PointKey.BYPASS_POSITION),
    _reading(PointKey.PREHEAT_OUTPUT),
    _reading(PointKey.REHEAT_OUTPUT),
    _reading(PointKey.HEAT_PUMP_CAPACITY),
    _reading(PointKey.SUCTION_PRESSURE, SensorDeviceClass.PRESSURE),
    _reading(PointKey.DISCHARGE_PRESSURE, SensorDeviceClass.PRESSURE),
    _reading(PointKey.TIME_IN_STATE, SensorDeviceClass.DURATION, enabled=False),
    _reading(PointKey.FILTER_REPLACE_TIME_AGO, SensorDeviceClass.DURATION),
    _reading(PointKey.FILTER_REPLACE_TIME_REMAIN, SensorDeviceClass.DURATION),
    _reading(PointKey.HUMIDITY, SensorDeviceClass.HUMIDITY),
    _reading(PointKey.HUMIDITY_AVG, SensorDeviceClass.HUMIDITY),
    _reading(PointKey.HUMIDITY_HIGH_LEVEL),
    _reading(PointKey.HUMIDITY_HIGH_LEVEL_TIME, SensorDeviceClass.DURATION),
    _reading(PointKey.VOC_LEVEL, SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS_PARTS),
    _temperature(PointKey.TEMP_EXHAUST),
    _temperature(PointKey.TEMP_EXTRACT),
    _temperature(PointKey.TEMP_OUTSIDE),
    _temperature(PointKey.TEMP_SUPPLY),
    _temperature(PointKey.TEMP_INTAKE),
    _temperature(PointKey.TEMP_PREHEAT_INTAKE),
    _temperature(PointKey.TEMP_SUPPLY_AFTER_HEATER),
    _temperature(PointKey.TEMP_ROOM),
    _temperature(PointKey.TEMP_ROOM_PANEL),
    _temperature(PointKey.TEMP_HEATER),
    _temperature(PointKey.TEMP_FROST_PROTECTION),
    _temperature(PointKey.TEMP_CONTROLLER, enabled=False),
    _temperature(PointKey.TEMP_AUX),
    _temperature(PointKey.TEMP_HOTWATER_TOP),
    _temperature(PointKey.TEMP_HOTWATER_BOTTOM),
    _temperature(PointKey.TEMP_CENTRAL_HEAT_SUPPLY),
    _temperature(PointKey.TEMP_CENTRAL_HEAT_RETURN),
    _temperature(PointKey.TEMP_CONDENSER),
    _temperature(PointKey.TEMP_EVAPORATOR),
    _temperature(PointKey.TEMP_BEFORE_CONDENSER),
    _temperature(PointKey.TEMP_AFTER_CONDENSER),
    _temperature(PointKey.TEMP_PRESSURE_PIPE),
    _temperature(PointKey.TEMP_BUFFER_TANK),
    _temperature(PointKey.TEMP_HEAT_PUMP_OUTDOOR),
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
    """The value of one point: a number, a date, or a state by its name."""

    def __init__(self, data: NilanData, description: NilanSensorDescription) -> None:
        (point,) = data.client.select([description.point])
        if description.device_class is SensorDeviceClass.ENUM:
            self._attr_options = [state_name(state) for state in point.states]
        self._attr_native_unit_of_measurement = ha_unit(data.client, description.point)
        super().__init__(data, description)

    def _show(self) -> None:
        value = self._current(self._key)
        if isinstance(value, IntEnum):
            name = state_name(value)
            self._attr_native_value = name if name in (self._attr_options or ()) else None
        elif isinstance(value, int | float | date):
            self._attr_native_value = value
        else:
            self._attr_native_value = None


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

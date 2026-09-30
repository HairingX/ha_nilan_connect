"""States of the unit: alarms, bypass, de-icing, filter, humidity, heating, heat pump and inputs."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from nilan_connect import Key, PointKey

from .data import NilanConfigEntry, NilanData
from .entity import NilanEntityDescription, NilanPointEntity, describe

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class NilanBinarySensorDescription(NilanEntityDescription, BinarySensorEntityDescription):
    """A binary sensor of one point that holds a bool."""

    on: bool = True
    """The value the sensor is on for."""


def _state(
    point: Key[bool],
    device_class: BinarySensorDeviceClass | None,
    *,
    on: bool = True,
    enabled: bool = True,
) -> NilanBinarySensorDescription:
    return NilanBinarySensorDescription(
        key=str(point),
        translation_key=str(point),
        point=point,
        device_class=device_class,
        on=on,
        entity_registry_enabled_default=enabled,
    )


def _alarm(point: Key[bool]) -> NilanBinarySensorDescription:
    """One alarm of a controller that reports its alarms as bits."""
    return NilanBinarySensorDescription(
        key=str(point),
        translation_key=str(point),
        point=point,
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    )


def _input(point: Key[bool]) -> NilanBinarySensorDescription:
    """A digital input of the controller, whatever the installer wired to it."""
    return NilanBinarySensorDescription(
        key=str(point),
        translation_key=str(point),
        point=point,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    )


BINARY_SENSORS: tuple[NilanBinarySensorDescription, ...] = (
    _state(PointKey.ALARM_STATUS, BinarySensorDeviceClass.PROBLEM),
    _state(PointKey.BYPASS_ACTIVE, BinarySensorDeviceClass.OPENING),
    _state(PointKey.DEFROST_ACTIVE, BinarySensorDeviceClass.RUNNING),
    # A problem when the filter must be changed.
    _state(PointKey.FILTER_OK, BinarySensorDeviceClass.PROBLEM, on=False),
    _state(PointKey.HUMIDITY_HIGH_ACTIVE, BinarySensorDeviceClass.MOISTURE),
    _state(PointKey.WINTER_MODE_ACTIVE, None),
    _state(PointKey.RUNNING, BinarySensorDeviceClass.RUNNING),
    # No register says whether an after-heating element is fitted.
    _state(PointKey.REHEAT_ACTIVE, BinarySensorDeviceClass.HEAT, enabled=False),
    _state(PointKey.HEAT_PUMP_ACTIVE, BinarySensorDeviceClass.RUNNING),
    _state(PointKey.HEAT_PUMP_HEATER_ACTIVE, BinarySensorDeviceClass.HEAT),
    _state(PointKey.HEAT_PUMP_ROOM_HEATING, BinarySensorDeviceClass.HEAT),
    _state(PointKey.HEAT_PUMP_WATER_HEATING, BinarySensorDeviceClass.HEAT),
    # A problem when the hot water tank's anode must be replaced.
    _state(PointKey.SACRIFICIAL_ANODE_OK, BinarySensorDeviceClass.PROBLEM, on=False),
    _input(PointKey.DIGITAL_INPUT_1),
    _input(PointKey.DIGITAL_INPUT_2),
    _input(PointKey.DIGITAL_INPUT_3),
    _alarm(PointKey.ALARM_EXTERNAL_STOP),
    _alarm(PointKey.ALARM_EXTERNAL_FILTER),
    _alarm(PointKey.ALARM_HIGH_PRESSURE),
    _alarm(PointKey.ALARM_LOW_PRESSURE),
    _alarm(PointKey.ALARM_FROST_FAILURE),
    _alarm(PointKey.ALARM_PANEL_COMMUNICATION),
    _alarm(PointKey.ALARM_INTERNAL_MODBUS),
    _alarm(PointKey.ALARM_FAN_ERROR),
    _alarm(PointKey.ALARM_SUPPLY_FAN_ERROR),
    _alarm(PointKey.ALARM_EXTRACT_FAN_ERROR),
    _alarm(PointKey.ALARM_ROTOR),
    _alarm(PointKey.ALARM_SENSOR_ERROR),
    _alarm(PointKey.ALARM_HUMIDITY_SENSOR_ERROR),
    _alarm(PointKey.ALARM_FLOW_TEMPERATURE_ERROR),
    _alarm(PointKey.ALARM_RETURN_TEMPERATURE_ERROR),
    _alarm(PointKey.ALARM_SENSOR_T1_ERROR),
    _alarm(PointKey.ALARM_SENSOR_T2_ERROR),
    _alarm(PointKey.ALARM_SENSOR_T3_ERROR),
    _alarm(PointKey.ALARM_SENSOR_T4_ERROR),
    _alarm(PointKey.ALARM_SENSOR_T5_ERROR),
    _alarm(PointKey.ALARM_SENSOR_T6_ERROR),
    _alarm(PointKey.ALARM_SENSOR_T7_ERROR),
    _alarm(PointKey.ALARM_SENSOR_T8_ERROR),
    _alarm(PointKey.ALARM_SENSOR_T9_ERROR),
    _alarm(PointKey.ALARM_SENSOR_T10_ERROR),
    _alarm(PointKey.ALARM_SENSOR_T11_ERROR),
    _alarm(PointKey.ALARM_FIRE_TEST_ERROR),
    _alarm(PointKey.ALARM_FIRE_DAMPER_1_ERROR),
    _alarm(PointKey.ALARM_FIRE_DAMPER_2_ERROR),
    _alarm(PointKey.ALARM_FIRE_DAMPER_3_ERROR),
    _alarm(PointKey.ALARM_FIRE_DAMPER_4_ERROR),
    _alarm(PointKey.ALARM_FIRE_BOX_1_ERROR),
    _alarm(PointKey.ALARM_FIRE_BOX_2_ERROR),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NilanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a binary sensor for every described point the unit has."""
    data = entry.runtime_data
    async_add_entities(
        NilanBinarySensor(data, description)
        for description in describe(data, BINARY_SENSORS)
    )


class NilanBinarySensor(NilanPointEntity, BinarySensorEntity):
    """One state of the unit."""

    def __init__(self, data: NilanData, description: NilanBinarySensorDescription) -> None:
        self._on = description.on
        super().__init__(data, description)

    def _show(self) -> None:
        value = self._current(self._key)
        self._attr_is_on = None if value is None else value is self._on

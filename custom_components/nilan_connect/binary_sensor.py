"""States of the unit: alarm, bypass, de-icing, filter, high humidity and winter mode."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
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
    point: Key[bool], device_class: BinarySensorDeviceClass | None, *, on: bool = True
) -> NilanBinarySensorDescription:
    return NilanBinarySensorDescription(
        key=str(point),
        translation_key=str(point),
        point=point,
        device_class=device_class,
        on=on,
    )


BINARY_SENSORS: tuple[NilanBinarySensorDescription, ...] = (
    _state(PointKey.ALARM_STATUS, BinarySensorDeviceClass.PROBLEM),
    _state(PointKey.BYPASS_ACTIVE, BinarySensorDeviceClass.OPENING),
    _state(PointKey.DEFROST_ACTIVE, BinarySensorDeviceClass.RUNNING),
    # A problem when the filter must be changed.
    _state(PointKey.FILTER_OK, BinarySensorDeviceClass.PROBLEM, on=False),
    _state(PointKey.HUMIDITY_HIGH_ACTIVE, BinarySensorDeviceClass.MOISTURE),
    _state(PointKey.WINTER_MODE_ACTIVE, None),
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

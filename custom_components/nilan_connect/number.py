"""Number settings: the target temperature, fan levels and presets, thresholds and timers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from nilan_connect import Key, Point, PointKey, Unit

from .data import NilanConfigEntry, NilanData
from .entity import NilanEntityDescription, NilanPointEntity, describe
from .units import ha_unit

# The client sends writes in order and folds a queued setting into a newer one, so actions
# are passed to it as they come.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class NilanNumberDescription(NilanEntityDescription, NumberEntityDescription):
    """A number of one point."""


def _setting(
    point: Key[Any],
    device_class: NumberDeviceClass | None,
    *,
    enabled: bool = False,
) -> NilanNumberDescription:
    """An installer's setting: hidden, and disabled unless `enabled`."""
    return NilanNumberDescription(
        key=str(point),
        translation_key=str(point),
        point=point,
        device_class=device_class,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=enabled,
        entity_registry_visible_default=False,
    )


def _user_setting(point: Key[Any], device_class: NumberDeviceClass | None) -> NilanNumberDescription:
    """A setting a user changes in daily use: shown, and enabled."""
    return NilanNumberDescription(
        key=str(point),
        translation_key=str(point),
        point=point,
        device_class=device_class,
    )


TARGET_TEMPERATURE = NilanNumberDescription(
    key=str(PointKey.TEMP_TARGET),
    translation_key=str(PointKey.TEMP_TARGET),
    point=PointKey.TEMP_TARGET,
    device_class=NumberDeviceClass.TEMPERATURE,
)

NUMBERS: tuple[NilanNumberDescription, ...] = (
    TARGET_TEMPERATURE,
    _setting(PointKey.CO2_THRESHOLD, NumberDeviceClass.CO2),
    _setting(PointKey.VOC_THRESHOLD, NumberDeviceClass.VOLATILE_ORGANIC_COMPOUNDS_PARTS),
    _setting(PointKey.DEFROST_BREAK_TIME, NumberDeviceClass.DURATION),
    _setting(PointKey.DEFROST_MAX_TIME, NumberDeviceClass.DURATION),
    _setting(PointKey.FAN_LEVEL1_SUPPLY_PRESET, None),
    _setting(PointKey.FAN_LEVEL2_SUPPLY_PRESET, None),
    _setting(PointKey.FAN_LEVEL3_SUPPLY_PRESET, None),
    _setting(PointKey.FAN_LEVEL4_SUPPLY_PRESET, None),
    _setting(PointKey.FAN_LEVEL1_EXTRACT_PRESET, None),
    _setting(PointKey.FAN_LEVEL2_EXTRACT_PRESET, None),
    _setting(PointKey.FAN_LEVEL3_EXTRACT_PRESET, None),
    _setting(PointKey.FAN_LEVEL4_EXTRACT_PRESET, None),
    _setting(PointKey.FAN_LEVEL_HIGH_CO2, None),
    _setting(PointKey.FAN_LEVEL_HIGH_HUMIDITY, None),
    _setting(PointKey.FAN_LEVEL_HIGH_HUMIDITY_TIME, NumberDeviceClass.DURATION, enabled=True),
    _setting(PointKey.FAN_LEVEL_LOW_HUMIDITY, None, enabled=True),
    _setting(PointKey.FILTER_REPLACE_INTERVAL, NumberDeviceClass.DURATION, enabled=True),
    _setting(PointKey.HUMIDITY_LOW_THRESHOLD, NumberDeviceClass.HUMIDITY, enabled=True),
    _setting(PointKey.TEMP_DEFROST_HIGH_THRESHOLD, NumberDeviceClass.TEMPERATURE),
    _setting(PointKey.TEMP_DEFROST_LOW_THRESHOLD, NumberDeviceClass.TEMPERATURE),
    # A dead band is a difference of temperatures, converted as one.
    _setting(PointKey.TEMP_REGULATION_DEAD_BAND, NumberDeviceClass.TEMPERATURE_DELTA),
    _setting(PointKey.TEMP_SUPPLY_MAX, NumberDeviceClass.TEMPERATURE),
    _setting(PointKey.TEMP_SUPPLY_MIN, NumberDeviceClass.TEMPERATURE),
    _setting(PointKey.TEMP_WINTER_MODE_THRESHOLD, NumberDeviceClass.TEMPERATURE),
    _user_setting(PointKey.TEMP_HOTWATER, NumberDeviceClass.TEMPERATURE),
    _user_setting(PointKey.TEMP_HOTWATER_BOOST, NumberDeviceClass.TEMPERATURE),
    _user_setting(PointKey.BOOST_TIME, NumberDeviceClass.DURATION),
    _setting(PointKey.TEMP_HOTWATER_SCALD_PROTECTION, NumberDeviceClass.TEMPERATURE),
    _setting(PointKey.TEMP_HOTWATER_BYPASS_OFFSET, NumberDeviceClass.TEMPERATURE_DELTA),
    _setting(PointKey.TEMP_SUMMER_SUPPLY_MIN, NumberDeviceClass.TEMPERATURE),
    _setting(PointKey.TEMP_SUMMER_SUPPLY_MAX, NumberDeviceClass.TEMPERATURE),
    _setting(PointKey.TEMP_WINTER_SUPPLY_MIN, NumberDeviceClass.TEMPERATURE),
    _setting(PointKey.TEMP_WINTER_SUPPLY_MAX, NumberDeviceClass.TEMPERATURE),
    _setting(PointKey.TEMP_NIGHT_COOLING_DAY_LIMIT, NumberDeviceClass.TEMPERATURE),
    _setting(PointKey.TEMP_NIGHT_COOLING_TARGET, NumberDeviceClass.TEMPERATURE),
    _setting(PointKey.TEMP_BYPASS_OPEN_OFFSET, NumberDeviceClass.TEMPERATURE_DELTA),
    _setting(PointKey.TEMP_BYPASS_CLOSE_OFFSET, NumberDeviceClass.TEMPERATURE_DELTA),
    _setting(PointKey.TEMP_BYPASS_FAN_INCREASE_OFFSET, NumberDeviceClass.TEMPERATURE_DELTA),
    _setting(PointKey.BYPASS_FAN_INCREASE, None),
    _setting(PointKey.TEMP_CENTRAL_HEAT_SUPPLY_MIN, NumberDeviceClass.TEMPERATURE),
    _setting(PointKey.TEMP_CENTRAL_HEAT_SUPPLY_MAX, NumberDeviceClass.TEMPERATURE),
    _setting(PointKey.TEMP_CENTRAL_HEAT_OFFSET, NumberDeviceClass.TEMPERATURE_DELTA),
    _setting(PointKey.TEMP_CENTRAL_HEAT_COMPENSATION, NumberDeviceClass.TEMPERATURE_DELTA),
    _setting(PointKey.CENTRAL_HEAT_CURVE, None),
    _setting(PointKey.CENTRAL_HEAT_REGULATION_TIME, NumberDeviceClass.DURATION),
    _setting(PointKey.COOLING_TEMPERATURE, None),
    _setting(PointKey.FAN_LEVEL_COOLING, None),
    _setting(PointKey.SERVICE_CAPACITY, None),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NilanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a number for every described point the unit has."""
    data = entry.runtime_data
    async_add_entities(
        NilanNumber(data, description)
        for description in describe(data, NUMBERS)
        if has_range(data.client.select([description.point])[0])
    )


def has_range(point: Point[Any]) -> bool:
    """Whether a source gives the lowest and highest value `point` can be written with."""
    limits = point.limits
    return limits is not None and limits.min is not None and limits.max is not None


DURATION_UNITS = frozenset({Unit.SECONDS, Unit.MINUTES, Unit.HOURS, Unit.DAYS})
"""The units Home Assistant accepts for a duration."""


def value_range(point: Point[Any]) -> tuple[float, float, float]:
    """The lowest and highest value `point` can be written with, and its step: the limits
    Nilan's manual gives, which every setting has."""
    limits = point.limits
    if limits is None or limits.min is None or limits.max is None:
        raise ValueError(f"{point.key} has no limits")
    return limits.min, limits.max, limits.step if limits.step is not None else point.scale


class NilanNumber(NilanPointEntity, NumberEntity):
    """One number setting, written to the unit."""

    def __init__(self, data: NilanData, description: NilanNumberDescription) -> None:
        (point,) = data.client.select([description.point])
        lowest, highest, step = value_range(point)
        self._attr_native_min_value = lowest
        self._attr_native_max_value = highest
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = ha_unit(data.client, description.point)
        if description.device_class is NumberDeviceClass.DURATION and point.unit not in DURATION_UNITS:
            # A filter interval in months is no duration Home Assistant can convert.
            self._attr_device_class = None
        super().__init__(data, description)

    def _show(self) -> None:
        value = self._current(self._key)
        self._attr_native_value = (
            value if isinstance(value, int | float) and not isinstance(value, bool) else None
        )

    async def async_set_native_value(self, value: float) -> None:
        point_type = self._key.type
        await self._write(self._key, int(value) if point_type is int else value)

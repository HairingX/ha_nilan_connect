"""The unit as a thermostat: on or off, its fan level, and the room temperature it aims for."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from nilan_connect import Key, PointKey

from .data import NilanConfigEntry, NilanData
from .entity import NilanEntity, shown
from .select import levels

# The client sends writes in order and folds a queued setting into a newer one, so actions
# are passed to it as they come.
PARALLEL_UPDATES = 0

THERMOSTAT = "hvac"
"""What the thermostat's unique id ends with."""

SHOWN: tuple[Key[Any], ...] = (
    PointKey.ENABLE,
    PointKey.FAN_LEVEL,
    PointKey.TEMP_TARGET,
    PointKey.TEMP_EXTRACT,
    PointKey.HUMIDITY,
    PointKey.DEFROST_ACTIVE,
    PointKey.HUMIDITY_HIGH_ACTIVE,
    PointKey.BYPASS_ACTIVE,
)
"""Every point the thermostat shows or writes."""

CONTROLS: tuple[Key[Any], ...] = (PointKey.ENABLE, PointKey.FAN_LEVEL, PointKey.TEMP_TARGET)
"""What the thermostat sets; a unit with none of them shown has no thermostat."""


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NilanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the thermostat, for a unit with something it sets."""
    data = entry.runtime_data
    if any(shown(data, key) for key in CONTROLS):
        async_add_entities([NilanClimate(data)])


class NilanClimate(NilanEntity, ClimateEntity):
    """The unit: AUTO while it runs, OFF while it is stopped; its fan level as the fan mode.

    A unit whose run setting is not shown is always AUTO: it cannot be turned off here.

    The temperature shown is the extract air's, the air taken from the rooms. What it is doing
    is, in order: off, de-icing, drying while high humidity is active, cooling while the bypass
    is open, and otherwise ventilating.
    """

    # The unit itself: the entity is named after its device.
    _attr_name = None
    _attr_translation_key = THERMOSTAT
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(self, data: NilanData) -> None:
        client = data.client
        self._shown = tuple(key for key in SHOWN if shown(data, key))
        features = ClimateEntityFeature(0)
        self._attr_hvac_modes = [HVACMode.AUTO]
        if PointKey.ENABLE in self._shown and client.can_write(PointKey.ENABLE):
            features |= ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
            self._attr_hvac_modes.append(HVACMode.OFF)
        if PointKey.FAN_LEVEL in self._shown and client.can_write(PointKey.FAN_LEVEL):
            features |= ClimateEntityFeature.FAN_MODE
            self._attr_fan_modes = levels(client, PointKey.FAN_LEVEL)
        if PointKey.TEMP_TARGET in self._shown and client.can_write(PointKey.TEMP_TARGET):
            features |= ClimateEntityFeature.TARGET_TEMPERATURE
            (point,) = client.select([PointKey.TEMP_TARGET])
            if point.limits is not None:
                if point.limits.min is not None:
                    self._attr_min_temp = point.limits.min
                if point.limits.max is not None:
                    self._attr_max_temp = point.limits.max
                if point.limits.step is not None:
                    self._attr_target_temperature_step = point.limits.step
        self._attr_supported_features = features
        super().__init__(data, THERMOSTAT)

    def _watched(self) -> tuple[Key[Any], ...]:
        return self._shown

    def _required(self) -> tuple[Key[Any], ...]:
        return (next(key for key in CONTROLS if key in self._shown),)

    def _show(self) -> None:
        running = self._current(PointKey.ENABLE) if PointKey.ENABLE in self._shown else True
        self._attr_hvac_mode = (
            None if running is None else HVACMode.AUTO if running else HVACMode.OFF
        )
        self._attr_hvac_action = self._action(running)
        level = self._current(PointKey.FAN_LEVEL)
        self._attr_fan_mode = str(level) if level is not None else None
        self._attr_target_temperature = self._current(PointKey.TEMP_TARGET)
        self._attr_current_temperature = self._current(PointKey.TEMP_EXTRACT)
        self._attr_current_humidity = self._current(PointKey.HUMIDITY)

    def _action(self, running: bool | None) -> HVACAction | None:
        if running is None:
            return None
        if not running:
            return HVACAction.OFF
        if self._current(PointKey.DEFROST_ACTIVE):
            return HVACAction.DEFROSTING
        if self._current(PointKey.HUMIDITY_HIGH_ACTIVE):
            return HVACAction.DRYING
        if self._current(PointKey.BYPASS_ACTIVE):
            # Outdoor air past the heat exchanger cools the rooms.
            return HVACAction.COOLING
        return HVACAction.FAN

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        await self._write(PointKey.ENABLE, hvac_mode is not HVACMode.OFF)

    async def async_turn_on(self) -> None:
        await self._write(PointKey.ENABLE, True)

    async def async_turn_off(self) -> None:
        await self._write(PointKey.ENABLE, False)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        await self._write(PointKey.FAN_LEVEL, int(fan_mode))

    async def async_set_temperature(self, **kwargs: Any) -> None:
        await self._write(PointKey.TEMP_TARGET, float(kwargs[ATTR_TEMPERATURE]))

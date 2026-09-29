"""On/off settings: whether the unit runs, its heating and boost, and the panel's locks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from nilan_connect import Key, PointKey

from .data import NilanConfigEntry
from .entity import NilanEntityDescription, NilanPointEntity, describe

# The client sends writes in order and folds a queued setting into a newer one, so actions
# are passed to it as they come.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class NilanSwitchDescription(NilanEntityDescription, SwitchEntityDescription):
    """A switch of one point that holds a bool."""


def _toggle(point: Key[bool], *, config: bool = True) -> NilanSwitchDescription:
    """An on/off setting; an installer's setting unless not `config`."""
    return NilanSwitchDescription(
        key=str(point),
        translation_key=str(point),
        point=point,
        device_class=SwitchDeviceClass.SWITCH,
        entity_category=EntityCategory.CONFIG if config else None,
    )


SWITCHES: tuple[NilanSwitchDescription, ...] = (
    # The thermostat turns the unit on and off too; this switch is for scripts.
    NilanSwitchDescription(
        key=str(PointKey.ENABLE),
        translation_key=str(PointKey.ENABLE),
        point=PointKey.ENABLE,
        device_class=SwitchDeviceClass.SWITCH,
        entity_registry_enabled_default=False,
    ),
    _toggle(PointKey.BOOST_ENABLE, config=False),
    _toggle(PointKey.COOLING_ENABLE, config=False),
    _toggle(PointKey.HOTWATER_HEATER_ENABLE, config=False),
    _toggle(PointKey.REHEAT_ENABLE),
    _toggle(PointKey.PREHEAT_ENABLE),
    _toggle(PointKey.HUMIDITY_CONTROL_ENABLE),
    _toggle(PointKey.DEFROST_SUPPLY_FAN),
    _toggle(PointKey.FILTER_ALARM_ON_PANEL),
    _toggle(PointKey.PANEL_LOCK_FAN_LEVEL),
    _toggle(PointKey.PANEL_LOCK_ON_OFF),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NilanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a switch for every described point the unit has."""
    data = entry.runtime_data
    async_add_entities(
        NilanSwitch(data, description) for description in describe(data, SWITCHES)
    )


class NilanSwitch(NilanPointEntity, SwitchEntity):
    """One on/off setting, written to the unit."""

    def _show(self) -> None:
        value = self._current(self._key)
        self._attr_is_on = value if isinstance(value, bool) else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._write(self._key, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._write(self._key, False)

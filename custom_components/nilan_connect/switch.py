"""Whether the unit runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from nilan_connect import PointKey

from .data import NilanConfigEntry
from .entity import NilanEntityDescription, NilanPointEntity, describe

# The client sends writes in order and folds a queued setting into a newer one, so actions
# are passed to it as they come.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class NilanSwitchDescription(NilanEntityDescription, SwitchEntityDescription):
    """A switch of one point that holds a bool."""


SWITCHES: tuple[NilanSwitchDescription, ...] = (
    # The thermostat turns the unit on and off too; this switch is for scripts.
    NilanSwitchDescription(
        key=str(PointKey.ENABLE),
        translation_key=str(PointKey.ENABLE),
        point=PointKey.ENABLE,
        device_class=SwitchDeviceClass.SWITCH,
        entity_registry_enabled_default=False,
    ),
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

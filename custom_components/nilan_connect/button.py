"""Actions on the unit: reset its alarm, and its filter timer."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from nilan_connect import Key, PointKey

from .data import NilanConfigEntry, NilanData
from .entity import NilanEntity, NilanEntityDescription, describe

# The client sends writes in order, so actions are passed to it as they come.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class NilanButtonDescription(NilanEntityDescription, ButtonEntityDescription):
    """A button that sends one command."""


def _command(point: Key[bool]) -> NilanButtonDescription:
    return NilanButtonDescription(
        key=str(point),
        translation_key=str(point),
        point=point,
        entity_category=EntityCategory.CONFIG,
    )


BUTTONS: tuple[NilanButtonDescription, ...] = (
    _command(PointKey.ALARM_RESET),
    _command(PointKey.FILTER_REPLACE_RESET),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NilanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a button for every described command the unit has."""
    data = entry.runtime_data
    async_add_entities(
        NilanButton(data, description) for description in describe(data, BUTTONS)
    )


class NilanButton(NilanEntity, ButtonEntity):
    """A command: a write with nothing to read back, usable while the gateway answers."""

    def __init__(self, data: NilanData, description: NilanButtonDescription) -> None:
        self.entity_description = description
        self._command = description.point
        super().__init__(data, str(description.point))

    async def async_press(self) -> None:
        await self._write(self._command, True)

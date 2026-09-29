"""The fan level chosen for the unit."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from nilan_connect import Client, Key, PointKey

from .data import NilanConfigEntry, NilanData
from .entity import NilanEntityDescription, NilanPointEntity, describe, shown

# The client sends writes in order and folds a queued setting into a newer one, so actions
# are passed to it as they come.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class NilanSelectDescription(NilanEntityDescription, SelectEntityDescription):
    """A select of one point, whose options are its limits' whole numbers."""


FAN_LEVEL = NilanSelectDescription(
    key=str(PointKey.FAN_LEVEL),
    translation_key=str(PointKey.FAN_LEVEL),
    point=PointKey.FAN_LEVEL,
    entity_registry_visible_default=False,
)

SELECTS: tuple[NilanSelectDescription, ...] = (FAN_LEVEL,)


def levels(client: Client, key: Key[int]) -> list[str]:
    """Every level `key` can be set to, lowest first, by its limits."""
    (point,) = client.select([key])
    limits = point.limits
    if limits is None or limits.min is None or limits.max is None:
        raise ValueError(f"{key} has no limits")
    return [str(level) for level in range(int(limits.min), int(limits.max) + 1)]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NilanConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a select for every described point the unit has."""
    data = entry.runtime_data
    async_add_entities(
        NilanSelect(data, description) for description in describe(data, SELECTS)
    )


class NilanSelect(NilanPointEntity, SelectEntity):
    """One level setting, written to the unit."""

    def __init__(self, data: NilanData, description: NilanSelectDescription) -> None:
        self._attr_options = levels(data.client, description.point)
        if not shown(data.client, PointKey.ENABLE):
            # Without a thermostat, this is where the fan level is set.
            self._attr_entity_registry_visible_default = True
        super().__init__(data, description)

    def _show(self) -> None:
        value = self._current(self._key)
        option = str(value) if isinstance(value, int) else None
        self._attr_current_option = option if option in self._attr_options else None

    async def async_select_option(self, option: str) -> None:
        await self._write(self._key, int(option))

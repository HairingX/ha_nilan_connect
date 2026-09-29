"""Choices: the fan level, and every setting that is one of a set of states."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from nilan_connect import Client, Key, OperationMode, PointKey

from .data import NilanConfigEntry, NilanData
from .entity import NilanEntityDescription, NilanPointEntity, describe, state_name

# The client sends writes in order and folds a queued setting into a newer one, so actions
# are passed to it as they come.
PARALLEL_UPDATES = 0

NOT_CHOSEN: tuple[IntEnum, ...] = (OperationMode.SERVICE,)
"""States a unit is put in some other way: the manual calls the operation mode's SERVICE
"readonly - write to register 1005", the service mode.

Compared by identity: states of different enums with the same number are equal as integers.
"""


@dataclass(frozen=True, kw_only=True)
class NilanSelectDescription(NilanEntityDescription, SelectEntityDescription):
    """A select of one point: a level by its limits' whole numbers, or a state by its name."""


FAN_LEVEL = NilanSelectDescription(
    key=str(PointKey.FAN_LEVEL),
    translation_key=str(PointKey.FAN_LEVEL),
    point=PointKey.FAN_LEVEL,
    entity_registry_visible_default=False,
)


def _choice(point: Key[Any], *, config: bool = True) -> NilanSelectDescription:
    """A setting that is one of the states its point has; an installer's setting unless not
    `config`."""
    return NilanSelectDescription(
        key=str(point),
        translation_key=str(point),
        point=point,
        entity_category=EntityCategory.CONFIG if config else None,
    )


STATE_SELECTS: tuple[NilanSelectDescription, ...] = (
    _choice(PointKey.OPERATION_MODE, config=False),
    _choice(PointKey.AIR_EXCHANGE_MODE),
    _choice(PointKey.TEMP_COOLING_START_OFFSET),
    _choice(PointKey.CONTROL_SENSOR),
    _choice(PointKey.HEAT_SOURCE),
    _choice(PointKey.COMPRESSOR_PRIORITY),
    _choice(PointKey.HOTWATER_SUPPLEMENT),
    _choice(PointKey.ANTILEGIONELLA_DAY),
    _choice(PointKey.CENTRAL_HEAT_MODE),
    _choice(PointKey.CENTRAL_HEAT_SOURCE),
    _choice(PointKey.CENTRAL_HEAT_PUMP_MODE),
    _choice(PointKey.SERVICE_MODE),
    _choice(PointKey.FILTER_REPLACE_INTERVAL_CHOICE),
    _choice(PointKey.EXTRA_SENSOR),
)

SELECTS: tuple[NilanSelectDescription, ...] = (FAN_LEVEL, *STATE_SELECTS)


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
    selects: list[SelectEntity] = [
        NilanLevelSelect(data, description) for description in describe(data, (FAN_LEVEL,))
    ]
    selects.extend(
        NilanStateSelect(data, description) for description in describe(data, STATE_SELECTS)
    )
    async_add_entities(selects)


class NilanLevelSelect(NilanPointEntity, SelectEntity):
    """One level setting, written to the unit."""

    def __init__(self, data: NilanData, description: NilanSelectDescription) -> None:
        self._attr_options = levels(data.client, description.point)
        super().__init__(data, description)

    def _show(self) -> None:
        value = self._current(self._key)
        option = str(value) if isinstance(value, int) else None
        self._attr_current_option = option if option in self._attr_options else None

    async def async_select_option(self, option: str) -> None:
        await self._write(self._key, int(option))


class NilanStateSelect(NilanPointEntity, SelectEntity):
    """One setting that is one of the states its point has, written to the unit."""

    def __init__(self, data: NilanData, description: NilanSelectDescription) -> None:
        (point,) = data.client.select([description.point])
        self._states = {
            state_name(state): state
            for state in point.states
            if all(state is not excluded for excluded in NOT_CHOSEN)
        }
        self._attr_options = list(self._states)
        super().__init__(data, description)

    def _show(self) -> None:
        value = self._current(self._key)
        option = state_name(value) if isinstance(value, IntEnum) else None
        self._attr_current_option = option if option in self._states else None

    async def async_select_option(self, option: str) -> None:
        await self._write(self._key, self._states[option])

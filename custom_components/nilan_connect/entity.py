"""What an entity is made of, and the entity every platform builds on."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription
from nilan_connect import (
    Certainty,
    DataValue,
    InvalidValueError,
    Key,
    Quality,
    Status,
    certainty,
)

from .const import DOMAIN
from .data import NilanData, identity_text, value

_LOGGER = logging.getLogger(__name__)

_USABLE = frozenset({Quality.GOOD, Quality.NO_DATA, Quality.STALE})
"""Qualities an entity shows: a value, "unknown" for no reading, or the last good value.

OFFLINE and MISSING leave the entity unavailable, as does a gateway that stopped answering.
"""


@dataclass(frozen=True, kw_only=True)
class NilanEntityDescription(EntityDescription):
    """Describes the entity of one point; its key and translation key are the point's key."""

    point: Key[Any]


def shown(data: NilanData, key: Key[Any]) -> bool:
    """Whether the unit has `key` at an address read on a unit or found published, or placed by
    its manual's register order when the user has chosen to see those too."""
    if not data.client.has(key):
        return False
    (point,) = data.client.select([key])
    return data.show_inferred or certainty(point) is not Certainty.INFERRED


def state_name(state: IntEnum) -> str:
    """The name a state is shown and translated by."""
    return state.name.lower()


def describe[D: NilanEntityDescription](data: NilanData, descriptions: tuple[D, ...]) -> list[D]:
    """The descriptions of the points this unit shows."""
    return [d for d in descriptions if shown(data, d.point)]


def device_info(data: NilanData) -> DeviceInfo:
    """The unit, identified by its name so that a replaced unit keeps its device."""
    model = data.client.model
    return DeviceInfo(
        identifiers={(DOMAIN, data.name)},
        name=data.name,
        manufacturer=model.manufacturer,
        model=model.name,
        model_id=identity_text(data.client.identity),
    )


def usable(current: DataValue[Any] | None) -> bool:
    """Whether a value may be shown: a reading, no reading, or the last good one."""
    return current is not None and current.quality in _USABLE


class NilanEntity(Entity):
    """An entity kept current by the client's subscriptions; it is never polled by HA.

    A subclass sets its `_attr_` values in `_show`, which runs here, before HA reads the
    entity's capabilities, and then on every change of a watched key and of whether the
    gateway answers. What `_show` uses is set before calling this constructor.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, data: NilanData, unique_key: str) -> None:
        """`unique_key` follows the unit's name in the unique id."""
        self._client = data.client
        self._attr_unique_id = f"{data.name}_{unique_key}"
        self._attr_device_info = device_info(data)
        data.unique_ids.add(self._attr_unique_id)
        self._added = False
        self._changed()

    def _watched(self) -> tuple[Key[Any], ...]:
        """Every key whose change changes this entity's state."""
        return ()

    def _required(self) -> tuple[Key[Any], ...]:
        """The watched keys without whose value the entity is unavailable."""
        return self._watched()

    async def async_update(self) -> None:
        """Read this entity's values from the unit now."""
        await self._client.refresh(list(self._watched()))

    def _show(self) -> None:
        """Set this entity's state from the client's current values."""

    async def async_added_to_hass(self) -> None:
        """Follow the watched keys and whether the gateway answers."""
        for key in self._watched():
            self.async_on_remove(self._client.subscribe(key, self._on_value))
        self.async_on_remove(
            self._client.subscribe_status(Status.CONNECTED, self._on_status)
        )
        # Each subscription has told its current value; HA writes the state once this returns.
        self._added = True

    @callback
    def _on_value(
        self, key: Key[Any], old: DataValue[Any] | None, new: DataValue[Any]
    ) -> None:
        self._changed()

    @callback
    def _on_status(
        self, status: Status, old: DataValue[bool] | None, new: DataValue[bool]
    ) -> None:
        self._changed()

    @callback
    def _changed(self) -> None:
        """Recompute the state: available while the gateway answers and every required value
        can be shown."""
        self._attr_available = self._client.status(Status.CONNECTED).value is True and all(
            usable(self._client.value(key)) for key in self._required()
        )
        self._show()
        if self._added:
            self.async_write_ha_state()

    def _current[T](self, key: Key[T]) -> T | None:
        return value(self._client, key)

    async def _write[T](self, key: Key[T], new: T) -> None:
        """Write `new` to `key`, raising an error the user can read when it is not taken."""
        _LOGGER.debug("Writing %s = %r", key, new)
        try:
            accepted = await self._client.write(key, new)
        except InvalidValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_value",
                translation_placeholders={"value": str(new)},
            ) from err
        _LOGGER.debug("Wrote %s = %r: %s", key, new, "taken" if accepted else "not taken")
        if not accepted:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="write_refused"
            )


class NilanPointEntity(NilanEntity):
    """The entity of one point."""

    def __init__(self, data: NilanData, description: NilanEntityDescription) -> None:
        self.entity_description = description
        self._key = description.point
        super().__init__(data, str(description.point))

    def _watched(self) -> tuple[Key[Any], ...]:
        return (self._key,)

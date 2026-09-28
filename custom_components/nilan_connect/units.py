"""The units of Nilan values, as Home Assistant spells them."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from homeassistant.const import UnitOfRatio, UnitOfTemperature, UnitOfTime
from nilan_connect import Client, Key, Unit

HA_UNITS: Mapping[Unit, str] = MappingProxyType(
    {
        Unit.CELSIUS: UnitOfTemperature.CELSIUS,
        Unit.PERCENT: UnitOfRatio.PERCENTAGE,
        Unit.PPM: UnitOfRatio.PARTS_PER_MILLION,
        Unit.MINUTES: UnitOfTime.MINUTES,
        Unit.DAYS: UnitOfTime.DAYS,
    }
)
"""Every unit a Nilan value has."""


def ha_unit(client: Client, key: Key[Any]) -> str | None:
    """The unit of `key`'s value, or None when it has none."""
    (point,) = client.select([key])
    return HA_UNITS[point.unit] if point.unit is not None else None

"""What a bug report needs to show the unit works: the versions, the unit's model, every value with
its quality, what is missing, the latest writes with how each ended, how the gateway answers, the
points tried at the Test level, and the unit's stored mappings."""

from __future__ import annotations

from datetime import date, time
from enum import Enum
from importlib import metadata
from typing import Any, cast

from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration
from nilan_connect import Client, DataValue, Key, Status

from .const import CONF_EMAIL, CONF_GATEWAY_ID, DOMAIN
from .data import NilanConfigEntry
from .mapping import load_mappings

REDACTED = "**REDACTED**"

REDACTED_SETTINGS = frozenset({CONF_EMAIL, CONF_HOST, CONF_GATEWAY_ID})
"""The credential, and what locates or identifies the gateway."""

LIBRARIES = ("nilan_connect", "modbus_event_connect", "event_connect")
"""The libraries whose installed versions a report names."""


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: NilanConfigEntry
) -> dict[str, Any]:
    """The client's picture of the unit, the writes sent to it and how the gateway has answered,
    without the email or where the gateway is.

    The entry's unique id is left out: it is the gateway's id. `writes` holds the latest writes
    of each key, the newest last, each with how it ended and the first read of the key after it.
    `test` lists each candidate the unit uses, with its value, its certainty and the key it
    replaces, and each inferred point, with its value. `mappings` holds the unit's latest
    mappings as stored, the oldest first; nothing is read from the unit for them.
    """
    client = entry.runtime_data.client
    integration = await async_get_integration(hass, DOMAIN)
    library = dict(client.diagnostics())
    level = library.pop("level")
    writes = library.pop("writes")
    certainty = cast(dict[str, str], library.pop("certainty", {}))
    candidates = cast(dict[str, str | None], library.pop("candidates", {}))
    read = {str(key): _plain(current.value) for key, current in client.values.items()}
    return {
        "entry": {
            "version": entry.version,
            "minor_version": entry.minor_version,
            "data": {
                key: REDACTED if key in REDACTED_SETTINGS else setting
                for key, setting in entry.data.items()
            },
            "options": dict(entry.options),
            "polling_disabled": entry.pref_disable_polling,
        },
        "integration_version": None if integration.version is None else str(integration.version),
        "libraries": {name: _version(name) for name in LIBRARIES},
        "model": client.model.name,
        "identity": dict(client.identity),
        "level": level,
        "status": {status.name: client.status(status).value for status in Status},
        "seconds_until_next_poll": client.seconds_until_next_poll(),
        "silent": client.silent,
        "silent_for": client.silent_for,
        "values": {
            str(key): _value(client, key, current)
            for key, current in sorted(client.values.items())
        },
        "unavailable": {
            str(key): reason for key, reason in sorted(client.unavailable_reasons.items())
        },
        "writes": writes,
        "certainty": certainty,
        "test": {
            "candidates": {
                key: {
                    "value": read.get(key),
                    "certainty": certainty[key],
                    "replaces": replaces,
                }
                for key, replaces in candidates.items()
            },
            "inferred": {
                key: {"value": read.get(key)}
                for key, found in certainty.items()
                if found == "inferred" and key not in candidates
            },
        },
        "gateway": library,
        "mappings": await load_mappings(hass, entry.entry_id),
    }


def _value(client: Client, key: Key[Any], current: DataValue[Any]) -> dict[str, Any]:
    """`current`, the value of `key`, as plain data: when the gateway last answered it, and how
    many reads of it have failed since."""
    point = client.points.get(key)
    return {
        "value": _plain(current.value),
        "raw": list(current.raw),
        "quality": current.quality.name,
        "certainty": None if point is None else str(point.certainty),
        "at": current.timestamp.isoformat(),
        "consecutive_failures": client.consecutive_failures(str(key)),
    }


def _plain(value: object) -> object:
    """`value` as JSON holds it: a state by its name, a time in ISO 8601."""
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, (date, time)):
        return value.isoformat()
    return value


def _version(name: str) -> str | None:
    """The installed version of the package `name`; None if it is not installed."""
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None

"""What a bug report needs: the unit's model, every value with its quality, and what is missing."""

from __future__ import annotations

from importlib import metadata
from typing import Any

from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from nilan_connect import Status

from .const import CONF_EMAIL, CONF_GATEWAY_ID
from .data import NilanConfigEntry

REDACTED = "**REDACTED**"

REDACTED_SETTINGS = frozenset({CONF_EMAIL, CONF_HOST, CONF_GATEWAY_ID})
"""The credential, and what locates or identifies the gateway."""

LIBRARIES = ("nilan_connect", "modbus_event_connect", "event_connect")
"""The libraries whose installed versions a report names."""


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: NilanConfigEntry
) -> dict[str, Any]:
    """The client's picture of the unit and how the gateway has answered, without the email or
    where the gateway is.

    The entry's unique id is left out: it is the gateway's id.
    """
    client = entry.runtime_data.client
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
        "libraries": {name: _version(name) for name in LIBRARIES},
        "model": client.model.name,
        "identity": dict(client.identity),
        "status": {status.name: client.status(status).value for status in Status},
        "seconds_until_next_poll": client.seconds_until_next_poll(),
        "silent": client.silent,
        "silent_for": client.silent_for,
        "gateway": dict(client.diagnostics()),
        "values": {
            str(key): {
                "value": current.value,
                "quality": current.quality.name,
                "raw": list(current.raw),
                "at": current.timestamp.isoformat(),
                "consecutive_failures": client.consecutive_failures(str(key)),
            }
            for key, current in sorted(client.values.items())
        },
        "unavailable": {
            str(key): reason for key, reason in sorted(client.unavailable_reasons.items())
        },
    }


def _version(name: str) -> str | None:
    """The installed version of the package `name`; None if it is not installed."""
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None

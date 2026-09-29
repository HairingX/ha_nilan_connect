"""What a bug report needs: the unit's model, every value with its quality, and what is missing."""

from __future__ import annotations

from typing import Any

from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from nilan_connect import Status

from .const import CONF_EMAIL, CONF_GATEWAY_ID
from .data import NilanConfigEntry

REDACTED = "**REDACTED**"

REDACTED_SETTINGS = frozenset({CONF_EMAIL, CONF_HOST, CONF_GATEWAY_ID})
"""The credential, and what locates or identifies the gateway."""


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: NilanConfigEntry
) -> dict[str, Any]:
    """The client's picture of the unit, without the email or where the gateway is.

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
        },
        "model": client.model.name,
        "status": {status.name: client.status(status).value for status in Status},
        "values": {
            str(key): {
                "value": current.value,
                "quality": current.quality.name,
                "raw": list(current.raw),
            }
            for key, current in sorted(client.values.items())
        },
        "unavailable": {
            str(key): reason for key, reason in sorted(client.unavailable_reasons.items())
        },
    }

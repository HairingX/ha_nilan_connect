"""The Nilan Connect integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
)
from homeassistant.helpers import entity_registry as er
from nilan_connect import (
    AuthenticationError,
    CannotConnectError,
    Client,
    Key,
    UnsupportedDeviceError,
    discover,
)

from . import const
from .const import CONF_EMAIL, CONF_GATEWAY_ID, DEFAULT_PORT, DOMAIN, POLL_TICK
from .data import NilanConfigEntry, NilanData, new_client

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Bring an entry of an earlier version to this one.

    Version 1 kept the unit's name as `device_id`, and the address only when it was entered by
    hand; without one, the name was the gateway's id, which it was found by.
    """
    if entry.version == 1:
        old = entry.data
        host = str(old.get("device_ip") or "").strip() or None
        hass.config_entries.async_update_entry(
            entry,
            data={
                CONF_NAME: old["device_id"],
                CONF_EMAIL: old["authorized_email"],
                CONF_HOST: host,
                CONF_PORT: int(old.get("device_port") or DEFAULT_PORT),
                CONF_GATEWAY_ID: old["device_id"] if host is None else None,
            },
            version=2,
            minor_version=1,
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: NilanConfigEntry) -> bool:
    """Connect to the gateway, create the unit's entities and start reading it."""
    name: str = entry.data[CONF_NAME]
    client = new_client(
        entry.data[CONF_EMAIL],
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        entry.data[CONF_GATEWAY_ID],
    )
    try:
        await client.connect()
    except AuthenticationError as err:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="email_refused",
            translation_placeholders={"name": name},
        ) from err
    except CannotConnectError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"name": name},
        ) from err
    except UnsupportedDeviceError as err:
        _LOGGER.warning("%s is not a supported Nilan controller: %s", name, err)
        raise ConfigEntryError(
            translation_domain=DOMAIN, translation_key="unsupported_device"
        ) from err

    try:
        await _identify_gateway(hass, entry)
        entry.runtime_data = NilanData(client=client, name=name)
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        _remove_lost_entities(hass, entry)
    except BaseException:
        await client.disconnect()
        raise

    _reload_when_the_unit_changes(hass, entry)
    # With polling disabled in the entry's system options, only what is asked for is read:
    # homeassistant.update_entity, and the read-back of a write. Changing it reloads the entry.
    client.set_scheduled_polling(not entry.pref_disable_polling)
    # Polling starts once the entities have subscribed: the client reads what is wanted.
    entry.runtime_data.poller = entry.async_create_background_task(
        hass, _poll(client), f"{DOMAIN} poll {entry.title}"
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NilanConfigEntry) -> bool:
    """Stop reading the unit and let go of the gateway."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    data = entry.runtime_data
    if data.poller is not None:
        # Stopped before the disconnect, so no read runs against a closing connection.
        data.poller.cancel()
        await asyncio.wait([data.poller])
    await data.client.disconnect()
    return True


async def _identify_gateway(hass: HomeAssistant, entry: NilanConfigEntry) -> None:
    """Learn the id of a gateway set up by its address, and make the id the entry's unique id.

    With the id, the client finds the gateway again when its address changes. A gateway that
    does not answer the discovery is asked again at the next setup.
    """
    gateway_id: str | None = entry.data[CONF_GATEWAY_ID]
    if gateway_id is None:
        found = await discover(
            timeout=const.DISCOVERY_TIMEOUT,
            target=(entry.data[CONF_HOST], entry.data[CONF_PORT]),
        )
        if len(found) != 1:
            return
        gateway_id = found[0].device_id
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_GATEWAY_ID: gateway_id}
        )
    if (
        entry.unique_id != gateway_id
        and hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, gateway_id)
        is None
    ):
        hass.config_entries.async_update_entry(entry, unique_id=gateway_id)


@callback
def _remove_lost_entities(hass: HomeAssistant, entry: NilanConfigEntry) -> None:
    """Remove the entities of points the unit no longer has."""
    registry = er.async_get(hass)
    built = entry.runtime_data.unique_ids
    for found in er.async_entries_for_config_entry(registry, entry.entry_id):
        if found.unique_id not in built:
            registry.async_remove(found.entity_id)


def _reload_when_the_unit_changes(hass: HomeAssistant, entry: NilanConfigEntry) -> None:
    """Reload the entry when the controller gains or loses points."""
    reloading = False

    @callback
    def points_changed(gained: frozenset[Key[Any]], lost: frozenset[Key[Any]]) -> None:
        nonlocal reloading
        if not reloading:
            reloading = True
            _LOGGER.info("The points of %s have changed; reloading it", entry.title)
            hass.config_entries.async_schedule_reload(entry.entry_id)

    entry.async_on_unload(entry.runtime_data.client.subscribe_points(points_changed))


async def _poll(client: Client) -> None:
    """Read whatever the client has due, for as long as the entry is loaded."""
    while True:
        try:
            await client.poll()
        except Exception:
            _LOGGER.exception("Reading the unit failed")
            delay = POLL_TICK
        else:
            delay = client.seconds_until_next_poll()
        await asyncio.sleep(POLL_TICK if delay is None else min(delay, POLL_TICK))

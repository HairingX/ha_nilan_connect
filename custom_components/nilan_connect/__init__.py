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
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from nilan_connect import (
    MODELS,
    OPTIMA_301,
    OPTIMA_312,
    OPTIMA_314,
    AuthenticationError,
    CannotConnectError,
    Certainty,
    Client,
    Key,
    Level,
    PointKey,
    UnsupportedDeviceError,
    discover,
    model_points,
)

from .const import (
    CONF_EMAIL,
    CONF_GATEWAY_ID,
    CONF_LEVEL,
    DEFAULT_LEVEL,
    DEFAULT_PORT,
    DOMAIN,
    SHOW_INFERRED,
    TEST_REPORT_URL,
    TESTING_ISSUE,
)
from .binary_sensor import BINARY_SENSORS
from .button import BUTTONS
from .climate import CONTROLS, THERMOSTAT
from .data import NilanConfigEntry, NilanData, identity_text, new_client
from .entity import NilanEntityDescription
from .mapping import remove_mappings
from .number import NUMBERS
from .select import SELECTS
from .sensor import EFFICIENCY, EFFICIENCY_FROM, SENSORS
from .switch import SWITCHES

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

RENAMED: tuple[tuple[frozenset[str], Platform, Key[Any], Key[Any]], ...] = (
    (
        frozenset({OPTIMA_301.name, OPTIMA_312.name, OPTIMA_314.name}),
        Platform.SENSOR,
        PointKey.TEMP_BEFORE_CONDENSER,
        PointKey.TEMP_BEFORE_EVAPORATOR,
    ),
    (
        frozenset({OPTIMA_301.name, OPTIMA_312.name}),
        Platform.SENSOR,
        PointKey.TEMP_ROOM,
        PointKey.TEMP_ROOM_PANEL,
    ),
)
"""The points the models of these names give a new key, on the same platform, for the same
register and meaning: on those models, the entity of the old key becomes the new key's."""

DESCRIBED: dict[str, tuple[NilanEntityDescription, ...]] = {
    Platform.BINARY_SENSOR: BINARY_SENSORS,
    Platform.BUTTON: BUTTONS,
    Platform.NUMBER: NUMBERS,
    Platform.SELECT: SELECTS,
    Platform.SENSOR: SENSORS,
    Platform.SWITCH: SWITCHES,
}
"""The entity of each point, by platform."""

PLATFORM_OF: dict[str, str] = {
    str(description.point): platform
    for platform, descriptions in DESCRIBED.items()
    for description in descriptions
}
"""The platform of each point's entity."""


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Bring an entry of an earlier version to this one.

    Version 1 kept the unit's name as `device_id`, and the address only when it was entered by
    hand; without one, the name was the gateway's id, which it was found by. Minor version 1
    chose whether to show values placed only by the manual's register order where the level
    is chosen now: showing them on a unit that has them is the Test level; not showing them, or
    a unit without them, where the option changed nothing, the Documented.
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
    if entry.version == 2 and entry.minor_version == 1:
        options = {key: setting for key, setting in entry.options.items() if key != SHOW_INFERRED}
        shown = bool(entry.options.get(SHOW_INFERRED)) and _has_inferred_points(hass, entry)
        level = Level.TEST if shown else Level.DOCUMENTED
        hass.config_entries.async_update_entry(
            entry, options={**options, CONF_LEVEL: str(level)}, minor_version=2
        )
    return True


def _has_inferred_points(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Whether the model the entry's device was registered with has a point placed only by its
    manual's register order."""
    names = {device.model for device in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)}
    return any(
        point.certainty is Certainty.INFERRED
        for model in MODELS
        if model.name in names
        for point in model_points(model)
    )


async def async_setup_entry(hass: HomeAssistant, entry: NilanConfigEntry) -> bool:
    """Connect to the gateway, create the unit's entities and start reading it."""
    name: str = entry.data[CONF_NAME]
    client = new_client(
        entry.data[CONF_EMAIL],
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        entry.data[CONF_GATEWAY_ID],
        level=Level(entry.options.get(CONF_LEVEL, DEFAULT_LEVEL)),
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
            translation_domain=DOMAIN,
            translation_key="unsupported_device",
            translation_placeholders={"identity": identity_text(err.identity)},
        ) from err

    try:
        await _keep_renamed_entities(hass, entry, name, client.model.name)
        await _identify_gateway(hass, entry)
        entry.runtime_data = NilanData(client=client, name=name)
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        _remove_lost_entities(hass, entry)
        _ask_testers_to_report(hass, entry, client)
    except BaseException:
        await client.disconnect()
        raise

    _reload_when_the_unit_changes(hass, entry)
    # With polling disabled in the entry's system options, only what is asked for is read:
    # homeassistant.update_entity, and the read-back of a write. Changing it reloads the entry.
    client.set_scheduled_polling(not entry.pref_disable_polling)
    # Polling starts once the entities have subscribed: the client reads what is wanted.
    entry.runtime_data.poller = entry.async_create_background_task(
        hass, client.run(), f"{DOMAIN} poll {entry.title}"
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


async def async_remove_entry(hass: HomeAssistant, entry: NilanConfigEntry) -> None:
    """Remove the unit's stored mappings with its entry."""
    await remove_mappings(hass, entry.entry_id)


@callback
def _ask_testers_to_report(hass: HomeAssistant, entry: NilanConfigEntry, client: Client) -> None:
    """At the Test level, raise an issue asking the user to report whether the points not
    confirmed on the unit's model match its panel; at any other level, or with no such point,
    remove it.

    It is not removed when the entry unloads, which would forget that the user ignored it; Home
    Assistant removes it with the entry.
    """
    issue_id = f"{TESTING_ISSUE}_{entry.entry_id}"
    testing = any(
        point.candidate is not None or point.certainty is Certainty.INFERRED
        for point in client.points.values()
    )
    if client.level is not Level.TEST or not testing:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        config_entry_id=entry.entry_id,
        is_fixable=False,
        learn_more_url=TEST_REPORT_URL,
        severity=ir.IssueSeverity.WARNING,
        translation_key=TESTING_ISSUE,
        translation_placeholders={
            "name": entry.title,
            "model": client.model.name,
            "report_url": TEST_REPORT_URL,
        },
    )


async def _identify_gateway(hass: HomeAssistant, entry: NilanConfigEntry) -> None:
    """Learn the id of a gateway set up by its address, and make the id the entry's unique id.

    With the id, the client finds the gateway again when its address changes. A gateway that
    does not answer the discovery is asked again at the next setup.
    """
    gateway_id: str | None = entry.data[CONF_GATEWAY_ID]
    if gateway_id is None:
        found = await discover(target=entry.data[CONF_HOST], port=entry.data[CONF_PORT])
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


async def _keep_renamed_entities(
    hass: HomeAssistant, entry: NilanConfigEntry, name: str, model: str
) -> None:
    """Give the entity of a point the unit's model has renamed the new key's unique id, so that
    it keeps its entity id and history.

    Where the new key's entity exists already, the old one is left to be removed as lost.
    """
    renamed = {
        (str(platform), f"{name}_{old}"): f"{name}_{new}"
        for models, platform, old, new in RENAMED
        if model in models
    }
    if not renamed:
        return
    registry = er.async_get(hass)

    @callback
    def rename(found: er.RegistryEntry) -> dict[str, Any] | None:
        unique_id = renamed.get((found.domain, found.unique_id))
        if unique_id is None or registry.async_get_entity_id(found.domain, DOMAIN, unique_id):
            return None
        return {"new_unique_id": unique_id}

    await er.async_migrate_entries(hass, entry.entry_id, rename)


@callback
def _remove_lost_entities(hass: HomeAssistant, entry: NilanConfigEntry) -> None:
    """Remove the entities of points the unit has at no level.

    An entity the chosen level leaves out stays in the registry, with its name and settings, for
    a level that has it again.
    """
    registry = er.async_get(hass)
    data = entry.runtime_data
    for found in er.async_entries_for_config_entry(registry, entry.entry_id):
        suffix = found.unique_id.removeprefix(f"{data.name}_")
        if found.unique_id not in data.unique_ids and not _at_some_level(data.client, found.domain, suffix):
            registry.async_remove(found.entity_id)


def _at_some_level(client: Client, platform: str, suffix: str) -> bool:
    """Whether the unit has, at some level, the entity of `platform` whose unique id ends with
    `suffix` after the unit's name."""
    keys = client.model.keys - set(client.unavailable_reasons)
    if (platform, suffix) == (Platform.CLIMATE, THERMOSTAT):
        return any(key in keys for key in CONTROLS)
    if (platform, suffix) == (Platform.SENSOR, EFFICIENCY):
        return all(key in keys for key in EFFICIENCY_FROM)
    return suffix in keys and PLATFORM_OF.get(suffix) == platform


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


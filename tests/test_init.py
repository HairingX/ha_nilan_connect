"""Loading and unloading a unit's config entry, and entries of the earlier version."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from nilan_connect import Client, DiscoveredDevice, Key, Status
from nilan_connect.testing import SimulatedMicroNabtoDevice
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.nilan_connect as integration
from custom_components.nilan_connect.const import (
    CONF_EMAIL,
    CONF_GATEWAY_ID,
    DEFAULT_PORT,
    DOMAIN,
)
from custom_components.nilan_connect.data import NilanData

from .conftest import EMAIL, GATEWAY_ID, HOST, NAME, entry_data, simulated_gateway


async def set_up(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_a_gateway_that_does_not_answer_is_retried_later(
    hass: HomeAssistant, config_entry: MockConfigEntry, gateway: SimulatedMicroNabtoDevice
) -> None:
    gateway.silent = True
    await set_up(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_a_refused_email_asks_the_user_for_the_email(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=GATEWAY_ID,
        data=entry_data(gateway, **{CONF_EMAIL: "old@example.invalid"}),
        version=2,
    )
    await set_up(hass, entry)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert [
        flow.get("context", {}).get("source") for flow in hass.config_entries.flow.async_progress()
    ] == ["reauth"]


async def test_a_controller_that_is_not_supported_is_not_set_up(hass: HomeAssistant) -> None:
    other = simulated_gateway(identity={
        "device_number": 1, "device_model": 9999, "slave_device_number": 1, "slave_device_model": 1
    })
    async with other:
        entry = MockConfigEntry(domain=DOMAIN, data=entry_data(other), version=2)
        await set_up(hass, entry)
    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_unloading_stops_reading_and_lets_go_of_the_gateway(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    await set_up(hass, config_entry)
    data: NilanData = config_entry.runtime_data
    assert data.poller is not None
    await unload(hass, config_entry)
    assert data.poller.done()
    assert data.client.status(Status.CONNECTED).value is False


async def test_a_failure_after_connecting_lets_go_of_the_gateway(
    hass: HomeAssistant,
    gateway: SimulatedMicroNabtoDevice,
    monkeypatch: pytest.MonkeyPatch,
    simulated_network: list[Client],
) -> None:
    async def broken(**_: Any) -> list[DiscoveredDevice]:
        raise RuntimeError("broken")

    monkeypatch.setattr(integration, "discover", broken)
    entry = MockConfigEntry(
        domain=DOMAIN, data=entry_data(gateway, **{CONF_GATEWAY_ID: None}), version=2
    )
    await set_up(hass, entry)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    (client,) = simulated_network
    assert client.status(Status.CONNECTED).value is False


async def test_the_gateway_is_kept_while_the_platforms_do_not_unload(
    hass: HomeAssistant, config_entry: MockConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    await set_up(hass, config_entry)

    async def refuse(*_: Any) -> bool:
        return False

    with monkeypatch.context() as patched:
        patched.setattr(hass.config_entries, "async_unload_platforms", refuse)
        assert not await integration.async_unload_entry(hass, config_entry)
    assert config_entry.runtime_data.client.status(Status.CONNECTED).value is True
    await unload(hass, config_entry)


async def test_an_entity_of_a_point_the_unit_no_longer_has_is_removed(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    lost = registry.async_get_or_create(
        "sensor", DOMAIN, f"{NAME}_temp_condenser", config_entry=config_entry
    )
    await set_up(hass, config_entry)
    assert registry.async_get(lost.entity_id) is None
    await unload(hass, config_entry)


async def test_the_entry_reloads_once_when_the_unit_gains_or_loses_points(
    hass: HomeAssistant, config_entry: MockConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    callbacks: list[Callable[[frozenset[Key[Any]], frozenset[Key[Any]]], None]] = []

    def record(client: Client, callback: Any) -> Callable[[], None]:
        callbacks.append(callback)
        return lambda: None

    monkeypatch.setattr(Client, "subscribe_points", record)
    reloads: list[str] = []
    monkeypatch.setattr(hass.config_entries, "async_schedule_reload", reloads.append)
    await set_up(hass, config_entry)
    (changed,) = callbacks
    changed(frozenset(), frozenset())
    changed(frozenset(), frozenset())
    assert reloads == [config_entry.entry_id]
    await unload(hass, config_entry)


async def test_a_failing_poll_is_logged_and_polling_goes_on(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    polls = 0

    async def failing(client: Client) -> None:
        nonlocal polls
        polls += 1
        raise RuntimeError("broken")

    monkeypatch.setattr(integration, "POLL_TICK", 0.01)
    monkeypatch.setattr(Client, "poll", failing)
    await set_up(hass, config_entry)
    for _ in range(100):
        if polls >= 2:
            break
        await asyncio.sleep(0.01)
    assert polls >= 2
    assert "Reading the unit failed" in caplog.text
    await unload(hass, config_entry)


async def test_with_polling_disabled_nothing_is_read_on_a_schedule(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=GATEWAY_ID,
        data=entry_data(gateway),
        version=2,
        pref_disable_polling=True,
    )
    await set_up(hass, entry)
    data: NilanData = entry.runtime_data
    assert data.client.seconds_until_next_poll() is None
    await unload(hass, entry)


# ============================================================================== migration


def version_1(gateway: SimulatedMicroNabtoDevice, **data: Any) -> MockConfigEntry:
    """An entry as the earlier version made it."""
    return MockConfigEntry(
        domain=DOMAIN, title=NAME, data={"authorized_email": EMAIL, **data}, version=1
    )


async def test_an_entry_set_up_by_address_keeps_its_name_and_learns_its_gateways_id(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    entry = version_1(
        gateway, device_id=NAME, device_ip=HOST, device_port=gateway.address[1]
    )
    await set_up(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert (entry.version, entry.minor_version) == (2, 1)
    assert dict(entry.data) == entry_data(gateway)
    assert entry.unique_id == GATEWAY_ID
    await unload(hass, entry)


async def test_an_entry_found_by_discovery_was_named_after_its_gateway(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    entry = version_1(gateway, device_id=GATEWAY_ID)
    await set_up(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert dict(entry.data) == {
        CONF_NAME: GATEWAY_ID,
        CONF_EMAIL: EMAIL,
        CONF_HOST: None,
        CONF_PORT: DEFAULT_PORT,
        CONF_GATEWAY_ID: GATEWAY_ID,
    }
    assert entry.unique_id == GATEWAY_ID
    await unload(hass, entry)


async def test_an_entry_with_an_empty_address_is_found_by_discovery(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    """The earlier version's reconfigure could store an empty address."""
    entry = version_1(gateway, device_id=GATEWAY_ID, device_ip=" ", device_port=5570)
    await set_up(hass, entry)
    assert entry.data[CONF_HOST] is None
    assert entry.state is ConfigEntryState.LOADED
    await unload(hass, entry)


async def test_an_entry_of_a_later_version_is_not_set_up(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={}, version=3)
    await set_up(hass, entry)
    assert entry.state is ConfigEntryState.MIGRATION_ERROR


async def test_a_gateway_that_does_not_answer_discovery_keeps_the_entry_without_an_id(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def nothing(**_: Any) -> list[DiscoveredDevice]:
        return []

    monkeypatch.setattr(integration, "discover", nothing)
    entry = version_1(gateway, device_id=NAME, device_ip=HOST, device_port=gateway.address[1])
    await set_up(hass, entry)
    assert entry.data[CONF_GATEWAY_ID] is None
    assert entry.unique_id is None
    await unload(hass, entry)


async def test_a_gateway_id_another_entry_has_is_not_taken_as_the_unique_id(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    MockConfigEntry(
        domain=DOMAIN, unique_id=GATEWAY_ID, data=entry_data(gateway, **{CONF_NAME: "Other"}),
        version=2, disabled_by=None,
    ).add_to_hass(hass)
    entry = version_1(gateway, device_id=NAME, device_ip=HOST, device_port=gateway.address[1])
    await set_up(hass, entry)
    assert entry.data[CONF_GATEWAY_ID] == GATEWAY_ID
    assert entry.unique_id is None
    await unload(hass, entry)

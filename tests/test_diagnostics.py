"""What a unit's diagnostics hold, and what they leave out."""

from __future__ import annotations

import json
from importlib import metadata

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant.common import MockConfigEntry

from nilan_connect.testing import FakeClock, SimulatedMicroNabtoDevice

from custom_components.nilan_connect.data import NilanData
from custom_components.nilan_connect.diagnostics import async_get_config_entry_diagnostics

from .conftest import EMAIL, GATEWAY_ID, HOST, NAME
from .test_entities import entity_id, refresh


async def test_diagnostics_hold_every_value_but_not_the_email_or_where_the_gateway_is(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry
) -> None:
    found = await async_get_config_entry_diagnostics(hass, config_entry)
    assert found["entry"]["data"]["email"] == "**REDACTED**"
    assert found["entry"]["data"]["host"] == "**REDACTED**"
    assert found["entry"]["data"]["gateway_id"] == "**REDACTED**"
    assert found["entry"]["data"]["name"] == NAME
    assert (found["model"], found["level"]) == ("CTS 400", "documented")
    assert found["identity"] == {
        "device_number": 72280, "device_model": 1140, "slave_device_number": 72270, "slave_device_model": 1}
    assert found["status"]["CONNECTED"] is True
    temp_outside = found["values"]["temp_outside"]
    assert (temp_outside["value"], temp_outside["quality"], temp_outside["raw"]) == (15.2, "GOOD", [152])
    assert (temp_outside["certainty"], temp_outside["consecutive_failures"]) == ("verified", 0)
    assert temp_outside["at"]
    assert found["values"]["extra_sensor"]["value"] == "NONE"
    text = repr(found)
    assert EMAIL not in text and GATEWAY_ID not in text and HOST not in text


async def test_diagnostics_hold_how_the_gateway_has_answered_and_the_versions(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry
) -> None:
    found = await async_get_config_entry_diagnostics(hass, config_entry)
    assert found["integration_version"] == "0.0.0"
    assert found["libraries"] == {
        "nilan_connect": metadata.version("nilan_connect"),
        "modbus_event_connect": metadata.version("modbus_event_connect"),
        "event_connect": metadata.version("event_connect"),
    }
    assert (found["silent"], found["silent_for"]) == (False, 0.0)
    gateway = found["gateway"]
    assert gateway["connected"] is True and gateway["answered"] > 0
    for counter in ("average_latency", "max_latency", "silences", "refusals", "answers_of_only_zeros",
                    "zeros_ended", "largest_read_with_values"):
        assert counter in gateway
    breaker = ("open", "open_for", "openings", "gave_up", "refused_while_open")
    assert [gateway[key] for key in breaker] == [False, 0.0, 0, False, 0]
    assert not {"level", "writes", "certainty", "candidates"} & set(gateway)
    assert found["entry"]["polling_disabled"] is False and "options" in found["entry"]


async def test_a_library_not_installed_has_no_version(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing(name: str) -> str:
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(metadata, "version", missing)
    found = await async_get_config_entry_diagnostics(hass, config_entry)
    assert found["libraries"] == {"nilan_connect": None, "modbus_event_connect": None, "event_connect": None}


async def test_a_values_failed_reads_are_counted_afresh_once_the_gateway_answers_again(
    hass: HomeAssistant,
    loaded: NilanData,
    config_entry: MockConfigEntry,
    gateway: SimulatedMicroNabtoDevice,
    clock: FakeClock,
) -> None:
    """The gateway answers a setting's read, held in other registers than the outdoor
    temperature's."""
    outdoor = entity_id(hass, "sensor", "temp_outside")
    gateway.silent = True
    for _ in range(2):
        await refresh(hass, outdoor)
        clock.advance(10)
    found = await async_get_config_entry_diagnostics(hass, config_entry)
    assert found["values"]["temp_outside"]["consecutive_failures"] == 2
    gateway.silent = False
    clock.advance(60)  # past the client's wait before it tries the gateway again
    await refresh(hass, entity_id(hass, "number", "temp_target"))
    found = await async_get_config_entry_diagnostics(hass, config_entry)
    assert found["values"]["temp_outside"]["consecutive_failures"] == 0


async def test_a_write_shows_that_the_unit_took_it_and_what_it_read_back(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, clock: FakeClock
) -> None:
    target = entity_id(hass, "number", "temp_target")
    await hass.services.async_call("number", "set_value", {"entity_id": target, "value": 21.5}, blocking=True)
    clock.advance(5)
    await refresh(hass, target)
    found = await async_get_config_entry_diagnostics(hass, config_entry)
    (record,) = found["writes"]["temp_target"]
    assert (record["value"], record["raw"], record["attempts"]) == (21.5, [215], 1)
    assert (record["outcome"], record["detail"]) == ("taken", "")
    assert record["sent_at"] and record["ended_at"]
    read_back = record["read_back"]
    assert (read_back["value"], read_back["quality"], read_back["raw"]) == (21.5, "GOOD", [215])
    assert read_back["at"] > record["ended_at"]


async def test_diagnostics_of_every_point_and_a_write_hold_nothing_that_locates_or_identifies(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, clock: FakeClock
) -> None:
    """Every point is read, as a real unit answered; the gateway's address and id and the email
    are what locate or identify it."""
    client = loaded.client
    await client.refresh()
    target = entity_id(hass, "number", "temp_target")
    await hass.services.async_call("number", "set_value", {"entity_id": target, "value": 21.5}, blocking=True)
    clock.advance(5)
    await client.refresh()
    found = await async_get_config_entry_diagnostics(hass, config_entry)
    text = json.dumps(found)  # raises for anything JSON cannot hold
    assert set(found["values"]) == {str(key) for key, point in client.points.items() if point.readable}
    assert found["writes"]["temp_target"][0]["read_back"] is not None
    for secret in (EMAIL, GATEWAY_ID, HOST):
        assert secret not in text, secret

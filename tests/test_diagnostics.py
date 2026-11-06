"""What a unit's diagnostics hold, and what they leave out."""

from __future__ import annotations

from importlib import metadata

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant.common import MockConfigEntry

from custom_components.nilan_connect.data import NilanData
from custom_components.nilan_connect.diagnostics import async_get_config_entry_diagnostics

from .conftest import EMAIL, GATEWAY_ID, HOST, NAME


async def test_diagnostics_hold_every_value_but_not_the_email_or_where_the_gateway_is(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry
) -> None:
    found = await async_get_config_entry_diagnostics(hass, config_entry)
    assert found["entry"]["data"]["email"] == "**REDACTED**"
    assert found["entry"]["data"]["host"] == "**REDACTED**"
    assert found["entry"]["data"]["gateway_id"] == "**REDACTED**"
    assert found["entry"]["data"]["name"] == NAME
    assert found["model"] == "CTS 400"
    assert found["identity"] == {
        "device_number": 72280, "device_model": 1140, "slave_device_number": 72270, "slave_device_model": 1}
    assert found["status"]["CONNECTED"] is True
    temp_outside = found["values"]["temp_outside"]
    assert (temp_outside["value"], temp_outside["quality"], temp_outside["raw"]) == (15.2, "GOOD", [152])
    assert temp_outside["consecutive_failures"] == 0 and temp_outside["at"]
    text = repr(found)
    assert EMAIL not in text and GATEWAY_ID not in text and HOST not in text


async def test_diagnostics_hold_how_the_gateway_has_answered_and_the_library_versions(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry
) -> None:
    found = await async_get_config_entry_diagnostics(hass, config_entry)
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
    assert found["entry"]["polling_disabled"] is False and "options" in found["entry"]


async def test_a_library_not_installed_has_no_version(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing(name: str) -> str:
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(metadata, "version", missing)
    found = await async_get_config_entry_diagnostics(hass, config_entry)
    assert found["libraries"] == {"nilan_connect": None, "modbus_event_connect": None, "event_connect": None}

"""Mapping a unit: the guide in the options, the reads it makes and only those, what it stores,
and what the diagnostics show of it."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from nilan_connect import CTS400, RawAddress, RegisterChange, model_points
from nilan_connect.testing import FakeClock, SimulatedMicroNabtoDevice
from pytest_homeassistant.common import MockConfigEntry

from custom_components.nilan_connect import guide as guide_module
from custom_components.nilan_connect.const import (
    CHANGES_SHOWN,
    MAPPING_REPORT_URL,
    MAPPINGS_KEPT,
)
from custom_components.nilan_connect.data import NilanData
from custom_components.nilan_connect.diagnostics import async_get_config_entry_diagnostics
from custom_components.nilan_connect.guide import changes_text
from custom_components.nilan_connect.mapping import Mappings, load_mappings, step

from .conftest import EMAIL, GATEWAY_ID, HOST

REPOSITORY = Path(__file__).parents[1]
TRANSLATIONS = REPOSITORY / "custom_components" / "nilan_connect" / "translations"
DATAPOINT_READ, SETPOINT_READ, SETPOINT_WRITE = 0x2D, 0x2A, 0x2B


def _options(hass: HomeAssistant) -> Any:
    # HA declares the options manager's user input as a bare `dict`.
    options: Any = hass.config_entries.options
    return options


async def _menu(hass: HomeAssistant, entry: MockConfigEntry, option: str) -> ConfigFlowResult:
    """The options of `entry`, at `option` of their menu."""
    flow: ConfigFlowResult = await _options(hass).async_init(entry.entry_id)
    return await _options(hass).async_configure(flow["flow_id"], {"next_step_id": option})


async def _read(hass: HomeAssistant, result: ConfigFlowResult) -> ConfigFlowResult:
    """The step a read in progress goes on with, once it has ended."""
    assert result.get("type") is FlowResultType.SHOW_PROGRESS
    assert result.get("progress_action") == "reading"
    await hass.async_block_till_done()
    return await _options(hass).async_configure(result["flow_id"])


async def _started(hass: HomeAssistant, entry: MockConfigEntry, unit: str = "Comfort 300, with a heat pump") -> ConfigFlowResult:
    """The guide, past its first read."""
    start = await _menu(hass, entry, "map_unit")
    return await _read(hass, await _options(hass).async_configure(start["flow_id"], {"unit": unit}))


async def _step(hass: HomeAssistant, flow_id: str, note: str) -> ConfigFlowResult:
    """One step: the change made, then the read after it."""
    return await _read(hass, await _options(hass).async_configure(flow_id, {"change": note}))


def _commands(gateway: SimulatedMicroNabtoDevice) -> list[tuple[int, tuple[tuple[int, ...], ...]]]:
    return [(command.code, command.items) for command in gateway.commands]


def test_the_options_offer_the_settings_and_the_guide() -> None:
    for language in ("en", "da"):
        translations = json.loads((TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8"))["options"]
        assert set(translations["step"]["init"]["menu_options"]) == {"settings", "map_unit"}
        steps = translations["step"]
        assert "{report_url}" in steps["map_start"]["description"]
        for name in ("map_change", "map_changed"):
            assert "{count}" in steps[name]["description"] and "{changes}" in steps[name]["description"]
        assert set(steps["map_changed"]["menu_options"]) == {"map_next", "map_done"}
        assert set(steps["map_done"]["menu_options"]) == {"map_full", "map_finish"}
        assert "{report_url}" in translations["abort"]["mapping_saved"]
        assert {"read_failed", "unknown"} <= set(translations["error"])
        assert "reading" in translations["progress"]


async def test_the_options_open_on_a_menu_of_the_settings_and_the_guide(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry
) -> None:
    menu: ConfigFlowResult = await _options(hass).async_init(config_entry.entry_id)
    assert (menu.get("type"), menu.get("menu_options")) == (FlowResultType.MENU, ["settings", "map_unit"])


async def test_a_unit_is_mapped_step_by_step_and_every_step_is_stored(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, gateway: SimulatedMicroNabtoDevice
) -> None:
    options = dict(config_entry.options)
    start = await _menu(hass, config_entry, "map_unit")
    assert (start.get("type"), start.get("step_id")) == (FlowResultType.FORM, "map_start")
    assert start.get("description_placeholders") == {"report_url": MAPPING_REPORT_URL}
    change = await _read(hass, await _options(hass).async_configure(start["flow_id"], {"unit": " Comfort 300 "}))
    assert (change.get("type"), change.get("step_id")) == (FlowResultType.FORM, "map_change")

    gateway.datapoint_registers[(0, 23)] = 0                 # the bypass closes
    changed = await _step(hass, change["flow_id"], "Closed the bypass damper.")
    assert (changed.get("type"), changed.get("menu_options")) == (FlowResultType.MENU, ["map_next", "map_done"])
    assert changed.get("description_placeholders") == {"count": "1", "changes": "- datapoint 23: 1 → 0 (bits 0)"}

    again = await _options(hass).async_configure(changed["flow_id"], {"next_step_id": "map_next"})
    assert (again.get("step_id"), again.get("description_placeholders")) == (
        "map_change", {"count": "1", "changes": "- datapoint 23: 1 → 0 (bits 0)"})
    nothing = await _step(hass, again["flow_id"], "Nothing.")
    assert nothing.get("description_placeholders") == {"count": "0", "changes": "-"}
    done = await _options(hass).async_configure(nothing["flow_id"], {"next_step_id": "map_done"})
    finished = await _options(hass).async_configure(done["flow_id"], {"next_step_id": "map_finish"})
    assert (finished.get("type"), finished.get("reason")) == (FlowResultType.ABORT, "mapping_saved")

    [stored] = await load_mappings(hass, config_entry.entry_id)
    assert stored["unit_description"] == "Comfort 300"
    assert (stored["model"], stored["identity"]["device_model"]) == ("CTS 400", 1140)
    assert stored["device"] == {"manufacturer": "Nilan", "model": "CTS 400", "sw_version": None}
    assert stored["areas"][0] == {"table": "datapoint", "start": 20, "count": 91}
    assert stored["baseline"]["values"]["datapoint"]["23"] == 1
    assert [each["note"] for each in stored["steps"]] == ["Closed the bypass damper.", "Nothing."]
    assert stored["steps"][0]["changes"] == [
        {"table": "datapoint", "number": 23, "before": 1, "after": 0, "bits": [0]}]
    assert "final" not in stored
    assert dict(config_entry.options) == options and not gateway.received(SETPOINT_WRITE)


async def test_a_mapping_ends_with_one_more_read_of_everything_if_asked(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, gateway: SimulatedMicroNabtoDevice
) -> None:
    change = await _started(hass, config_entry)
    done = await _options(hass).async_configure(
        (await _step(hass, change["flow_id"], "Nothing."))["flow_id"], {"next_step_id": "map_done"})
    gateway.datapoint_registers[(0, 151)] = 7               # a register that answers only now
    finished = await _read(hass, await _options(hass).async_configure(done["flow_id"], {"next_step_id": "map_full"}))
    assert (finished.get("type"), finished.get("reason")) == (FlowResultType.ABORT, "mapping_saved")
    assert finished.get("description_placeholders") == {
        "count": "1", "changes": "- datapoint 151: – → 7", "report_url": MAPPING_REPORT_URL}
    [stored] = await load_mappings(hass, config_entry.entry_id)
    assert stored["final"]["changes"] == [{"table": "datapoint", "number": 151, "before": None, "after": 7, "bits": []}]


async def test_a_read_that_goes_unanswered_returns_to_its_form_with_the_reason(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, gateway: SimulatedMicroNabtoDevice,
    clock: FakeClock,
) -> None:
    start = await _menu(hass, config_entry, "map_unit")
    gateway.silent = True
    back = await _read(hass, await _options(hass).async_configure(start["flow_id"], {"unit": "Comfort 300"}))
    assert (back.get("step_id"), back.get("errors")) == ("map_start", {"base": "read_failed"})
    assert await load_mappings(hass, config_entry.entry_id) == []
    gateway.silent = False
    clock.advance(60)  # past the client's wait before it asks the gateway again
    change = await _read(hass, await _options(hass).async_configure(back["flow_id"], {"unit": "Comfort 300"}))
    gateway.silent = True
    failed = await _step(hass, change["flow_id"], "Opened the bypass.")
    assert (failed.get("step_id"), failed.get("errors")) == ("map_change", {"base": "read_failed"})
    gateway.silent = False
    clock.advance(60)
    [stored] = await load_mappings(hass, config_entry.entry_id)
    assert stored["steps"] == []
    assert (await _step(hass, failed["flow_id"], "Opened the bypass.")).get("step_id") == "map_changed"


async def test_a_last_read_of_everything_that_fails_keeps_the_steps(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, gateway: SimulatedMicroNabtoDevice
) -> None:
    change = await _started(hass, config_entry)
    done = await _options(hass).async_configure(
        (await _step(hass, change["flow_id"], "Nothing."))["flow_id"], {"next_step_id": "map_done"})
    gateway.silent = True
    ended = await _read(hass, await _options(hass).async_configure(done["flow_id"], {"next_step_id": "map_full"}))
    assert (ended.get("type"), ended.get("reason")) == (FlowResultType.ABORT, "mapping_saved_without_full_read")
    [stored] = await load_mappings(hass, config_entry.entry_id)
    assert len(stored["steps"]) == 1 and "final" not in stored


async def test_an_unexpected_error_in_a_read_returns_to_its_form(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*, limit: int) -> None:
        raise RuntimeError("broken")

    monkeypatch.setattr(loaded.client, "map_areas", broken)
    start = await _menu(hass, config_entry, "map_unit")
    back = await _read(hass, await _options(hass).async_configure(start["flow_id"], {"unit": ""}))
    assert (back.get("step_id"), back.get("errors")) == ("map_start", {"base": "unknown"})


async def test_closing_the_guide_during_a_read_stops_it_and_keeps_the_steps_taken(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    change = await _started(hass, config_entry)
    await _step(hass, change["flow_id"], "Opened the bypass.")
    flow_id = change["flow_id"]
    await _options(hass).async_configure(flow_id, {"next_step_id": "map_next"})
    reading = asyncio.Event()
    stopped = asyncio.Event()

    async def hanging(found: Any) -> None:
        reading.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setattr(loaded.client, "read_mapped", hanging)
    progress = await _options(hass).async_configure(flow_id, {"change": "Closed the bypass."})
    assert progress.get("type") is FlowResultType.SHOW_PROGRESS
    await reading.wait()
    _options(hass).async_abort(flow_id)
    await asyncio.wait_for(stopped.wait(), 1)
    [stored] = await load_mappings(hass, config_entry.entry_id)
    assert [each["note"] for each in stored["steps"]] == ["Opened the bypass."]


async def test_a_unit_keeps_its_latest_mappings_the_oldest_giving_way(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry
) -> None:
    for number in range(MAPPINGS_KEPT + 1):
        await _started(hass, config_entry, f"mapping {number}")
    stored = await load_mappings(hass, config_entry.entry_id)
    assert [each["unit_description"] for each in stored] == [f"mapping {n}" for n in range(1, MAPPINGS_KEPT + 1)]
    mappings = Mappings(hass, config_entry.entry_id)
    assert not await mappings.async_add_step("gone", step(loaded.client.values[next(iter(loaded.client.values))].timestamp, "", ()))


async def test_a_mapping_takes_no_more_steps_than_are_kept(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(guide_module, "STEPS_KEPT", 2)
    monkeypatch.setattr("custom_components.nilan_connect.mapping.STEPS_KEPT", 2)
    change = await _started(hass, config_entry)
    first = await _step(hass, change["flow_id"], "one")
    assert first.get("menu_options") == ["map_next", "map_done"]
    await _options(hass).async_configure(first["flow_id"], {"next_step_id": "map_next"})
    second = await _step(hass, first["flow_id"], "two")
    assert second.get("menu_options") == ["map_done"]
    started_at = (await load_mappings(hass, config_entry.entry_id))[0]["started_at"]
    assert not await Mappings(hass, config_entry.entry_id).async_add_step(started_at, {"note": "three"})


async def test_a_mapping_of_a_unit_whose_device_is_gone_says_nothing_of_the_device(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry
) -> None:
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, config_entry.entry_id):
        registry.async_remove_device(device.id)
    await _started(hass, config_entry)
    [stored] = await load_mappings(hass, config_entry.entry_id)
    assert stored["device"] == {"manufacturer": None, "model": None, "sw_version": None}


async def test_a_unit_not_loaded_cannot_be_mapped(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    config_entry.add_to_hass(hass)
    ended = await _menu(hass, config_entry, "map_unit")
    assert (ended.get("type"), ended.get("reason")) == (FlowResultType.ABORT, "not_loaded")


async def test_nothing_is_read_for_a_mapping_unless_the_guide_reads(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, gateway: SimulatedMicroNabtoDevice
) -> None:
    """The unit is read only at the addresses of its model's points, the guide's menu and the
    diagnostics included."""
    codes = {"datapoint": DATAPOINT_READ, "setpoint": SETPOINT_READ}
    known = {(codes[p.read.table], p.read.address) for p in model_points(CTS400) if p.read is not None}
    await loaded.client.refresh()
    await _menu(hass, config_entry, "map_unit")
    await async_get_config_entry_diagnostics(hass, config_entry)
    read = {(code, item[1]) for code, items in _commands(gateway) for item in items if code != 0x11}
    assert read and read <= known


async def test_the_diagnostics_show_the_stored_mappings_without_reading_the_unit(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, gateway: SimulatedMicroNabtoDevice
) -> None:
    change = await _started(hass, config_entry)
    await _step(hass, change["flow_id"], "Opened the bypass.")
    sent = len(gateway.commands)
    found = await async_get_config_entry_diagnostics(hass, config_entry)
    assert len(gateway.commands) == sent
    assert found["mappings"] == await load_mappings(hass, config_entry.entry_id)
    assert found["mappings"][0]["steps"][0]["note"] == "Opened the bypass."
    text = repr(found)
    assert EMAIL not in text and GATEWAY_ID not in text and HOST not in text


async def test_the_mappings_are_removed_with_the_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    await _started(hass, config_entry)
    assert await load_mappings(hass, config_entry.entry_id)
    await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()
    assert await load_mappings(hass, config_entry.entry_id) == []


def test_a_list_of_changes_shows_the_first_few() -> None:
    changes = [RegisterChange(RawAddress("setpoint", n), n, None, ()) for n in range(CHANGES_SHOWN + 3)]
    text = changes_text(changes).splitlines()
    assert (text[0], text[-1], len(text)) == ("- setpoint 0: 0 → –", "- …", CHANGES_SHOWN + 1)


def test_the_mapping_form_is_the_one_the_guide_links_to() -> None:
    form_name = MAPPING_REPORT_URL.rsplit("template=", 1)[1]
    form = yaml.safe_load((REPOSITORY / ".github" / "ISSUE_TEMPLATE" / form_name).read_text(encoding="utf-8"))
    fields = {field.get("id"): field for field in form["body"]}
    assert {"model", "integration_version", "diagnostics"} <= set(fields)
    assert form["name"].startswith("Kortlægning")


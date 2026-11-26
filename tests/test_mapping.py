"""Mapping a unit: the guide in the options, the scans it makes and only those, what it shows and
stores, the user's comments, and what the diagnostics show of it."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
import probatio
import yaml
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from nilan_connect import CTS400, RawAddress, RegisterChange, model_points
from nilan_connect.testing import FakeClock, SimulatedMicroNabtoDevice
from pytest_homeassistant.common import MockConfigEntry

from custom_components.nilan_connect import guide as guide_module
from custom_components.nilan_connect.const import (
    DOMAIN,
    MAPPING_REPORT_URL,
    MAPPINGS_KEPT,
    REGISTER_FIELDS,
    VALUES_PER_PAGE,
)
from custom_components.nilan_connect.data import NilanData
from custom_components.nilan_connect.diagnostics import async_get_config_entry_diagnostics
from custom_components.nilan_connect.guide import (
    SUGGESTIONS,
    MappingGuide,
    address_text,
    comment_lines,
    parse_comments,
    space_text,
)
from custom_components.nilan_connect.mapping import Mappings, load_mappings, step

from .conftest import EMAIL, GATEWAY_ID, HOST

REPOSITORY = Path(__file__).parents[1]
TRANSLATIONS = REPOSITORY / "custom_components" / "nilan_connect" / "translations"
DATAPOINT_READ, SETPOINT_READ, SETPOINT_WRITE = 0x2D, 0x2A, 0x2B


def _options(hass: HomeAssistant) -> Any:
    # HA declares the options manager's user input as a bare `dict`.
    options: Any = hass.config_entries.options
    return options


def _translations(language: str) -> dict[str, Any]:
    translations: dict[str, Any] = json.loads((TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8"))
    return translations


LABELS = _translations("en")["selector"]["mapping_label"]["options"]


def selectors_of(language: str) -> dict[str, Any]:
    selectors: dict[str, Any] = _translations(language)["selector"]
    return selectors


async def _menu(hass: HomeAssistant, entry: MockConfigEntry, option: str) -> ConfigFlowResult:
    """The options of `entry`, at `option` of their menu."""
    flow: ConfigFlowResult = await _options(hass).async_init(entry.entry_id)
    return await _options(hass).async_configure(flow["flow_id"], {"next_step_id": option})


async def _go(hass: HomeAssistant, flow_id: str, option: str) -> ConfigFlowResult:
    return await _options(hass).async_configure(flow_id, {"next_step_id": option})


async def _read(hass: HomeAssistant, result: ConfigFlowResult) -> ConfigFlowResult:
    """The step a scan in progress goes on with, once it has ended."""
    assert result.get("type") is FlowResultType.SHOW_PROGRESS
    assert result.get("progress_action") == "reading"
    await hass.async_block_till_done()
    return await _options(hass).async_configure(result["flow_id"])


async def _scanned(hass: HomeAssistant, entry: MockConfigEntry, fitted: str = "a heat pump") -> ConfigFlowResult:
    """The guide, past its first scan."""
    start = await _menu(hass, entry, "map_unit")
    return await _read(hass, await _options(hass).async_configure(start["flow_id"], {"fitted": fitted}))


async def _test(hass: HomeAssistant, flow_id: str, title: str, suggestion: str = "other",
                change: Callable[[], object] | None = None) -> ConfigFlowResult:
    """One test from the menu: chosen and named, the unit read before the change, `change` made,
    and the unit read again; where the read before fails, the step it goes on with."""
    await _go(hass, flow_id, "map_test")
    made = await _read(hass, await _options(hass).async_configure(
        flow_id, {"suggestion": suggestion, "change": title}))
    if made.get("step_id") != "map_change":
        return made
    if change is not None:
        change()
    return await _read(hass, await _options(hass).async_configure(flow_id, {}))


def _schema(form: ConfigFlowResult) -> list[dict[str, Any]]:
    """The form's fields as the frontend is sent them."""
    # As Home Assistant's flow views serialize a form for the frontend.
    fields: Any = probatio.to_field_list(form.get("data_schema"), custom_serializer=cv.custom_serializer)
    assert isinstance(fields, list)
    return cast(list[dict[str, Any]], fields)


def _commands(gateway: SimulatedMicroNabtoDevice) -> list[tuple[int, tuple[tuple[int, ...], ...]]]:
    return [(command.code, command.items) for command in gateway.commands]


# =========================================================================== translations


@pytest.mark.parametrize("language", ["en", "da"])
def test_the_guide_is_translated_with_its_placeholders_labels_and_suggestions(language: str) -> None:
    options = _translations(language)["options"]
    steps = options["step"]
    assert set(steps["init"]["menu_options"]) == {"settings", "map_unit"}
    assert "{report_url}" in steps["map_start"]["description"] and "{unit}" in steps["map_start"]["description"]
    assert set(steps["map_start"]["data"]) == set(steps["map_start"]["data_description"]) == {"fitted"}
    assert "{found}" in steps["map_found"]["description"]
    assert set(steps["map_found"]["menu_options"]) == {"map_send", "map_test"}
    assert steps["map_found"]["menu_options"]["map_send"] == steps["map_tested"]["menu_options"]["map_send"]
    assert steps["map_tested"]["description"].split("\n\n")[-1] not in steps["map_found"]["description"]
    assert steps["map_tested"]["title"] != steps["map_found"]["title"]
    assert all("{unit}" in steps[name]["description"] for name in steps if name.startswith("map_"))
    unit_line, on_this_unit, step_one, step_two = {
        "en": ("Mapping **{unit}** (ventilation).", "Make changes on this unit", "**Step 1 of 2:", "**Step 2 of 2:"),
        "da": ("Kortlægger **{unit}** (ventilation).", "Lav ændringer på dette anlæg", "**Trin 1 af 2:",
               "**Trin 2 af 2:")}[language]
    mapping = [name for name in steps if name.startswith("map_")]
    assert [name for name in mapping if on_this_unit in steps[name]["description"]] == ["map_start", "map_test"]
    assert all(steps[name]["description"].startswith(unit_line + "\n\n")
               for name in mapping if name not in ("map_start", "map_test", "map_change"))
    assert steps["map_test"]["description"].startswith(f"{unit_line} {on_this_unit}")
    assert steps["map_test"]["description"].split("\n\n")[1].startswith(step_one)
    assert steps["map_change"]["description"].startswith(step_two) and "**" not in steps["map_change"]["title"]
    assert not any(words in json.dumps(steps) for words in ("1 of 3", "1 af 3", "**2. ", "**3. "))
    assert steps["map_result"]["submit"] in ("Save comments", "Gem kommentarer")
    assert steps["map_test"]["submit"] == "Start test" and steps["map_change"]["submit"] in ("Scan", "Skan")
    suggestions = " ".join(selectors_of(language)["mapping_suggestion"]["options"].values()).lower()
    assert "floor" not in suggestions and "gulv" not in suggestions and "17 °c" in suggestions
    assert all("submit" in steps[name] for name in ("map_start", "map_test", "map_send"))
    assert set(steps["map_test"]["data"]) == {"suggestion", "change"}
    assert set(steps["map_test"]["data_description"]) == {"change"}
    assert "{result}" in steps["map_result"]["description"] and set(steps["map_result"]["data"]) == {"more"}
    assert set(steps["map_tested"]["menu_options"]) == {"map_test", "map_values", "map_send"}
    assert set(steps["map_values"]["menu_options"]) == {"map_values_previous", "map_values_next", "map_values_back"}
    assert "{values}" in steps["map_values"]["description"] and "{pages}" in steps["map_values"]["title"]
    assert "data" not in steps["map_send"] and "{duration}" in steps["map_send"]["description"]
    assert all(f"{{{key}}}" in options["abort"]["mapping_saved"] for key in ("summary", "report_url"))
    assert "{total}" in options["progress"]["reading"]
    assert "data" not in steps["map_change"] and "submit" in steps["map_change"]
    assert {"not_loaded", "mapping_saved", "mapping_gone_test", "mapping_gone_comments",
            "mapping_gone_final"} <= set(options["abort"])
    assert {"read_failed", "unknown", "describe_other"} <= set(options["error"]) and "reading" in options["progress"]
    assert "title_required" not in options["error"]
    selectors = _translations(language)["selector"]
    labels = selectors["mapping_label"]["options"]
    assert set(labels) == {"unknown", "nothing_changed", "changed", "changed_one", "found_space", "moment",
                           "second_one",
                           "second", "minute_one", "minute", "test_one", "test", "changed_last_one",
                           "changed_last", "done", "done_scanned", *(f"short_{key}" for key in (*SUGGESTIONS, "other")),
                           *(f"{kind}_{space}" for kind in ("space", "spaces") for space in ("datapoint", "setpoint"))}
    assert "{count}" in labels["changed"]
    assert all(f"{{{key}}}" in labels["found_space"] for key in ("space", "answered", "nonzero", "absent"))
    assert list(selectors["mapping_suggestion"]["options"]) == ["mode", "setting", "switch", "temperature", "alarm",
                                                                 "other"]
    assert all(f"short_{key}" in labels for key in (*SUGGESTIONS, "other"))
    assert "23.5" not in json.dumps(_translations(language)) and "23,5" not in json.dumps(_translations(language))


# ================================================================================= guide


async def test_the_options_open_on_a_menu_of_the_settings_and_the_guide(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry
) -> None:
    menu: ConfigFlowResult = await _options(hass).async_init(config_entry.entry_id)
    assert (menu.get("type"), menu.get("menu_options")) == (FlowResultType.MENU, ["settings", "map_unit"])


async def test_a_unit_is_scanned_tested_and_commented_register_by_register_and_every_test_is_stored(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, gateway: SimulatedMicroNabtoDevice
) -> None:
    options = dict(config_entry.options)
    start = await _menu(hass, config_entry, "map_unit")
    assert (start.get("type"), start.get("step_id")) == (FlowResultType.FORM, "map_start")
    assert start.get("description_placeholders") == {"unit": "Nilan CTS 400", "report_url": MAPPING_REPORT_URL}
    assert [field["name"] for field in _schema(start)] == ["fitted"]
    found = await _read(hass, await _options(hass).async_configure(start["flow_id"], {"fitted": " a heat pump "}))
    assert (found.get("step_id"), found.get("menu_options")) == ("map_found", ["map_test", "map_send"])
    assert found.get("description_placeholders") == {"unit": "Nilan CTS 400",
        "found": "- datapoints: 45 answered, 21 not 0, 255 absent\n- setpoints: 47 answered, 33 not 0, 253 absent"}

    result = await _test(hass, found["flow_id"], "Bypass closed", "switch",
                         lambda: gateway.datapoint_registers.update({(0, 23): 0, (0, 28): 170, (0, 79): 1}))
    assert result.get("step_id") == "map_result"
    assert result.get("description_placeholders") == {"unit": "Nilan CTS 400",
                                                      "result": "3 registers changed during the test."}
    names = [field["name"] for field in _schema(result)]
    assert names == ["datapoint 23: 1 → 0 (Bypass damper)", "datapoint 28: 164 → 170 (Supply air temperature)",
                     "datapoint 79: 0 → 1"]
    tested = await _options(hass).async_configure(result["flow_id"], {names[0]: "bypass closed", names[2]: "?"})
    assert (tested.get("step_id"), tested.get("menu_options")) == ("map_tested", ["map_test", "map_values", "map_send"])

    nothing = await _test(hass, tested["flow_id"], "Nothing")
    assert nothing.get("description_placeholders") == {"unit": "Nilan CTS 400", "result": LABELS["nothing_changed"]}
    assert _schema(nothing) == []
    after = await _options(hass).async_configure(nothing["flow_id"], {})
    send = await _go(hass, after["flow_id"], "map_send")
    assert (send.get("step_id"), _schema(send)) == ("map_send", [])
    assert send.get("description_placeholders") == {"unit": "Nilan CTS 400", "duration": "a moment"}
    scanning = await _options(hass).async_configure(send["flow_id"], {})
    assert scanning.get("description_placeholders") == {"total": "600"}
    finished = await _read(hass, scanning)
    assert (finished.get("type"), finished.get("reason")) == (FlowResultType.ABORT, "mapping_saved")
    assert finished.get("description_placeholders") == {
        "summary": "Done and saved: 2 tests; 0 registers changed in the last scan.", "report_url": MAPPING_REPORT_URL}

    [stored] = await load_mappings(hass, config_entry.entry_id)
    assert stored["fitted"] == "a heat pump" and "unit_description" not in stored
    assert (stored["model"], stored["identity"]["device_model"]) == ("CTS 400", 1140)
    assert stored["device"] == {"manufacturer": "Nilan", "model": "CTS 400", "sw_version": None}
    assert stored["areas"] == [{"space": "datapoint", "start": 0, "count": 300},
                               {"space": "setpoint", "start": 0, "count": 300}]
    assert [(each["title"], each["suggestion"]) for each in stored["steps"]] == [("Bypass closed", "switch"),
                                                                                ("Nothing", "other")]
    first = stored["steps"][0]["changes"]
    assert first[0] == {"space": "datapoint", "number": 23, "before": 1, "after": 0, "bits": [0],
                        "comment": "bypass closed"}
    assert "comment" not in first[1] and first[2]["comment"] == "?"
    assert stored["steps"][1]["changes"] == [] and stored["final"]["changes"] == []
    assert dict(config_entry.options) == options and not gateway.received(SETPOINT_WRITE)


async def test_the_first_scan_is_sent_in_at_once_without_scanning_again(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, gateway: SimulatedMicroNabtoDevice
) -> None:
    found = await _scanned(hass, config_entry)
    sent = len(gateway.commands)
    finished = await _go(hass, found["flow_id"], "map_send")
    assert (finished.get("type"), finished.get("reason")) == (FlowResultType.ABORT, "mapping_saved")
    assert (finished.get("description_placeholders") or {})["summary"] == "Done and saved: 0 tests."
    [stored] = await load_mappings(hass, config_entry.entry_id)
    assert stored["steps"] == [] and "final" not in stored and len(gateway.commands) == sent


async def test_a_gateway_that_answers_every_address_is_told_by_how_many_are_not_0_and_read_in_few_requests(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, gateway: SimulatedMicroNabtoDevice
) -> None:
    """As a real CTS400's gateway answered: every address 0-299, 0 where nothing is."""
    for registers in (gateway.datapoint_registers, gateway.setpoint_registers):
        registers.update({(0, address): 0 for address in range(300) if (0, address) not in registers})
    gateway.commands.clear()
    found = await _scanned(hass, config_entry)
    first = len(gateway.commands)
    assert found.get("description_placeholders") == {"unit": "Nilan CTS 400",
        "found": "- datapoints: 300 answered, 21 not 0, 0 absent\n- setpoints: 300 answered, 33 not 0, 0 absent"}
    gateway.commands.clear()
    await _test(hass, found["flow_id"], "Nothing")
    reads = [command for command in gateway.commands if command.code in (DATAPOINT_READ, SETPOINT_READ)]
    assert (first, len(reads)) == (10, 20)        # 300 addresses a space, 64 a request; read before and after


async def test_no_extra_equipment_is_needed_to_scan(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry
) -> None:
    start = await _menu(hass, config_entry, "map_unit")
    found = await _read(hass, await _options(hass).async_configure(start["flow_id"], {}))
    assert found.get("step_id") == "map_found"
    [stored] = await load_mappings(hass, config_entry.entry_id)
    assert stored["fitted"] == ""


async def test_a_test_shows_only_what_changed_between_the_reads_just_before_and_after_the_change(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, gateway: SimulatedMicroNabtoDevice
) -> None:
    """An hour after the first scan, temperatures and counters have drifted by themselves."""
    found = await _scanned(hass, config_entry)
    gateway.datapoint_registers.update({(0, 28): 170, (0, 77): 3400})
    result = await _test(hass, found["flow_id"], "Bypass closed",
                         change=lambda: gateway.datapoint_registers.update({(0, 23): 0}))
    assert [field["name"] for field in _schema(result)] == ["datapoint 23: 1 → 0 (Bypass damper)"]
    await _options(hass).async_configure(result["flow_id"], {})
    [stored] = await load_mappings(hass, config_entry.entry_id)
    made = stored["steps"][0]
    assert made["changes"] == [{"space": "datapoint", "number": 23, "before": 1, "after": 0, "bits": [0]}]
    assert made["drifted"] == 2
    assert [(each["number"], each["after"]) for each in made["drift"]] == [(28, 170), (77, 3400)]
    assert made["before_at"] <= made["at"]


async def test_closing_the_guide_between_the_reads_before_and_after_stores_no_test(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, gateway: SimulatedMicroNabtoDevice
) -> None:
    found = await _scanned(hass, config_entry)
    await _go(hass, found["flow_id"], "map_test")
    change = await _read(hass, await _options(hass).async_configure(
        found["flow_id"], {"suggestion": "other", "change": "Bypass"}))
    assert change.get("step_id") == "map_change"
    sent = len(gateway.commands)
    _options(hass).async_abort(found["flow_id"])
    await hass.async_block_till_done()
    [stored] = await load_mappings(hass, config_entry.entry_id)
    assert stored["steps"] == [] and len(gateway.commands) == sent


@pytest.mark.parametrize(("seconds", "text"), [(0.029, "a moment"), (1.9, "a moment"), (2.0, "2 seconds"),
                                                (6.4, "6 seconds"), (59.4, "59 seconds"),
                                                (61.0, "1 minute"), (150.0, "3 minutes")])
async def test_the_time_the_first_scan_took_is_told_in_seconds_or_minutes(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, seconds: float, text: str
) -> None:
    guide = MappingGuide(hass, config_entry)
    await guide.first_read()
    setattr(guide, "_first_seconds", seconds)
    assert guide.duration_text() == text


async def test_the_last_scan_shows_its_progress_by_the_time_the_first_took(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(guide_module, "PROGRESS_EVERY", 0.01)
    monkeypatch.setattr(guide_module, "ESTIMATED_FROM", 0.04)
    guide = MappingGuide(hass, config_entry)
    await guide.first_read()
    setattr(guide, "_first_seconds", 0.05)
    told: list[float] = []
    guide.on_progress = told.append
    real = loaded.client.map_areas

    async def slow(*, limit: int) -> Any:
        await asyncio.sleep(0.1)
        return await real(limit=limit)

    monkeypatch.setattr(loaded.client, "map_areas", slow)
    assert await guide.full_read() == "map_finish"
    assert len(told) > 2 and told[0] < told[1] and max(told[:-1]) == 0.95 and told[-1] == 1.0
    setattr(guide, "_first_seconds", 0.03)          # quicker than a bar would say anything
    told.clear()
    await guide.full_read()
    assert told == []


async def test_the_closing_text_counts_tests_and_changes_in_the_singular_and_plural(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, gateway: SimulatedMicroNabtoDevice
) -> None:
    found = await _scanned(hass, config_entry)
    tested = await _options(hass).async_configure((await _test(hass, found["flow_id"], "One"))["flow_id"], {})
    send = await _go(hass, tested["flow_id"], "map_send")
    gateway.datapoint_registers[(0, 150)] = 1
    finished = await _read(hass, await _options(hass).async_configure(send["flow_id"], {}))
    assert (finished.get("description_placeholders") or {})["summary"] == (
        "Done and saved: 1 test; 1 register changed in the last scan.")


async def test_every_step_of_the_guide_names_the_unit_it_maps(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry
) -> None:
    found = await _scanned(hass, config_entry)
    test = await _go(hass, found["flow_id"], "map_test")
    change = await _read(hass, await _options(hass).async_configure(test["flow_id"], {"suggestion": "other",
                                                                                     "change": "Bypass"}))
    result = await _read(hass, await _options(hass).async_configure(change["flow_id"], {}))
    tested = await _options(hass).async_configure(result["flow_id"], {})
    values = await _go(hass, tested["flow_id"], "map_values")
    tested = await _go(hass, values["flow_id"], "map_values_back")
    send = await _go(hass, tested["flow_id"], "map_send")
    for shown in (found, test, change, result, tested, values, send):
        assert (shown.get("description_placeholders") or {})["unit"] == "Nilan CTS 400", shown.get("step_id")


async def test_a_test_is_chosen_from_the_suggestions_and_other_needs_a_description(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry
) -> None:
    found = await _scanned(hass, config_entry)
    form = await _go(hass, found["flow_id"], "map_test")
    fields = _schema(form)
    assert [field["name"] for field in fields] == ["suggestion", "change"]
    assert fields[0]["required"] is True and "default" not in fields[0]
    assert fields[1].get("required") is not True
    again = await _options(hass).async_configure(form["flow_id"], {"suggestion": "other", "change": "  "})
    assert (again.get("step_id"), again.get("errors")) == ("map_test", {"change": "describe_other"})
    assert _schema(again)[0]["description"]["suggested_value"] == "other"


@pytest.mark.parametrize(("suggestion", "change", "title"), [
    ("mode", "", "Fan level"), ("alarm", "", "An alarm"), ("mode", "level 1 → 3", "level 1 → 3"),
    ("other", "bypass by hand", "bypass by hand")])
async def test_a_tests_title_is_what_the_user_changes_or_else_the_kind_of_test(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, suggestion: str, change: str, title: str
) -> None:
    found = await _scanned(hass, config_entry)
    await _go(hass, found["flow_id"], "map_test")
    made = await _read(hass, await _options(hass).async_configure(
        found["flow_id"], {"suggestion": suggestion, "change": change}))
    assert made.get("step_id") == "map_change"
    await _read(hass, await _options(hass).async_configure(found["flow_id"], {}))
    [stored] = await load_mappings(hass, config_entry.entry_id)
    assert (stored["steps"][0]["title"], stored["steps"][0]["suggestion"]) == (title, suggestion)


async def test_registers_beyond_those_given_a_field_share_one_a_line_each(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, gateway: SimulatedMicroNabtoDevice
) -> None:
    found = await _scanned(hass, config_entry)
    changed = sorted(address for _, address in gateway.setpoint_registers)[:REGISTER_FIELDS + 2]
    registers = gateway.setpoint_registers
    bumped = {(0, address): registers[(0, address)] + 1 for address in changed}
    result = await _test(hass, found["flow_id"], "Many at once", change=lambda: registers.update(bumped))
    fields = _schema(result)
    assert len(fields) == REGISTER_FIELDS + 1 and fields[-1]["name"] == "more"
    more: str = fields[-1]["description"]["suggested_value"]
    lines = more.splitlines()
    assert len(lines) == 2 and lines[0].startswith(f"setpoint {changed[REGISTER_FIELDS]}: ")
    assert lines[0].endswith(" = ")
    await _options(hass).async_configure(result["flow_id"], {"more": f"{lines[0]}eco mode\n{lines[1]}"})
    [stored] = await load_mappings(hass, config_entry.entry_id)
    comments = [change.get("comment") for change in stored["steps"][0]["changes"]]
    assert comments == [None] * REGISTER_FIELDS + ["eco mode", None]


async def test_in_danish_the_guide_names_the_spaces_in_danish_and_stores_them_by_the_protocols_names(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, gateway: SimulatedMicroNabtoDevice
) -> None:
    hass.config.language = "da"
    found = await _scanned(hass, config_entry)
    assert (found.get("description_placeholders") or {})["found"] == (
        "- datapunkter: 45 svarede, 21 forskellige fra 0, 255 findes ikke\n"
        "- setpunkter: 47 svarede, 33 forskellige fra 0, 253 findes ikke")
    changed = sorted(address for _, address in gateway.setpoint_registers)[:REGISTER_FIELDS + 1]
    registers = gateway.setpoint_registers
    bumped = {(0, address): registers[(0, address)] + 1 for address in changed}
    result = await _test(hass, found["flow_id"], "Mange på én gang", change=lambda: registers.update(bumped))
    fields = _schema(result)
    assert all(field["name"].startswith("setpunkt ") for field in fields[:-1])
    more: str = fields[-1]["description"]["suggested_value"]
    assert more.startswith(f"setpunkt {changed[REGISTER_FIELDS]}: ")
    tested = await _options(hass).async_configure(result["flow_id"], {fields[0]["name"]: "trin", "more": more + "eco"})
    [stored] = await load_mappings(hass, config_entry.entry_id)
    made = stored["steps"][0]["changes"]
    assert {change["space"] for change in made} == {"setpoint"}
    assert (made[0]["comment"], made[-1]["comment"]) == ("trin", "eco")
    values = (await _go(hass, tested["flow_id"], "map_values")).get("description_placeholders") or {}
    assert values["values"].startswith("- datapunkt 20: 0 · ")


async def test_after_a_test_sending_in_scans_every_address_once_more_so_no_register_a_test_brought_is_missed(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, gateway: SimulatedMicroNabtoDevice
) -> None:
    found = await _scanned(hass, config_entry)
    result = await _test(hass, found["flow_id"], "After-heating off",     # 87 gone at the test, back at the end
                         change=lambda: gateway.datapoint_registers.pop((0, 87)))
    tested = await _options(hass).async_configure(result["flow_id"], {})
    send = await _go(hass, tested["flow_id"], "map_send")
    gateway.datapoint_registers.update({(0, 87): 0, (0, 150): 7})   # 150 brought by the test
    finished = await _read(hass, await _options(hass).async_configure(send["flow_id"], {}))
    assert (finished.get("type"), finished.get("reason")) == (FlowResultType.ABORT, "mapping_saved")
    [stored] = await load_mappings(hass, config_entry.entry_id)
    assert stored["steps"][0]["changes"] == [
        {"space": "datapoint", "number": 87, "before": 0, "after": None, "bits": []}]
    assert stored["final"]["changes"] == [
        {"space": "datapoint", "number": 87, "before": None, "after": 0, "bits": []},
        {"space": "datapoint", "number": 150, "before": None, "after": 7, "bits": []}]
    assert stored["final"]["snapshot"]["values"]["datapoint"]["150"] == 7


async def test_all_values_are_shown_page_by_page_without_reading_the_unit(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, gateway: SimulatedMicroNabtoDevice
) -> None:
    found = await _scanned(hass, config_entry)
    tested = await _options(hass).async_configure((await _test(hass, found["flow_id"], "Nothing"))["flow_id"], {})
    sent = len(gateway.commands)
    first = await _go(hass, tested["flow_id"], "map_values")
    assert first.get("menu_options") == ["map_values_next", "map_values_back"]
    shown = first.get("description_placeholders") or {}
    assert (shown["page"], shown["pages"]) == ("1", "2")
    rows = shown["values"].splitlines()
    assert len(rows) == min(VALUES_PER_PAGE, 45)
    assert "- datapoint 28: 164 · Supply air temperature" in rows and "- datapoint 79: 0 · unknown" in rows
    second = await _go(hass, first["flow_id"], "map_values_next")
    assert second.get("menu_options") == ["map_values_previous", "map_values_back"]
    assert (second.get("description_placeholders") or {})["values"].startswith("- setpoint 30:")
    previous = await _go(hass, second["flow_id"], "map_values_previous")
    assert (previous.get("description_placeholders") or {})["page"] == "1"
    back = await _go(hass, previous["flow_id"], "map_values_back")
    assert back.get("step_id") == "map_tested"
    assert len(gateway.commands) == sent


async def test_the_values_shown_follow_a_scan_that_has_fewer(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, gateway: SimulatedMicroNabtoDevice,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(guide_module, "VALUES_PER_PAGE", 10)
    found = await _scanned(hass, config_entry)
    tested = await _options(hass).async_configure((await _test(hass, found["flow_id"], "Nothing"))["flow_id"], {})
    shown = await _go(hass, tested["flow_id"], "map_values")
    while "map_values_next" in (shown.get("menu_options") or []):
        shown = await _go(hass, shown["flow_id"], "map_values_next")
    assert (shown.get("description_placeholders") or {})["page"] == "10"
    await _go(hass, shown["flow_id"], "map_values_back")
    for address in (30, 81, 82, 83, 84, 85, 86):          # setpoints no point reads
        del gateway.setpoint_registers[(0, address)]
    again = await _options(hass).async_configure((await _test(hass, found["flow_id"], "Fewer"))["flow_id"], {})
    page = await _go(hass, again["flow_id"], "map_values")
    assert ((page.get("description_placeholders") or {})["page"], (page.get("description_placeholders") or {})[
        "pages"]) == ("1", "9")


async def test_a_change_of_one_register_is_told_in_the_singular(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, gateway: SimulatedMicroNabtoDevice
) -> None:
    found = await _scanned(hass, config_entry)
    result = await _test(hass, found["flow_id"], "Bypass",
                         change=lambda: gateway.datapoint_registers.update({(0, 79): 1}))
    assert result.get("description_placeholders") == {"unit": "Nilan CTS 400", "result": LABELS["changed_one"]}


async def test_guides_storing_at_once_lose_nothing_of_each_other(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _scanned(hass, config_entry)
    started_at = (await load_mappings(hass, config_entry.entry_id))[0]["started_at"]

    async def slow(hass: HomeAssistant, entry_id: str) -> list[dict[str, Any]]:
        """Loading as a slow disk does, so that the guides' stores overlap."""
        found = await load_mappings(hass, entry_id)
        await asyncio.sleep(0.01)
        return found

    monkeypatch.setattr("custom_components.nilan_connect.mapping.load_mappings", slow)
    guides = [Mappings(hass, config_entry.entry_id) for _ in range(5)]
    added = await asyncio.gather(*(guide.async_add_step(started_at, {"title": str(n), "changes": []})
                                   for n, guide in enumerate(guides)))
    [stored] = await load_mappings(hass, config_entry.entry_id)
    assert added == [True] * 5 and sorted(each["title"] for each in stored["steps"]) == ["0", "1", "2", "3", "4"]


async def test_a_scan_that_goes_unanswered_returns_to_its_form_with_the_reason(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, gateway: SimulatedMicroNabtoDevice,
    clock: FakeClock,
) -> None:
    start = await _menu(hass, config_entry, "map_unit")
    gateway.silent = True
    back = await _read(hass, await _options(hass).async_configure(start["flow_id"], {"fitted": ""}))
    assert (back.get("step_id"), back.get("errors")) == ("map_start", {"base": "read_failed"})
    assert await load_mappings(hass, config_entry.entry_id) == []
    gateway.silent = False
    clock.advance(60)  # past the client's wait before it asks the gateway again
    found = await _read(hass, await _options(hass).async_configure(back["flow_id"], {"fitted": ""}))
    gateway.silent = True
    failed = await _test(hass, found["flow_id"], "Bypass")
    assert (failed.get("step_id"), failed.get("errors")) == ("map_test", {"base": "read_failed"})
    gateway.silent = False
    clock.advance(60)
    [stored] = await load_mappings(hass, config_entry.entry_id)
    assert stored["steps"] == []
    change = await _read(hass, await _options(hass).async_configure(
        failed["flow_id"], {"suggestion": "other", "change": "Bypass"}))
    assert change.get("step_id") == "map_change"
    gateway.silent = True
    after = await _read(hass, await _options(hass).async_configure(change["flow_id"], {}))
    assert (after.get("step_id"), after.get("errors")) == ("map_change", {"base": "read_failed"})
    gateway.silent = False
    clock.advance(60)
    result = await _read(hass, await _options(hass).async_configure(after["flow_id"], {}))
    tested = await _options(hass).async_configure(result["flow_id"], {})
    send = await _go(hass, tested["flow_id"], "map_send")
    gateway.silent = True
    again = await _read(hass, await _options(hass).async_configure(send["flow_id"], {}))
    assert (again.get("step_id"), again.get("errors")) == ("map_send", {"base": "read_failed"})


async def test_an_unexpected_error_in_a_scan_returns_to_its_form(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*, limit: int) -> None:
        raise RuntimeError("broken")

    monkeypatch.setattr(loaded.client, "map_areas", broken)
    start = await _menu(hass, config_entry, "map_unit")
    back = await _read(hass, await _options(hass).async_configure(start["flow_id"], {}))
    assert (back.get("step_id"), back.get("errors")) == ("map_start", {"base": "unknown"})


async def test_closing_the_guide_during_a_scan_stops_it_and_keeps_the_tests_made(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    found = await _scanned(hass, config_entry)
    tested = await _options(hass).async_configure((await _test(hass, found["flow_id"], "Bypass"))["flow_id"], {})
    flow_id = tested["flow_id"]
    await _go(hass, flow_id, "map_test")
    scanning = asyncio.Event()
    stopped = asyncio.Event()

    async def hanging(found: Any) -> None:
        scanning.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setattr(loaded.client, "read_mapped", hanging)
    progress = await _options(hass).async_configure(flow_id, {"suggestion": "other", "change": "Boost"})
    assert progress.get("type") is FlowResultType.SHOW_PROGRESS
    await scanning.wait()
    _options(hass).async_abort(flow_id)
    await asyncio.wait_for(stopped.wait(), 1)
    [stored] = await load_mappings(hass, config_entry.entry_id)
    assert [each["title"] for each in stored["steps"]] == ["Bypass"]


@pytest.mark.parametrize("step_id", ["map_start", "map_found", "map_test", "map_change", "map_result",
                                     "map_tested", "map_values", "map_send"])
async def test_every_step_of_a_unit_no_longer_set_up_ends_the_guide(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, step_id: str
) -> None:
    found = await _scanned(hass, config_entry)
    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    flow: Any = getattr(_options(hass), "_progress")[found["flow_id"]]
    ended: ConfigFlowResult = await getattr(flow, f"async_step_{step_id}")()
    assert (ended.get("type"), ended.get("reason")) == (FlowResultType.ABORT, "not_loaded")
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


async def test_a_unit_keeps_its_latest_mappings_and_one_that_gave_way_says_so(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, gateway: SimulatedMicroNabtoDevice
) -> None:
    oldest = await _scanned(hass, config_entry, "mapping 0")
    result = await _test(hass, oldest["flow_id"], "Bypass",
                         change=lambda: gateway.datapoint_registers.update({(0, 79): 1}))
    for number in range(1, MAPPINGS_KEPT + 1):
        await _scanned(hass, config_entry, f"mapping {number}")
    stored = await load_mappings(hass, config_entry.entry_id)
    assert [each["fitted"] for each in stored] == [f"mapping {n}" for n in range(1, MAPPINGS_KEPT + 1)]
    gone = await _options(hass).async_configure(result["flow_id"], {"datapoint 79: 0 → 1": "motor"})
    assert (gone.get("type"), gone.get("reason")) == (FlowResultType.ABORT, "mapping_gone_comments")
    other = await _scanned(hass, config_entry, "mapping 4")
    for number in range(5, 5 + MAPPINGS_KEPT):
        await _scanned(hass, config_entry, f"mapping {number}")
    gone = await _test(hass, other["flow_id"], "Bypass")
    assert (gone.get("type"), gone.get("reason")) == (FlowResultType.ABORT, "mapping_gone_test")


async def test_a_mapping_takes_no_more_tests_than_are_kept(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(guide_module, "STEPS_KEPT", 2)
    monkeypatch.setattr("custom_components.nilan_connect.mapping.STEPS_KEPT", 2)
    found = await _scanned(hass, config_entry)
    first = await _options(hass).async_configure((await _test(hass, found["flow_id"], "one"))["flow_id"], {})
    assert first.get("menu_options") == ["map_test", "map_values", "map_send"]
    second = await _options(hass).async_configure((await _test(hass, first["flow_id"], "two"))["flow_id"], {})
    assert second.get("menu_options") == ["map_values", "map_send"]
    started_at = (await load_mappings(hass, config_entry.entry_id))[0]["started_at"]
    mappings = Mappings(hass, config_entry.entry_id)
    assert not await mappings.async_add_step(started_at, {"title": "three"})
    assert not await mappings.async_annotate(started_at, 5, {})
    assert not await mappings.async_finish("gone", {})


async def test_a_last_scan_for_a_mapping_that_gave_way_says_so(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry
) -> None:
    found = await _scanned(hass, config_entry, "mapping 0")
    tested = await _options(hass).async_configure((await _test(hass, found["flow_id"], "x"))["flow_id"], {})
    send = await _go(hass, tested["flow_id"], "map_send")
    for number in range(1, MAPPINGS_KEPT + 1):
        await _scanned(hass, config_entry, f"mapping {number}")
    gone = await _read(hass, await _options(hass).async_configure(send["flow_id"], {}))
    assert (gone.get("type"), gone.get("reason")) == (FlowResultType.ABORT, "mapping_gone_final")


async def test_a_mapping_of_a_unit_whose_device_is_gone_says_nothing_of_the_device(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry
) -> None:
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, config_entry.entry_id):
        registry.async_remove_device(device.id)
    await _scanned(hass, config_entry)
    [stored] = await load_mappings(hass, config_entry.entry_id)
    assert stored["device"] == {"manufacturer": None, "model": None, "sw_version": None}


async def test_a_unit_not_loaded_cannot_be_mapped(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    config_entry.add_to_hass(hass)
    ended = await _menu(hass, config_entry, "map_unit")
    assert (ended.get("type"), ended.get("reason")) == (FlowResultType.ABORT, "not_loaded")


async def test_nothing_is_read_for_a_mapping_unless_the_guide_scans(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, gateway: SimulatedMicroNabtoDevice
) -> None:
    """The unit is read only at the addresses of its model's points, the guide's first form and
    the diagnostics included."""
    codes = {"datapoint": DATAPOINT_READ, "setpoint": SETPOINT_READ}
    known = {(codes[p.read.space], p.read.address) for p in model_points(CTS400) if p.read is not None}
    await loaded.client.refresh()
    await _menu(hass, config_entry, "map_unit")
    await async_get_config_entry_diagnostics(hass, config_entry)
    read = {(code, item[1]) for code, items in _commands(gateway) for item in items if code != 0x11}
    assert read and read <= known


async def test_the_first_scan_holds_every_address_from_0_to_299(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry
) -> None:
    await _scanned(hass, config_entry)
    [stored] = await load_mappings(hass, config_entry.entry_id)
    baseline = stored["baseline"]
    for space in ("datapoint", "setpoint"):
        held = {int(n) for n in baseline["values"].get(space, {})} | set(baseline["missing"].get(space, []))
        assert held == set(range(300)), space


async def test_the_diagnostics_show_the_stored_mappings_and_comments_without_reading_the_unit(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry, gateway: SimulatedMicroNabtoDevice
) -> None:
    found = await _scanned(hass, config_entry)
    result = await _test(hass, found["flow_id"], "Bypass",
                         change=lambda: gateway.datapoint_registers.update({(0, 79): 1}))
    await _options(hass).async_configure(result["flow_id"], {"datapoint 79: 0 → 1": "motor"})
    sent = len(gateway.commands)
    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)
    assert len(gateway.commands) == sent
    assert diagnostics["mappings"] == await load_mappings(hass, config_entry.entry_id)
    assert diagnostics["mappings"][0]["steps"][0]["changes"][0]["comment"] == "motor"
    text = repr(diagnostics)
    assert EMAIL not in text and GATEWAY_ID not in text and HOST not in text


async def test_the_mappings_are_removed_with_the_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    await _scanned(hass, config_entry)
    assert await load_mappings(hass, config_entry.entry_id)
    await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()
    assert await load_mappings(hass, config_entry.entry_id) == []
    assert config_entry.entry_id not in hass.data.get(f"{DOMAIN}_mapping_locks", {})


# =============================================================================== comments


CHANGES = (RegisterChange(RawAddress("datapoint", 205), 0, 1, (0,)),
           RegisterChange(RawAddress("setpoint", 40), 70, None, ()))


def test_the_other_registers_are_offered_a_line_each() -> None:
    assert comment_lines(CHANGES) == "datapoint 205: 0 → 1 = \nsetpoint 40: 70 → – = "


def test_a_space_of_another_object_keeps_its_object_in_any_language() -> None:
    names = {"datapoint": "datapunkt"}
    assert space_text("datapoint:1", names) == "datapunkt:1"
    assert address_text(RawAddress("setpoint:2", 7), names) == "setpoint:2 7"
    found = parse_comments("datapunkt:1 5: 0 → 1 = flap", [RegisterChange(RawAddress("datapoint:1", 5), 0, 1, (0,))],
                           names)
    assert found == {RawAddress("datapoint:1", 5): "flap"}


@pytest.mark.parametrize(("text", "comments"), [
    ("datapoint 205: 0 → 1 = bypass\nsetpoint 40: 70 → – = target",
     {"datapoint 205": "bypass", "setpoint 40": "target"}),
    ("datapoint 205: 0 → 1 = \nsetpoint 40: 70 → – =   ", {}),
    ("setpoint 40: 70 → – = ?", {"setpoint 40": "?"}),
    ("datapoint 205: 9 → 9 = edited = still the comment", {"datapoint 205": "edited = still the comment"}),
    ("  datapoint 205 : 0 → 1 =bypass  ", {"datapoint 205": "bypass"}),
    ("datapoint 99: 1 → 0 = not a change\nthe panel flickered\n\n", {}),
    ("datapoint 205: 0 → 1 = the bypass\n  damper, motorised\nsetpoint 40: 70 → – = ",
     {"datapoint 205": "the bypass\ndamper, motorised"}),
    ("before any line\ndatapoint 205: 0 → 1 = \n  on a line of its own", {"datapoint 205": "on a line of its own"}),
], ids=["each", "left-empty", "deleted-line", "edited", "spacing", "extra-text", "continued", "own-line"])
def test_the_comments_are_taken_by_the_address_on_their_line(text: str, comments: dict[str, str]) -> None:
    found = parse_comments(text, CHANGES)
    assert {str(address): comment for address, comment in found.items()} == comments


def test_the_mapping_form_is_the_one_the_guide_links_to() -> None:
    form_name = MAPPING_REPORT_URL.rsplit("template=", 1)[1]
    form = yaml.safe_load((REPOSITORY / ".github" / "ISSUE_TEMPLATE" / form_name).read_text(encoding="utf-8"))
    fields = {field.get("id"): field for field in form["body"]}
    assert {"model", "integration_version", "diagnostics"} <= set(fields)
    assert form["name"] == "Mapping"


def test_a_test_is_plain_data() -> None:
    at = FakeClock().now()
    assert step(at, "Bypass", "switch", CHANGES[:1]) == {"at": at.isoformat(), "title": "Bypass",
                                                         "suggestion": "switch", "changes": [
        {"space": "datapoint", "number": 205, "before": 0, "after": 1, "bits": [0]}]}

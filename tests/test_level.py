"""The level of values an entry shows: the entities of each level, how certain each entity is,
the Repairs issue asking a tester to report, and what the diagnostics say of the points tried."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_socket
import yaml
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from nilan_connect import MODELS, Certainty, PointKey
from nilan_connect.testing import SimulatedMicroNabtoDevice
from pytest_homeassistant.common import MockConfigEntry

from custom_components.nilan_connect.climate import THERMOSTAT
from custom_components.nilan_connect.const import (
    CONF_LEVEL,
    DOMAIN,
    TEST_REPORT_URL,
    TESTING_ISSUE,
)
from custom_components.nilan_connect.data import NilanData
from custom_components.nilan_connect.diagnostics import async_get_config_entry_diagnostics
from custom_components.nilan_connect.entity import CERTAINTIES

from .conftest import CTS400, GATEWAY_ID, NAME, entry_data, simulated_gateway

REPOSITORY = Path(__file__).parents[1]
TRANSLATIONS = REPOSITORY / "custom_components" / "nilan_connect" / "translations"

EVERY_REGISTER = {(0, address): 0 for address in range(300)}
OPTIMA_250 = {"device_number": 0, "device_model": 1040, "slave_device_number": 79250, "slave_device_model": 1}
OPTIMA_301 = {"device_number": 0, "device_model": 1040, "slave_device_number": 79250, "slave_device_model": 5}
CTS602 = {"device_number": 0, "device_model": 1140, "slave_device_number": 2763306, "slave_device_model": 0}


@pytest.fixture(params=[OPTIMA_250], ids=["optima_250"])
async def gateway(request: pytest.FixtureRequest) -> AsyncIterator[SimulatedMicroNabtoDevice]:
    """A gateway in front of the controller asked for, every register it reads holding 0; a CTS400
    answers what the real one did."""
    pytest_socket.enable_socket()
    if request.param is CTS400:
        simulated = simulated_gateway()
    else:
        simulated = simulated_gateway(
            identity=request.param,
            datapoint_registers=dict(EVERY_REGISTER),
            setpoint_registers=dict(EVERY_REGISTER),
        )
    async with simulated:
        yield simulated


def _entry(gateway: SimulatedMicroNabtoDevice, level: str) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN, title=NAME, unique_id=GATEWAY_ID, data=entry_data(gateway),
        options={CONF_LEVEL: level}, version=2, minor_version=2,
    )


async def _set_up(hass: HomeAssistant, entry: MockConfigEntry) -> NilanData:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    data: NilanData = entry.runtime_data
    return data


async def _unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def _entities(hass: HomeAssistant, entry: MockConfigEntry) -> set[tuple[str, str]]:
    return {
        (found.domain, found.unique_id.removeprefix(f"{NAME}_"))
        for found in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }


def _state(hass: HomeAssistant, platform: str, key: str) -> State:
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{NAME}_{key}")
    assert entity_id is not None, key
    state = hass.states.get(entity_id)
    assert state is not None, key
    return state


def _attributes(hass: HomeAssistant, platform: str, key: str) -> dict[str, Any]:
    return dict(_state(hass, platform, key).attributes)


def _issue(hass: HomeAssistant, entry: MockConfigEntry) -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(DOMAIN, f"{TESTING_ISSUE}_{entry.entry_id}")


# ================================================================================ entities


@pytest.mark.parametrize("gateway", [CTS602], indirect=True, ids=["cts602"])
@pytest.mark.parametrize("level", ["verified", "documented", "test"])
async def test_each_level_shows_the_entities_of_the_points_of_the_certainties_it_admits(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice, level: str
) -> None:
    """A CTS602 has points of every certainty: four temperatures verified, the run setting
    inferred."""
    entry = _entry(gateway, level)
    data = await _set_up(hass, entry)
    certainties = {str(point.certainty) for point in data.client.points.values()}
    assert certainties == {"verified": {"verified"}, "documented": {"verified", "reported"},
                           "test": {"verified", "reported", "inferred"}}[level]
    found = _entities(hass, entry)
    assert (("sensor", str(PointKey.TEMP_SUPPLY)) in found) is True
    assert (("sensor", str(PointKey.TEMP_ROOM)) in found) is (level != "verified")
    assert (("switch", str(PointKey.ENABLE)) in found) is (level == "test")
    await _unload(hass, entry)


@pytest.mark.parametrize("level", ["documented", "test"])
async def test_an_optima_250s_bypass_is_read_from_its_on_off_datapoint_only_at_the_test_level(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice, level: str
) -> None:
    """Datapoint 104 is the bypass's opening, 0-100 %; the workbook gives 107 as "Bypass ON/OFF".
    The entity keeps its id at either level."""
    gateway.datapoint_registers[(0, 104)] = 63
    entry = _entry(gateway, level)
    await _set_up(hass, entry)
    bypass = _state(hass, "binary_sensor", PointKey.BYPASS_ACTIVE)
    assert bypass.state == (STATE_OFF if level == "test" else STATE_ON)
    assert bypass.attributes["certainty"] == ("test-candidate" if level == "test" else "reported")
    await _unload(hass, entry)


@pytest.mark.parametrize("gateway", [OPTIMA_301], indirect=True, ids=["optima_301"])
async def test_an_optima_301_has_a_preheat_switch_and_a_minimum_air_volume_only_at_the_test_level(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    gateway.setpoint_registers[(0, 16)] = 1
    entry = _entry(gateway, "test")
    await _set_up(hass, entry)
    switch = _attributes(hass, "switch", PointKey.PREHEAT_ENABLE)
    assert switch["certainty"] == "test-candidate"
    registry = er.async_get(hass)
    volume = registry.async_get(registry.async_get_entity_id("number", DOMAIN, f"{NAME}_min_air_volume") or "")
    assert volume is not None and volume.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    hass.config_entries.async_update_entry(entry, options={CONF_LEVEL: "documented"})
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    data: NilanData = entry.runtime_data
    assert {f"{NAME}_preheat_enable", f"{NAME}_min_air_volume"}.isdisjoint(data.unique_ids)
    assert {("switch", "preheat_enable"), ("number", "min_air_volume")} <= _entities(hass, entry)
    await _unload(hass, entry)


@pytest.mark.parametrize(
    ("gateway", "key"), [(CTS602, "temp_room"), (CTS400, "temp_supply")], indirect=["gateway"],
    ids=["cts602", "cts400"],
)
async def test_an_entity_a_level_leaves_out_keeps_its_name_for_a_level_that_has_it_again(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice, key: str
) -> None:
    """A CTS602's room temperature is documented, not verified."""
    entry = _entry(gateway, "documented")
    await _set_up(hass, entry)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{NAME}_{key}")
    assert entity_id is not None
    registry.async_update_entity(entity_id, name="Living room")
    options: Any = hass.config_entries.options
    for level in ("verified", "documented"):
        flow: ConfigFlowResult = await options.async_init(entry.entry_id)
        await options.async_configure(flow["flow_id"], {CONF_LEVEL: level})
        await hass.async_block_till_done()
        kept = registry.async_get(entity_id)
        assert kept is not None and kept.name == "Living room", level
    assert hass.states.get(entity_id) is not None
    await _unload(hass, entry)


# ============================================================================== migration


def _showed_estimated_values(hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice, model: str | None
                             ) -> MockConfigEntry:
    """An entry of minor version 1 whose user chose to show estimated values, its device
    registered under `model`'s name, or none."""
    entry = MockConfigEntry(
        domain=DOMAIN, title=NAME, unique_id=GATEWAY_ID, data=entry_data(gateway),
        options={"show_inferred": True}, version=2, minor_version=1,
    )
    entry.add_to_hass(hass)
    if model is not None:
        dr.async_get(hass).async_get_or_create(
            config_entry_id=entry.entry_id, identifiers={(DOMAIN, NAME)}, manufacturer="Nilan", model=model
        )
    return entry


async def _set_up_added(hass: HomeAssistant, entry: MockConfigEntry) -> NilanData:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    data: NilanData = entry.runtime_data
    return data


@pytest.mark.parametrize("gateway", [CTS602], indirect=True, ids=["cts602"])
async def test_an_entry_that_showed_estimated_values_of_a_model_that_has_them_is_on_test(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    entry = _showed_estimated_values(hass, gateway, "CTS 602")
    data = await _set_up_added(hass, entry)
    assert dict(entry.options) == {CONF_LEVEL: "test"} and str(data.client.level) == "test"
    assert ("switch", str(PointKey.ENABLE)) in _entities(hass, entry)
    await _unload(hass, entry)


@pytest.mark.parametrize(
    ("gateway", "model"),
    [(OPTIMA_301, "Optima 301"), (OPTIMA_250, "Optima 250"), (CTS602, None)],
    indirect=["gateway"],
    ids=["optima_301", "optima_250", "cts602-never-registered"],
)
async def test_an_entry_that_showed_estimated_values_of_a_model_without_them_is_on_documented(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice, model: str | None
) -> None:
    """Only a model with estimated values was changed by the option, so it gains no candidate,
    no entity and no request to report."""
    gateway.datapoint_registers[(0, 104)] = 63
    entry = _showed_estimated_values(hass, gateway, model)
    data = await _set_up_added(hass, entry)
    assert dict(entry.options) == {CONF_LEVEL: "documented"} and str(data.client.level) == "documented"
    found = _entities(hass, entry)
    assert {("switch", "preheat_enable"), ("number", "min_air_volume")}.isdisjoint(found)
    assert not any(point.candidate is not None for point in data.client.points.values())
    assert _issue(hass, entry) is None
    await _unload(hass, entry)


# ============================================================================== certainty


@pytest.mark.parametrize("gateway", [CTS400], indirect=True, ids=["cts400"])
async def test_every_entity_of_a_cts400_says_it_is_verified(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    entry = _entry(gateway, "documented")
    await _set_up(hass, entry)
    for platform, key in _entities(hass, entry):
        entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{NAME}_{key}")
        state = hass.states.get(entity_id or "")
        if state is not None:
            assert state.attributes["certainty"] == "verified", (platform, key)
    assert _attributes(hass, "button", PointKey.FILTER_REPLACE_RESET)["certainty"] == "verified"
    await _unload(hass, entry)


@pytest.mark.parametrize("gateway", [CTS602], indirect=True, ids=["cts602"])
async def test_an_entity_is_as_certain_as_the_least_certain_point_it_shows(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    """The thermostat shows a CTS602's run setting, which is inferred, beside verified values."""
    entry = _entry(gateway, "test")
    await _set_up(hass, entry)
    assert _attributes(hass, "sensor", PointKey.TEMP_SUPPLY)["certainty"] == "verified"
    assert _attributes(hass, "sensor", PointKey.TEMP_ROOM)["certainty"] == "reported"
    assert _attributes(hass, "climate", THERMOSTAT)["certainty"] == "inferred"
    await _unload(hass, entry)


async def test_a_thermostat_showing_a_point_under_test_says_so(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    """An Optima 250's thermostat shows whether the bypass is open."""
    entry = _entry(gateway, "test")
    await _set_up(hass, entry)
    assert _attributes(hass, "climate", THERMOSTAT)["certainty"] == "test-candidate"
    await _unload(hass, entry)


def test_the_certainty_attribute_names_every_certainty_and_a_point_under_test() -> None:
    assert set(CERTAINTIES) == {str(certainty) for certainty in Certainty} | {"test-candidate"}


@pytest.mark.parametrize("language", ["en", "da"])
def test_every_entity_translates_its_certainty_and_each_of_its_values(language: str) -> None:
    translations = json.loads((TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8"))
    found = {
        json.dumps(entity.get("state_attributes"), sort_keys=True)
        for entities in translations["entity"].values()
        for entity in entities.values()
    }
    assert len(found) == 1
    (only,) = found
    certainty = json.loads(only)["certainty"]
    assert set(certainty["state"]) == set(CERTAINTIES)
    assert certainty["name"] == {"en": "Certainty", "da": "Sikkerhed"}[language]


# ================================================================================= repairs


async def test_at_the_test_level_the_user_is_asked_to_report_whether_the_points_tried_match_the_panel(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    entry = _entry(gateway, "test")
    await _set_up(hass, entry)
    issue = _issue(hass, entry)
    assert issue is not None
    assert (issue.is_fixable, issue.severity, issue.learn_more_url) == (
        False, ir.IssueSeverity.WARNING, TEST_REPORT_URL)
    assert issue.translation_key == TESTING_ISSUE
    assert issue.translation_placeholders == {
        "name": NAME, "model": "Optima 250", "report_url": TEST_REPORT_URL}
    await _unload(hass, entry)


async def test_an_ignored_request_to_report_stays_ignored_when_the_entry_reloads(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    entry = _entry(gateway, "test")
    await _set_up(hass, entry)
    ir.async_ignore_issue(hass, DOMAIN, f"{TESTING_ISSUE}_{entry.entry_id}", True)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    issue = _issue(hass, entry)
    assert issue is not None and issue.dismissed_version is not None
    await _unload(hass, entry)


async def test_the_request_to_report_goes_with_the_entry(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    entry = _entry(gateway, "test")
    await _set_up(hass, entry)
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert _issue(hass, entry) is None


async def test_choosing_another_level_than_test_removes_the_request_to_report(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    entry = _entry(gateway, "test")
    await _set_up(hass, entry)
    assert _issue(hass, entry) is not None
    # HA declares the options manager's user input as a bare `dict`.
    options: Any = hass.config_entries.options
    flow: ConfigFlowResult = await options.async_init(entry.entry_id)
    await options.async_configure(flow["flow_id"], {CONF_LEVEL: "documented"})
    await hass.async_block_till_done()
    assert _issue(hass, entry) is None
    await _unload(hass, entry)


@pytest.mark.parametrize("level", ["verified", "documented"])
async def test_below_the_test_level_nobody_is_asked_to_report(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice, level: str
) -> None:
    entry = _entry(gateway, level)
    await _set_up(hass, entry)
    assert _issue(hass, entry) is None
    await _unload(hass, entry)


@pytest.mark.parametrize("gateway", [CTS400], indirect=True, ids=["cts400"])
async def test_a_unit_with_nothing_under_test_is_not_asked_to_report_at_the_test_level(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    """Every point of a CTS400 is verified, and it has no candidate."""
    entry = _entry(gateway, "test")
    await _set_up(hass, entry)
    assert _issue(hass, entry) is None
    await _unload(hass, entry)


# ============================================================================= diagnostics


async def test_the_diagnostics_list_each_candidate_used_with_what_it_replaces(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    gateway.datapoint_registers[(0, 107)] = 1
    entry = _entry(gateway, "test")
    await _set_up(hass, entry)
    found = await async_get_config_entry_diagnostics(hass, entry)
    assert found["level"] == "test"
    assert found["test"]["candidates"] == {
        "bypass_active": {"value": True, "certainty": "reported", "replaces": "bypass_active"}}
    assert found["test"]["inferred"] == {}
    assert found["certainty"]["temp_supply"] == "reported"
    assert not {"level", "certainty", "candidates"} & set(found["gateway"])
    await _unload(hass, entry)


@pytest.mark.parametrize("gateway", [CTS602], indirect=True, ids=["cts602"])
async def test_the_diagnostics_list_each_inferred_point_used_at_the_test_level(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    entry = _entry(gateway, "test")
    data = await _set_up(hass, entry)
    found = await async_get_config_entry_diagnostics(hass, entry)
    inferred = {str(key) for key, point in data.client.points.items() if point.certainty is Certainty.INFERRED}
    assert set(found["test"]["inferred"]) == inferred and inferred
    assert found["test"]["inferred"]["enable"] == {"value": False}
    assert found["test"]["candidates"] == {}
    await _unload(hass, entry)


@pytest.mark.parametrize("gateway", [CTS400], indirect=True, ids=["cts400"])
async def test_the_diagnostics_list_nothing_under_test_below_the_test_level(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    entry = _entry(gateway, "documented")
    await _set_up(hass, entry)
    found = await async_get_config_entry_diagnostics(hass, entry)
    assert found["level"] == "documented"
    assert found["test"] == {"candidates": {}, "inferred": {}}
    assert set(found["certainty"].values()) == {"verified"}
    await _unload(hass, entry)


# ================================================================================= options


async def _offered(hass: HomeAssistant, entry: MockConfigEntry) -> list[str]:
    """The levels the entry's options offer."""
    options: Any = hass.config_entries.options
    flow: ConfigFlowResult = await options.async_init(entry.entry_id)
    schema: Any = flow.get("data_schema")
    ((marker, field),) = schema.schema.items()
    assert str(marker) == CONF_LEVEL
    assert field.config["translation_key"] == CONF_LEVEL
    assert flow.get("description_placeholders") == {"report_url": TEST_REPORT_URL}
    offered: list[str] = field.config["options"]
    return offered


@pytest.mark.parametrize("gateway", [CTS400], indirect=True, ids=["cts400"])
async def test_the_options_offer_each_level_by_its_translated_name_with_where_to_report(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    entry = _entry(gateway, "documented")
    await _set_up(hass, entry)
    assert await _offered(hass, entry) == ["verified", "documented", "test"]
    await _unload(hass, entry)


async def test_verified_is_not_offered_for_a_model_with_no_verified_value(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    """No value of an Optima 250 has been read on a unit: Verified would leave it no entity."""
    entry = _entry(gateway, "documented")
    await _set_up(hass, entry)
    assert await _offered(hass, entry) == ["documented", "test"]
    await _unload(hass, entry)


async def test_every_level_is_offered_while_the_unit_is_not_loaded(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    entry = _entry(gateway, "documented")
    entry.add_to_hass(hass)
    assert await _offered(hass, entry) == ["verified", "documented", "test"]


@pytest.mark.parametrize("language", ["en", "da"])
def test_the_level_and_the_request_to_report_are_translated_with_their_placeholders(language: str) -> None:
    translations = json.loads((TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8"))
    assert set(translations["selector"][CONF_LEVEL]["options"]) == {"verified", "documented", "test"}
    assert "{report_url}" in translations["options"]["step"]["init"]["description"]
    issue = translations["issues"][TESTING_ISSUE]
    assert "{name}" in issue["title"] and "{model}" in issue["title"]
    assert "{report_url}" in issue["description"]


def test_the_test_report_form_is_the_one_the_request_links_to_and_offers_every_model() -> None:
    form_name = TEST_REPORT_URL.rsplit("template=", 1)[1]
    form = yaml.safe_load((REPOSITORY / ".github" / "ISSUE_TEMPLATE" / form_name).read_text(encoding="utf-8"))
    fields = {field.get("id"): field for field in form["body"]}
    assert fields["model"]["attributes"]["options"] == [model.name for model in MODELS]
    assert {"integration_version", "diagnostics", "points"} <= set(fields)

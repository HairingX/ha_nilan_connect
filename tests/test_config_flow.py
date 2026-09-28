"""Setting a unit up by discovery or by address, changing where it is reached, and renewing its
email."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.config_entries import SOURCE_USER, ConfigEntry, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from nilan_connect import DiscoveredDevice
from nilan_connect.testing import SimulatedMicroNabtoDevice
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nilan_connect.const import CONF_EMAIL, CONF_GATEWAY_ID, DOMAIN

from custom_components.nilan_connect import config_flow

from .conftest import EMAIL, GATEWAY_ID, HOST, NAME, entry_data, simulated_gateway


async def start(hass: HomeAssistant, step: str) -> ConfigFlowResult:
    """A user's flow, past the menu to `step`."""
    started = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert started.get("type") is FlowResultType.MENU
    return await configure(hass, started, {"next_step_id": step})


async def configure(
    hass: HomeAssistant, result: ConfigFlowResult, user_input: dict[str, Any]
) -> ConfigFlowResult:
    # HA declares the flow manager's user input as a bare `dict`.
    flow: Any = hass.config_entries.flow
    configured: ConfigFlowResult = await flow.async_configure(result["flow_id"], user_input)
    return configured


def created(result: ConfigFlowResult) -> ConfigEntry:
    assert result.get("type") is FlowResultType.CREATE_ENTRY, result
    entry = result.get("result")
    assert isinstance(entry, ConfigEntry)
    return entry


def discovered(gateway: SimulatedMicroNabtoDevice, **changes: Any) -> dict[str, Any]:
    return {CONF_GATEWAY_ID: GATEWAY_ID, CONF_NAME: NAME, CONF_EMAIL: EMAIL, **changes}


def by_address(gateway: SimulatedMicroNabtoDevice, **changes: Any) -> dict[str, Any]:
    return {
        CONF_NAME: NAME,
        CONF_HOST: HOST,
        CONF_PORT: gateway.address[1],
        CONF_EMAIL: EMAIL,
        **changes,
    }


# ================================================================================ discovery


async def test_a_discovered_gateway_is_set_up_by_its_id_under_the_name_given(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    form = await start(hass, "discover")
    assert form.get("type") is FlowResultType.FORM
    entry = created(await configure(hass, form, discovered(gateway, **{CONF_NAME: "Upstairs"})))
    assert entry.title == "Upstairs"
    assert entry.unique_id == GATEWAY_ID
    assert dict(entry.data) == entry_data(gateway, **{CONF_NAME: "Upstairs"})
    await hass.async_block_till_done()


async def test_without_an_answering_gateway_one_can_look_again_or_enter_the_address(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice, monkeypatch: pytest.MonkeyPatch
) -> None:
    found: list[DiscoveredDevice] = []
    broadcast = config_flow.discover  # the simulated network's

    async def maybe(**kwargs: Any) -> list[DiscoveredDevice]:
        return await broadcast(**kwargs) if found else []

    monkeypatch.setattr("custom_components.nilan_connect.config_flow.discover", maybe)
    menu = await start(hass, "discover")
    assert menu.get("type") is FlowResultType.MENU
    assert menu.get("step_id") == "no_gateways"
    assert menu.get("menu_options") == ["discover", "manual"]
    assert (await configure(hass, menu, {"next_step_id": "manual"})).get("step_id") == "manual"

    menu = await start(hass, "discover")
    found.append(DiscoveredDevice(GATEWAY_ID, HOST, gateway.address[1]))
    again = await configure(hass, menu, {"next_step_id": "discover"})
    assert again.get("type") is FlowResultType.FORM
    assert again.get("step_id") == "discover"


async def test_a_gateway_already_set_up_is_not_offered(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    result = await start(hass, "discover")
    assert result.get("step_id") == "no_gateways"


async def test_a_gateway_set_up_meanwhile_moves_its_entry_to_where_it_answers(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    form = await start(hass, "discover")
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=GATEWAY_ID,
        data=entry_data(gateway, **{CONF_HOST: "192.0.2.1"}),
        version=2,
    )
    entry.add_to_hass(hass)
    result = await configure(hass, form, discovered(gateway))
    assert result.get("reason") == "already_configured"
    assert entry.data[CONF_HOST] == HOST


async def test_an_email_the_gateway_takes_only_in_lower_case_is_kept_in_lower_case(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    form = await start(hass, "discover")
    entry = created(await configure(hass, form, discovered(gateway, **{CONF_EMAIL: "User@Example.invalid"})))
    assert entry.data[CONF_EMAIL] == EMAIL
    await hass.async_block_till_done()


async def test_an_email_the_gateway_refuses_is_asked_for_again(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    form = await start(hass, "discover")
    result = await configure(hass, form, discovered(gateway, **{CONF_EMAIL: "other@example.invalid"}))
    assert result.get("errors") == {CONF_EMAIL: "invalid_auth"}


@pytest.mark.parametrize(("name", "error"), [("  ", "invalid_name"), (NAME, "name_in_use")])
async def test_a_unit_needs_a_name_no_other_unit_has(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice, name: str, error: str
) -> None:
    """Every unique id starts with the name."""
    MockConfigEntry(
        domain=DOMAIN, unique_id="another.gateway.invalid", data=entry_data(gateway), version=2
    ).add_to_hass(hass)
    form = await start(hass, "discover")
    result = await configure(hass, form, discovered(gateway, **{CONF_NAME: name}))
    assert result.get("errors") == {CONF_NAME: error}


# ================================================================================== address


async def test_a_gateway_set_up_by_address_is_recognised_by_the_id_it_answers_with(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    form = await start(hass, "manual")
    entry = created(await configure(hass, form, by_address(gateway)))
    assert entry.unique_id == GATEWAY_ID
    assert dict(entry.data) == entry_data(gateway)
    await hass.async_block_till_done()


async def test_a_gateway_that_does_not_answer_discovery_at_first_is_set_up_without_an_id(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The id is asked for again when the unit is set up."""

    async def silent(host: str, port: int) -> None:
        return None

    monkeypatch.setattr("custom_components.nilan_connect.config_flow.gateway_at", silent)
    form = await start(hass, "manual")
    result = await configure(hass, form, by_address(gateway))
    assert result.get("data", {}).get(CONF_GATEWAY_ID, "missing") is None
    entry = created(result)
    await hass.async_block_till_done()
    assert entry.unique_id == GATEWAY_ID
    assert entry.data[CONF_GATEWAY_ID] == GATEWAY_ID


async def test_a_gateway_already_set_up_moves_to_the_address_entered(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=GATEWAY_ID,
        data=entry_data(gateway, **{CONF_HOST: "192.0.2.1", CONF_NAME: "Old"}),
        version=2,
    )
    entry.add_to_hass(hass)
    form = await start(hass, "manual")
    result = await configure(hass, form, by_address(gateway))
    assert result.get("reason") == "already_configured"
    assert entry.data[CONF_HOST] == HOST


async def test_an_address_must_be_entered(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    form = await start(hass, "manual")
    result = await configure(hass, form, by_address(gateway, **{CONF_HOST: " "}))
    assert result.get("errors") == {CONF_HOST: "invalid_host"}


async def test_a_gateway_that_does_not_answer_is_reported(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    gateway.silent = True
    form = await start(hass, "manual")
    result = await configure(hass, form, by_address(gateway))
    assert result.get("errors") == {"base": "cannot_connect"}


async def test_a_controller_that_is_not_supported_is_reported(hass: HomeAssistant) -> None:
    other = simulated_gateway(identity={
        "device_number": 1, "device_model": 9999, "slave_device_number": 1, "slave_device_model": 1
    })
    async with other:
        form = await start(hass, "manual")
        result = await configure(hass, form, by_address(other))
    assert result.get("errors") == {"base": "unsupported_device"}


async def test_an_unexpected_error_is_reported(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*_: Any) -> str:
        raise RuntimeError("broken")

    monkeypatch.setattr("custom_components.nilan_connect.config_flow.connect_once", broken)
    form = await start(hass, "manual")
    result = await configure(hass, form, by_address(gateway))
    assert result.get("errors") == {"base": "unknown"}


# ============================================================================= reconfigure


async def reconfigure(hass: HomeAssistant, entry: MockConfigEntry) -> ConfigFlowResult:
    form = await entry.start_reconfigure_flow(hass)
    assert form.get("type") is FlowResultType.FORM
    return form


async def test_the_address_port_and_email_can_be_changed(
    hass: HomeAssistant, loaded: Any, config_entry: MockConfigEntry, gateway: SimulatedMicroNabtoDevice
) -> None:
    form = await reconfigure(hass, config_entry)
    result = await configure(
        hass,
        form,
        {CONF_HOST: HOST, CONF_PORT: gateway.address[1], CONF_EMAIL: "User@Example.invalid"},
    )
    assert result.get("reason") == "reconfigure_successful"
    await hass.async_block_till_done()
    assert config_entry.data[CONF_EMAIL] == EMAIL
    assert config_entry.data[CONF_NAME] == NAME


async def test_without_an_address_the_gateway_is_found_by_its_id(
    hass: HomeAssistant, config_entry: MockConfigEntry, gateway: SimulatedMicroNabtoDevice
) -> None:
    config_entry.add_to_hass(hass)
    form = await reconfigure(hass, config_entry)
    result = await configure(hass, form, {CONF_PORT: gateway.address[1], CONF_EMAIL: EMAIL})
    assert result.get("reason") == "reconfigure_successful"
    assert config_entry.data[CONF_HOST] is None
    await hass.async_block_till_done()


async def test_without_an_address_or_an_id_the_gateway_cannot_be_found(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, data=entry_data(gateway, **{CONF_GATEWAY_ID: None}), version=2
    )
    entry.add_to_hass(hass)
    form = await reconfigure(hass, entry)
    result = await configure(hass, form, {CONF_PORT: gateway.address[1], CONF_EMAIL: EMAIL})
    assert result.get("errors") == {CONF_HOST: "invalid_host"}


async def test_another_gateway_at_the_address_is_refused(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="another.gateway.invalid",
        data=entry_data(gateway, **{CONF_GATEWAY_ID: "another.gateway.invalid"}),
        version=2,
    )
    entry.add_to_hass(hass)
    form = await reconfigure(hass, entry)
    result = await configure(
        hass, form, {CONF_HOST: HOST, CONF_PORT: gateway.address[1], CONF_EMAIL: EMAIL}
    )
    assert result.get("errors") == {"base": "wrong_gateway"}


async def test_a_gateway_set_up_without_an_id_learns_it_when_reconfigured(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, data=entry_data(gateway, **{CONF_GATEWAY_ID: None}), version=2
    )
    entry.add_to_hass(hass)
    form = await reconfigure(hass, entry)
    result = await configure(
        hass, form, {CONF_HOST: HOST, CONF_PORT: gateway.address[1], CONF_EMAIL: EMAIL}
    )
    assert result.get("reason") == "reconfigure_successful"
    assert entry.data[CONF_GATEWAY_ID] == GATEWAY_ID
    await hass.async_block_till_done()


async def test_a_refused_email_is_asked_for_again_when_reconfigured(
    hass: HomeAssistant, config_entry: MockConfigEntry, gateway: SimulatedMicroNabtoDevice
) -> None:
    config_entry.add_to_hass(hass)
    form = await reconfigure(hass, config_entry)
    result = await configure(
        hass,
        form,
        {CONF_HOST: HOST, CONF_PORT: gateway.address[1], CONF_EMAIL: "other@example.invalid"},
    )
    assert result.get("errors") == {CONF_EMAIL: "invalid_auth"}


# ================================================================================== reauth


async def test_a_refused_email_is_renewed_and_the_unit_set_up_again(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=GATEWAY_ID,
        data=entry_data(gateway, **{CONF_EMAIL: "old@example.invalid"}),
        version=2,
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    (flow,) = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert flow.get("context", {}).get("source") == "reauth"

    refused = await configure(hass, flow, {CONF_EMAIL: "still@example.invalid"})
    assert refused.get("errors") == {CONF_EMAIL: "invalid_auth"}
    result = await configure(hass, flow, {CONF_EMAIL: EMAIL})
    assert result.get("reason") == "reauth_successful"
    assert entry.data[CONF_EMAIL] == EMAIL
    await hass.async_block_till_done()
    assert entry.runtime_data.client.model.name == "CTS 400"
    await hass.config_entries.async_unload(entry.entry_id)

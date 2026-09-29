"""Controllers besides the CTS400: each is set up with the entities it shows."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_socket
from homeassistant.config_entries import ConfigEntryState, ConfigFlowResult
from homeassistant.const import UnitOfTime
from homeassistant.components.climate.const import HVACMode
from homeassistant.core import HomeAssistant, State
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from nilan_connect import PointKey
from nilan_connect.testing import SimulatedMicroNabtoDevice
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nilan_connect.climate import THERMOSTAT
from custom_components.nilan_connect.const import CONF_SHOW_INFERRED, DOMAIN
from custom_components.nilan_connect.data import NilanData

from .conftest import GATEWAY_ID, NAME, entry_data, simulated_gateway

EVERY_REGISTER = {(0, address): 0 for address in range(300)}
"""A register at every address a controller's model reads, each holding 0."""

OPTIMA_250 = {"device_number": 0, "device_model": 1040, "slave_device_number": 79250, "slave_device_model": 1}
OPTIMA_270 = {"device_number": 79265, "device_model": 2010, "slave_device_number": 0, "slave_device_model": 0}
CTS602 = {"device_number": 0, "device_model": 1140, "slave_device_number": 2763306, "slave_device_model": 0}


@pytest.fixture(params=[OPTIMA_250, OPTIMA_270, CTS602], ids=["optima_250", "optima_270", "cts602"])
async def gateway(request: pytest.FixtureRequest) -> AsyncIterator[SimulatedMicroNabtoDevice]:
    """A gateway in front of another controller, every register it reads holding 0."""
    pytest_socket.enable_socket()
    simulated = simulated_gateway(
        identity=request.param, datapoint_registers=EVERY_REGISTER, setpoint_registers=EVERY_REGISTER
    )
    async with simulated:
        yield simulated


def _entity(hass: HomeAssistant, platform: str, key: str) -> er.RegistryEntry | None:
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(platform, DOMAIN, f"{NAME}_{key}")
    return registry.async_get(entity_id) if entity_id else None


async def test_another_controller_is_set_up(
    hass: HomeAssistant, config_entry: MockConfigEntry, loaded: NilanData
) -> None:
    assert config_entry.state is ConfigEntryState.LOADED
    assert _entity(hass, "sensor", PointKey.TEMP_SUPPLY) is not None
    assert _entity(hass, "select", PointKey.FAN_LEVEL) is not None


def _state(hass: HomeAssistant, platform: str, key: str) -> State:
    entry = _entity(hass, platform, key)
    assert entry is not None
    state = hass.states.get(entry.entity_id)
    assert state is not None
    return state


@pytest.mark.parametrize("gateway", [CTS602], indirect=True, ids=["cts602"])
async def test_a_point_placed_only_by_the_manual_gets_no_entity(hass: HomeAssistant, loaded: NilanData) -> None:
    """A CTS602's run setting is placed by its manual's register order."""
    assert loaded.client.has(PointKey.ENABLE)
    assert _entity(hass, "switch", PointKey.ENABLE) is None


@pytest.mark.parametrize("gateway", [CTS602, OPTIMA_270], indirect=True, ids=["cts602", "optima_270"])
async def test_a_unit_without_a_shown_run_setting_has_a_thermostat_that_cannot_turn_it_off(
    hass: HomeAssistant, loaded: NilanData
) -> None:
    thermostat = _state(hass, "climate", THERMOSTAT)
    assert thermostat.attributes["hvac_modes"] == [HVACMode.AUTO]
    assert thermostat.state == HVACMode.AUTO


@pytest.mark.parametrize("gateway", [CTS602], indirect=True, ids=["cts602"])
async def test_the_user_can_choose_to_see_values_found_only_from_the_manual(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, title=NAME, unique_id=GATEWAY_ID, data=entry_data(gateway),
        options={CONF_SHOW_INFERRED: True}, version=2, minor_version=1,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert _entity(hass, "switch", PointKey.ENABLE) is not None
    assert HVACMode.OFF in _state(hass, "climate", THERMOSTAT).attributes["hvac_modes"]
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_the_choice_to_see_them_is_an_option_of_the_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry, loaded: NilanData
) -> None:
    # HA declares the options manager's user input as a bare `dict`.
    options: Any = hass.config_entries.options
    flow: ConfigFlowResult = await options.async_init(config_entry.entry_id)
    assert flow.get("type") is FlowResultType.FORM
    result: ConfigFlowResult = await options.async_configure(flow["flow_id"], {CONF_SHOW_INFERRED: True})
    await hass.async_block_till_done()
    assert result.get("type") is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {CONF_SHOW_INFERRED: True}


@pytest.mark.parametrize("gateway", [CTS602], indirect=True, ids=["cts602"])
async def test_a_choice_offers_only_the_states_the_units_point_has(hass: HomeAssistant, loaded: NilanData) -> None:
    """The CTS602's manual: "0: Pressure guard (input) 1: 30 days 2: 90 days 3: 180 days 4: 360 days 5: 70 days
    and pressure guard"; its operation mode's SERVICE is set through the service mode."""
    interval = _state(hass, "select", PointKey.FILTER_REPLACE_INTERVAL_CHOICE)
    assert interval.attributes["options"] == [
        "pressure_guard", "days_30", "days_90", "days_180", "days_360", "days_70_and_pressure_guard"]
    assert interval.state == "pressure_guard"
    assert "service" not in _state(hass, "select", PointKey.OPERATION_MODE).attributes["options"]


@pytest.mark.parametrize("gateway", [CTS602], indirect=True, ids=["cts602"])
async def test_a_state_is_shown_by_its_name(hass: HomeAssistant, loaded: NilanData) -> None:
    """Every register holds 0: no alarm, and the control state OFF."""
    assert _state(hass, "sensor", PointKey.ALARM_1).state == "none"
    assert _state(hass, "sensor", PointKey.OPERATION_STATE).state == "off"


@pytest.mark.parametrize("gateway", [OPTIMA_270], indirect=True, ids=["optima_270"])
async def test_a_setting_no_source_gives_a_range_for_gets_no_number(hass: HomeAssistant, loaded: NilanData) -> None:
    assert loaded.client.has(PointKey.FILTER_REPLACE_INTERVAL)
    assert _entity(hass, "number", PointKey.FILTER_REPLACE_INTERVAL) is None


@pytest.mark.parametrize("gateway", [OPTIMA_250], indirect=True, ids=["optima_250"])
async def test_a_filter_interval_in_months_is_a_number_without_a_duration(
    hass: HomeAssistant, loaded: NilanData
) -> None:
    interval = _entity(hass, "number", PointKey.FILTER_REPLACE_INTERVAL)
    assert interval is not None
    assert interval.unit_of_measurement == UnitOfTime.MONTHS
    state = hass.states.get(interval.entity_id)
    assert state is not None and "device_class" not in state.attributes

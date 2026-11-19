"""Controllers besides the CTS400: each is set up with the entities it shows."""

from __future__ import annotations

import asyncio

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_socket
from homeassistant.config_entries import ConfigEntryState, ConfigFlowResult
from homeassistant.const import (
    PERCENTAGE,
    STATE_OFF,
    STATE_ON,
    EntityCategory,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.components.climate.const import HVACMode
from homeassistant.core import HomeAssistant, State
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from nilan_connect import PointKey
from nilan_connect.testing import SimulatedMicroNabtoDevice
from pytest_homeassistant.common import MockConfigEntry

from custom_components.nilan_connect.climate import THERMOSTAT
from custom_components.nilan_connect.const import CONF_LEVEL, DOMAIN
from custom_components.nilan_connect.data import NilanData
from custom_components.nilan_connect.sensor import EFFICIENCY

from .conftest import GATEWAY_ID, NAME, entry_data, simulated_gateway

SETPOINT_WRITE = 0x2B

EVERY_REGISTER = {(0, address): 0 for address in range(300)}
"""A register at every address a controller's model reads, each holding 0."""

OPTIMA_250 = {"device_number": 0, "device_model": 1040, "slave_device_number": 79250, "slave_device_model": 1}
OPTIMA_260 = {"device_number": 0, "device_model": 1040, "slave_device_number": 70810, "slave_device_model": 26}
OPTIMA_270 = {"device_number": 79265, "device_model": 2010, "slave_device_number": 0, "slave_device_model": 0}
OPTIMA_301 = {"device_number": 0, "device_model": 1040, "slave_device_number": 79250, "slave_device_model": 5}
OPTIMA_312 = {"device_number": 0, "device_model": 1040, "slave_device_number": 79250, "slave_device_model": 9}
OPTIMA_314 = {"device_number": 79280, "device_model": 2020, "slave_device_number": 0, "slave_device_model": 0}
CTS602 = {"device_number": 0, "device_model": 1140, "slave_device_number": 2763306, "slave_device_model": 0}
CTS602_HEAT_PUMP = {**CTS602, "slave_device_model": 44}
CTS602_LIGHT = {**CTS602, "slave_device_model": 2}


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


async def _set_up(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def _at_test_level(gateway: SimulatedMicroNabtoDevice) -> MockConfigEntry:
    """An entry whose user has chosen the Test level, which shows the values found only from the
    manual."""
    return MockConfigEntry(
        domain=DOMAIN, title=NAME, unique_id=GATEWAY_ID, data=entry_data(gateway),
        options={CONF_LEVEL: "test"}, version=2, minor_version=2,
    )


def _registered(hass: HomeAssistant, entry: MockConfigEntry, platform: str, key: str) -> er.RegistryEntry:
    """An entity of `key` as an earlier version of the integration left it in the registry."""
    return er.async_get(hass).async_get_or_create(platform, DOMAIN, f"{NAME}_{key}", config_entry=entry)


def _state(hass: HomeAssistant, platform: str, key: str) -> State:
    entry = _entity(hass, platform, key)
    assert entry is not None
    state = hass.states.get(entry.entity_id)
    assert state is not None
    return state


@pytest.mark.parametrize("gateway", [CTS602], indirect=True, ids=["cts602"])
async def test_a_point_placed_only_by_the_manual_gets_no_entity(hass: HomeAssistant, loaded: NilanData) -> None:
    """A CTS602's run setting is placed by its manual's register order."""
    assert not loaded.client.has(PointKey.ENABLE)
    assert _entity(hass, "switch", PointKey.ENABLE) is None


@pytest.mark.parametrize("gateway", [CTS602, OPTIMA_270], indirect=True, ids=["cts602", "optima_270"])
async def test_a_unit_without_a_shown_run_setting_has_a_thermostat_that_cannot_turn_it_off(
    hass: HomeAssistant, loaded: NilanData
) -> None:
    thermostat = _state(hass, "climate", THERMOSTAT)
    assert thermostat.attributes["hvac_modes"] == [HVACMode.AUTO]
    assert thermostat.state == HVACMode.AUTO


@pytest.mark.parametrize("gateway", [CTS602], indirect=True, ids=["cts602"])
async def test_at_the_test_level_a_value_found_only_from_the_manual_gets_an_entity(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    entry = _at_test_level(gateway)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert _entity(hass, "switch", PointKey.ENABLE) is not None
    assert HVACMode.OFF in _state(hass, "climate", THERMOSTAT).attributes["hvac_modes"]
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_the_level_is_an_option_of_the_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry, loaded: NilanData
) -> None:
    # HA declares the options manager's user input as a bare `dict`.
    options: Any = hass.config_entries.options
    flow: ConfigFlowResult = await options.async_init(config_entry.entry_id)
    assert flow.get("type") is FlowResultType.FORM
    result: ConfigFlowResult = await options.async_configure(flow["flow_id"], {CONF_LEVEL: "test"})
    await hass.async_block_till_done()
    assert result.get("type") is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {CONF_LEVEL: "test"}
    data: NilanData = config_entry.runtime_data
    assert str(data.client.level) == "test"


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


@pytest.mark.parametrize("gateway", [CTS602], indirect=True, ids=["cts602"])
async def test_a_setting_no_source_gives_a_range_for_gets_no_number(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    """A CTS602's service capacity is placed by its manual, which gives it no range."""
    entry = _at_test_level(gateway)
    await _set_up(hass, entry)
    data: NilanData = entry.runtime_data
    assert data.client.has(PointKey.SERVICE_CAPACITY)
    assert _entity(hass, "number", PointKey.SERVICE_CAPACITY) is None
    await _unload(hass, entry)


@pytest.mark.parametrize("gateway", [OPTIMA_270], indirect=True, ids=["optima_270"])
async def test_a_write_an_optima_270s_gateway_answers_0x01_is_taken_and_sent_once(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice, loaded: NilanData
) -> None:
    """An Optima 270's gateway answered 0x01 to every write it took."""
    gateway.write_taken = frozenset({0, 1})
    gateway.write_statuses = [1]
    entry = _entity(hass, "climate", THERMOSTAT)
    assert entry is not None
    # A write sent again waits on the fake clock, which nothing moves here.
    async with asyncio.timeout(5.0):
        await hass.services.async_call(
            "climate", "set_temperature", {"entity_id": entry.entity_id, "temperature": 22.0}, blocking=True
        )
    assert [command.items for command in gateway.received(SETPOINT_WRITE)] == [((0, 12, 120),)]


@pytest.mark.parametrize("gateway", [OPTIMA_250], indirect=True, ids=["optima_250"])
async def test_a_filter_interval_in_months_is_a_number_without_a_duration(
    hass: HomeAssistant, loaded: NilanData
) -> None:
    interval = _entity(hass, "number", PointKey.FILTER_REPLACE_INTERVAL)
    assert interval is not None
    assert interval.unit_of_measurement == UnitOfTime.MONTHS
    state = hass.states.get(interval.entity_id)
    assert state is not None and "device_class" not in state.attributes


@pytest.mark.parametrize("gateway", [CTS602], indirect=True, ids=["cts602"])
async def test_choosing_a_state_writes_the_units_code_for_it(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice, loaded: NilanData
) -> None:
    entry = _entity(hass, "select", PointKey.FILTER_REPLACE_INTERVAL_CHOICE)
    assert entry is not None
    await hass.services.async_call(
        "select", "select_option", {"entity_id": entry.entity_id, "option": "days_90"}, blocking=True
    )
    for _ in range(100):
        if gateway.received(SETPOINT_WRITE):
            break
        await asyncio.sleep(0.01)
    assert (0, 159, 2) in [item for command in gateway.received(SETPOINT_WRITE) for item in command.items]


@pytest.mark.parametrize(
    ("gateway", "old", "new"),
    [
        (OPTIMA_301, PointKey.TEMP_BEFORE_CONDENSER, PointKey.TEMP_BEFORE_EVAPORATOR),
        (OPTIMA_312, PointKey.TEMP_BEFORE_CONDENSER, PointKey.TEMP_BEFORE_EVAPORATOR),
        (OPTIMA_314, PointKey.TEMP_BEFORE_CONDENSER, PointKey.TEMP_BEFORE_EVAPORATOR),
        (OPTIMA_301, PointKey.TEMP_ROOM, PointKey.TEMP_ROOM_PANEL),
        (OPTIMA_312, PointKey.TEMP_ROOM, PointKey.TEMP_ROOM_PANEL),
    ],
    indirect=["gateway"],
    ids=["optima_301_t5", "optima_312_t5", "optima_314_t5", "optima_301_t2", "optima_312_t2"],
)
async def test_the_entity_of_a_renamed_point_keeps_its_entity_id_and_history(
    hass: HomeAssistant, config_entry: MockConfigEntry, old: str, new: str
) -> None:
    """The point reads the same register, with the same meaning, under a key that names it."""
    config_entry.add_to_hass(hass)
    before = _registered(hass, config_entry, "sensor", old)
    await _set_up(hass, config_entry)
    after = er.async_get(hass).async_get(before.entity_id)
    assert after is not None and after.unique_id == f"{NAME}_{new}"
    assert _entity(hass, "sensor", old) is None
    assert hass.states.get(before.entity_id) is not None
    await _unload(hass, config_entry)


@pytest.mark.parametrize("gateway", [OPTIMA_301], indirect=True, ids=["optima_301"])
async def test_a_renamed_points_old_entity_is_removed_where_its_new_one_exists(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    old = _registered(hass, config_entry, "sensor", PointKey.TEMP_ROOM)
    new = _registered(hass, config_entry, "sensor", PointKey.TEMP_ROOM_PANEL)
    await _set_up(hass, config_entry)
    registry = er.async_get(hass)
    assert registry.async_get(old.entity_id) is None
    kept = registry.async_get(new.entity_id)
    assert kept is not None and kept.unique_id == f"{NAME}_{PointKey.TEMP_ROOM_PANEL}"
    await _unload(hass, config_entry)


@pytest.mark.parametrize("gateway", [CTS602_HEAT_PUMP], indirect=True, ids=["cts602_heat_pump"])
async def test_a_cts602_keeps_its_temperatures_before_the_condenser_and_of_the_room(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Only an Optima's T5 and T2 were renamed."""
    config_entry.add_to_hass(hass)
    kept = [_registered(hass, config_entry, "sensor", key)
            for key in (PointKey.TEMP_BEFORE_CONDENSER, PointKey.TEMP_ROOM)]
    await _set_up(hass, config_entry)
    registry = er.async_get(hass)
    found = [registry.async_get(entry.entity_id) for entry in kept]
    assert [entry.unique_id if entry else None for entry in found] == [entry.unique_id for entry in kept]
    assert _entity(hass, "sensor", PointKey.TEMP_BEFORE_EVAPORATOR) is None
    await _unload(hass, config_entry)


@pytest.mark.parametrize("gateway", [CTS602_HEAT_PUMP], indirect=True, ids=["cts602_heat_pump"])
async def test_a_heat_pump_states_code_is_a_disabled_code_sensor(hass: HomeAssistant, loaded: NilanData) -> None:
    """Several of a heat pump's codes share a state; the code tells them apart."""
    code = _entity(hass, "sensor", PointKey.HEAT_PUMP_STATE_CODE)
    assert code is not None and code.disabled_by is er.RegistryEntryDisabler.INTEGRATION


@pytest.mark.parametrize("gateway", [OPTIMA_312], indirect=True, ids=["optima_312"])
async def test_an_optima_312s_electric_coil_is_shown_and_never_switched(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice, config_entry: MockConfigEntry
) -> None:
    """Its setpoint 21 is the coil fitted, 2 an electric preheater; the switch that wrote it is
    removed, as it means something else."""
    gateway.setpoint_registers[(0, 21)] = 2
    config_entry.add_to_hass(hass)
    switch = _registered(hass, config_entry, "switch", PointKey.REHEAT_ENABLE)
    await _set_up(hass, config_entry)
    assert er.async_get(hass).async_get(switch.entity_id) is None
    assert _state(hass, "binary_sensor", PointKey.PREHEAT_COIL_FITTED).state == STATE_ON
    assert _state(hass, "binary_sensor", PointKey.REHEAT_COIL_FITTED).state == STATE_OFF
    coil = _entity(hass, "sensor", PointKey.ELECTRIC_COIL)
    assert coil is not None and coil.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert coil.entity_category is EntityCategory.DIAGNOSTIC
    await _unload(hass, config_entry)


@pytest.mark.parametrize("gateway", [OPTIMA_312], indirect=True, ids=["optima_312"])
async def test_an_optima_312s_electric_coil_is_shown_by_its_name(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice, config_entry: MockConfigEntry
) -> None:
    gateway.setpoint_registers[(0, 21)] = 1
    config_entry.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "sensor", DOMAIN, f"{NAME}_{PointKey.ELECTRIC_COIL}", config_entry=config_entry
    )
    await _set_up(hass, config_entry)
    coil = _state(hass, "sensor", PointKey.ELECTRIC_COIL)
    assert coil.state == "reheat"
    assert coil.attributes["options"] == ["none", "reheat", "preheat"]
    await _unload(hass, config_entry)


@pytest.mark.parametrize("gateway", [OPTIMA_301], indirect=True, ids=["optima_301"])
async def test_an_optima_301_shows_no_preheat_switch_below_the_test_level_and_its_cooling_setting_is_in_c(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice, config_entry: MockConfigEntry
) -> None:
    """Its setpoint 20 is the minimum air volume, which the preheat switch wrote; the switch's
    entry stays for the preheat tried at setpoint 16 at the Test level."""
    gateway.setpoint_registers[(0, 1)] = 55
    config_entry.add_to_hass(hass)
    switch = _registered(hass, config_entry, "switch", PointKey.PREHEAT_ENABLE)
    cooling = _registered(hass, config_entry, "number", PointKey.COOLING_TEMPERATURE)
    await _set_up(hass, config_entry)
    registry = er.async_get(hass)
    data: NilanData = config_entry.runtime_data
    assert switch.unique_id not in data.unique_ids
    assert registry.async_get(switch.entity_id) is not None
    number = registry.async_get(cooling.entity_id)
    assert number is not None and number.unit_of_measurement == UnitOfTemperature.CELSIUS
    state = hass.states.get(cooling.entity_id)
    assert state is not None and state.state == "5.5"
    assert (state.attributes["min"], state.attributes["max"], state.attributes["step"]) == (3, 10, 0.1)
    await _unload(hass, config_entry)


@pytest.mark.parametrize("gateway", [OPTIMA_270, OPTIMA_314], indirect=True, ids=["optima_270", "optima_314"])
async def test_an_optimas_days_since_the_filter_change_is_a_sensor(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice, config_entry: MockConfigEntry
) -> None:
    """Setpoint 100 counts the days, and stays at 250 once a change is due."""
    gateway.setpoint_registers[(0, 100)] = 250
    await _set_up(hass, config_entry)
    days = _state(hass, "sensor", PointKey.FILTER_REPLACE_TIME_AGO)
    assert float(days.state) == 250
    assert days.attributes["unit_of_measurement"] == UnitOfTime.DAYS
    assert _entity(hass, "number", PointKey.FILTER_REPLACE_INTERVAL) is None
    await _unload(hass, config_entry)


@pytest.mark.parametrize("gateway", [OPTIMA_250, OPTIMA_260], indirect=True, ids=["optima_250", "optima_260"])
async def test_an_optimas_bypass_opening_is_a_sensor_in_percent(
    hass: HomeAssistant, loaded: NilanData
) -> None:
    position = _state(hass, "sensor", PointKey.BYPASS_POSITION)
    assert position.attributes["unit_of_measurement"] == PERCENTAGE


@pytest.mark.parametrize("gateway", [CTS602_LIGHT], indirect=True, ids=["cts602_light"])
async def test_a_cts602_lights_supply_air_after_its_heater_is_a_new_entity(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Its supply air was read after the heater, under the key of the air before it: that entity
    goes, and so does the efficiency worked out from it."""
    config_entry.add_to_hass(hass)
    supply = _registered(hass, config_entry, "sensor", PointKey.TEMP_SUPPLY)
    efficiency = _registered(hass, config_entry, "sensor", EFFICIENCY)
    await _set_up(hass, config_entry)
    registry = er.async_get(hass)
    assert registry.async_get(supply.entity_id) is None
    assert registry.async_get(efficiency.entity_id) is None
    after_heater = _entity(hass, "sensor", PointKey.TEMP_SUPPLY_AFTER_HEATER)
    assert after_heater is not None and after_heater.entity_id != supply.entity_id
    await _unload(hass, config_entry)


@pytest.mark.parametrize("gateway", [CTS602], indirect=True, ids=["cts602"])
async def test_a_cts602s_electric_hot_water_supplement_is_a_switch(
    hass: HomeAssistant, gateway: SimulatedMicroNabtoDevice
) -> None:
    """HR 1704 HotWater.HeatType: "Use of electricity supplement: 0=OFF, 1=El"; it was a select."""
    gateway.setpoint_registers[(0, 193)] = 1
    entry = _at_test_level(gateway)
    entry.add_to_hass(hass)
    select = _registered(hass, entry, "select", "hotwater_supplement")
    await _set_up(hass, entry)
    assert er.async_get(hass).async_get(select.entity_id) is None
    assert _state(hass, "switch", PointKey.HOTWATER_HEATER_ENABLE).state == STATE_ON
    await _unload(hass, entry)

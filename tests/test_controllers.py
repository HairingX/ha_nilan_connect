"""Controllers besides the CTS400: each is set up with the entities it shows."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_socket
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from nilan_connect import PointKey
from nilan_connect.testing import SimulatedMicroNabtoDevice
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nilan_connect.climate import THERMOSTAT
from custom_components.nilan_connect.const import DOMAIN
from custom_components.nilan_connect.data import NilanData

from .conftest import NAME, simulated_gateway

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


@pytest.mark.parametrize("gateway", [CTS602], indirect=True, ids=["cts602"])
async def test_a_point_placed_only_by_the_manual_gets_no_entity(hass: HomeAssistant, loaded: NilanData) -> None:
    """A CTS602's run setting is placed by its manual's register order, so it has no thermostat."""
    assert loaded.client.has(PointKey.ENABLE)
    assert _entity(hass, "climate", THERMOSTAT) is None
    assert _entity(hass, "switch", PointKey.ENABLE) is None


@pytest.mark.parametrize("gateway", [CTS602], indirect=True, ids=["cts602"])
async def test_without_a_thermostat_the_fan_level_is_shown(hass: HomeAssistant, loaded: NilanData) -> None:
    fan_level = _entity(hass, "select", PointKey.FAN_LEVEL)
    assert fan_level is not None and fan_level.hidden_by is None


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

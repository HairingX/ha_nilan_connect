"""The entities of a CTS400: the ones an existing installation has, their values, and writes."""

from __future__ import annotations

import asyncio
import dataclasses
import math
from typing import Any

import pytest
from homeassistant.components.climate.const import HVACAction, HVACMode
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_component import EntityComponent
from homeassistant.setup import async_setup_component
from nilan_connect import Client, Point, PointKey
from nilan_connect.testing import FakeClock, SimulatedMicroNabtoDevice
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nilan_connect.const import DOMAIN
from custom_components.nilan_connect.data import NilanData
from custom_components.nilan_connect.number import value_range
from custom_components.nilan_connect.select import levels

from .conftest import NAME

SETPOINT_WRITE = 0x2B

# (platform, what the unique id ends with): (disabled by default, hidden by default)
EXISTING: dict[tuple[str, str], tuple[bool, bool]] = {
    **{("binary_sensor", key): (False, False) for key in (
        "alarm_status", "bypass_active", "defrost_active", "filter_ok",
        "humidity_high_active", "winter_mode_active")},
    **{("button", key): (False, False) for key in ("alarm_reset", "filter_replace_reset")},
    ("climate", "hvac"): (False, False),
    **{("number", key): (True, True) for key in (
        "co2_threshold", "defrost_break_time", "defrost_max_time",
        *(f"fan_level{n}_{side}_preset" for n in range(1, 5) for side in ("supply", "extract")),
        "fan_level_high_co2", "fan_level_high_humidity", "temp_defrost_high_threshold",
        "temp_defrost_low_threshold", "temp_regulation_dead_band", "temp_supply_max",
        "temp_supply_min", "temp_winter_mode_threshold", "voc_threshold")},
    **{("number", key): (False, True) for key in (
        "fan_level_high_humidity_time", "fan_level_low_humidity", "filter_replace_interval",
        "humidity_low_threshold")},
    ("number", "temp_target"): (False, False),
    ("select", "fan_level"): (False, True),
    **{("sensor", f"alarm_{n}_{kind}"): (True, False) for n in (1, 2, 3) for kind in ("code", "info")},
    **{("sensor", key): (False, False) for key in (
        "co2_level", "efficiency", "fan_dutycycle_extract", "fan_dutycycle_supply",
        "fan_level_current", "filter_replace_time_ago", "filter_replace_time_remain", "humidity",
        "humidity_average", "humidity_high_level", "humidity_high_level_time", "temp_exhaust",
        "temp_extract", "temp_outside", "temp_supply", "voc_level")},
    ("switch", "enable"): (True, False),
}
"""Every entity a CTS400 had with Nilan Connect before this integration, as its entity registry
held them, and whether it was disabled or hidden by default. Their unique ids are the unit's
name, an underscore, and this."""


def entity_id(hass: HomeAssistant, platform: str, key: str) -> str:
    found = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{NAME}_{key}")
    assert found is not None, key
    return found


def state_of(hass: HomeAssistant, platform: str, key: str) -> State:
    found = hass.states.get(entity_id(hass, platform, key))
    assert found is not None, key
    return found


def entity_of(hass: HomeAssistant, platform: str, key: str) -> Any:
    component: EntityComponent[Any] = hass.data["entity_components"][platform]
    return component.get_entity(entity_id(hass, platform, key))


async def refresh(hass: HomeAssistant, *entity_ids: str) -> None:
    """Read the entities' values from the unit now, as homeassistant.update_entity does."""
    assert await async_setup_component(hass, "homeassistant", {})
    await hass.services.async_call(
        "homeassistant", "update_entity", {"entity_id": list(entity_ids)}, blocking=True
    )
    await hass.async_block_till_done()


async def written(gateway: SimulatedMicroNabtoDevice) -> list[tuple[int, ...]]:
    """A write gets no answer to wait for, so wait for the gateway to have received it."""
    for _ in range(100):
        if gateway.received(SETPOINT_WRITE):
            break
        await asyncio.sleep(0.01)
    return [item for command in gateway.received(SETPOINT_WRITE) for item in command.items]


async def test_an_existing_installation_keeps_every_entity_it_has(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry
) -> None:
    registry = er.async_get(hass)
    found = {
        (entry.domain, entry.unique_id.removeprefix(f"{NAME}_")): (
            entry.disabled_by is not None,
            entry.hidden_by is not None,
        )
        for entry in er.async_entries_for_config_entry(registry, config_entry.entry_id)
    }
    assert {key: found.get(key) for key in EXISTING} == EXISTING


async def test_the_unit_is_one_device_identified_by_its_name(
    hass: HomeAssistant, loaded: NilanData, config_entry: MockConfigEntry
) -> None:
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), config_entry.entry_id)
    assert [(d.identifiers, d.name, d.manufacturer, d.model) for d in devices] == [
        ({(DOMAIN, NAME)}, NAME, "Nilan", "CTS 400")
    ]


@pytest.mark.parametrize(
    ("platform", "key", "state"),
    [
        ("sensor", "temp_outside", "15.2"),
        ("sensor", "temp_supply", "16.4"),
        ("sensor", "temp_extract", "23.1"),
        ("sensor", "temp_exhaust", "23.9"),
        ("sensor", "humidity", "56.0"),
        ("sensor", "fan_dutycycle_extract", "26.0"),
        ("sensor", "fan_level_current", "1"),
        ("sensor", "filter_replace_time_ago", "139.0"),
        ("sensor", "filter_replace_time_remain", "0.0"),
        ("binary_sensor", "alarm_status", STATE_ON),
        ("binary_sensor", "bypass_active", STATE_ON),
        ("binary_sensor", "filter_ok", STATE_ON),
        ("binary_sensor", "humidity_high_active", STATE_OFF),
        ("binary_sensor", "winter_mode_active", STATE_OFF),
        ("number", "temp_target", "23.0"),
        ("select", "fan_level", "1"),
    ],
)
async def test_a_real_units_values_are_shown(
    hass: HomeAssistant, loaded: NilanData, platform: str, key: str, state: str
) -> None:
    """The filter entity is a problem, on, while the filter must be changed."""
    assert state_of(hass, platform, key).state == state


async def test_the_efficiency_is_the_supply_sides_temperature_ratio(
    hass: HomeAssistant, loaded: NilanData
) -> None:
    efficiency = state_of(hass, "sensor", "efficiency")
    assert math.isclose(float(efficiency.state), (16.4 - 15.2) / (23.1 - 15.2) * 100)
    assert efficiency.attributes["unit_of_measurement"] == "%"


async def test_the_efficiency_follows_a_temperature_as_it_changes(
    hass: HomeAssistant, loaded: NilanData, gateway: SimulatedMicroNabtoDevice
) -> None:
    gateway.datapoint_registers[(0, 28)] = 192  # supply air 19.2 °C
    await refresh(hass, entity_id(hass, "sensor", "temp_supply"))
    assert math.isclose(
        float(state_of(hass, "sensor", "efficiency").state), (19.2 - 15.2) / (23.1 - 15.2) * 100
    )


async def test_the_efficiency_is_unknown_while_extract_and_outdoor_air_are_equally_warm(
    hass: HomeAssistant, loaded: NilanData, gateway: SimulatedMicroNabtoDevice
) -> None:
    gateway.datapoint_registers[(0, 29)] = 152  # extract air 15.2 °C, as outdoor
    await refresh(hass, entity_id(hass, "sensor", "efficiency"))
    assert state_of(hass, "sensor", "efficiency").state == STATE_UNKNOWN


async def test_entities_are_unavailable_while_the_gateway_does_not_answer(
    hass: HomeAssistant, loaded: NilanData, gateway: SimulatedMicroNabtoDevice, clock: FakeClock
) -> None:
    outdoor = entity_id(hass, "sensor", "temp_outside")
    gateway.silent = True
    await refresh(hass, outdoor)
    assert state_of(hass, "sensor", "temp_outside").state == STATE_UNAVAILABLE
    gateway.silent = False
    clock.advance(60)  # past the client's wait before it tries the gateway again
    await refresh(hass, outdoor)
    assert state_of(hass, "sensor", "temp_outside").state == "15.2"


@pytest.mark.parametrize(
    ("platform", "service", "key", "data", "register", "raw"),
    [
        ("number", "set_value", "temp_target", {"value": 21.5}, 37, 215),
        ("number", "set_value", "filter_replace_interval", {"value": 60}, 50, 60),
        ("select", "select_option", "fan_level", {"option": "3"}, 69, 3),
        ("switch", "turn_off", "enable", {}, 70, 0),
        ("switch", "turn_on", "enable", {}, 70, 1),
        ("button", "press", "alarm_reset", {}, 30, 1),
        ("button", "press", "filter_replace_reset", {}, 51, 1),
        ("climate", "set_temperature", "hvac", {"temperature": 21.0}, 37, 210),
        ("climate", "set_fan_mode", "hvac", {"fan_mode": "2"}, 69, 2),
        ("climate", "set_hvac_mode", "hvac", {"hvac_mode": HVACMode.OFF}, 70, 0),
        ("climate", "set_hvac_mode", "hvac", {"hvac_mode": HVACMode.AUTO}, 70, 1),
        ("climate", "turn_off", "hvac", {}, 70, 0),
        ("climate", "turn_on", "hvac", {}, 70, 1),
    ],
)
async def test_an_action_writes_its_setting(
    hass: HomeAssistant,
    loaded: NilanData,
    gateway: SimulatedMicroNabtoDevice,
    platform: str,
    service: str,
    key: str,
    data: dict[str, Any],
    register: int,
    raw: int,
) -> None:
    target = entity_id(hass, platform, key)
    registry = er.async_get(hass)
    found = registry.async_get(target)
    assert found is not None
    if found.disabled_by is not None:
        registry.async_update_entity(target, disabled_by=None)
        await hass.config_entries.async_reload(loaded_entry(hass).entry_id)
        await hass.async_block_till_done()
    await hass.services.async_call(
        platform, service, {"entity_id": target, **data}, blocking=True
    )
    assert (0, register, raw) in await written(gateway)


def loaded_entry(hass: HomeAssistant) -> Any:
    (entry,) = hass.config_entries.async_entries(DOMAIN)
    return entry


async def test_a_value_the_setting_cannot_take_is_refused_before_it_is_sent(
    hass: HomeAssistant, loaded: NilanData, gateway: SimulatedMicroNabtoDevice
) -> None:
    number = entity_of(hass, "number", "temp_target")
    with pytest.raises(ServiceValidationError) as raised:
        await number.async_set_native_value(30.5)
    assert raised.value.translation_key == "invalid_value"
    assert not gateway.received(SETPOINT_WRITE)


async def test_a_write_the_unit_does_not_take_is_an_error(
    hass: HomeAssistant, loaded: NilanData, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def refused(key: Any, value: Any) -> bool:
        return False

    monkeypatch.setattr(loaded.client, "write", refused)
    with pytest.raises(HomeAssistantError) as raised:
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": entity_id(hass, "button", "alarm_reset")},
            blocking=True,
        )
    assert raised.value.translation_key == "write_refused"


@pytest.mark.parametrize(
    ("changes", "action"),
    [
        ({}, HVACAction.COOLING),
        ({(0, 23): 0}, HVACAction.FAN),
        ({(0, 23): 0, (0, 64): 0}, HVACAction.DRYING),
        ({(0, 91): 1, (0, 64): 0}, HVACAction.DEFROSTING),
    ],
    ids=["bypass open", "ventilating", "high humidity", "de-icing"],
)
async def test_the_thermostat_says_what_the_unit_is_doing(
    hass: HomeAssistant,
    loaded: NilanData,
    gateway: SimulatedMicroNabtoDevice,
    changes: dict[tuple[int, int], int],
    action: HVACAction,
) -> None:
    """IR64 is the manual's "average level humidity 24 hours OK": 0 while it is high."""
    gateway.datapoint_registers.update(changes)
    await refresh(hass, entity_id(hass, "climate", "hvac"))
    state = state_of(hass, "climate", "hvac")
    assert state.state == HVACMode.AUTO
    assert state.attributes["hvac_action"] == action


async def test_the_thermostat_shows_the_unit_it_is(
    hass: HomeAssistant, loaded: NilanData
) -> None:
    state = state_of(hass, "climate", "hvac")
    assert state.name == NAME
    assert state.attributes["current_temperature"] == 23.1
    assert state.attributes["current_humidity"] == 56.0
    assert state.attributes["temperature"] == 23.0
    assert state.attributes["fan_mode"] == "1"
    assert state.attributes["fan_modes"] == ["1", "2", "3", "4"]
    assert state.attributes["hvac_modes"] == [HVACMode.AUTO, HVACMode.OFF]
    assert (state.attributes["min_temp"], state.attributes["max_temp"]) == (10.0, 30.0)
    assert state.attributes["target_temp_step"] == 0.5


async def test_a_stopped_unit_is_off(
    hass: HomeAssistant, loaded: NilanData, gateway: SimulatedMicroNabtoDevice
) -> None:
    gateway.setpoint_registers[(0, 70)] = 0
    await refresh(hass, entity_id(hass, "climate", "hvac"))
    state = state_of(hass, "climate", "hvac")
    assert state.state == HVACMode.OFF
    assert state.attributes["hvac_action"] == HVACAction.OFF


async def test_the_thermostat_shows_nothing_it_does_not_know(
    hass: HomeAssistant, loaded: NilanData
) -> None:
    thermostat = entity_of(hass, "climate", "hvac")
    assert thermostat._action(None) is None


async def test_a_setting_without_limits_has_no_range(loaded: NilanData) -> None:
    (point,) = loaded.client.select([PointKey.TEMP_TARGET])
    with pytest.raises(ValueError):
        value_range(dataclasses.replace(point, limits=None))


async def test_a_level_without_limits_has_no_levels(
    loaded: NilanData, monkeypatch: pytest.MonkeyPatch
) -> None:
    client: Client = loaded.client
    (point,) = client.select([PointKey.FAN_LEVEL])
    def without_limits(keys: object) -> tuple[Point[Any], ...]:
        return (dataclasses.replace(point, limits=None),)

    monkeypatch.setattr(client, "select", without_limits)
    with pytest.raises(ValueError):
        levels(client, PointKey.FAN_LEVEL)

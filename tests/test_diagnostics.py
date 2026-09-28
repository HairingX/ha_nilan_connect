"""What a unit's diagnostics hold, and what they leave out."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

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
    assert found["status"]["CONNECTED"] is True
    assert found["values"]["temp_outside"] == {"value": 15.2, "quality": "GOOD", "raw": [152]}
    text = repr(found)
    assert EMAIL not in text and GATEWAY_ID not in text and HOST not in text

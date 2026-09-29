"""The integration against a real Nilan gateway, read-only: added through its config flow by
address, loaded with every entity of its unit, and unloaded again.

Skipped unless a gateway is configured, by its IP address and the email it is paired with:

    NILAN_HOST=<gateway-ip> NILAN_EMAIL=<email>        (environment variables)
    NILAN_HOST = "<gateway-ip>"; NILAN_EMAIL = "<email>"  (in mysecrets.py, which is gitignored)

Every client is read-only, so every write is refused before it reaches the unit.
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Iterator
from typing import Any

import pytest
import pytest_socket
from homeassistant.config_entries import SOURCE_USER, ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from nilan_connect import Client, Status, create_client

from custom_components.nilan_connect.const import CONF_EMAIL, DEFAULT_PORT, DOMAIN
from custom_components.nilan_connect.data import NilanData


def _setting(name: str) -> str | None:
    if found := os.environ.get(name):
        return found
    try:
        secrets = importlib.import_module("mysecrets")
    except ModuleNotFoundError:
        return None
    value = getattr(secrets, name, None)
    return value if isinstance(value, str) else None


HOST = _setting("NILAN_HOST")
EMAIL = _setting("NILAN_EMAIL")

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(HOST is None or EMAIL is None, reason="no gateway configured (NILAN_HOST, NILAN_EMAIL)"),
]


@pytest.fixture
def real_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[Client]]:
    """Every client the integration makes reaches the real gateway, read-only."""
    pytest_socket.enable_socket()
    made: list[Client] = []

    def read_only(
        email: str, *, host: str | None, port: int, device_id: str | None, read_only: bool
    ) -> Client:
        client = create_client(email, host=host, port=port, device_id=device_id, read_only=True)
        made.append(client)
        return client

    monkeypatch.setattr("custom_components.nilan_connect.data.create_client", read_only)
    yield made


async def test_a_real_gateway_is_added_with_every_entity_of_its_unit(
    hass: HomeAssistant, real_network: list[Client]
) -> None:
    started = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    # HA declares the flow manager's user input as a bare `dict`.
    flow: Any = hass.config_entries.flow
    manual = await flow.async_configure(started["flow_id"], {"next_step_id": "manual"})
    result = await flow.async_configure(
        manual["flow_id"],
        {CONF_NAME: "Live", CONF_HOST: HOST, CONF_PORT: DEFAULT_PORT, CONF_EMAIL: EMAIL},
    )
    assert result.get("type") is FlowResultType.CREATE_ENTRY, result
    entry = result.get("result")
    assert isinstance(entry, ConfigEntry)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    found = hass.config_entries.async_get_entry(entry.entry_id)
    assert found is not None
    data: NilanData = found.runtime_data
    assert data.client.status(Status.CONNECTED).value is True
    assert len(data.unique_ids) == 58
    shown = [state for state in hass.states.async_all() if state.entity_id.split(".")[1].startswith("live")]
    assert shown and all(state.state != "unavailable" for state in shown)

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert data.client.status(Status.CONNECTED).value is False

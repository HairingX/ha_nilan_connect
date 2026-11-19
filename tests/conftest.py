"""A simulated Nilan gateway behind the integration, and a config entry for it.

The integration runs the real client and the real CTS400 model; only the micro_nabto link is
simulated, by a gateway on a local UDP port that answers what a real CTS400 answered.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
import pytest_socket
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant
from nilan_connect import PORT, Client, Clock, DiscoveredDevice, Level, create_client
from nilan_connect.testing import FakeClock, SimulatedMicroNabtoDevice, client_for
from pytest_homeassistant.common import MockConfigEntry

from custom_components.nilan_connect.const import CONF_EMAIL, CONF_GATEWAY_ID, DOMAIN
from custom_components.nilan_connect.data import NilanData

REGISTERS: dict[str, dict[str, int]] = json.loads(
    (Path(__file__).parent / "cts400_registers.json").read_text(encoding="utf-8")
)
"""Every register the CTS400 manual lists, as a real unit answered them on 2026-09-27, its
bypass open and its filter alarm active."""

CTS400 = {
    "device_number": 72280,
    "device_model": 1140,
    "slave_device_number": 72270,
    "slave_device_model": 1,
}
"""What a real CTS400 says in the handshake."""

GATEWAY_ID = "gateway.example.invalid"
EMAIL = "user@example.invalid"
NAME = "Nilan"
HOST = "127.0.0.1"
"""The simulated gateway listens here, on a port of its own."""


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> Iterator[None]:
    yield


@pytest.fixture(autouse=True)
def no_deprecated_usage(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    """Fail a test in which Home Assistant reports this integration using something deprecated."""
    yield
    reports = [
        record.getMessage()
        for phase in ("setup", "call")
        for record in caplog.get_records(phase)
        if "Detected that custom integration 'nilan_connect'" in record.getMessage()
        or " was used from nilan_connect" in record.getMessage()
    ]
    assert reports == []


def simulated_gateway(**changes: Any) -> SimulatedMicroNabtoDevice:
    """A gateway in front of a CTS400 with the real unit's registers."""
    settings: dict[str, Any] = {
        "device_id": GATEWAY_ID,
        "emails": frozenset({EMAIL}),
        "identity": CTS400,
        "datapoint_registers": {(0, int(a)): v for a, v in REGISTERS["datapoints"].items()},
        "setpoint_registers": {(0, int(a)): v for a, v in REGISTERS["setpoints"].items()},
    }
    settings.update(changes)
    return SimulatedMicroNabtoDevice(**settings)


@pytest.fixture
async def gateway() -> AsyncIterator[SimulatedMicroNabtoDevice]:
    """The simulated gateway, listening; change its registers to change what it answers."""
    pytest_socket.enable_socket()
    simulated = simulated_gateway()
    async with simulated:
        yield simulated


@pytest.fixture
def clock() -> FakeClock:
    """The clients' clock: it moves only when a test advances it, so nothing is read by itself."""
    return FakeClock()


@pytest.fixture(autouse=True)
def simulated_network(
    monkeypatch: pytest.MonkeyPatch, gateway: SimulatedMicroNabtoDevice, clock: FakeClock
) -> list[Client]:
    """The network the integration sees holds only the simulated gateway.

    A discovery broadcast finds it, and so does one sent to its address; a client that finds it
    by its id or by its address reaches it, and requests sent elsewhere go out as they are.
    Returns the clients made, in order.
    """
    made: list[Client] = []
    fake = clock

    async def discovery(*, target: str | None = None, port: int = PORT) -> list[DiscoveredDevice]:
        answers = not gateway.silent and (target is None or (target, port) == gateway.address)
        return [DiscoveredDevice(*gateway.address, gateway.device_id)] if answers else []

    def found_by_id(
        *,
        email: str,
        host: str | None = None,
        device_id: str | None = None,
        port: int = PORT,
        level: Level = Level.DOCUMENTED,
        read_only: bool = False,
        clock: Clock | None = None,
    ) -> Client:
        if (host, port) == gateway.address or (host is None and device_id == gateway.device_id):
            client = client_for(
                gateway, email=email, timeout=0.2, retries=1, clock=clock or fake, level=level,
                read_only=read_only,
            )
        else:
            client = create_client(
                email=email, host=host, device_id=device_id, port=port, level=level,
                read_only=read_only, clock=clock or fake,
            )
        made.append(client)
        return client

    monkeypatch.setattr("custom_components.nilan_connect.discover", discovery)
    monkeypatch.setattr("custom_components.nilan_connect.config_flow.discover", discovery)
    monkeypatch.setattr("custom_components.nilan_connect.data.create_client", found_by_id)
    return made


def entry_data(gateway: SimulatedMicroNabtoDevice, **changes: Any) -> dict[str, Any]:
    """The data of an entry for the simulated gateway, set up by discovery."""
    data: dict[str, Any] = {
        CONF_NAME: NAME,
        CONF_EMAIL: EMAIL,
        CONF_HOST: HOST,
        CONF_PORT: gateway.address[1],
        CONF_GATEWAY_ID: GATEWAY_ID,
    }
    data.update(changes)
    return data


@pytest.fixture
def config_entry(gateway: SimulatedMicroNabtoDevice) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title=NAME,
        unique_id=GATEWAY_ID,
        data=entry_data(gateway),
        version=2,
        minor_version=1,
    )


@pytest.fixture
async def loaded(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> AsyncIterator[NilanData]:
    """The config entry, set up; unloaded again after the test."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    data: NilanData = config_entry.runtime_data
    yield data
    await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

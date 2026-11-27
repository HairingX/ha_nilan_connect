"""The client behind a config entry, and how one is made."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field

from homeassistant.config_entries import ConfigEntry
from nilan_connect import UNRECOGNISED, Client, Key, Level, create_client

type NilanConfigEntry = ConfigEntry[NilanData]


@dataclass
class NilanData:
    """What a loaded config entry holds."""

    client: Client
    name: str
    """The unit's name, which every unique id and the device's identifier start with."""
    unit_model: str = ""
    """The model the owner of a unit no model matches named it; empty for every other unit."""
    poller: asyncio.Task[None] | None = field(default=None, repr=False)
    unique_ids: set[str] = field(default_factory=set[str])
    """The unique id of every entity built for the entry, disabled ones included."""


def new_client(
    email: str,
    host: str | None,
    port: int,
    gateway_id: str | None,
    *,
    level: Level = Level.DOCUMENTED,
    read_only: bool = False,
) -> Client:
    """A client for the gateway at `host`, or found by `gateway_id`, with the points of `level`;
    not yet connected. A controller no model matches is connected as `UNRECOGNISED`, so that it
    can be mapped."""
    return create_client(
        email=email, host=host, port=port, device_id=gateway_id, level=level, read_only=read_only,
        unrecognised=True,
    )


def recognised(client: Client) -> bool:
    """Whether a model matches the controller the connected `client` reaches."""
    return client.model is not UNRECOGNISED


IDENTITY_NUMBERS = ("device_model", "device_number", "slave_device_number", "slave_device_model")
"""What a gateway's handshake says the controller behind it is, in the order it is shown."""


def identity_text(identity: Mapping[str, object]) -> str:
    """The handshake's numbers, as a user copies them into an issue: "1140/72280/72270/1"."""
    return "/".join(str(identity.get(number)) for number in IDENTITY_NUMBERS)


def value[T](client: Client, key: Key[T]) -> T | None:
    """The current value of `key`: None when it was never read or holds no reading."""
    current = client.value(key)
    return current.value if current is not None else None

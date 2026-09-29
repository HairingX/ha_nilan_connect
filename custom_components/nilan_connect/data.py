"""The client behind a config entry, and how one is made."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from homeassistant.config_entries import ConfigEntry
from nilan_connect import Client, Key, create_client

type NilanConfigEntry = ConfigEntry[NilanData]


@dataclass
class NilanData:
    """What a loaded config entry holds."""

    client: Client
    name: str
    """The unit's name, which every unique id and the device's identifier start with."""
    poller: asyncio.Task[None] | None = field(default=None, repr=False)
    unique_ids: set[str] = field(default_factory=set[str])
    """The unique id of every entity built for the entry, disabled ones included."""


def new_client(
    email: str,
    host: str | None,
    port: int,
    gateway_id: str | None,
    *,
    read_only: bool = False,
) -> Client:
    """A client for the gateway at `host`, or found by `gateway_id`; not yet connected."""
    return create_client(
        email, host=host, port=port, device_id=gateway_id, read_only=read_only
    )


def value[T](client: Client, key: Key[T]) -> T | None:
    """The current value of `key`: None when it was never read or holds no reading."""
    current = client.value(key)
    return current.value if current is not None else None

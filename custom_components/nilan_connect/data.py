"""The client behind a config entry, and how one is made."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from nilan_connect import Client, DataValue, Key, Status, create_client

from . import const

type NilanConfigEntry = ConfigEntry[NilanData]


class GatewayAnswers:
    """Whether the gateway answers, as the unit's entities show it.

    It counts as answering until it has left every read unanswered for `SILENCE_TOLERATED`
    seconds; meanwhile the entities show their last good values.
    """

    def __init__(self, hass: HomeAssistant, client: Client) -> None:
        """Follow the client's status from now on, until `close`."""
        self._hass = hass
        self._listeners: list[Callable[[], None]] = []
        self._silence: CALLBACK_TYPE | None = None
        self._answering = client.status(Status.CONNECTED).value is True
        self._unsubscribe = client.subscribe_status(Status.CONNECTED, self._on_status)

    @property
    def answering(self) -> bool:
        """Whether the gateway answers, or has been silent for too short a time to tell."""
        return self._answering

    def subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Call `listener` whenever `answering` changes; returns the unsubscriber."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    @callback
    def close(self) -> None:
        """Stop following the client."""
        self._unsubscribe()
        self._cancel_silence()

    @callback
    def _on_status(
        self, status: Status, old: DataValue[bool] | None, new: DataValue[bool]
    ) -> None:
        if new.value is True:
            self._cancel_silence()
            self._set(True)
        elif self._answering and self._silence is None:
            self._silence = async_call_later(
                self._hass, const.SILENCE_TOLERATED, self._silence_lasted
            )

    @callback
    def _silence_lasted(self, _: datetime) -> None:
        self._silence = None
        self._set(False)

    def _cancel_silence(self) -> None:
        if self._silence is not None:
            self._silence()
            self._silence = None

    def _set(self, answering: bool) -> None:
        if answering != self._answering:
            self._answering = answering
            for listener in list(self._listeners):
                listener()


@dataclass
class NilanData:
    """What a loaded config entry holds."""

    client: Client
    answers: GatewayAnswers
    name: str
    """The unit's name, which every unique id and the device's identifier start with."""
    show_inferred: bool = False
    """Whether a value placed only by its manual's register order gets an entity."""
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


IDENTITY_NUMBERS = ("device_model", "device_number", "slave_device_number", "slave_device_model")
"""What a gateway's handshake says the controller behind it is, in the order it is shown."""


def identity_text(identity: Mapping[str, object]) -> str:
    """The handshake's numbers, as a user copies them into an issue: "1140/72280/72270/1"."""
    return "/".join(str(identity.get(number)) for number in IDENTITY_NUMBERS)


def value[T](client: Client, key: Key[T]) -> T | None:
    """The current value of `key`: None when it was never read or holds no reading."""
    current = client.value(key)
    return current.value if current is not None else None

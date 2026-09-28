"""Constants for the Nilan Connect integration."""

from typing import Final

DOMAIN: Final = "nilan_connect"

CONF_EMAIL: Final = "email"
"""The account the gateway is paired with in Nilan's app; a credential, never logged."""

CONF_GATEWAY_ID: Final = "gateway_id"
"""The id the gateway answers discovery with; None while it is not known."""

DEFAULT_NAME: Final = "Nilan"
"""What a unit is called unless the user names it: every unique id starts with the name, so the
entities keep theirs when the unit is replaced."""

DEFAULT_PORT: Final = 5570
"""The UDP port a Nilan gateway answers micro_nabto on."""

DISCOVERY_TIMEOUT: Final = 2.0
"""Seconds to wait for gateways to answer a discovery."""

POLL_TICK: Final = 1.0
"""Longest wait, in seconds, between two calls to the client's poll.

The client plans every read itself, and a poll with nothing due sends nothing. The wait is
capped because a new subscription or a write's read-back can make a point due while the
loop sleeps.
"""

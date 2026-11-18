"""Constants for the Nilan Connect integration."""

from typing import Final

from nilan_connect import PORT

DOMAIN: Final = "nilan_connect"

CONF_EMAIL: Final = "email"
"""The account the gateway is paired with in Nilan's app; a credential, never logged."""

CONF_GATEWAY_ID: Final = "gateway_id"
"""The id the gateway answers discovery with; None while it is not known."""

CONF_SHOW_INFERRED: Final = "show_inferred"
"""Whether a value whose address is known only from the order of its manual's registers gets an
entity."""

DEFAULT_NAME: Final = "Nilan"
"""What a unit is called unless the user names it: every unique id starts with the name, so the
entities keep theirs when the unit is replaced."""

DEFAULT_PORT: Final = PORT
"""The UDP port a Nilan gateway answers micro_nabto on."""


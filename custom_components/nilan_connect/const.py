"""Constants for the Nilan Connect integration."""

from typing import Final

from nilan_connect import PORT, Level

DOMAIN: Final = "nilan_connect"

CONF_EMAIL: Final = "email"
"""The account the gateway is paired with in Nilan's app; a credential, never logged."""

CONF_GATEWAY_ID: Final = "gateway_id"
"""The id the gateway answers discovery with; None while it is not known."""

CONF_LEVEL: Final = "level"
"""Which of the unit's points get an entity: a `Level`, stored by its text."""

DEFAULT_LEVEL: Final = Level.DOCUMENTED
"""The level of an entry whose user has not chosen one."""

SHOW_INFERRED: Final = "show_inferred"
"""The option an entry of minor version 1 had in place of the level: whether a value placed only
by the order of its manual's registers got an entity."""

ATTR_CERTAINTY: Final = "certainty"
"""The state attribute saying how certain the points an entity shows are."""

TEST_CANDIDATE: Final = "test-candidate"
"""The certainty of a point tried only at the Test level."""

TEST_REPORT_URL: Final = "https://github.com/HairingX/ha_nilan_connect/issues/new?template=test-report.yml"
"""Where a user reports whether the points tried match the unit's panel."""

DEFAULT_NAME: Final = "Nilan"
"""What a unit is called unless the user names it: every unique id starts with the name, so the
entities keep theirs when the unit is replaced."""

DEFAULT_PORT: Final = PORT
"""The UDP port a Nilan gateway answers micro_nabto on."""


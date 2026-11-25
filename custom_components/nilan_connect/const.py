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

TESTING_ISSUE: Final = "testing_points"
"""The Repairs issue asking a user at the Test level to report what the unit shows."""

TEST_REPORT_URL: Final = "https://github.com/HairingX/ha_nilan_connect/issues/new?template=test-report.yml"
"""Where a user reports whether the points tried match the unit's panel."""

DEFAULT_NAME: Final = "Nilan"
"""What a unit is called unless the user names it: every unique id starts with the name, so the
entities keep theirs when the unit is replaced."""

DEFAULT_PORT: Final = PORT
"""The UDP port a Nilan gateway answers micro_nabto on."""


MAPPING_LIMIT: Final = 300
"""How far up each of the gateway's tables a mapping reads: the owner chose 300 from the measured
cost of the first read of every model's simulated gateway, about 15 to 500 requests, a few seconds
at the gateways' usual answer time."""

MAPPINGS_KEPT: Final = 3
"""How many of a unit's latest mappings are stored; the oldest gives way first."""

STEPS_KEPT: Final = 30
"""How many steps of one mapping are stored."""

CHANGES_SHOWN: Final = 12
"""How many of a step's changes the guide lists; the diagnostics hold every one."""

MAPPING_REPORT_URL: Final = "https://github.com/HairingX/ha_nilan_connect/issues/new?template=mapping.yml"
"""Where a user sends the mappings of their unit."""

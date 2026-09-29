"""The integration against what it is built on: every library point and unit, the translations,
the manifest and the Home Assistant it is tested with."""

from __future__ import annotations

import ast
import hashlib
import importlib.metadata
import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, cast

import homeassistant
import pytest
import yaml
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.helpers.entity import EntityDescription
from nilan_connect import PointKey

from custom_components.nilan_connect.binary_sensor import BINARY_SENSORS
from custom_components.nilan_connect.button import BUTTONS
from custom_components.nilan_connect.climate import SHOWN
from custom_components.nilan_connect.data import NilanData
from custom_components.nilan_connect.entity import NilanEntityDescription
from custom_components.nilan_connect.number import NUMBERS
from custom_components.nilan_connect.select import SELECTS
from custom_components.nilan_connect.sensor import EFFICIENCY, SENSORS
from custom_components.nilan_connect.switch import SWITCHES
from custom_components.nilan_connect.units import HA_UNITS

INTEGRATION = Path(__file__).parents[1] / "custom_components" / "nilan_connect"
REPOSITORY = INTEGRATION.parents[1]

PLATFORMS: dict[str, tuple[NilanEntityDescription, ...]] = {
    "binary_sensor": BINARY_SENSORS,
    "button": BUTTONS,
    "number": NUMBERS,
    "select": SELECTS,
    "sensor": SENSORS,
    "switch": SWITCHES,
}

NOT_AN_ENTITY: dict[str, str] = {}
"""Library points that are no entity, with the reason."""


def _described() -> list[str]:
    return [str(d.point) for descriptions in PLATFORMS.values() for d in descriptions]


def test_every_library_point_is_one_entity_or_has_a_reason_not_to_be() -> None:
    described = _described()
    assert len(described) == len(set(described)), "a point with two entities"
    assert set(PointKey.all()) - set(described) - set(NOT_AN_ENTITY) == set()
    assert set(described) - set(PointKey.all()) == set()


@pytest.mark.parametrize("platform", list(PLATFORMS))
def test_an_entity_is_named_and_found_by_its_points_key(platform: str) -> None:
    """The key is what an existing installation's unique ids end with."""
    for description in PLATFORMS[platform]:
        assert description.key == description.translation_key == str(description.point)


async def test_every_unit_of_the_library_has_its_home_assistant_unit(loaded: NilanData) -> None:
    units = {point.unit for point in loaded.client.points.values()}
    assert units - {None} <= set(HA_UNITS)


def _translations(language: str) -> dict[str, Any]:
    path = INTEGRATION / "translations" / f"{language}.json"
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def _paths(tree: Mapping[str, Any], prefix: str = "") -> Iterator[str]:
    """Every leaf of a JSON tree, as its dotted path."""
    for key, value in tree.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            yield from _paths(cast(dict[str, Any], value), path)
        else:
            yield path


def test_danish_translates_exactly_what_english_does() -> None:
    assert set(_paths(_translations("da"))) == set(_paths(_translations("en")))


@pytest.mark.parametrize("platform", list(PLATFORMS))
def test_every_entity_has_a_name(platform: str) -> None:
    names = _translations("en")["entity"][platform]
    descriptions: tuple[EntityDescription, ...] = PLATFORMS[platform]
    assert {d.translation_key for d in descriptions} | (
        {EFFICIENCY} if platform == "sensor" else set()
    ) == set(names)


def test_every_icon_belongs_to_a_translated_entity() -> None:
    icons = json.loads((INTEGRATION / "icons.json").read_text(encoding="utf-8"))
    names = _translations("en")["entity"]
    for platform, entities in icons["entity"].items():
        for key in entities:
            assert key in names[platform], f"{platform}.{key}"


def _manifest() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(
        (INTEGRATION / "manifest.json").read_text(encoding="utf-8")
    )
    return loaded


def test_the_manifest_pins_the_library_version_the_tests_run() -> None:
    installed = importlib.metadata.version("nilan_connect")
    assert _manifest()["requirements"] == [f"nilan_connect=={installed}"]


def test_the_tests_run_the_pymodbus_home_assistant_installs() -> None:
    """Home Assistant installs requirements under its package constraints, pymodbus among them;
    the library needs pymodbus."""
    constraints = Path(homeassistant.__file__).parent / "package_constraints.txt"
    pins = [
        line
        for line in constraints.read_text(encoding="utf-8").splitlines()
        if line.startswith("pymodbus==")
    ]
    assert pins == [f"pymodbus=={importlib.metadata.version('pymodbus')}"]


def test_hacs_requires_the_home_assistant_the_tests_run() -> None:
    hacs = json.loads((REPOSITORY / "hacs.json").read_text(encoding="utf-8"))
    assert hacs["homeassistant"] == HA_VERSION


def test_the_library_is_imported_from_its_package_not_from_the_integration() -> None:
    """The integration's folder has the library's name."""
    import nilan_connect

    assert INTEGRATION not in Path(nilan_connect.__file__).parents


NILAN_BRAND = {
    "icon.png": "631c858403b107e37affc69935f0dd4fec9984c0fc68e91738f31301334caaf5",
    "icon@2x.png": "b2468dd9ff3b1695e67d1dd873a3c748ec2cf18b1c89f2ae6fe4ae0b2f557b89",
    "logo.png": "20028d7244f1bc8ccb256b5541785f725928e5dd962c709dd18469ec0e9b644d",
    "logo@2x.png": "8ec76cca729c4bdb6bed02a2ae0fad878f5a3a47a5de4df04345bd98ae5bb3fa",
    "dark_logo.png": "c61815e2207fd50301314238fb1a994bf90a6df44670c481ac520adf06f87318",
    "dark_logo@2x.png": "c15cacd1d6e765ca1e46ff64a1d028fd8ee11449add2542a9257ccf04967141e",
}
"""Nilan's brand images, as Home Assistant's brands repository has them for this domain
(custom_integrations/nilan_connect)."""


def test_the_brand_images_are_nilans_as_the_brands_repository_has_them() -> None:
    found = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (INTEGRATION / "brand").iterdir()
    }
    assert found == NILAN_BRAND


QUALITY_SCALE_RULES = frozenset({
    # Bronze
    "action-setup", "appropriate-polling", "brands", "common-modules",
    "config-flow-test-coverage", "config-flow", "dependency-transparency", "docs-actions",
    "docs-conditions", "docs-high-level-description", "docs-installation-instructions",
    "docs-removal-instructions", "docs-triggers", "entity-event-setup", "entity-unique-id",
    "has-entity-name", "runtime-data", "test-before-configure", "test-before-setup",
    "unique-config-entry",
    # Silver
    "action-exceptions", "config-entry-unloading", "docs-configuration-parameters",
    "docs-installation-parameters", "entity-unavailable", "integration-owner",
    "log-when-unavailable", "parallel-updates", "reauthentication-flow", "test-coverage",
    # Gold
    "devices", "diagnostics", "discovery-update-info", "discovery", "docs-data-update",
    "docs-examples", "docs-known-limitations", "docs-supported-devices",
    "docs-supported-functions", "docs-troubleshooting", "docs-use-cases", "dynamic-devices",
    "entity-category", "entity-device-class", "entity-disabled-by-default",
    "entity-translations", "exception-translations", "icon-translations",
    "reconfiguration-flow", "repair-issues", "stale-devices",
    # Platinum
    "async-dependency", "inject-websession", "strict-typing",
})
"""The rules of Home Assistant's Integration Quality Scale, as its developer documentation lists
them. hassfest does not check this file for a custom integration, so this test does."""


def test_the_quality_scale_states_every_rule_and_explains_every_exemption() -> None:
    text = (INTEGRATION / "quality_scale.yaml").read_text(encoding="utf-8")
    rules = cast(dict[str, Any], yaml.safe_load(text)["rules"])
    assert set(rules) == QUALITY_SCALE_RULES
    for rule, state in rules.items():
        if state == "done":
            continue
        assert isinstance(state, dict), rule
        entry = cast(dict[str, Any], state)
        assert entry["status"] in ("done", "exempt", "todo"), rule
        if entry["status"] != "done":
            assert entry.get("comment"), f"{rule} is {entry['status']} without a reason"


@pytest.mark.parametrize("point", SHOWN)
def test_everything_the_thermostat_shows_is_also_an_entity_of_its_own(point: str) -> None:
    """Each has a history of its own, and a plain action for scripts."""
    assert point in _described()


def test_nothing_imports_modbus_event_connect_itself() -> None:
    """nilan_connect gives the integration and its tests everything they use."""
    found: list[str] = []
    for path in [*INTEGRATION.rglob("*.py"), *Path(__file__).parent.rglob("*.py")]:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            modules = (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else []
            )
            found += [f"{path.name}: {m}" for m in modules if m.startswith("modbus_event_connect")]
    assert found == []

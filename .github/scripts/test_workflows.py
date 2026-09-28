"""The repository's workflows."""

from pathlib import Path

import pytest

WORKFLOWS = sorted((Path(__file__).parents[1] / "workflows").glob("*.yml"))

BASH = "defaults:\n  run:\n    shell: bash\n"


def test_the_workflows_are_found() -> None:
    assert WORKFLOWS


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=[path.name for path in WORKFLOWS])
def test_a_step_fails_when_a_command_piped_into_another_fails(workflow: Path) -> None:
    """GitHub runs a step as `bash -eo pipefail` only when the shell is given; without one it
    runs `bash -e`, where a failing command piped into another fails nothing."""
    assert BASH in workflow.read_text(encoding="utf-8")

@pytest.mark.parametrize("workflow", WORKFLOWS, ids=[path.name for path in WORKFLOWS])
def test_no_step_pipes_into_a_command_that_stops_reading(workflow: Path) -> None:
    """With pipefail, the command before `head` fails when head stops reading its output."""
    assert "| head" not in workflow.read_text(encoding="utf-8")

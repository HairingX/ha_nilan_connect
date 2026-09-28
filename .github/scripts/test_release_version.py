"""Tests of how the release works out its version."""
import pytest
from packaging.version import Version

from release_version import FINAL_RELEASE, RELEASE_CANDIDATE, known_versions, next_version, previous_tag, require_changes


def _next(kind: str, draft: str, known: list[str], override: str = "") -> str:
    return str(next_version(kind, draft, override, known_versions(known))[0])


def test_a_release_candidate_continues_the_open_series_below_the_draft() -> None:
    assert _next(RELEASE_CANDIDATE, "v0.1.10", ["v0.1.8", "0.1.9", "v0.2.0rc1", "0.2.0rc1"]) == "0.2.0rc2"


def test_a_final_release_ends_the_open_series() -> None:
    assert _next(FINAL_RELEASE, "v0.1.10", ["v0.1.8", "v0.2.0rc1", "v0.2.0rc2"]) == "0.2.0"


def test_a_draft_above_the_open_series_starts_a_new_one() -> None:
    assert _next(RELEASE_CANDIDATE, "v0.3.0", ["v0.2.0rc2"]) == "0.3.0rc1"
    assert _next(FINAL_RELEASE, "v0.3.0", ["v0.2.0rc2"]) == "0.3.0"


@pytest.mark.parametrize("kind", [RELEASE_CANDIDATE, FINAL_RELEASE])
def test_a_new_major_version_is_never_worked_out(kind: str) -> None:
    with pytest.raises(SystemExit, match="1.0.0(rc1)? is a new major version"):
        _next(kind, "v1.0.0", ["v0.2.0rc2"])


def test_a_new_major_version_is_taken_as_an_override() -> None:
    assert _next(RELEASE_CANDIDATE, "v0.2.1", ["v0.2.0"], override="1.0.0rc1") == "1.0.0rc1"


def test_without_an_open_series_the_draft_names_the_version() -> None:
    assert _next(RELEASE_CANDIDATE, "v0.3.0", ["v0.2.0rc1", "v0.2.0"]) == "0.3.0rc1"
    assert _next(FINAL_RELEASE, "v0.3.0", ["v0.2.0"]) == "0.3.0"


def test_the_first_release_needs_nothing_known() -> None:
    assert _next(FINAL_RELEASE, "v0.1.0", []) == "0.1.0"


def test_a_series_of_betas_continues_with_its_first_release_candidate() -> None:
    assert _next(RELEASE_CANDIDATE, "v0.2.0", ["v0.1.0", "v0.2.0b3"]) == "0.2.0rc1"


def test_an_open_series_needs_no_draft() -> None:
    assert _next(RELEASE_CANDIDATE, "", ["v0.2.0rc1"]) == "0.2.0rc2"
    assert _next(FINAL_RELEASE, "", ["v0.2.0rc1"]) == "0.2.0"


def test_without_a_draft_or_an_open_series_the_version_must_be_given() -> None:
    with pytest.raises(SystemExit, match="give the version as the override"):
        _next(FINAL_RELEASE, "", ["v0.2.0"])


def test_a_draft_below_what_is_published_is_refused() -> None:
    with pytest.raises(SystemExit, match="0.1.10 is not higher than 0.2.0"):
        _next(FINAL_RELEASE, "v0.1.10", ["v0.2.0"])


def test_the_override_replaces_the_version_worked_out() -> None:
    assert _next(RELEASE_CANDIDATE, "v0.1.10", ["v0.2.0rc1"], override="0.3.0rc1") == "0.3.0rc1"


def test_the_override_must_still_be_higher_than_every_known_version() -> None:
    with pytest.raises(SystemExit, match="0.2.0rc1 is not higher than 0.2.0rc1"):
        _next(RELEASE_CANDIDATE, "", ["v0.2.0rc1"], override="0.2.0rc1")


@pytest.mark.parametrize(("kind", "override"), [(FINAL_RELEASE, "0.2.0rc2"), (RELEASE_CANDIDATE, "0.2.0")])
def test_the_override_must_be_the_kind_chosen(kind: str, override: str) -> None:
    with pytest.raises(SystemExit, match=f"not a {kind}"):
        _next(kind, "", ["v0.2.0rc1"], override=override)


@pytest.mark.parametrize("override", ["v0.3.0", "0.3", "0.3.0-rc1", "0.3.0+local"])
def test_the_override_must_be_canonical_major_minor_patch(override: str) -> None:
    with pytest.raises(SystemExit, match="::error::"):
        _next(FINAL_RELEASE, "", [], override=override)


def test_an_unknown_kind_is_refused() -> None:
    with pytest.raises(SystemExit, match="neither"):
        _next("final", "v0.1.0", [])


def test_tags_that_name_no_version_are_skipped() -> None:
    assert known_versions(["v0.1.0", "latest", "", "0.2.0rc1"]) == [Version("0.1.0"), Version("0.2.0rc1")]


def test_the_notes_of_a_release_candidate_start_at_the_one_before() -> None:
    assert previous_tag(Version("0.2.0rc2"), ["v0.1.9", "v0.2.0rc1", "v0.2.0rc2"]) == "v0.2.0rc1"


def test_the_notes_of_a_final_release_start_at_the_final_release_before() -> None:
    assert previous_tag(Version("0.2.0"), ["v0.1.9", "v0.2.0rc1", "v0.2.0rc2"]) == "v0.1.9"


def test_the_notes_of_a_new_series_start_at_the_final_release_before() -> None:
    assert previous_tag(Version("0.3.0rc1"), ["v0.2.0rc2", "v0.2.0", "latest"]) == "v0.2.0"


def test_the_notes_skip_test_builds() -> None:
    assert previous_tag(Version("0.2.0rc1"), ["v0.1.0", "v0.2.0b3"]) == "v0.1.0"


def test_the_first_release_notes_start_from_the_beginning() -> None:
    assert previous_tag(Version("0.1.0"), []) is None
    assert previous_tag(Version("0.2.0"), ["v0.2.0rc1", "v0.2.0rc2"]) is None


def test_a_release_without_a_merged_pull_request_is_refused() -> None:
    with pytest.raises(SystemExit, match="no pull request has been merged since v0.3.0"):
        require_changes("v0.3.0", ["", "  "])


def test_a_release_with_a_merged_pull_request_goes_ahead() -> None:
    require_changes("v0.3.0", ["10"])

"""The release version: work it out, check it is PEP 440 in canonical form, write it into the manifest.

    release_version.py next KIND DRAFT OVERRIDE TAGS
                                            prints version=, tag=, prerelease= and previous_tag=
                                            lines for the next KIND ("release candidate" or
                                            "final release"); DRAFT is the draft release's
                                            version, OVERRIDE a version to take instead, either
                                            may be empty; TAGS is a file of every tag, one per line
    release_version.py check VERSION        prints version=, tag= and prerelease= lines
    release_version.py changes SINCE MERGED refuses a release when MERGED, a file of the pull
                                            requests merged since the release SINCE, is empty
    release_version.py write VERSION FILE   sets the one `"version": "..."` line in FILE
"""
import re
import sys
from pathlib import Path

from packaging.version import InvalidVersion, Version

_LINE = re.compile(r'^(\s*)"version": "[^"\n]*"(,?)$', re.MULTILINE)

RELEASE_CANDIDATE = "release candidate"
FINAL_RELEASE = "final release"


def _canonical(text: str) -> Version:
    """The version `text` names, refused unless `text` is already its canonical form."""
    try:
        version = Version(text)
    except InvalidVersion:
        sys.exit(f"::error::{text!r} is not a PEP 440 version, such as 1.2.3 or 1.2.3rc1")
    if str(version) != text:
        # The tag and the manifest must spell the version one way.
        sys.exit(f"::error::write {text!r} as {str(version)!r}, its canonical PEP 440 form")
    if len(version.release) != 3 or version.epoch or version.local:
        # 1.2 and 1.2.0 are one version to PEP 440 but two tags.
        sys.exit(f"::error::{text!r} must be MAJOR.MINOR.PATCH, optionally with a pre-release, "
                 f"such as 1.2.3 or 1.2.3rc1")
    return version


def known_versions(lines: list[str]) -> list[Version]:
    """The versions `lines` name, skipping tags that name none."""
    versions: list[Version] = []
    for line in lines:
        try:
            versions.append(Version(line.strip().removeprefix("v")))
        except InvalidVersion:
            continue
    return versions


def next_version(kind: str, draft: str, override: str, known: list[Version]) -> tuple[Version, str]:
    """The version to release as `kind`, and how it was found.

    Without an override, an open release-candidate series - the highest known version being a
    pre-release - is continued, or ended by a final release, unless the draft names a higher
    version; that starts a new series. A new major version is taken only as an override, so that
    a label placed wrongly cannot release one. The result must be higher than every known version,
    so that no version is released twice.
    """
    if kind not in (RELEASE_CANDIDATE, FINAL_RELEASE):
        sys.exit(f"::error::{kind!r} is neither {RELEASE_CANDIDATE!r} nor {FINAL_RELEASE!r}")
    top = max(known, default=None)
    if override:
        version = _canonical(override)
        if version.is_prerelease != (kind == RELEASE_CANDIDATE):
            sys.exit(f"::error::{version} is {'a pre-release' if version.is_prerelease else 'a final release'}, "
                     f"not a {kind}")
        how = "given as the override"
    else:
        series = Version(top.base_version) if top is not None and top.is_prerelease else None
        base = series
        if draft:
            proposed = _canonical(draft.removeprefix("v"))
            if proposed.is_prerelease:
                sys.exit(f"::error::the draft release names {proposed}, a pre-release, not the next version")
            if base is None or proposed > base:
                base = proposed
        if base is None:
            sys.exit("::error::no draft release names the next version, and no release-candidate "
                     "series is open; give the version as the override")
        if kind == FINAL_RELEASE:
            version = base
            how = "ends the release-candidate series" if base == series else "the draft release's version"
        elif base == series and top is not None and top.pre is not None and top.pre[0] == "rc":
            version = Version(f"{base}rc{top.pre[1] + 1}")
            how = f"the release candidate after {top}"
        else:
            version = Version(f"{base}rc1")
            how = f"the first release candidate of {base}"
        if top is not None and version.major > top.major:
            sys.exit(f"::error::{version} is a new major version; type it as the override")
    if top is not None and version <= top:
        sys.exit(f"::error::{version} is not higher than {top}, the highest version already tagged")
    return version, how


def previous_tag(version: Version, tags: list[str]) -> str | None:
    """The tag the notes of `version` start from, None to start from the beginning.

    That is the release candidate or final release before it; before a final release, the final
    release before it, so that its notes hold every change its release candidates had. Other
    pre-releases, such as test builds, are skipped.
    """
    found: list[tuple[Version, str]] = []
    for tag in tags:
        try:
            earlier = Version(tag.strip().removeprefix("v"))
        except InvalidVersion:
            continue
        if earlier >= version or earlier.dev is not None:
            continue
        if earlier.pre is not None and (earlier.pre[0] != "rc" or not version.is_prerelease):
            continue
        found.append((earlier, tag.strip()))
    return max(found)[1] if found else None


def require_changes(since: str, pull_requests: list[str]) -> None:
    """Refuse a release when no pull request has been merged since the release `since`.

    What users get comes through pull requests; a change pushed straight to main - CI, tests,
    the release itself - gives them nothing to release.
    """
    if not any(line.strip() for line in pull_requests):
        sys.exit(f"::error::no pull request has been merged since {since}; there is nothing to release")


def _lines(path: str) -> list[str]:
    return Path(path).read_text(encoding="utf-8").splitlines()


def _print(version: Version) -> None:
    print(f"version={version}")
    print(f"tag=v{version}")
    print(f"prerelease={'true' if version.is_prerelease else 'false'}")


def write(text: str, path: Path) -> None:
    version = _canonical(text)
    source = path.read_text(encoding="utf-8")
    found = _LINE.findall(source)
    if len(found) != 1:
        sys.exit(f'::error::{path} must hold exactly one `"version": "..."` line, '
                 f'found {len(found)}')
    path.write_text(_LINE.sub(rf'\1"version": "{version}"\2', source), encoding="utf-8")


if __name__ == "__main__":
    match sys.argv[1:]:
        case ["next", kind, draft, override, tags]:
            found, how = next_version(kind, draft, override, known_versions(_lines(tags)))
            print(f"{found}: {how}", file=sys.stderr)
            _print(found)
            print(f"previous_tag={previous_tag(found, _lines(tags)) or ''}")
        case ["check", text]:
            _print(_canonical(text))
        case ["changes", since, merged]:
            require_changes(since, _lines(merged))
        case ["write", text, path]:
            write(text, Path(path))
        case _:
            sys.exit(__doc__)

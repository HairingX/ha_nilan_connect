"""What a test build of a branch consists of: the libraries it uses, its version, its manifest.

    test_build.py libraries BRANCH          one requirement per library that has BRANCH, pinned
                                            to that branch's current commit
    test_build.py version BASE              the first free BASEb<n>, such as 0.1.0b3
    test_build.py manifest FILE VERSION [REQUIREMENT ...]
                                            sets the manifest's version, and replaces each
                                            library's requirement with the one given
"""
import json
import subprocess
import sys
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

OWNER = "https://github.com/HairingX"
LIBRARIES = ("modbus_event_connect", "nilan_connect")
"""In the order they are installed: modbus_event_connect first, as nilan_connect needs it."""


def _heads(repository: str, branch: str) -> str | None:
    """The commit `branch` points to in `repository`, or None if it has no such branch."""
    out = subprocess.run(["git", "ls-remote", repository, f"refs/heads/{branch}"],
                         capture_output=True, text=True, check=True).stdout.split()
    return out[0] if out else None


def libraries(branch: str) -> None:
    for library in LIBRARIES:
        commit = _heads(f"{OWNER}/{library}", branch)
        if commit is not None:
            # An archive of the commit needs no git where it is installed.
            print(f"{library} @ {OWNER}/{library}/archive/{commit}.tar.gz")


def version(base: str) -> None:
    release = Version(base)
    if release.is_prerelease or len(release.release) != 3:
        sys.exit(f"::error::{base!r} must be MAJOR.MINOR.PATCH, the version the next release gets")
    repository = subprocess.run(["git", "remote", "get-url", "origin"],
                                capture_output=True, text=True, check=True).stdout.strip()
    tags = subprocess.run(["git", "ls-remote", "--tags", repository, f"refs/tags/v{release}b*"],
                          capture_output=True, text=True, check=True).stdout.split()
    builds = [Version(tag.removeprefix("refs/tags/v"))
              for tag in tags if tag.startswith("refs/tags/") and not tag.endswith("^{}")]
    used = {build.pre[1] for build in builds if build.pre is not None}
    number = next(n for n in range(1, len(used) + 2) if n not in used)
    print(f"{release}b{number}")


def manifest(path: Path, new_version: str, requirements: list[str]) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = str(Version(new_version))
    replaced = {Requirement(r).name for r in requirements}
    kept = [r for r in data["requirements"] if Requirement(r).name not in replaced]
    data["requirements"] = [*requirements, *kept]
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    match sys.argv[1:]:
        case ["libraries", branch]:
            libraries(branch)
        case ["version", base]:
            version(base)
        case ["manifest", path, new_version, *requirements]:
            manifest(Path(path), new_version, requirements)
        case _:
            sys.exit(__doc__)

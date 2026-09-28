"""The zip HACS installs from a release: HACS unpacks it into the integration's directory, so the
integration's files are at its root.

    release_zip.py DIRECTORY ZIP VERSION    writes ZIP from the files of DIRECTORY, leaving out
                                            __pycache__ and .pyc, and refuses it unless the
                                            manifest.json at its root says VERSION
"""
import json
import sys
import zipfile
from pathlib import Path

MANIFEST = "manifest.json"


def build(directory: Path, target: Path, version: str) -> None:
    files = sorted(path for path in directory.rglob("*")
                   if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(directory).as_posix())
    check(target, version)


def check(target: Path, version: str) -> None:
    """Refuse `target` unless its root holds a manifest.json that says `version`."""
    with zipfile.ZipFile(target) as archive:
        if MANIFEST not in archive.namelist():
            sys.exit(f"::error::{target.name} has no {MANIFEST} at its root")
        found = json.loads(archive.read(MANIFEST)).get("version")
    if found != version:
        sys.exit(f"::error::the {MANIFEST} in {target.name} says {found}, not {version}")


if __name__ == "__main__":
    match sys.argv[1:]:
        case [directory, target, version]:
            build(Path(directory), Path(target), version)
        case _:
            sys.exit(__doc__)

"""Tests of the zip a release publishes for HACS."""
import json
import zipfile
from pathlib import Path

import pytest

from release_zip import build


def _integration(root: Path, version: str) -> Path:
    directory = root / "integration"
    (directory / "translations").mkdir(parents=True)
    (directory / "__pycache__").mkdir()
    (directory / "manifest.json").write_text(json.dumps({"domain": "x", "version": version}), encoding="utf-8")
    (directory / "__init__.py").write_text("", encoding="utf-8")
    (directory / "translations" / "en.json").write_text("{}", encoding="utf-8")
    (directory / "__pycache__" / "__init__.cpython-314.pyc").write_bytes(b"")
    (directory / "stray.pyc").write_bytes(b"")
    return directory


def test_the_integrations_files_are_at_the_zips_root(tmp_path: Path) -> None:
    build(_integration(tmp_path, "1.2.3"), tmp_path / "x.zip", "1.2.3")
    with zipfile.ZipFile(tmp_path / "x.zip") as archive:
        assert sorted(archive.namelist()) == ["__init__.py", "manifest.json", "translations/en.json"]


def test_a_zip_whose_manifest_says_another_version_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="says 0.0.0, not 1.2.3"):
        build(_integration(tmp_path, "0.0.0"), tmp_path / "x.zip", "1.2.3")


def test_a_zip_without_a_manifest_at_its_root_is_refused(tmp_path: Path) -> None:
    directory = _integration(tmp_path, "1.2.3")
    (directory / "manifest.json").unlink()
    with pytest.raises(SystemExit, match="no manifest.json at its root"):
        build(directory, tmp_path / "x.zip", "1.2.3")

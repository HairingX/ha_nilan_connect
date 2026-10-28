#!/usr/bin/env bash
# Installs Home Assistant, the library and the test tools, as the tests pin them, under Home
# Assistant's package constraints, as Home Assistant installs an integration's requirements.
#
# The integrations of the owner keep this file word for word; it comes from HairingX/workflows.

set -e
cd "$(dirname "$0")/.."
pip="python3 -m pip --disable-pip-version-check --no-cache-dir"
$pip install -r requirements-test.txt

# Home Assistant installs an integration's requirements under its package constraints. Installed
# without them, a package such as cffi can be at another version than the one Home Assistant then
# adds, and the two halves of it fail to load together.
constraints=$(python3 -c 'import homeassistant, pathlib; print(pathlib.Path(homeassistant.__file__).parent / "package_constraints.txt")')
$pip install -r requirements-test.txt -c "$constraints"

# Home Assistant installs what its own integrations need, such as the frontend, into the user's
# site-packages, and Python adds that folder to its path only if it exists when it starts.
# Without it, Home Assistant's first start fails to import what it has just installed.
mkdir -p "$(python3 -m site --user-site)"

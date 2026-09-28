#!/usr/bin/env bash
# Installs Home Assistant, the library and the test tools, as the tests pin them.

set -e
cd "$(dirname "$0")/.."
python3 -m pip --disable-pip-version-check --no-cache-dir install -r requirements-test.txt

# Home Assistant installs what its own integrations need, such as the frontend, into the user's
# site-packages, and Python adds that folder to its path only if it exists when it starts.
# Without it, Home Assistant's first start fails to import what it has just installed.
mkdir -p "$(python3 -m site --user-site)"

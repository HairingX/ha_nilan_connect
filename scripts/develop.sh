#!/usr/bin/env bash
# Runs Home Assistant with this integration, using config/ as its configuration directory.

set -e
cd "$(dirname "$0")/.."

if [[ ! -d "${PWD}/config" ]]; then
    mkdir -p "${PWD}/config"
    hass --config "${PWD}/config" --script ensure_config
fi

# Home Assistant loads custom integrations from <config>/custom_components. A link keeps the
# integration in one place; putting custom_components/ on PYTHONPATH instead would let the
# integration's folder shadow the nilan_connect library it imports.
ln -sfn "${PWD}/custom_components" "${PWD}/config/custom_components"

hass --config "${PWD}/config" --debug

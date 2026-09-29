"""Set up a Nilan unit behind its gateway, change where it is reached, and renew its email."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from nilan_connect import (
    AuthenticationError,
    CannotConnectError,
    DiscoveredDevice,
    UnsupportedDeviceError,
    discover,
)

from . import const
from .const import CONF_EMAIL, CONF_GATEWAY_ID, DEFAULT_NAME, DEFAULT_PORT, DOMAIN
from .data import new_client

_LOGGER = logging.getLogger(__name__)

_PORT = vol.All(int, vol.Range(min=1, max=65535))


class EmailRefusedError(Exception):
    """The gateway refused the email, as entered and in lower case."""


async def connect_once(
    email: str, host: str | None, port: int, gateway_id: str | None
) -> str:
    """Connect to the gateway once, read-only, and return the email it accepted.

    The email is tried as entered, then in lower case: the gateway compares it exactly, and an
    app account's email is often typed with a capital letter.

    Raises:
        EmailRefusedError: the gateway refused both.
        CannotConnectError: nothing answered.
        UnsupportedDeviceError: the controller behind the gateway is not supported.
    """
    for candidate in dict.fromkeys((email, email.lower())):
        client = new_client(candidate, host, port, gateway_id, read_only=True)
        try:
            await client.connect()
        except AuthenticationError:
            continue
        finally:
            await client.disconnect()
        return candidate
    raise EmailRefusedError


async def gateway_at(host: str, port: int) -> str | None:
    """The id of the gateway answering discovery at `host`, or None if it does not answer."""
    found = await discover(timeout=const.DISCOVERY_TIMEOUT, target=(host, port))
    return found[0].device_id if len(found) == 1 else None


class NilanConnectConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a unit found on the network, or at an address; it is recognised by its gateway's
    id, and named by the user."""

    VERSION = 2
    MINOR_VERSION = 1

    _gateways: dict[str, DiscoveredDevice]

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Find the gateway on the network, or enter its address."""
        return self.async_show_menu(step_id="user", menu_options=["discover", "manual"])

    async def async_step_discover(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a gateway that answered discovery, name the unit, and give the email."""
        errors: dict[str, str] = {}
        if user_input is None:
            configured = self._async_current_ids(include_ignore=False)
            self._gateways = {
                gateway.device_id: gateway
                for gateway in await discover(timeout=const.DISCOVERY_TIMEOUT)
                if gateway.device_id not in configured
            }
            if not self._gateways:
                return await self.async_step_no_gateways()
        else:
            gateway = self._gateways[user_input[CONF_GATEWAY_ID]]
            name = str(user_input[CONF_NAME]).strip()
            await self.async_set_unique_id(gateway.device_id)
            self._abort_if_unique_id_configured(
                updates={CONF_HOST: gateway.host, CONF_PORT: gateway.port}
            )
            email = await self._check(
                name, user_input[CONF_EMAIL], gateway.host, gateway.port, gateway.device_id, errors
            )
            if email is not None:
                return self.async_create_entry(
                    title=name,
                    data={
                        CONF_NAME: name,
                        CONF_EMAIL: email,
                        CONF_HOST: gateway.host,
                        CONF_PORT: gateway.port,
                        CONF_GATEWAY_ID: gateway.device_id,
                    },
                )
        schema = vol.Schema(
            {
                vol.Required(CONF_GATEWAY_ID): vol.In(sorted(self._gateways)),
                vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                vol.Required(CONF_EMAIL): str,
            }
        )
        return self.async_show_form(
            step_id="discover",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )

    async def async_step_no_gateways(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """No gateway answered discovery: look again, or enter the gateway's address."""
        return self.async_show_menu(
            step_id="no_gateways", menu_options=["discover", "manual"]
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Name the unit, and give its gateway's address and the email."""
        errors: dict[str, str] = {}
        if user_input is not None:
            name = str(user_input[CONF_NAME]).strip()
            host = str(user_input[CONF_HOST]).strip()
            port = int(user_input[CONF_PORT])
            if not host:
                errors[CONF_HOST] = "invalid_host"
            else:
                email = await self._check(name, user_input[CONF_EMAIL], host, port, None, errors)
                if email is not None:
                    gateway_id = await gateway_at(host, port)
                    if gateway_id is not None:
                        await self.async_set_unique_id(gateway_id)
                        self._abort_if_unique_id_configured(
                            updates={CONF_HOST: host, CONF_PORT: port}
                        )
                    return self.async_create_entry(
                        title=name,
                        data={
                            CONF_NAME: name,
                            CONF_EMAIL: email,
                            CONF_HOST: host,
                            CONF_PORT: port,
                            CONF_GATEWAY_ID: gateway_id,
                        },
                    )
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): _PORT,
                vol.Required(CONF_EMAIL): str,
            }
        )
        return self.async_show_form(
            step_id="manual",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the gateway's address or port, or the email.

        Without an address, a gateway whose id is known is found by discovery. The unit's name
        is kept: every unique id starts with it.
        """
        entry = self._get_reconfigure_entry()
        gateway_id: str | None = entry.data[CONF_GATEWAY_ID]
        errors: dict[str, str] = {}
        if user_input is not None:
            host = str(user_input.get(CONF_HOST) or "").strip() or None
            port = int(user_input[CONF_PORT])
            if host is None and gateway_id is None:
                errors[CONF_HOST] = "invalid_host"
            else:
                found = await gateway_at(host, port) if host is not None else None
                if found is not None and gateway_id is not None and found != gateway_id:
                    errors["base"] = "wrong_gateway"
                else:
                    gateway_id = found or gateway_id
                    email = await self._connect(
                        user_input[CONF_EMAIL], host, port, gateway_id, errors
                    )
                    if email is not None:
                        return self.async_update_reload_and_abort(
                            entry,
                            data_updates={
                                CONF_EMAIL: email,
                                CONF_HOST: host,
                                CONF_PORT: port,
                                CONF_GATEWAY_ID: gateway_id,
                            },
                        )
        schema = vol.Schema(
            {
                vol.Optional(CONF_HOST): str,
                vol.Required(CONF_PORT): _PORT,
                vol.Required(CONF_EMAIL): str,
            }
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                schema, user_input if user_input is not None else entry.data
            ),
            description_placeholders={"name": entry.title},
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """The gateway refused the email the unit was set up with."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the email the gateway is paired with now."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            email = await self._connect(
                user_input[CONF_EMAIL],
                entry.data[CONF_HOST],
                entry.data[CONF_PORT],
                entry.data[CONF_GATEWAY_ID],
                errors,
            )
            if email is not None:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_EMAIL: email}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_EMAIL): str}),
            description_placeholders={"name": entry.title},
            errors=errors,
        )

    async def _check(
        self,
        name: str,
        email: str,
        host: str | None,
        port: int,
        gateway_id: str | None,
        errors: dict[str, str],
    ) -> str | None:
        """A new unit's name and connection: the email the gateway accepted, or None with the
        reason put in `errors`."""
        if not name:
            errors[CONF_NAME] = "invalid_name"
            return None
        if any(entry.data.get(CONF_NAME) == name for entry in self._async_current_entries()):
            # Every unique id starts with the name.
            errors[CONF_NAME] = "name_in_use"
            return None
        return await self._connect(email, host, port, gateway_id, errors)

    async def _connect(
        self,
        email: str,
        host: str | None,
        port: int,
        gateway_id: str | None,
        errors: dict[str, str],
    ) -> str | None:
        """The email the gateway accepted, or None with the reason put in `errors`."""
        try:
            return await connect_once(str(email).strip(), host, port, gateway_id)
        except EmailRefusedError:
            errors[CONF_EMAIL] = "invalid_auth"
        except CannotConnectError:
            errors["base"] = "cannot_connect"
        except UnsupportedDeviceError:
            errors["base"] = "unsupported_device"
        except Exception:
            _LOGGER.exception("Unexpected error while connecting to the gateway")
            errors["base"] = "unknown"
        return None

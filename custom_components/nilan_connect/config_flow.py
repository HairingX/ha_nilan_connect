"""Set up a Nilan unit behind its gateway, change where it is reached, renew its email, choose
the level of the values it shows, and map it."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, cast

import probatio
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import selector
from nilan_connect import (
    AuthenticationError,
    CannotConnectError,
    DiscoveredDevice,
    Level,
    UnsupportedDeviceError,
    discover,
)

from .const import (
    CONF_EMAIL,
    CONF_GATEWAY_ID,
    CONF_LEVEL,
    DEFAULT_LEVEL,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DOMAIN,
    MAPPING_REPORT_URL,
    TEST_REPORT_URL,
)
from .data import NilanConfigEntry, identity_text, new_client
from .guide import CONF_CHANGE, CONF_UNIT, MappingGuide

_LOGGER = logging.getLogger(__name__)

_PORT = probatio.All(int, probatio.Range(min=1, max=65535))

# HA's selector registry declares the classes registered in it without their configuration's
# type, so the class is taken by name and given that type here.
_SELECT = cast(
    type[selector.Selector[selector.SelectSelectorConfig]], getattr(selector, "SelectSelector")
)
_TEXT = cast(
    type[selector.Selector[selector.TextSelectorConfig]], getattr(selector, "TextSelector")
)
_MULTILINE = selector.TextSelectorConfig(multiline=True)


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
    found = await discover(target=host, port=port)
    return found[0].device_id if len(found) == 1 else None


class NilanConnectConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a unit found on the network, or at an address; it is recognised by its gateway's
    id, and named by the user."""

    VERSION = 2
    MINOR_VERSION = 2

    _gateways: dict[str, DiscoveredDevice]
    _identity: str = ""
    """What an unsupported controller reported, shown in the error so it can be copied."""

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> NilanOptionsFlow:
        """Choose the level of the values the unit shows, or map the unit."""
        return NilanOptionsFlow()

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
                for gateway in await discover()
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
        schema = probatio.Schema(
            {
                probatio.Required(CONF_GATEWAY_ID): probatio.In(sorted(self._gateways)),
                probatio.Required(CONF_NAME, default=DEFAULT_NAME): str,
                probatio.Required(CONF_EMAIL): str,
            }
        )
        return self.async_show_form(
            step_id="discover",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            description_placeholders={"identity": self._identity},
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
        schema = probatio.Schema(
            {
                probatio.Required(CONF_NAME, default=DEFAULT_NAME): str,
                probatio.Required(CONF_HOST): str,
                probatio.Required(CONF_PORT, default=DEFAULT_PORT): _PORT,
                probatio.Required(CONF_EMAIL): str,
            }
        )
        return self.async_show_form(
            step_id="manual",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            description_placeholders={"identity": self._identity},
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
        schema = probatio.Schema(
            {
                probatio.Optional(CONF_HOST): str,
                probatio.Required(CONF_PORT): _PORT,
                probatio.Required(CONF_EMAIL): str,
            }
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                schema, user_input if user_input is not None else entry.data
            ),
            description_placeholders={"name": entry.title, "identity": self._identity},
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
            data_schema=probatio.Schema({probatio.Required(CONF_EMAIL): str}),
            description_placeholders={"name": entry.title, "identity": self._identity},
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
        except UnsupportedDeviceError as err:
            errors["base"] = "unsupported_device"
            self._identity = identity_text(err.identity)
        except Exception:
            _LOGGER.exception("Unexpected error while connecting to the gateway")
            errors["base"] = "unknown"
        return None


class NilanOptionsFlow(OptionsFlowWithReload):
    """The unit's settings, and the guide that maps it.

    Settings choose the level of the values the unit shows; the entry reloads with the choice.
    Verified is offered only where the unit's model has a verified point, or while the entry is
    not loaded and its model is not known.

    Mapping reads the unit's registers once in full, then, after each change the user makes on
    the unit's panel, only those it found, and stores what changed; it changes no option.
    """

    _started: MappingGuide | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The settings, or the guide."""
        return self.async_show_menu(step_id="init", menu_options=["settings", "map_unit"])

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The level of the values the unit shows."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        entry: NilanConfigEntry = self.config_entry
        offered = [
            level
            for level in Level
            if level is not Level.VERIFIED
            or entry.state is not ConfigEntryState.LOADED
            or entry.runtime_data.client.model.keys_at(Level.VERIFIED)
        ]
        levels = _SELECT(
            selector.SelectSelectorConfig(
                options=[str(level) for level in offered],
                translation_key=CONF_LEVEL,
                mode=selector.SelectSelectorMode.LIST,
            )
        )
        schema = probatio.Schema({probatio.Required(CONF_LEVEL, default=str(DEFAULT_LEVEL)): levels})
        return self.async_show_form(
            step_id="settings",
            data_schema=self.add_suggested_values_to_schema(schema, self.config_entry.options),
            description_placeholders={"report_url": TEST_REPORT_URL},
        )

    async def async_step_map_unit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Start mapping the unit, which must be loaded."""
        entry: NilanConfigEntry = self.config_entry
        if entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        return await self.async_step_map_start()

    async def async_step_map_start(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask what the user knows of the unit, then read it in full."""
        guide = self._require_guide()
        if user_input is not None:
            guide.unit_description = str(user_input.get(CONF_UNIT, "")).strip()
            return await self._read(guide.first_read, on_failure="map_start")
        schema = probatio.Schema({probatio.Optional(CONF_UNIT): _TEXT(_MULTILINE)})
        return self.async_show_form(
            step_id="map_start",
            data_schema=self.add_suggested_values_to_schema(
                schema, {CONF_UNIT: guide.unit_description}
            ),
            description_placeholders={"report_url": MAPPING_REPORT_URL},
            errors=guide.take_errors(),
        )

    async def async_step_map_change(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask what the user changed on the unit's panel, then read the unit again."""
        guide = self._require_guide()
        if user_input is not None:
            guide.note = str(user_input.get(CONF_CHANGE, "")).strip()
            return await self._read(guide.step_read, on_failure="map_change")
        schema = probatio.Schema({probatio.Optional(CONF_CHANGE): _TEXT(_MULTILINE)})
        return self.async_show_form(
            step_id="map_change",
            data_schema=self.add_suggested_values_to_schema(schema, {CONF_CHANGE: guide.note}),
            description_placeholders=guide.placeholders(),
            errors=guide.take_errors(),
        )

    async def async_step_map_read(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the read in progress; when it ends, go on, or back with its error."""
        guide = self._require_guide()
        task, started = guide.reading()
        # Progress is shown at least once: a read that fails at once ends as it starts.
        if started or not task.done():
            return self.async_show_progress(
                step_id="map_read", progress_action="reading", progress_task=task
            )
        return self.async_show_progress_done(next_step_id=await guide.finished(task))

    async def async_step_map_changed(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """What the last read changed; the next change, or done."""
        guide = self._require_guide()
        options = ["map_next", "map_done"] if guide.room_for_steps else ["map_done"]
        return self.async_show_menu(
            step_id="map_changed", menu_options=options, description_placeholders=guide.placeholders()
        )

    async def async_step_map_next(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Make the next change."""
        self._require_guide().note = ""
        return await self.async_step_map_change()

    async def async_step_map_done(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Finish, after reading everything once more, or as it is."""
        return self.async_show_menu(step_id="map_done", menu_options=["map_full", "map_finish"])

    async def async_step_map_full(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Read everything once more, as the first read did, to find registers that appeared."""
        return await self._read(self._require_guide().full_read, on_failure="map_full_failed")

    async def async_step_map_full_failed(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The last full read failed; the steps are stored."""
        return self.async_abort(reason="mapping_saved_without_full_read")

    async def async_step_map_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The mapping is stored."""
        guide = self._require_guide()
        return self.async_abort(
            reason="mapping_saved",
            description_placeholders={**guide.placeholders(), "report_url": MAPPING_REPORT_URL},
        )

    async def _read(
        self, read: Callable[[], Awaitable[str]], *, on_failure: str
    ) -> ConfigFlowResult:
        """Start `read`, which gives the step to go on with, and show its progress."""
        self._require_guide().prepare(read, on_failure=on_failure)
        return await self.async_step_map_read()

    def _require_guide(self) -> MappingGuide:
        """The guide of this flow, made the first time it is needed."""
        if self._started is None:
            self._started = MappingGuide(self.hass, self.config_entry)
        return self._started

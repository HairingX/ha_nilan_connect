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
from .guide import (
    CONF_CHANGE,
    CONF_FITTED,
    CONF_MORE,
    CONF_SUGGESTION,
    CONF_VALUE,
    CONF_WHAT,
    OTHER_TEST,
    READING_KINDS,
    READINGS,
    SUGGESTIONS,
    MappingGuide,
)

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

    Mapping scans every address of the unit once, then, after each test the user makes on the
    unit's panel and each value the user writes down from it, only those that answered, and stores
    what changed with the user's comments, and each value with its read; it changes no option.
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
        """Start mapping the unit."""
        return await self.async_step_map_start()

    async def async_step_map_start(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the model the unit was recognised as, ask what extra equipment is fitted, if any,
        then scan every address of it."""
        if not self._loaded():
            return self.async_abort(reason="not_loaded")
        guide = self._require_guide()
        if user_input is not None:
            guide.fitted = str(user_input.get(CONF_FITTED, "")).strip()
            return await self._read(guide.first_read, on_failure="map_start")
        schema = probatio.Schema({probatio.Optional(CONF_FITTED): str})
        return self.async_show_form(
            step_id="map_start",
            data_schema=self.add_suggested_values_to_schema(schema, {CONF_FITTED: guide.fitted}),
            description_placeholders=self._unit(report_url=MAPPING_REPORT_URL),
            errors=guide.take_errors(),
        )

    async def async_step_map_read(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the scan in progress; when it ends, go on, or back with its error."""
        guide = self._require_guide()
        task, started = guide.reading()
        # Progress is shown at least once: a scan that fails at once ends as it starts.
        if started or not task.done():
            return self.async_show_progress(
                step_id="map_read",
                progress_action="reading",
                progress_task=task,
                description_placeholders={"total": str(guide.read_total())},
            )
        return self.async_show_progress_done(next_step_id=await guide.finished(task))

    async def async_step_map_found(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """What the first scan found; write down what the panel shows, test functions, or send it
        in now."""
        if not self._loaded():
            return self.async_abort(reason="not_loaded")
        return self.async_show_menu(
            step_id="map_found",
            menu_options=["map_reading", "map_test", "map_send"],
            description_placeholders=self._unit(found=self._require_guide().found_text()),
        )

    async def async_step_map_reading(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """One value the panel shows, and what it is; saving it reads the unit at once. Both left
        empty end the writing down."""
        if not self._loaded():
            return self.async_abort(reason="not_loaded")
        guide = self._require_guide()
        if user_input is not None:
            guide.what = str(user_input.get(CONF_WHAT) or "").strip()
            guide.value = str(user_input.get(CONF_VALUE) or "").strip()
            if guide.what or guide.value:
                return await self._read(guide.reading_read, on_failure="map_reading")
            return await (self.async_step_map_tested() if guide.saved_any else self.async_step_map_found())
        if not guide.room_for_readings:
            return await self.async_step_map_tested()
        kinds = _SELECT(
            selector.SelectSelectorConfig(
                options=list(READINGS),
                translation_key=READING_KINDS,
                mode=selector.SelectSelectorMode.DROPDOWN,
                custom_value=True,
            )
        )
        schema = probatio.Schema({probatio.Optional(CONF_WHAT): kinds, probatio.Optional(CONF_VALUE): str})
        # A value whose read failed is offered again, so that it need not be written anew.
        suggested = {key: text for key, text in ((CONF_WHAT, guide.what), (CONF_VALUE, guide.value)) if text}
        return self.async_show_form(
            step_id="map_reading",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            description_placeholders=self._unit(saved=guide.saved_text()),
            errors=guide.take_errors(),
        )

    async def async_step_map_test(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose what to test, and say what changes if wanted; the unit is then read as it is,
        before the change."""
        if not self._loaded():
            return self.async_abort(reason="not_loaded")
        guide = self._require_guide()
        errors = guide.take_errors()
        if user_input is not None:
            guide.suggestion = str(user_input[CONF_SUGGESTION])
            guide.change = str(user_input.get(CONF_CHANGE, "")).strip()
            if guide.change or guide.suggestion != OTHER_TEST:
                return await self._read(guide.before_read, on_failure="map_test")
            errors = {CONF_CHANGE: "describe_other"}
        suggestions = _SELECT(
            selector.SelectSelectorConfig(
                options=[*SUGGESTIONS, OTHER_TEST],
                translation_key="mapping_suggestion",
                mode=selector.SelectSelectorMode.LIST,
            )
        )
        schema = probatio.Schema(
            {
                probatio.Required(CONF_SUGGESTION): suggestions,
                probatio.Optional(CONF_CHANGE): str,
            }
        )
        suggested = {CONF_CHANGE: guide.change}
        if guide.suggestion is not None:
            suggested[CONF_SUGGESTION] = guide.suggestion
        return self.async_show_form(
            step_id="map_test",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            description_placeholders=self._unit(),
            errors=errors,
        )

    async def async_step_map_change(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The unit was read before the change: the user makes it now, then the unit is read again."""
        if not self._loaded():
            return self.async_abort(reason="not_loaded")
        guide = self._require_guide()
        if user_input is not None:
            return await self._read(guide.step_read, on_failure="map_change")
        return self.async_show_form(
            step_id="map_change",
            data_schema=probatio.Schema({}),
            description_placeholders=self._unit(),
            errors=guide.take_errors(),
        )

    async def async_step_map_result(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """What the test changed, a field for the user's comment on each register."""
        if not self._loaded():
            return self.async_abort(reason="not_loaded")
        guide = self._require_guide()
        if user_input is not None:
            if not await guide.write_comments(user_input):
                return self.async_abort(reason="mapping_gone_comments")
            return await self.async_step_map_tested()
        # A field's name is its label where no translation names it: the register and its change.
        fields: dict[Any, Any] = {probatio.Optional(name): str for name in guide.register_fields()}
        suggested: dict[str, str] = {}
        if guide.more_changes:
            fields[probatio.Optional(CONF_MORE)] = _TEXT(_MULTILINE)
            suggested[CONF_MORE] = guide.more_lines()
        return self.async_show_form(
            step_id="map_result",
            data_schema=self.add_suggested_values_to_schema(probatio.Schema(fields), suggested),
            description_placeholders=self._unit(result=guide.result_text()),
        )

    async def async_step_map_tested(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Write down what the panel shows, the next test, the values, or send it in."""
        if not self._loaded():
            return self.async_abort(reason="not_loaded")
        guide = self._require_guide()
        options = [*(["map_reading"] if guide.room_for_readings else []),
                   *(["map_test"] if guide.room_for_steps else []), "map_values", "map_send"]
        return self.async_show_menu(step_id="map_tested", menu_options=options, description_placeholders=self._unit())

    async def async_step_map_values(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """A page of the values the scans found; nothing is read for it."""
        if not self._loaded():
            return self.async_abort(reason="not_loaded")
        guide = self._require_guide()
        pages = len(guide.pages())
        options = [
            *(["map_values_previous"] if guide.page > 0 else []),
            *(["map_values_next"] if guide.page + 1 < pages else []),
            "map_values_back",
        ]
        return self.async_show_menu(
            step_id="map_values", menu_options=options, description_placeholders=self._unit(**guide.page_placeholders())
        )

    async def async_step_map_values_next(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The next page of values."""
        self._require_guide().page += 1
        return await self.async_step_map_values()

    async def async_step_map_values_previous(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The page of values before."""
        self._require_guide().page -= 1
        return await self.async_step_map_values()

    async def async_step_map_values_back(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Back to the next test or sending it in."""
        return await self.async_step_map_tested()

    async def async_step_map_send(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Finish; after a test, once every address has been scanned once more, so that a
        register a test brought is not missed."""
        if not self._loaded():
            return self.async_abort(reason="not_loaded")
        guide = self._require_guide()
        if not guide.tested:
            return await self.async_step_map_finish()
        if user_input is not None:
            guide.on_progress = self.async_update_progress
            return await self._read(guide.full_read, on_failure="map_send")
        return self.async_show_form(
            step_id="map_send",
            data_schema=probatio.Schema({}),
            description_placeholders=self._unit(duration=guide.duration_text()),
            errors=guide.take_errors(),
        )

    async def async_step_map_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The mapping is stored: how many tests it holds, and what the last scan changed."""
        guide = self._require_guide()
        return self.async_abort(
            reason="mapping_saved",
            description_placeholders={
                "summary": guide.summary_text(scanned=guide.tested),
                "report_url": MAPPING_REPORT_URL,
            },
        )

    async def async_step_map_gone_test(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The mapping gave way to newer ones of the unit, and took not the last test."""
        return self.async_abort(reason="mapping_gone_test")

    async def async_step_map_gone_reading(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The mapping gave way to newer ones of the unit, and took not the last value from the
        panel."""
        return self.async_abort(reason="mapping_gone_reading")

    async def async_step_map_gone_final(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The mapping gave way to newer ones of the unit, and took not the last scan."""
        return self.async_abort(reason="mapping_gone_final")

    async def _read(
        self, read: Callable[[], Awaitable[str]], *, on_failure: str
    ) -> ConfigFlowResult:
        """Start `read`, which gives the step to go on with, and show its progress."""
        self._require_guide().prepare(read, on_failure=on_failure)
        return await self.async_step_map_read()

    def _unit(self, **placeholders: str) -> dict[str, str]:
        """`placeholders`, with the unit the guide maps by its manufacturer and model."""
        model = self.config_entry.runtime_data.client.model
        return {"unit": f"{model.manufacturer} {model.name}", **placeholders}

    def _loaded(self) -> bool:
        """Whether the unit's entry is set up, which every read needs."""
        return self.config_entry.state is ConfigEntryState.LOADED

    def _require_guide(self) -> MappingGuide:
        """The guide of this flow, made the first time it is needed."""
        if self._started is None:
            self._started = MappingGuide(self.hass, self.config_entry)
        return self._started

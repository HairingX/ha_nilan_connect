"""The guide that maps a unit: its reads, what each changed, and what is stored of them."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Final

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util
from nilan_connect import CannotConnectError, NotConnectedError, RegisterChange, Snapshot, difference

from .const import CHANGES_SHOWN, DOMAIN, MAPPING_LIMIT, STEPS_KEPT
from .data import NilanConfigEntry
from .mapping import Mappings, mapping, step

_LOGGER = logging.getLogger(__name__)

CONF_UNIT: Final = "unit"
"""What the user says the unit is, and what is fitted to it."""

CONF_CHANGE: Final = "change"
"""What the user changed on the unit's panel, and what it shows now."""


def changes_text(changes: Sequence[RegisterChange]) -> str:
    """`changes` as a list, the first few only: "- datapoint 38: 1 → 0 (bits 0)"."""
    if not changes:
        return "-"
    lines = [f"- {change.address}: {_word(change.before)} → {_word(change.after)}"
             + (f" (bits {', '.join(map(str, change.bits))})" if change.bits else "")
             for change in changes[:CHANGES_SHOWN]]
    if len(changes) > CHANGES_SHOWN:
        lines.append("- …")
    return "\n".join(lines)


def _word(word: int | None) -> str:
    return "–" if word is None else str(word)


class MappingGuide:
    """One mapping of a loaded unit, read step by step; each read is stored as soon as it ends."""

    def __init__(self, hass: HomeAssistant, entry: NilanConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._mappings = Mappings(hass, entry.entry_id)
        self.unit_description = ""
        self.note = ""
        self._task: asyncio.Task[str] | None = None
        self._pending: tuple[Callable[[], Awaitable[str]], str] = (self.first_read, "map_start")
        self._errors: dict[str, str] = {}
        self._started_at = ""
        nothing = Snapshot(dt_util.utcnow(), {}, [])
        self._found = self._last = nothing
        """The first full read, and the read last; nothing before the first read."""
        self._changes: tuple[RegisterChange, ...] = ()
        self._steps = 0

    @property
    def room_for_steps(self) -> bool:
        """Whether another step would be stored."""
        return self._steps < STEPS_KEPT

    def placeholders(self) -> dict[str, str]:
        """What the last read changed, for a step's description."""
        return {"count": str(len(self._changes)), "changes": changes_text(self._changes)}

    def take_errors(self) -> dict[str, str]:
        """Why the last read failed, once; empty when it did not."""
        errors, self._errors = self._errors, {}
        return errors

    def prepare(self, read: Callable[[], Awaitable[str]], *, on_failure: str) -> None:
        """Make `read` the next read; when it fails, the guide goes on with `on_failure`, saying why."""
        self._pending = (read, on_failure)

    def reading(self) -> tuple[asyncio.Task[str], bool]:
        """The read under way, which gives the step to go on with, and whether it was started now,
        from the one prepared, as none was."""
        if self._task is not None:
            return self._task, False
        read, on_failure = self._pending
        self._task = self._hass.async_create_task(self._run(read, on_failure), "nilan_connect mapping read")
        return self._task, True

    async def finished(self, task: asyncio.Task[str]) -> str:
        """The step the ended read `task` goes on with; the next read starts afresh."""
        self._task = None
        return await task

    async def _run(self, read: Callable[[], Awaitable[str]], on_failure: str) -> str:
        try:
            return await read()
        except (CannotConnectError, NotConnectedError) as err:
            _LOGGER.info("Mapping %s stopped: %s", self._entry.title, err)
            self._errors = {"base": "read_failed"}
        except Exception:
            _LOGGER.exception("Unexpected error while mapping %s", self._entry.title)
            self._errors = {"base": "unknown"}
        return on_failure

    async def first_read(self) -> str:
        """Find and read every register of the unit, and store the mapping with it."""
        client = self._entry.runtime_data.client
        found = await client.map_areas(limit=MAPPING_LIMIT)
        started = dt_util.utcnow()
        self._started_at = started.isoformat()
        await self._mappings.async_start(mapping(
            started_at=started,
            unit_description=self.unit_description,
            model=client.model.name,
            identity=dict(client.identity),
            device=self._device(),
            areas=client.mapping_areas(limit=MAPPING_LIMIT),
            baseline=found,
        ))
        self._found = self._last = found
        self._changes, self._steps = (), 0
        return "map_change"

    async def step_read(self) -> str:
        """Read again the registers found, and store what changed since the read before."""
        again = await self._entry.runtime_data.client.read_mapped(self._found)
        self._changes = difference(self._last, again)
        await self._mappings.async_add_step(self._started_at, step(again.taken_at, self.note, self._changes))
        self._steps += 1
        self._last = again
        return "map_changed"

    async def full_read(self) -> str:
        """Find and read every register once more, and store what changed since the last read."""
        again = await self._entry.runtime_data.client.map_areas(limit=MAPPING_LIMIT)
        # Against the last words and what the first read found missing, so that a register that
        # answers only now shows as a change.
        known = Snapshot(self._last.taken_at, {**self._found.values, **self._last.values},
                         self._found.missing.difference(self._last.values))
        self._changes = difference(known, again)
        await self._mappings.async_finish(self._started_at, step(again.taken_at, "", self._changes))
        self._last = again
        return "map_finish"

    def _device(self) -> dict[str, str | None]:
        """What Home Assistant's device of the unit says it is."""
        identifier = (DOMAIN, self._entry.runtime_data.name)
        devices = dr.async_entries_for_config_entry(dr.async_get(self._hass), self._entry.entry_id)
        device = next((each for each in devices if identifier in each.identifiers), None)
        if device is None:
            return {"manufacturer": None, "model": None, "sw_version": None}
        return {"manufacturer": device.manufacturer, "model": device.model, "sw_version": device.sw_version}

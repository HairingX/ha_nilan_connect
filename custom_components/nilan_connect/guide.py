"""The guide that maps a unit: its scans, what each test changed, what is known of each register,
the user's comments, and what is stored of them."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from typing import Any, Final

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.translation import async_get_translations
from homeassistant.util import dt as dt_util
from nilan_connect import (
    MODELS,
    CannotConnectError,
    Client,
    NotConnectedError,
    Point,
    RawAddress,
    RegisterChange,
    Snapshot,
    difference,
    model_points,
)

from .const import DOMAIN, MAPPING_LIMIT, PROGRESS_EVERY, REGISTER_FIELDS, STEPS_KEPT, VALUES_PER_PAGE
from .data import NilanConfigEntry
from .mapping import Mappings, mapping, step

_LOGGER = logging.getLogger(__name__)

CONF_FITTED: Final = "fitted"
"""The extra equipment the user says is fitted to the unit, if any."""

CONF_SUGGESTION: Final = "suggestion"
"""The kind of test the user chose from the suggestions, or their own."""

CONF_TITLE: Final = "title"
"""What the user tested, in one short line."""

CONF_MORE: Final = "more"
"""The user's comments on the changed registers beyond those given a field each, a line each."""

OWN_TEST: Final = "own"
"""The suggestion of a test of the user's own."""

SUGGESTIONS: Final = ("temperature", "setting", "switch", "mode", "alarm")
"""The tests the guide suggests, by their translation keys."""

LABELS: Final = "mapping_label"
"""The translation key of the words the guide puts into its texts."""

_LINE = re.compile(r"^\s*(?P<space>[\w:]+)\s+(?P<number>\d+)\s*:[^=]*=(?P<comment>.*)$")
"""A line of the comments: "datapoint 205: 0 → 1 = the bypass", the comment after the first "="."""


def _word(word: int | None) -> str:
    return "–" if word is None else str(word)


def change_text(change: RegisterChange) -> str:
    """A change by its register and raw words: "datapoint 79: 0 → 1"."""
    return f"{change.address}: {_word(change.before)} → {_word(change.after)}"


def comment_lines(changes: Iterable[RegisterChange]) -> str:
    """One line for each change, for the user to write its meaning after."""
    return "\n".join(f"{change_text(change)} = " for change in changes)


def parse_comments(text: str, changes: Sequence[RegisterChange]) -> dict[RawAddress, str]:
    """The comment written for each change in `text`, by its address: after the "=" of its line,
    and on the lines after it up to the next change's line, joined by line breaks. A change whose
    line is deleted, or left without text, gives none, as do lines before the first change's line
    and those after a line of a register not among `changes`."""
    changed = {change.address for change in changes}
    written: dict[RawAddress, list[str]] = {}
    current: RawAddress | None = None
    for line in text.splitlines():
        found = _LINE.match(line)
        if found is not None:
            address = RawAddress(found["space"], int(found["number"]))
            current = address if address in changed else None
            line = found["comment"]
        if current is not None and line.strip():
            written.setdefault(current, []).append(line.strip())
    return {address: "\n".join(lines) for address, lines in written.items()}


class Known:
    """What the unit's model says of each register: the points at it, by name."""

    def __init__(self, points: Iterable[Point[Any]], names: Mapping[str, str], unknown: str) -> None:
        self._unknown = unknown
        self._names: dict[RawAddress, list[str]] = {}
        for point in points:
            for access in {access for access in (point.read, point.write) if access is not None}:
                for offset in range(point.registers):
                    found = self._names.setdefault(RawAddress(access.space, access.address + offset), [])
                    name = names.get(str(point.key), str(point.key))
                    if name not in found:
                        found.append(name)

    def name(self, address: RawAddress) -> str | None:
        """The points at `address`, by name; None for one no point is at."""
        found = self._names.get(address)
        return "; ".join(found) if found else None

    def describe(self, address: RawAddress) -> str:
        """The points at `address`, by name, or that it is unknown."""
        return self.name(address) or self._unknown


class MappingGuide:
    """One mapping of a loaded unit, scanned test by test; each scan is stored as soon as it ends."""

    def __init__(self, hass: HomeAssistant, entry: NilanConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._mappings = Mappings(hass, entry.entry_id)
        self.fitted = ""
        self.title = ""
        self.suggestion = OWN_TEST
        self.page = 0
        """The page of values shown."""
        self._task: asyncio.Task[str] | None = None
        self._pending: tuple[Callable[[], Awaitable[str]], str] = (self.first_read, "map_start")
        self._errors: dict[str, str] = {}
        self._started_at = ""
        self._found = Snapshot(dt_util.utcnow(), {}, [])
        """The first full scan; nothing before it."""
        self._words: dict[RawAddress, int] = {}
        self._missing: set[RawAddress] = set()
        """What the scans so far found, each address as the last scan of it found it."""
        self._changes: tuple[RegisterChange, ...] = ()
        self._before = Snapshot(dt_util.utcnow(), {}, [])
        """The read just before the change of the test under way."""
        self._drift: tuple[RegisterChange, ...] = ()
        """What changed by itself between the scan before the test and its read before the change."""
        self._steps = 0
        self._first_seconds = 0.0
        """How long the first scan took."""
        self.on_progress: Callable[[float], None] = lambda _: None
        """Told how far the last scan of every address has come, from 0 to 1."""
        self._known = Known((), {}, "")
        self._labels: dict[str, str] = {}

    # ------------------------------------------------------------------------- what is shown

    @property
    def room_for_steps(self) -> bool:
        """Whether another test would be stored."""
        return self._steps < STEPS_KEPT

    def found_text(self) -> str:
        """What the first scan found, per space: how many registers answered, how many of them
        were not 0, and how many are absent. A gateway may answer 0 where nothing is, so an answer
        alone says little."""
        spaces = sorted({address.space for address in (*self._found.values, *self._found.missing)})
        lines: list[str] = []
        for space in spaces:
            words = [word for address, word in self._found.values.items() if address.space == space]
            absent = sum(1 for address in self._found.missing if address.space == space)
            lines.append("- " + self._label("found_space").replace("{space}", space)
                         .replace("{answered}", str(len(words)))
                         .replace("{nonzero}", str(sum(1 for word in words if word)))
                         .replace("{absent}", str(absent)))
        return "\n".join(lines)

    @property
    def tested(self) -> bool:
        """Whether a test has been scanned."""
        return self._steps > 0

    def result_text(self) -> str:
        """How many registers the last scan changed, or that nothing changed."""
        if not self._changes:
            return self._label("nothing_changed")
        if len(self._changes) == 1:
            return self._label("changed_one")
        return self._label("changed").replace("{count}", str(len(self._changes)))

    def register_fields(self) -> dict[str, RawAddress]:
        """The registers the last scan changed that get a field of their own, by the field's name:
        the register, its raw change, and the points at it."""
        fields: dict[str, RawAddress] = {}
        for change in self._changes[:REGISTER_FIELDS]:
            name = self._known.name(change.address)
            fields[change_text(change) + (f" ({name})" if name else "")] = change.address
        return fields

    @property
    def more_changes(self) -> tuple[RegisterChange, ...]:
        """The changes beyond those given a field each."""
        return self._changes[REGISTER_FIELDS:]

    def pages(self) -> list[list[RawAddress]]:
        """The addresses the scans found a word at, per space, `VALUES_PER_PAGE` a page."""
        by_space: dict[str, list[RawAddress]] = {}
        for address in sorted(self._words):
            by_space.setdefault(address.space, []).append(address)
        return [addresses[at:at + VALUES_PER_PAGE] for addresses in by_space.values()
                for at in range(0, len(addresses), VALUES_PER_PAGE)]

    def page_placeholders(self) -> dict[str, str]:
        """The page of values shown: each address with its last word and what is known of it."""
        pages = self.pages() or [[]]
        # The pages change with each scan: a page past the last shows the last.
        self.page = min(self.page, len(pages) - 1)
        rows = "\n".join(f"- {address}: {self._words[address]} · {self._known.describe(address)}"
                         for address in pages[self.page])
        return {"page": str(self.page + 1), "pages": str(len(pages)), "values": rows or "-"}

    def take_errors(self) -> dict[str, str]:
        """Why the last scan failed, once; empty when it did not."""
        errors, self._errors = self._errors, {}
        return errors

    # ------------------------------------------------------------------------------ reading

    def prepare(self, read: Callable[[], Awaitable[str]], *, on_failure: str) -> None:
        """Make `read` the next scan; when it fails, the guide goes on with `on_failure`, saying why."""
        self._pending = (read, on_failure)

    def reading(self) -> tuple[asyncio.Task[str], bool]:
        """The scan under way, which gives the step to go on with, and whether it was started now,
        from the one prepared, as none was."""
        if self._task is not None:
            return self._task, False
        read, on_failure = self._pending
        self._task = self._hass.async_create_task(self._run(read, on_failure), "nilan_connect mapping scan")
        return self._task, True

    async def finished(self, task: asyncio.Task[str]) -> str:
        """The step the ended scan `task` goes on with; the next scan starts afresh."""
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
        """Scan every address of the unit once, and store the mapping with it."""
        client = self._entry.runtime_data.client
        await self._load_labels(client)
        device = self._device()
        began = self._hass.loop.time()
        found = await client.map_areas(limit=MAPPING_LIMIT)
        self._first_seconds = self._hass.loop.time() - began
        started = dt_util.utcnow()
        self._started_at = started.isoformat()
        await self._mappings.async_start(mapping(
            started_at=started,
            fitted=self.fitted,
            model=client.model.name,
            identity=dict(client.identity),
            device=device,
            areas=client.mapping_areas(limit=MAPPING_LIMIT),
            baseline=found,
            seconds=self._first_seconds,
        ))
        self._found = found
        self._words, self._missing = dict(found.values), set(found.missing)
        self._changes, self._steps = (), 0
        return "map_found"

    async def before_read(self) -> str:
        """Read the registers the first scan found just before the user makes the change, so that
        what drifts by itself in between scans is not taken as the change."""
        before = await self._entry.runtime_data.client.read_mapped(self._found)
        self._drift = difference(self._last(), before)
        self._learn(before)
        self._before = before
        return "map_change"

    async def step_read(self) -> str:
        """Read the registers again after the change, and store what changed since the read just
        before it, as the test the user made, with what had drifted before it."""
        again = await self._entry.runtime_data.client.read_mapped(self._found)
        self._changes = difference(self._before, again)
        self._learn(again)
        suggestion = None if self.suggestion == OWN_TEST else self.suggestion
        made = step(again.taken_at, self.title, suggestion, self._changes)
        made.update({"before_at": self._before.taken_at.isoformat(), "drifted": len(self._drift),
                     "drift": [change.as_plain() for change in self._drift]})
        if not await self._mappings.async_add_step(self._started_at, made):
            return "map_gone_test"
        self._steps += 1
        self.page = 0
        return "map_result"

    async def full_read(self) -> str:
        """Scan every address once more, and store it and what changed since the scans before.

        How far it has come is told to `on_progress` as the share of the first scan's time gone,
        as the library tells no progress of its own; at most 0.95 until it ends.
        """
        began = self._hass.loop.time()
        ticker = self._hass.async_create_background_task(self._tick(began), "nilan_connect mapping progress")
        try:
            again = await self._entry.runtime_data.client.map_areas(limit=MAPPING_LIMIT)
        finally:
            ticker.cancel()
        self.on_progress(1.0)
        self._changes = difference(self._last(), again)
        self._learn(again)
        final = {**step(again.taken_at, "", None, self._changes), "snapshot": again.as_plain(),
                 "seconds": self._hass.loop.time() - began}
        if not await self._mappings.async_finish(self._started_at, final):
            return "map_gone_final"
        return "map_finish"

    async def _tick(self, began: float) -> None:
        while True:
            elapsed = self._hass.loop.time() - began
            self.on_progress(min(0.95, elapsed / self._first_seconds) if self._first_seconds > 0 else 0.95)
            await asyncio.sleep(PROGRESS_EVERY)

    def read_total(self) -> int:
        """How many addresses the prepared scan reads: every address of the areas for a full
        scan, else those the first scan found."""
        read, _ = self._pending
        if read == self.first_read or read == self.full_read:
            return sum(area.count for area in self._entry.runtime_data.client.mapping_areas(limit=MAPPING_LIMIT))
        return len(self._found.values)

    def duration_text(self) -> str:
        """How long the first scan took, in seconds under a minute, else in minutes."""
        seconds = max(1, int(self._first_seconds + 0.5))
        if seconds < 60:
            return self._counted("second", seconds)
        return self._counted("minute", int(self._first_seconds / 60 + 0.5))

    def summary_text(self, scanned: bool) -> str:
        """What the mapping holds: how many tests, and, after the last scan, how many registers
        it changed."""
        tests = self._counted("test", self._steps)
        if not scanned:
            return self._label("done").replace("{tests}", tests)
        changed = self._counted("changed_last", len(self._changes))
        return self._label("done_scanned").replace("{tests}", tests).replace("{changed}", changed)

    def _counted(self, key: str, count: int) -> str:
        """The label of `key` for `count`: `key`_one for 1, else `key` with the count."""
        if count == 1:
            return self._label(f"{key}_one")
        return self._label(key).replace("{count}", str(count))

    async def write_comments(self, given: Mapping[str, Any]) -> bool:
        """Store the user's comments on the last test's changes: from the field of each register
        that has one, and from the lines of the rest. Whether the mapping still takes them."""
        comments = {address: str(given[field]).strip() for field, address in self.register_fields().items()
                    if str(given.get(field) or "").strip()}
        comments.update(parse_comments(str(given.get(CONF_MORE) or ""), self.more_changes))
        if not comments:
            return True
        return await self._mappings.async_annotate(
            self._started_at, self._steps - 1, {str(address): comment for address, comment in comments.items()})

    def _last(self) -> Snapshot:
        """The unit as the scans so far found it: each address as the last scan of it found it."""
        return Snapshot(dt_util.utcnow(), self._words, self._missing)

    def _learn(self, read: Snapshot) -> None:
        for address, word in read.values.items():
            self._words[address] = word
            self._missing.discard(address)
        for address in read.missing:
            self._missing.add(address)
            self._words.pop(address, None)

    # ----------------------------------------------------------------------------- helpers

    async def _load_labels(self, client: Client) -> None:
        """The guide's words and the points' names, in Home Assistant's language."""
        language = self._hass.config.language
        labels = await async_get_translations(self._hass, language, "selector", [DOMAIN])
        prefix = f"component.{DOMAIN}.selector.{LABELS}.options."
        self._labels = {key.removeprefix(prefix): text for key, text in labels.items() if key.startswith(prefix)}
        entities = await async_get_translations(self._hass, language, "entity", [DOMAIN])
        points = [point for model in MODELS if model is client.model for point in model_points(model)]
        self._known = Known(points, _entity_names(entities), self._label("unknown"))

    def _label(self, key: str) -> str:
        return self._labels.get(key, key)

    def _device(self) -> dict[str, str | None]:
        """What Home Assistant's device of the unit says it is."""
        identifier = (DOMAIN, self._entry.runtime_data.name)
        devices = dr.async_entries_for_config_entry(dr.async_get(self._hass), self._entry.entry_id)
        device = next((each for each in devices if identifier in each.identifiers), None)
        if device is None:
            return {"manufacturer": None, "model": None, "sw_version": None}
        return {"manufacturer": device.manufacturer, "model": device.model, "sw_version": device.sw_version}


def _entity_names(translations: Mapping[str, str]) -> dict[str, str]:
    """Each point's entity name, by its key: "component.<domain>.entity.<platform>.<key>.name"."""
    names: dict[str, str] = {}
    for key, text in translations.items():
        parts = key.split(".")
        if len(parts) == 6 and parts[5] == "name":
            names.setdefault(parts[4], text)
    return names

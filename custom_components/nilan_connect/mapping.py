"""The mappings of a unit, kept so that its diagnostics can show them: what the user said about it,
its identity, the first full read and what changed at each step after it."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from nilan_connect import Area, RegisterChange, Snapshot

from .const import DOMAIN, MAPPINGS_KEPT, STEPS_KEPT

STORAGE_VERSION = 1
"""The version of the stored mappings' shape."""

type Plain = dict[str, Any]


def _store(hass: HomeAssistant, entry_id: str) -> Store[Plain]:
    return Store[Plain](hass, STORAGE_VERSION, f"{DOMAIN}.mappings.{entry_id}")


async def load_mappings(hass: HomeAssistant, entry_id: str) -> list[Plain]:
    """The entry's mappings as stored, the oldest first; none before the first is stored."""
    stored = await _store(hass, entry_id).async_load()
    return list(stored["mappings"]) if stored is not None else []


async def remove_mappings(hass: HomeAssistant, entry_id: str) -> None:
    """Remove the entry's stored mappings."""
    await _store(hass, entry_id).async_remove()


def mapping(
    *,
    started_at: datetime,
    unit_description: str,
    model: str,
    identity: dict[str, Any],
    device: dict[str, str | None],
    areas: Sequence[Area],
    baseline: Snapshot,
) -> Plain:
    """A new mapping, with its first full read and no steps yet."""
    return {
        "started_at": started_at.isoformat(),
        "unit_description": unit_description,
        "model": model,
        "identity": identity,
        "device": device,
        "areas": [{"table": area.table, "start": area.start, "count": area.count} for area in areas],
        "baseline": baseline.as_plain(),
        "steps": [],
    }


def step(at: datetime, note: str, changes: Sequence[RegisterChange]) -> Plain:
    """One step of a mapping: what the user changed and what the read after it changed."""
    return {"at": at.isoformat(), "note": note, "changes": [change.as_plain() for change in changes]}


class Mappings:
    """Adds to the entry's stored mappings, each time saved at once, so that a guide closed part
    way keeps what it found until then."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._store = _store(hass, entry_id)

    async def async_start(self, found: Plain) -> None:
        """Store `found` as the newest mapping; the oldest gives way beyond the latest kept."""
        kept = [*await load_mappings(self._hass, self._entry_id), found][-MAPPINGS_KEPT:]
        await self._store.async_save({"mappings": kept})

    async def async_add_step(self, started_at: str, added: Plain) -> bool:
        """Add `added` to the mapping that started at `started_at`, unless it has the most steps
        kept; whether it was added. A mapping that gave way to newer ones takes none."""
        return await self._update(started_at, lambda found: _append(found["steps"], added))

    async def async_finish(self, started_at: str, final: Plain) -> None:
        """Store what the full read at the end of the mapping that started at `started_at` found."""

        def set_final(found: Plain) -> bool:
            found["final"] = final
            return True
        await self._update(started_at, set_final)

    async def _update(self, started_at: str, change: Callable[[Plain], bool]) -> bool:
        kept = await load_mappings(self._hass, self._entry_id)
        found = next((each for each in kept if each["started_at"] == started_at), None)
        if found is None or not change(found):
            return False
        await self._store.async_save({"mappings": kept})
        return True


def _append(steps: list[Plain], added: Plain) -> bool:
    if len(steps) >= STEPS_KEPT:
        return False
    steps.append(added)
    return True

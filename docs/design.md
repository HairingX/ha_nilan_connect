# Design

How the integration is built, and the facts each choice rests on. Home Assistant facts are from
its 2026.11.0 source, the release the tests run; the unit's from Nilan's CTS400 Modbus manual, as
modelled by `nilan_connect`.

## A client, not a coordinator

The library's client plans every read itself: each point has a poll rate, only what is subscribed
to is read, and a poll with nothing due sends nothing. The integration therefore owns no update
interval and no loop. It runs the client's `run()` as one background task per config entry, which
polls whenever the client has something due; a new subscription, a refresh or a write wakes it at
once.

- The task is made with `ConfigEntry.async_create_background_task`, which Home Assistant cancels
  when the entry unloads. That cancellation runs after `async_unload_entry` returns, so unloading
  cancels the task itself and awaits it before disconnecting: no read runs against a closing
  connection.
- A poll that raises is logged by the client, and polling goes on; the client reports a gateway
  that does not answer through its status, not by raising. A disconnect turns that status too, so
  the integration logs nothing on it: an unload or a reload says nothing of the gateway answering.
- With polling disabled in the entry's system options, the client reads nothing on its schedule:
  only what is asked for, by `homeassistant.update_entity`, and what a write asks to be read back.
  The task still runs, as it makes that read-back. Changing it reloads the entry.

## A unit's name, and its gateway's id

Every unique id is the unit's name, an underscore, and the point's key: `Nilan_temp_supply`. The
name is the user's; `Nilan` unless changed, and different names for several units. It never
changes after setup, so a unit that is replaced keeps its entities, and the device is identified
by it too.

The gateway's id is what it answers discovery with. It is the entry's unique id, which tells two
entries of the same gateway apart, and it lets the client find the gateway again when its address
changes. A gateway set up by its address is asked for its id by a discovery sent to that address,
in the config flow and again at every setup until it answers.

| At setup | Home Assistant is told | Effect |
|---|---|---|
| Nothing answers (`CannotConnectError`) | `ConfigEntryNotReady` | retried later |
| The gateway refuses the email (`AuthenticationError`) | `ConfigEntryAuthFailed` | the user is asked for the email |
| The controller is not supported (`UnsupportedDeviceError`) | `ConfigEntryError` | not retried |

The gateway compares the email exactly. The config flow tries it as entered, then in lower case,
and keeps the one the gateway takes.

### Entries of version 1

Version 1 kept the name as `device_id`, the email as `authorized_email`, and the address as
`device_ip` and `device_port` only when it was entered by hand. Without an address, the entry was
found by discovery, so its name was the gateway's id. `async_migrate_entry` keeps the name, the
email and the address, and takes the name as the gateway's id for an entry without an address.

### Entries of minor version 1

Minor version 1 had the option `show_inferred`: whether a point placed only by the order of its
manual's registers got an entity. The level replaces it. `async_migrate_entry` gives an entry that
showed them the Test level, which shows them too, and any other the Documented, which does not, so
an existing installation keeps its entities.

## The level of values

The library chooses which of a model's points a unit has by the level the client is made with
(`nilan_connect.Level`), stored by its text as the entry's one option:

| Level | Points |
|---|---|
| `verified` | `Certainty.VERIFIED` |
| `documented`, the default | `VERIFIED` and `REPORTED` |
| `test` | every certainty, and each candidate in place of the point it replaces |

An entity is created for a point the client has, so the level alone decides the entities;
changing it reloads the entry, and the entities of points the new level leaves out are removed as
lost. A candidate that replaces a point of the same key keeps that entity and its id: only the
register behind it changes.

- **Certainty attribute.** Every entity has the state attribute `certainty`: `test-candidate` for a
  candidate, otherwise its point's `Certainty`, `verified`, `reported` or `inferred`. An entity
  that shows several points, such as the thermostat or the efficiency, has the least certain of
  them, in that order. It is translated per entity, as Home Assistant translates a state attribute
  by the entity's translation key, and not recorded, as it changes only with a reload.
- **Repairs.** At `test`, a unit with a point under test - a candidate, or an inferred point -
  raises the issue `testing_points_<entry id>`, not fixable, of severity warning (the lowest
  Home Assistant has), asking the user to report whether the values match the unit's panel, with
  the test report form as its link. It is removed when the entry unloads, which a change of level
  does too, and not raised at another level or for a unit with nothing under test.
- **Diagnostics.** The library's `level`, `certainty` and `candidates` are lifted out of `gateway`:
  `level`, `certainty` per point, and `test`, which lists each candidate used with its value,
  certainty and the key it replaces, and each inferred point used with its value.

## Entities

Each platform describes its entities once per point, and creates one where the unit has that
point at the entry's level. A CTS400 has every entity it had with version 1 of this integration,
on the same platform, with the same unique id, disabled or hidden by default as it was: a test
holds the whole list, on an entry migrated from minor version 1.

An entity subscribes to its keys and to the client's `CONNECTED` status, and sets its `_attr_`
values in `_show` on every change. It sets them in its constructor too: Home Assistant reads
capability attributes such as a thermostat's `hvac_modes` when it adds the entity, before
`async_added_to_hass`.

An entity shows a value whose quality has something to show (`Quality.shows_a_value`):

| Quality of the value | The entity |
|---|---|
| `GOOD` | shows it |
| `NO_DATA` | is unknown |
| `STALE` | shows the last good value |
| `OFFLINE`, `MISSING`, or the gateway counts as not answering | is unavailable |

The client's `CONNECTED` status turns false only once the gateway has left a read unanswered and
then the next one too, as the library makes the client for every Nilan model: one missed read
leaves the entities their last values, as `STALE`, and a gateway that stays silent makes them
unavailable.

- Device classes follow Home Assistant's: a fan level or a fan preset has none; a dead band,
  a difference of temperatures, is `temperature_delta` (`number/const.py`).
- An alarm code and its info are numbers without an order, so they have no state class and no
  long-term statistics.
- The heat recovery efficiency is the supply side's temperature ratio,
  (supply - outdoor) / (extract - outdoor) x 100: EN 308's temperature ratio, as Czech Technical
  University's course "Ventilation 7. Air to Air Heat Recovery" gives it (page 2), and as Svensk
  Ventilation's guidelines on temperature efficiency refer to EN 308:1997 section 5.5. It is
  worked out again whenever one of the three temperatures changes, and is unknown while the
  extract and outdoor air are equally warm. A unit that reads its supply air only after the
  heater, such as a CTS602 Light, has none: the heater's warmth would count as recovered.

### Points the library renames

A unique id names what its entity shows, so a point whose meaning or platform changes gets a new
entity, and the old one is removed with the other entities of points the unit no longer has.
Where the library gives a model's point a new key for the same register and the same meaning, on
the same platform, the entity keeps its entity id and its history: at setup, before the platforms
create their entities, `er.async_migrate_entries` gives it the new key's unique id, on the models
that renamed it. Where the new key's entity exists already, the old one is removed instead.

| Models | Platform | Old key | New key |
|---|---|---|---|
| Optima 301, 312, 314 | sensor | `temp_before_condenser` | `temp_before_evaporator` |
| Optima 301, 312 | sensor | `temp_room` | `temp_room_panel` |

### The thermostat

- The unit is `AUTO` while it runs and `OFF` while it is stopped; its fan level is the fan mode,
  and the room temperature it aims for the target.
- The temperature shown is the extract air's, the air taken from the rooms.
- The action is, in order: off, de-icing, drying while high humidity is active, cooling while the
  bypass is open, and otherwise ventilating. `HVACAction` has no bypass (`climate/const.py`); an
  open bypass lets outdoor air past the heat exchanger, which the rooms feel as cooling.
- Every point it shows or writes is an entity of its own too.

## Writes

The client sends writes in order and folds a queued setting into a newer one, so every platform
has `PARALLEL_UPDATES = 0` and passes actions straight on. A value outside the manual's limits is
refused before it is sent; a write the unit does not take is an error the user reads.

A number, and the thermostat's target temperature, offer the values their point can be written
with, as the library's `Point.write_range()` gives them: the manual's limits, and its step, or else
what one step of the register is worth. A setting the manual gives no lowest and highest value
for has no number, rather than one offering every value its register can carry.

## Dependencies

- `manifest.json` pins the library with `==`, as the manifest documentation asks.
- Home Assistant installs requirements under its package constraints
  (`homeassistant/package_constraints.txt`), which pin `pymodbus`, a dependency of the library;
  the tests run that version.
- Nilan's brand images ship in `brand/`, which Home Assistant serves for custom integrations: the
  ones Home Assistant's brands repository has for this domain (`custom_integrations/nilan_connect`).

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
an existing installation keeps its entities. Only a model with such points was changed by the
option: on any other, Test would add candidates and a Repairs issue the user never asked for. The
migration does not connect to the unit, so it takes the model from the entry's device, registered
under the model's name, and the library's `model_points` says whether that model has an inferred
point.

## The level of values

The library chooses which of a model's points a unit has by the level the client is made with
(`nilan_connect.Level`), stored by its text as the entry's one option, chosen under Settings in
the options:

| Level | Points |
|---|---|
| `verified` | `Certainty.VERIFIED` |
| `documented`, the default | `VERIFIED` and `REPORTED` |
| `test` | every certainty, and each candidate in place of the point it replaces |

An entity is created for a point the client has, so the level alone decides the entities;
changing it reloads the entry. An entity the new level leaves out stays in the entity registry,
unavailable, with the name, area and settings the user gave it, for a level that has it again;
only an entity of a point the unit has at no level - not among its model's keys, or found missing
by its scan - is removed as lost. A candidate that replaces a point of the same key keeps that
entity and its id: only the register behind it changes. Verified is offered only for a model
with a verified point: on any other it would leave no entity.

- **Certainty attribute.** Every entity has the state attribute `certainty`: `test-candidate` for a
  candidate, otherwise its point's `Certainty`, `verified`, `reported` or `inferred`. An entity
  that shows several points, such as the thermostat or the efficiency, has the least certain of
  them, in that order. It is translated per entity, as Home Assistant translates a state attribute
  by the entity's translation key, and not recorded, as it changes only with a reload.
- **Repairs.** At `test`, a unit with a point under test - a candidate, or an inferred point -
  raises the issue `testing_points_<entry id>`, not fixable, of severity warning (the lowest
  Home Assistant has), asking the user to report whether the values match the unit's panel, with
  the test report form as its link. A setup at another level, or of a unit with nothing under
  test, removes it. Unloading does not: removing it there would forget that the user ignored it,
  and Home Assistant removes an entry's issues with the entry.
- **Diagnostics.** The library's `level`, `writes`, `certainty` and `candidates` are lifted out
  of `gateway`: `level`, `writes` with the latest writes of each key and how each ended,
  `certainty` per point, and `test`, which lists each candidate used with its value, certainty
  and the key it replaces, and each inferred point used with its value. Each value also states
  its certainty, so one entry shows whether a point was read, how it was decoded and how sure
  that decoding is.

## Mapping a unit

The options open on a menu: **Settings**, the level, and **Map the unit**, a guide that finds out
with the user what the unit's registers mean, whether the model knows them or not. The options
flow is Home Assistant's place for how an integration behaves, and shows menus, forms and
progress between steps; a button is one action without steps, Repairs is for faults the user
must fix, and the debug log only logs.

- **Steps.** `map_start` shows the model the unit was recognised as and asks, optionally, what
  extra equipment is fitted; then `map_read` shows the progress of the first scan,
  `Client.map_areas(limit=MAPPING_LIMIT)`, and `map_found` says per space how many registers
  answered, how many of those were not 0, and how many are absent - a gateway may answer 0 where
  nothing is, so an answer alone says little - and that the scan is saved, with **Write what the
  panel shows (easiest)** (`map_reading`), **Make a test** (`map_test`) and **Finish and save**
  (`map_send`): nothing is sent anywhere. A
  test is chosen from the suggestions, translated under the selector `mapping_suggestion`, or the
  user's own ("Other"), with an optional line saying what the user changes, required only for
  Other; a test is named by that line, or else by the short name of the kind chosen (`short_<kind>`
  under `mapping_label`). The test's two screens are numbered as steps 1 and 2 of 2, and the
  first says not to make the change yet: its **Start test** button, a step's `submit` translation,
  starts `map_read`, which reads again only what the first scan found, `Client.read_mapped`, as
  the unit is just before the change. `map_change` then asks the user to make the change, and its
  **Scan** reads them once more: a test's changes are between these two reads, so what drifts by
  itself between tests - a real unit's temperatures and counters, in the 57 minutes between a
  first scan and a first test - does not hide the change; what drifted before the test is stored
  beside it. `map_result` gives each changed
  register, up to `REGISTER_FIELDS` (20), a field of its own, and the rest one multiline field a
  line each, parsed back by the address at the start of each line; a register is shown with its
  space in Home Assistant's language (`space_<kind>`, and `spaces_<kind>` in what `map_found`
  counts, under `mapping_label`), and parsed back by either word, but stored by the protocol's; a line of its own belongs to
  the register above it. `map_tested` offers writing down what the panel shows, the next test, `map_values` - the latest state, the
  first scan with every scan after it, `VALUES_PER_PAGE` (50) registers of one space a page, read
  from what the guide holds, from the first page again after each scan - and `map_send`. After a
  test, finishing scans every address once more, with the same limit, as a test can switch on
  something whose registers answer only then, and no register may be missed; finished straight
  after the first scan, it needs none. Before it, the guide says how long the first scan took,
  measured then and stored: "a moment" under `ESTIMATED_FROM` (2 s), as a real CTS400's took
  0.03 s, in seconds under a minute and in minutes above. During it, from 2 s on, the
  progress bar is the share of the first scan's time gone; a quicker scan shows none, as it ends
  before a bar would say anything. The bar is at most 0.95 until the scan ends, as the library
  tells no progress of its own, and the progress text names how many addresses are read;
  Home Assistant does not change a progress step's text while it runs. After it, the closing
  message says how many tests and values from the panel were saved and how many registers the
  last scan changed.
- **Values from the panel.** `map_reading` is for an owner who knows nothing of registers: one
  value at a time, what it is - chosen from the suggestions, translated under the selector
  `mapping_reading`, or the user's own words, such as "T7" or "I set level 4" - and the value as
  the panel shows it, which may be empty. **Save** reads what the first scan found at once,
  `Client.read_mapped`, so that the read is seconds from the user looking at the panel; a unit's
  values change all the time, and several values written before one read would be read minutes
  after they were seen. Nothing is matched or checked on the user's side: the panel may show a
  value with an offset or worked out from several registers, and what it means is found from the
  stored reads afterwards. The next form says what was saved last, and how many so far; both
  fields left empty end it, back to `map_tested`, or to `map_found` while nothing is saved. A
  read that fails offers the value again. It changes nothing on the unit, so finishing needs no
  last scan for it.
- **The unit named.** Every step's description names the unit mapped by its manufacturer and
  model, and says to make changes on it, not on other devices in the house: a change made on
  another integration's device shows nothing here. The suggestions are things a ventilation
  unit has, a setting set to a value it never normally has, so that the change stands out.
- **Field names.** A field Home Assistant has no translation for is labelled by its name, so a
  register's field is named by the register and its raw change, "datapoint 79: 0 → 1", with the
  name of the entity of a point at it in Home Assistant's language. Values are shown raw: a
  register's meaning is what the mapping is to find.
- **Words in lists.** What the guide writes into a placeholder - unknown, nothing changed, how
  many changed, one changed, what each space holds - is taken from the selector translation
  `mapping_label`, loaded with `async_get_translations` in Home Assistant's language. An
  integration's translations have no category for free strings it composes itself: the step,
  error and abort texts are fixed per key, and a selector's options are the one place whose keys an
  integration names and whose texts it can load by key. A flow is not told the language of the
  user's browser, so Home Assistant's own language is used.
- **Failures.** A scan that fails returns to the form it came from, saying why. A progress step is
  shown at least once, as a scan that fails at once ends as it starts. Every step ends the guide
  with `not_loaded` when the entry is no longer loaded. A mapping that gave way to three newer
  ones ends the guide saying what was lost: the last test (`mapping_gone_test`), the last value
  from the panel (`mapping_gone_reading`), the comments on
  it (`mapping_gone_comments`), or the last scan (`mapping_gone_final`). Nothing changes the entry's
  options, so the entry does not reload.
- **What is read.** The library reads, for each of the gateway's spaces, every address from 0 up
  to `MAPPING_LIMIT`, 300, or up to the highest address the model's points read or write; the
  owner chose the limit from the measured cost of the first scan. Nothing is read for a mapping
  unless the guide scans, only reads, through the client's own requests and between its polls;
  busy or no answer stops a scan with `CannotConnectError`. While the first and the last scan of
  every address run, as a polling pass of their own, the unit's values are not read; they keep
  their last value, and as the gateway answers, nothing becomes unavailable.
- **Storage.** One `Store` per entry, `nilan_connect.mappings.<entry id>`, holds the latest
  `MAPPINGS_KEPT` (3) mappings, the oldest giving way, each with up to `STEPS_KEPT` (30) tests:
  when it started, the extra equipment the user named (`fitted`), the model, the handshake's identity, the
  device's manufacturer, model and software version, the areas, the first scan in full with how
  many seconds it took, per test its time and the time of its read before the change, name,
  suggestion and changes with the user's comment on each, and what drifted before it (`drifted`
  and `drift`), up to `READINGS_KEPT` (100) values from the panel, each as written with every
  register its read found, in full, and the last full scan in full with what it changed and how long it took. Each scan is stored as soon as it ends, under a lock per entry, so
  two guides of one unit never store over each other; removing the entry removes the store under
  the same lock, and then the lock, and a guide closed during a scan, which
  cancels it, keeps the tests made; closed between a test's two reads, it stores no test. The
  drift before a test, and the last full scan's changes, are against what the scans before found,
  each address as the last scan of it found it. `async_remove_entry` removes the store.
- **Diagnostics.** `mappings` is what the store holds, read from it: the diagnostics never read
  the unit for it. The identity holds the controller's type and model numbers, not a serial
  number; the email, the gateway's address and its id are not in it.
- **Reporting.** The issue form `mapping.yml` asks for the unit as the user knows it, the
  integration's version and the diagnostics.

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

- `manifest.json` pins the library with `==`, as the manifest documentation asks, and
  `modbus_event_connect` too, though the library requires it: Home Assistant installs a
  requirement only while the version installed does not meet it, so an installation that already
  has `nilan_connect` keeps the `modbus_event_connect` it has unless the manifest names the one the
  integration needs - for the diagnostics' `writes`, 0.10.1.
- Home Assistant installs requirements under its package constraints
  (`homeassistant/package_constraints.txt`), which pin `pymodbus`, a dependency of the library;
  the tests run that version.
- Nilan's brand images ship in `brand/`, which Home Assistant serves for custom integrations: the
  ones Home Assistant's brands repository has for this domain (`custom_integrations/nilan_connect`).

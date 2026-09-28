# Design

How the integration is built, and the facts each choice rests on. Home Assistant facts are from
its 2026.9.3 source, the release the tests run; the unit's from Nilan's CTS400 Modbus manual, as
modelled by `nilan_connect`.

## A client, not a coordinator

The library's client plans every read itself: each point has a poll rate, only what is subscribed
to is read, and a poll with nothing due sends nothing. The integration therefore owns no update
interval. It runs one background task per config entry that calls `client.poll()` and sleeps
until the client has something due, at most `POLL_TICK`, as a new subscription or a write's
read-back can make a point due while it sleeps.

- The task is made with `ConfigEntry.async_create_background_task`, which Home Assistant cancels
  when the entry unloads. That cancellation runs after `async_unload_entry` returns, so unloading
  cancels the task itself and awaits it before disconnecting: no read runs against a closing
  connection.
- A poll that raises is logged and the loop goes on; the client reports a gateway that does not
  answer through its status, not by raising.

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

## Entities

Each platform describes its entities once per point, and creates one where the unit has that
point. A CTS400 has every entity it had with version 1 of this integration, on the same platform,
with the same unique id, disabled or hidden by default as it was: a test holds the whole list.

An entity subscribes to its keys and to the client's `CONNECTED` status, and sets its `_attr_`
values in `_show` on every change. It sets them in its constructor too: Home Assistant reads
capability attributes such as a thermostat's `hvac_modes` when it adds the entity, before
`async_added_to_hass`.

| Quality of the value | The entity |
|---|---|
| `GOOD` | shows it |
| `NO_DATA` | is unknown |
| `STALE` | shows the last good value |
| `OFFLINE`, `MISSING`, or the gateway does not answer | is unavailable |

- Device classes follow Home Assistant's: a fan level or a fan preset has none; a dead band,
  a difference of temperatures, is `temperature_delta` (`number/const.py`).
- An alarm code and its info are numbers without an order, so they have no state class and no
  long-term statistics.
- The heat recovery efficiency is the supply side's temperature ratio,
  (supply - outdoor) / (extract - outdoor) x 100: EN 308's temperature ratio, as Czech Technical
  University's course "Ventilation 7. Air to Air Heat Recovery" gives it (page 2), and as Svensk
  Ventilation's guidelines on temperature efficiency refer to EN 308:1997 section 5.5. It is
  worked out again whenever one of the three temperatures changes, and is unknown while the
  extract and outdoor air are equally warm.

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

## Dependencies

- `manifest.json` pins the library with `==`, as the manifest documentation asks.
- Home Assistant installs requirements under its package constraints
  (`homeassistant/package_constraints.txt`), which pin `pymodbus`, a dependency of the library;
  the tests run that version.
- Nilan's brand images ship in `brand/`, which Home Assistant serves for custom integrations: the
  ones Home Assistant's brands repository has for this domain (`custom_integrations/nilan_connect`).

# Nilan Connect

A Home Assistant integration for Nilan and Genvex ventilation units, through the Nilan gateway on
your own network - no cloud.

## Supported units

| Controller | Tested on a real unit |
|---|---|
| Nilan CTS400 | yes |
| Genvex Optima 270 | its addresses were read on a unit; not tested with this integration |
| Nilan CTS602, including Geo, and CTS602 Light | no |
| Genvex Optima 250, 251, 260, 301, 312, 314 | no |

Every unit gets an entity for each value it has: temperatures, humidity, fans, heating, hot water,
central heating and heat pump, its alarms and operating states - named, in English and Danish - and
its settings. The thermostat shows the unit's fan level and target temperature, and turns it on
and off where the unit's on/off setting is known.

### Help us support more of your unit

Most of these units have no official register list for the Nilan gateway, so what the
integration shows comes from manuals and from owners who checked their own unit. You can help:

- **A value or setting is missing, or looks wrong?** Run [Map the unit](#map-the-unit) on your
  unit. The easiest: write down what its panel or app shows, one value at a time, such as
  "Outdoor air 8". Or change one thing at a time on the panel, and the guide shows which
  registers changed. Send us the result through a
  [mapping report](https://github.com/HairingX/ha_nilan_connect/issues/new?template=mapping.yml),
  and we can add the value, or confirm one we have only from a manual. It only reads; nothing is
  written to your unit.
- **Your unit is not in the list?** Open an
  [issue](https://github.com/HairingX/ha_nilan_connect/issues/new) with its model name. The
  integration cannot be set up on a unit it does not recognise yet; mapping such units is the
  next step, and owners who will map theirs help us support them.

## Level of values

How certain a value must be to get an entity is your choice: Settings > Devices & services >
Nilan Connect > Configure > *Settings* > *Level*.

| Level | Entities |
|---|---|
| **Verified**, offered where the model has such values | only values read on a unit of the same model |
| **Documented** (the default) | also values from the manufacturer's documentation |
| **Test** | every value: also those inferred from the order of Nilan's manual, and values tried in place of others, or new, from a source not yet confirmed on a unit |

Test values may be wrong, and changing one may change a different setting. While a unit is on
Test and uses such values, Settings > Repairs asks you to report whether they match your unit's
panel, with a [test report](https://github.com/HairingX/ha_nilan_connect/issues/new?template=test-report.yml):
attach the diagnostics, which list each value under test. A value confirmed this way is shown
without Test in a later release. The message goes when you choose another level.

Every entity has the attribute *Certainty*: *Verified*, *Documented*, *Inferred* or *Test* (in the
state attributes, `verified`, `reported`, `inferred` or `test-candidate`), the least certain of the
values it shows. An entry of a unit with estimated entities (a CTS602 or a CTS602 Light) that
showed them before levels existed is on Test; any other is on Documented, so no entity comes or
goes with the change. An entity that a level leaves out is kept, unavailable, with its name and
settings, for when you choose a level that has it again.

## Map the unit

Help find out what your unit's registers mean, those we know and those we do not: Settings >
Devices & services > Nilan Connect > Configure > **Map the unit**. It is offered on every unit.

1. The guide shows the model it recognised the unit as, and asks whether any extra equipment is
   fitted that we should know about, such as a heat pump, a preheater or a CO2 sensor; leave it
   empty if there is none. **Scan** then reads every address of the unit once, from 0 to 299,
   and the guide says per space how many answered, how many of those were not 0 - a gateway may
   answer 0 where nothing is - and how many are absent. That takes from seconds to a few minutes
   on a slow gateway. The scan is saved.
2. **Write what the panel shows (easiest)**, **Make a test**, or **Finish and save**.

   **Write what the panel shows** needs no knowledge of registers. Look at the unit's own panel
   or app, and write one thing it shows right now, or what you just did: choose what it is, such
   as the outdoor air or the fan level, or write your own words, such as "T7" or "I set level 4",
   and the value as the panel shows it, such as 8 or 21.5. **Save** reads the unit at once, as
   its values change all the time, and the screen is ready for the next value; leave both fields
   empty and press **Save** to stop. The guide checks nothing: we work out afterwards where each
   value is, also where the panel shows it with an offset or works it out. Up to 100 values are
   kept per mapping.

   A test has two numbered screens. Every
   screen names the unit mapped, and the first screen and the test's say to make changes on this
   unit, its panel or its app, not on other devices in the house.
   - **Step 1 of 2:** choose what you will test - the fan level (e.g. from level 1 to 3), a
     setting set to an unusual value (e.g. a target temperature of 17 °C), something on and off
     (e.g. the bypass or boost), a temperature sensor, an alarm (e.g. a filter reset), or other -
     and, if you like, say what you change, such as "level 1 → 3"; for Other that is required.
     Do not make the change yet: **Start test** reads the registers that answered, as they are
     now. The test is named by what you said you change, or else by the kind of test.
   - **Step 2 of 2:** make the change on the unit, wait if the test needs it, and press
     **Scan**: the guide reads them once more, and shows only what changed between the two
     reads, so values that drift by themselves in the meantime, such as temperatures, do not hide
     the change. Each read takes a few seconds.
3. Each register that changed gets a field, named by the register and its raw change, such as
   "datapoint 79: 0 → 1" - in Danish "datapunkt 79" - with the name of the value we know at it,
   if any. Write what it is; "?" is fine, and an empty field is no comment. Beyond 20 registers,
   the rest share one field, a line each, where a line of its own belongs to the register above
   it. **Save comments** stores them. If nothing changed, the guide says so: the function may be
   switched off by another setting.
4. **Write what the panel shows**, **Make a test**, **Show all values** - every register's latest
   value, page by page, read from what the scans found - or **Finish and save**. After a test,
   finishing scans every address once more, so that no register is missed that a function
   switched on during the tests brought; the guide says how long the first scan took - "a
   moment" under 2 seconds - shows the scan's progress where it takes that long, and then how
   many tests and values from the panel were saved and how many registers the last scan changed.
5. The mapping is saved with the unit; nothing is sent anywhere. To send it to us, download the
   diagnostics and attach the file to a
   [mapping report](https://github.com/HairingX/ha_nilan_connect/issues/new?template=mapping.yml).

Nothing is written to the unit, and nothing is read for a mapping unless the guide scans. While
the first and the last scan of every address run - seconds to a few minutes - the unit's values
are not updated; they keep their last value, and nothing becomes unavailable. A scan stops at
once when the gateway is busy or does not answer, and the guide says so. Closing the guide
during a scan stops it; the tests already made are kept. The latest three mappings of a unit are
kept, each with up to 30 tests, and are deleted with the integration. The diagnostics show them
under `mappings`: the extra equipment you named, the unit's identity and model, the first scan in
full, per test its name, the suggestion it followed, what changed and your comments, and how
many registers drifted by themselves before it, and each value from the panel as you wrote it,
with every register read as you saved it; never
the email, the gateway's address or its id.

## Installation

Through HACS, as a custom repository.

## Setup

Settings > Devices & services > Add integration > Nilan Connect. Either let it find the gateway on
the network, or enter the gateway's address.

- **Name**: every entity id of the unit starts with it, and it stays when the unit is replaced.
  Give several units different names, such as Upstairs.
- **Email**: the email of the account the gateway is paired with in Nilan's app.
- **Address**: when you enter it, give the gateway a fixed address in your router. A gateway whose
  id is known is found again on the network when its address changes.

The address, port and email can be changed later: the entry's menu > Reconfigure.

## Entities

Temperatures, humidity, CO2 and VOC, fan speeds and level, filter status and timers, alarm status
and codes, bypass, de-icing and winter mode; a thermostat that turns the unit on and off, sets its
fan level and the room temperature it aims for; the settings Nilan's manual lists, as numbers; and
buttons to reset the alarm and the filter timer. The heat recovery efficiency is worked out from
the outdoor, supply and extract air temperatures.

## How data is updated

The library reads each value at its own rate, and only what an enabled entity shows; a setting
is read again after it is written. One read the gateway misses leaves the entities their last
values; if it leaves the next one unanswered too, they are unavailable until it answers again.

## Known limitations

- The alarm code entities read the registers Nilan's manual names. On a CTS400 with its filter
  alarm active they read 0; what they show for other alarms is not known yet.

## Troubleshooting

- **The email is refused**: use the email of the app account the gateway is paired with. It is
  tried as entered and in lower case.
- **No gateway is found**: discovery is a broadcast on the local network. Enter the gateway's
  address instead.
- The diagnostics, downloaded from the integration's entry, hold every value without the email or
  where the gateway is, the level, how certain each value is, the latest writes, under
  `test`, each value under test with what it replaces, and under `mappings` the unit's mappings.

### Reporting a problem

A report is answered fastest with the log and the diagnostics from the time it happened:

1. Settings > Devices & services > Nilan Connect > the three dots > **Enable debug logging**.
2. Leave it on until the problem has happened, for a problem that comes and goes a few hours.
3. The three dots > **Disable debug logging**: Home Assistant downloads the log.
4. The three dots > **Download diagnostics**.

Without debug logging, the warnings alone say when the gateway stopped answering and answered
again, why each session with it began, and when it answered with only zeros and how long that
lasted: Settings > System > Logs. Neither the log nor the diagnostics hold the email or the
gateway's id; the log can hold its address, which you may remove before sharing it.

The diagnostics hold the integration's and the installed libraries' versions, how the gateway
has answered - requests, resends, response times, silences, refused sessions, answers of only
zeros and how each ended, and whether the client is waiting before it tries the gateway again -
every value with its quality, its raw registers, how certain it is, when it was read and how
many reads of it have failed in a row, and, under `writes`, the latest five writes of each
setting: the value and registers sent, when, how many times, how it ended, and the value the
unit answered the next read with.

## Removal

Settings > Devices & services > Nilan Connect > the three dots > Delete; then remove it in HACS.

## License

MIT - see [LICENSE](LICENSE).

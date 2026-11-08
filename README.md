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

Some entities of units other than the CTS400 have an address estimated from Nilan's manual, never
checked on a real unit. They are hidden unless you choose to see them: Settings > Devices &
services > Nilan Connect > Configure > *Show estimated, untested entities*. They may show wrong
values, and changing one may change a different setting; please report what your unit shows in an
issue.

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
values; once it has not answered for 10 seconds, they are unavailable until it answers again.

## Known limitations

- The alarm code entities read the registers Nilan's manual names. On a CTS400 with its filter
  alarm active they read 0; what they show for other alarms is not known yet.

## Troubleshooting

- **The email is refused**: use the email of the app account the gateway is paired with. It is
  tried as entered and in lower case.
- **No gateway is found**: discovery is a broadcast on the local network. Enter the gateway's
  address instead.
- The diagnostics, downloaded from the integration's entry, hold every value without the email or
  where the gateway is.

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

The diagnostics hold the installed library versions, how the gateway has answered - requests,
resends, response times, silences, refused sessions, answers of only zeros and how each ended,
and whether the client is waiting before it tries the gateway again - and every value with its
quality, when it was read and how many reads of it have failed in a row.

## Removal

Settings > Devices & services > Nilan Connect > the three dots > Delete; then remove it in HACS.

## License

MIT - see [LICENSE](LICENSE).

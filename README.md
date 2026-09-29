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

A controller other than the CTS400 gets an entity for each value the CTS400 has too: temperatures,
humidity, fan levels and speeds, the target temperature and the filter, where it has them. Values
of its own - hot water, central heating, heat pump, its operating states - follow in a later
release. A value whose address is known only from the order of its manual's registers gets no
entity yet.

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
is read again after it is written.

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

## Removal

Settings > Devices & services > Nilan Connect > the three dots > Delete; then remove it in HACS.

## License

MIT - see [LICENSE](LICENSE).

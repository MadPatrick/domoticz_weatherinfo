# Domoticz Rain Forecast

This plugin retrieves rain forecast data from Buienradar and shows it in Domoticz.
It updates 3 devices automatically.

## What does this plugin do

The plugin reads the Buienradar `raintext` feed based on latitude/longitude and
adds weather details from the Buienradar JSON feed.

You get:
- current rain intensity (`mm/h`)
- accumulated rain over the configured poll interval (`mm`)
- status text in NL or EN
- optional temperature, icon, description, and wind in the text

Example status (EN):
- `Raining now 0.8 mm/h`
- `Rain expected 1.2 mm/h`
- `Rain expected at 14:35: 2.4 mm/h`
- `Dry for now <icon> - 19.7°C - Cloudy NW4`

## Installation

```bash
cd /home/domoticz/plugins
git clone https://github.com/MadPatrick/domoticz_rainforecast Rain_Forecast
sudo systemctl restart domoticz
```

Then go to:

```text
Setup -> Hardware
```

Add hardware with type **Rain Forecast**.

## Configuration

The labels below are exactly as defined in the script:

| Field (script) | Description | Default |
| --- | --- | --- |
| `Latitude (lat)` | Optional latitude override. Empty = Domoticz system location. | empty |
| `Longitude (lon)` | Optional longitude override. Empty = Domoticz system location. | empty |
| `Poll-interval (min)` | Poll frequency in minutes. | `5` |
| `Language` | Status text language (`NL` or `EN`). | `NL` |
| `Text device` | Which parts are included in the text output. | `Status - temperature - description - logo - wind` |
| `Debug` | Extra Domoticz debug logging (`Yes`/`No`). | `No` |

`Text device` options (exact script labels):
- `Status - temperature`
- `Status - temperature - logo`
- `Status - temperature - logo - wind`
- `Status - temperature - description - logo - wind`

## Created devices

The plugin creates these devices automatically (exact script names):

| Unit | Name (script) | Type |
| --- | --- | --- |
| `1` | `Rainfall` | `Rain` |
| `2` | `Rain forecast` | `Text` |
| `3` | `Temperature` | `Temperature` |

## How it works (short)

1. The plugin starts and reads configuration.
2. Devices are created if they do not exist yet.
3. Data is fetched periodically from Buienradar.
4. Raw rain values are converted to `mm/h`.
5. Rain amount is integrated over the configured poll interval.
6. Devices are updated only when values change.

## Troubleshooting

### Plugin not visible
Check the plugin folder name in `/home/domoticz/plugins` and restart Domoticz.

### No data
Check internet connectivity and coordinates.
Used rain URL:
`https://gpsgadget.buienradar.nl/data/raintext?lat=<lat>&lon=<lon>`

### Text stays "Voorlopig droog" / "Dry for now"
Usually Buienradar is not forecasting rain for that location.

## Updating

```bash
cd /home/domoticz/plugins/Rain_Forecast
git pull
sudo systemctl restart domoticz
```

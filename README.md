# Domoticz Rain Forecast

Domoticz Rain Forecast is a Python plugin for Domoticz that retrieves the
current rain forecast from Buienradar. The plugin automatically creates two
devices:

- **Neerslag**: a Domoticz Rain device with the current rain value and the
  accumulated total.
- **Buienradar**: a text device with a short, readable forecast.

The plugin is intended for users who want to quickly see in Domoticz whether it
is raining now, whether rain is expected soon, and roughly how much rain is
forecast.

## What does the plugin do?

The plugin uses the Buienradar `raintext` feed based on your latitude and
longitude. On each poll, it retrieves the forecast and converts it into a
Domoticz status.

Depending on the data, the text device may show messages such as:

- `Het regent nu 0.8 mm`
- `Regen verwacht 1.2 mm`
- `2.4 mm regen verwacht om 14:35`
- `Voorlopig droog`

The Rain device is also updated with:

- the current rain intensity in mm/hour;
- the accumulated rain estimate based on the configured poll interval.

The accumulated rain total is calculated from the Buienradar rain forecast feed
while the plugin is running. It is not the same as the measured daily total that
Buienradar may show on the website for "today".

## Installation

Go to the Domoticz plugin directory:

```bash
cd /home/pi/domoticz/plugins
```

Clone this repository:

```bash
git clone https://github.com/MadPatrick/domoticz_rainforecast Rain_Forecast
```

Restart Domoticz after installing the plugin:

```bash
sudo systemctl restart domoticz
```

Then open Domoticz and go to:

```text
Setup -> Hardware
```

Add a new hardware item with type **Rain Forecast**.

## Configuration

When adding the plugin, the following fields can be configured:

| Field | Description | Default |
| --- | --- | --- |
| Latitude (lat) | The latitude of the location for which the rain forecast should be retrieved. Use a dot as the decimal separator. | `52.37` |
| Longitude (lon) | The longitude of the location for which the rain forecast should be retrieved. Use a dot as the decimal separator. | `4.90` |
| Poll interval (min) | How often the plugin should query Buienradar. | `5` |
| Debug | Enables additional Domoticz debug logging. | `No` |

Example for Amsterdam:

```text
Latitude: 52.37
Longitude: 4.90
```

## Created devices

After startup, the plugin automatically creates the following devices if they do
not already exist:

| Unit | Device | Type | Purpose |
| --- | --- | --- | --- |
| 1 | Neerslag | Rain | Current rain and accumulated total |
| 2 | Buienradar | Text | Readable rain forecast |

You do not need to create these devices manually.

## How it works

1. Domoticz starts the plugin and reads the configured location and poll
   interval.
2. The plugin creates the required devices if they do not already exist.
3. A first measurement is performed immediately on startup.
4. After that, the plugin periodically retrieves new data from Buienradar.
5. The raw Buienradar values are converted to mm/hour.
6. The plugin integrates the 5-minute forecast values over the configured poll
   interval to estimate the amount of rain since the previous poll.
7. The Domoticz devices are only updated when the value or text changes.

The plugin retrieves data in a background thread, so the Domoticz main loop
remains available while the Buienradar feed is queried.

## Troubleshooting

### The plugin does not appear in Domoticz

Check whether the repository is located in the correct plugin directory and
restart Domoticz. The directory name may be `Rain_Forecast`, for example.

### No devices are created

Check the Domoticz log. If needed, set **Debug** to `Yes` in the plugin
configuration and restart the plugin.

### No Buienradar data is received

Check whether Domoticz has internet access and whether the configured
coordinates are correct. The plugin uses this URL:

```text
https://gpsgadget.buienradar.nl/data/raintext?lat=<lat>&lon=<lon>
```

### The text stays on "Voorlopig droog"

This usually means that Buienradar does not forecast rain for the configured
location. Check the coordinates if this is unexpected.

### The Rain total differs from Buienradar today

The Rain device total is built from the short-term `raintext` forecast and only
counts while the plugin is running. Buienradar's website can show a measured
daily total, so both values can differ after missed polls, restarts, forecast
changes, or local differences between forecast and measurement.

## Updating

Go to the plugin directory and pull the latest version:

```bash
cd /home/pi/domoticz/plugins/Rain_Forecast
git pull
sudo systemctl restart domoticz
```

## Requirements

- Domoticz with Python plugin support.
- Internet access from the machine running Domoticz.
- No API key required; the plugin uses the public Buienradar raintext feed.

# Domoticz Rain Forecast

Deze plugin haalt neerslagverwachting op van Buienradar en toont die in Domoticz.
This plugin retrieves rain forecast data from Buienradar and updates 3 devices.

## Wat doet deze plugin / What does it do

De plugin leest de `raintext` feed op basis van latitude/longitude en vult ook
weerinfo aan via de Buienradar JSON feed.

Je krijgt o.a.:
- actuele regenintensiteit (`mm/u`)
- geschatte neerslag over de ingestelde poll-interval
- status tekst in NL of EN
- optioneel temperatuur, icoon, omschrijving en wind in de tekst

Voorbeeld status (NL):
- `Het regent nu 0.8 mm/u`
- `Regen verwacht 1.2 mm/u`
- `2.4 mm/u regen verwacht om 14:35`
- `Voorlopig droog ...`

Example status (EN):
- `Raining now 0.8 mm/u`
- `Rain expected 1.2 mm/u`
- `2.4 mm/u rain expected at 14:35`
- `Dry for now ...`

## Installatie / Installation

```bash
cd /home/domoticz/plugins
git clone https://github.com/MadPatrick/domoticz_rainforecast Rain_Forecast
sudo systemctl restart domoticz
```

Ga daarna naar / Then go to:

```text
Setup -> Hardware
```

Voeg hardware toe met type **Rain Forecast**.

## Configuratie / Configuration

Onderstaande labels zijn exact zoals in het script:

| Field (script) | Uitleg / Description | Default |
| --- | --- | --- |
| `Latitude (lat)` | Optionele override voor latitude. Leeg = Domoticz systeemlocatie. | empty |
| `Longitude (lon)` | Optionele override voor longitude. Leeg = Domoticz systeemlocatie. | empty |
| `Poll-interval (min)` | Hoe vaak de plugin Buienradar opvraagt / Poll frequency in minutes. | `5` |
| `Language` | Taal voor statusbericht (`NL` of `EN`). | `NL` |
| `Text device` | Welke onderdelen in de tekst komen. | `Status - temperature - description - logo - wind` |
| `Debug` | Extra Domoticz debug logging (`Yes`/`No`). | `No` |

`Text device` opties (exact script labels):
- `Status - temperature`
- `Status - temperature - logo`
- `Status - temperature - logo - wind`
- `Status - temperature - description - logo - wind`

## Devices die worden aangemaakt / Created devices

De plugin maakt automatisch deze devices aan (exact script names):

| Unit | Name (script) | Type |
| --- | --- | --- |
| `1` | `Rainfall` | `Rain` |
| `2` | `Rain forecast` | `Text` |
| `3` | `Temperature` | `Temperature` |

## Werking in het kort / How it works (short)

1. Plugin start en leest configuratie.
2. Devices worden aangemaakt als ze nog niet bestaan.
3. Data wordt periodiek opgehaald van Buienradar.
4. Rain raw values worden omgerekend naar `mm/u`.
5. Regenhoeveelheid wordt geïntegreerd over de ingestelde poll-interval.
6. Devices worden alleen geüpdatet als er echt iets verandert.

## Troubleshooting

### Plugin niet zichtbaar / Plugin not visible
Controleer de mapnaam in `/home/domoticz/plugins` en herstart Domoticz.

### Geen data / No data
Controleer internettoegang en coördinaten.
Gebruikte rain URL:
`https://gpsgadget.buienradar.nl/data/raintext?lat=<lat>&lon=<lon>`

### Tekst blijft "Voorlopig droog" / Text stays "Dry for now"
Meestal voorspelt Buienradar dan geen regen op die locatie.

## Updaten / Updating

```bash
cd /home/domoticz/plugins/Rain_Forecast
git pull
sudo systemctl restart domoticz
```

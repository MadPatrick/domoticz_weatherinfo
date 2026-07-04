"""
<plugin key="RainForecast" name="Rain Forecast" author="MadPatrick" version="1.0.3" externallink="https://buienradar.nl" wikilink="https://github.com/MadPatrick/domoticz_rainforecast">
    <description>
        <h2>Buienradar</h2>
        <p>Version 1.0.3</p>
        Haalt de komende neerslagverwachting op via Buienradar en werkt
        twee devices bij: een Regen-sensor en een Tekst-device.
    </description>
    <params>
        <param field="Mode1" label="Breedtegraad (lat)"  width="80px" default=""/>
        <param field="Mode2" label="Lengtegraad (lon)"   width="80px" default=""/>
        <param field="Mode3" label="Poll-interval (min)" width="80px"  required="true" default="5"/>
        <param field="Mode6" label="Debug" width="75px">
            <options>
                <option label="Yes" value="Debug"/>
                <option label="No" value="Normal" default="true"/>
            </options>
        </param>
    </params>
</plugin>
"""

import Domoticz
import re
import urllib.request
import urllib.error
import threading
from typing import Optional

# ---------------------------------------------------------------------------
# Constanten
# ---------------------------------------------------------------------------
BUIENRADAR_URL = "https://gpsgadget.buienradar.nl/data/raintext?lat={lat}&lon={lon}"
UNIT_RAIN = 1   # Regen-device (Neerslag)
UNIT_TEXT = 2   # Tekst-device (Buienradar)
RAIN_STEP_MINUTES = 5

# ---------------------------------------------------------------------------
# Hulpfuncties
# ---------------------------------------------------------------------------

def raw_to_mm(raw: float) -> float:
    """Ruwe Buienradar-waarde omrekenen naar mm/uur."""
    if raw == 0:
        return 0.0
    return 10 ** ((raw - 109) / 32)

def fmt(value: float, decimals: int = 1) -> str:
    return f"{value:.{decimals}f}"

def normalize_coordinate(value: str) -> Optional[str]:
    """Normaliseer een coördinaat naar decimale notatie met 2 decimalen."""
    value = (value or "").strip().replace(",", ".")
    if not value:
        return None

    try:
        return f"{float(value):.2f}"
    except ValueError:
        return None

def build_status(prefix: str, mm_now: float, mm_max: Optional[float]):
    if mm_max is not None and mm_max > mm_now:
        html = (f"{prefix} <font color='yellow'>{fmt(mm_now)}</font> tot "
                f"<font color='yellow'>{fmt(mm_max)} mm/u</font>")
        text = f"{prefix} {fmt(mm_now)} tot {fmt(mm_max)} mm/u"
    else:
        html = f"{prefix} <font color='yellow'>{fmt(mm_now)} mm/u</font>"
        text = f"{prefix} {fmt(mm_now)} mm/u"
    return html, text

def rain_amount_for_interval(rain_values, interval_minutes: int) -> float:
    """Bereken de verwachte hoeveelheid neerslag voor het poll-interval."""
    if not rain_values or interval_minutes <= 0:
        return 0.0

    remaining = float(interval_minutes)
    amount = 0.0
    previous_mm = rain_values[0]

    for current_mm in rain_values[1:]:
        if remaining <= 0:
            break
        segment_minutes = min(RAIN_STEP_MINUTES, remaining)
        amount += ((previous_mm + current_mm) / 2) * (segment_minutes / 60)
        remaining -= segment_minutes
        previous_mm = current_mm

    if remaining > 0:
        amount += previous_mm * (remaining / 60)

    return amount

def parse_buienradar(data: str):
    counter       = 0
    max_now_raw   = 0
    rain_values   = []
    max_soon_raw  = 0
    first_rain_at = ""
    max_raw       = 0

    for line in data.splitlines():
        line = line.strip()
        if "|" not in line:
            continue
        parts = line.split("|", 1)
        try:
            raw = int(parts[0])
        except ValueError:
            continue
        time_str = parts[1].strip() if len(parts) > 1 else ""
        mm = raw_to_mm(raw)
        rain_values.append(mm)

        if counter <= 1:
            if raw > max_now_raw:
                max_now_raw = raw
        if counter <= 3 and raw > max_soon_raw:
            max_soon_raw = raw
        if first_rain_at == "" and raw > 0:
            first_rain_at = time_str
        if raw > max_raw:
            max_raw = raw

        counter += 1

    return {
        "mm_now":        raw_to_mm(max_now_raw),
        "mm_soon":       raw_to_mm(max_soon_raw),
        "mm_max":        raw_to_mm(max_raw),
        "rain_values":   rain_values,
        "max_now_raw":   max_now_raw,
        "max_soon_raw":  max_soon_raw,
        "max_raw":       max_raw,
        "first_rain_at": first_rain_at,
    }

def build_status_text(p: dict):
    """Bouwt de HTML- en logtekst op uit de geparseerde data."""
    if p["max_now_raw"] > 0:
        mm_max_arg = p["mm_max"] if p["mm_max"] > p["mm_now"] else None
        return build_status("Het regent nu", p["mm_now"], mm_max_arg)

    if p["max_soon_raw"] > 0:
        mm_max_arg = p["mm_max"] if p["mm_max"] > p["mm_soon"] else None
        return build_status("Regen verwacht", p["mm_soon"], mm_max_arg)

    if p["first_rain_at"]:
        html = (f"<font color='yellow'>{fmt(p['mm_max'])} mm/u</font> regen verwacht om "
                f"<font color='yellow'>{p['first_rain_at']}</font>")
        text = f"{fmt(p['mm_max'])} mm/u regen verwacht om {p['first_rain_at']}"
        return html, text

    return "Voorlopig droog", "Voorlopig droog"

# ---------------------------------------------------------------------------
# Plugin-klasse
# ---------------------------------------------------------------------------

class BasePlugin:

    def __init__(self):
        self._lat       = "52.37"
        self._lon       = "4.90"
        self._interval  = 10        # minuten
        self._heartbeat = 30        # seconden (Domoticz heartbeat)
        self._ticks     = 0         # telt heartbeats
        self._debug     = False
        self._lock      = threading.Lock()

    # ------------------------------------------------------------------
    # Levenscyclus
    # ------------------------------------------------------------------

    def onStart(self):
        self._debug = (Parameters["Mode6"] == "Debug")
        if self._debug:
            Domoticz.Debugging(1)

        if not self._resolve_location():
            return

        try:
            self._interval = max(1, int(Parameters["Mode3"]))
        except ValueError:
            self._interval = 10

        Domoticz.Heartbeat(self._heartbeat)

        # Devices aanmaken indien nog niet aanwezig
        if UNIT_RAIN not in Devices:
            Domoticz.Device(Name="Neerslag", Unit=UNIT_RAIN,
                            TypeName="Rain", Used=1).Create()
            Domoticz.Log("Device 'Neerslag' aangemaakt")

        if UNIT_TEXT not in Devices:
            Domoticz.Device(Name="Buienradar", Unit=UNIT_TEXT,
                            Type=243, Subtype=19, Used=1).Create()
            Domoticz.Log("Device 'Buienradar' aangemaakt")

        Domoticz.Log(f"Plugin gestart - lat={self._lat}, lon={self._lon}, "
                     f"interval={self._interval} min")

        # Direct eerste poll uitvoeren
        self._fetch_async()

    def onStop(self):
        Domoticz.Log("Plugin gestopt")

    def onHeartbeat(self):
        self._ticks += 1
        ticks_needed = (self._interval * 60) // self._heartbeat
        if self._ticks >= ticks_needed:
            self._ticks = 0
            self._fetch_async()

    def _resolve_location(self) -> bool:
        """Bepaal lat/lon waarbij handmatige overrides voorrang hebben op Domoticz."""
        manual_lat_raw = Parameters.get("Mode1", "")
        manual_lon_raw = Parameters.get("Mode2", "")
        manual_lat = normalize_coordinate(manual_lat_raw)
        manual_lon = normalize_coordinate(manual_lon_raw)

        if manual_lat_raw.strip() and manual_lat is None:
            Domoticz.Error("Ongeldige Breedtegraad (lat) in hardware instellingen.")
            return False
        if manual_lon_raw.strip() and manual_lon is None:
            Domoticz.Error("Ongeldige Lengtegraad (lon) in hardware instellingen.")
            return False

        domoticz_lat, domoticz_lon = self._read_domoticz_location()
        self._lat = manual_lat or domoticz_lat
        self._lon = manual_lon or domoticz_lon

        if not self._lat or not self._lon:
            Domoticz.Error(
                "Geen geldige locatie gevonden. Controleer lat/lon in Domoticz of de plugin."
            )
            return False

        Domoticz.Log(f"Locatie actief: lat={self._lat}, lon={self._lon}")
        return True

    def _read_domoticz_location(self):
        """Lees en normaliseer lat/lon uit de Domoticz-systeemlocatie."""
        try:
            location = Settings["Location"].strip()
        except Exception:
            return None, None

        parts = [x.strip() for x in location.split(";", 1)]
        if len(parts) != 2:
            return None, None

        lat = normalize_coordinate(parts[0])
        lon = normalize_coordinate(parts[1])
        if lat and lon:
            Domoticz.Log(f"Locatie uit Domoticz: lat={lat}, lon={lon}")
        return lat, lon

    # ------------------------------------------------------------------
    # Ophalen & verwerken
    # ------------------------------------------------------------------

    def _fetch_async(self):
        """Start een achtergrond-thread zodat de Domoticz-hoofdloop vrij blijft."""
        t = threading.Thread(target=self._fetch_and_update, daemon=True)
        t.start()

    def _fetch_and_update(self):
        url = BUIENRADAR_URL.format(lat=self._lat, lon=self._lon)
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            Domoticz.Error(f"HTTP-fout van Buienradar (statuscode: {e.code})")
            return
        except Exception as e:
            Domoticz.Error(f"Verbindingsfout Buienradar: {e}")
            return

        if not data or not data.strip():
            Domoticz.Error("Lege response ontvangen van Buienradar")
            return

        if not re.search(r"\d+\|\d+:\d+", data):
            Domoticz.Error("Onverwacht formaat in Buienradar response")
            return

        with self._lock:
            self._process(data)

    def _process(self, data: str):
        p = parse_buienradar(data)
        status_html, status_log = build_status_text(p)

        # --- regen-device bijwerken ---
        rain_dev = Devices[UNIT_RAIN]
        try:
            parts         = rain_dev.sValue.split(";") if rain_dev.sValue else []
            current_rate  = float(parts[0]) if len(parts) > 0 else 0.0
            current_total = float(parts[1]) if len(parts) > 1 else 0.0
        except ValueError:
            current_rate, current_total = 0.0, 0.0

        # Domoticz Rain stores the rate as hundredths of mm/hour.
        rain_increment = rain_amount_for_interval(p["rain_values"], self._interval)
        new_rate       = round(p["mm_now"] * 100)
        new_total      = current_total + rain_increment

        if self._debug:
            Domoticz.Debug(f"Rain calc: now={fmt(p['mm_now'])} mm/u, "
                           f"interval={self._interval} min, "
                           f"add={rain_increment:.3f} mm, total={new_total:.2f} mm")

        new_svalue     = f"{new_rate:.0f};{new_total:.2f}"
        current_svalue = f"{current_rate:.0f};{current_total:.2f}"

        if new_svalue != current_svalue:
            rain_dev.Update(nValue=0, sValue=new_svalue)

        # --- Tekst-device bijwerken ---
        text_dev = Devices[UNIT_TEXT]
        if text_dev.sValue != status_html:
            Domoticz.Log(status_log)
            text_dev.Update(nValue=0, sValue=status_html)

# ---------------------------------------------------------------------------
# Domoticz plugin-API hooks  (module-niveau functies vereist)
# ---------------------------------------------------------------------------

_plugin = BasePlugin()

def onStart():    _plugin.onStart()
def onStop():     _plugin.onStop()
def onHeartbeat(): _plugin.onHeartbeat()

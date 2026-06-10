"""
<plugin key="RainForecast" name="Rain Forecast" author="MadPatrick" version="1.0.1" externallink="https://buienradar.nl" wikilink="https://github.com/MadPatrick/domoticz_rainforecast">
    <description>
        <h2>Buienradar</h2>
        <p>Version 1.0.1</p>
        Haalt de komende neerslagverwachting op via Buienradar en werkt
        twee devices bij: een Regen-sensor en een Tekst-device.
    </description>
    <params>
        <param field="Mode1" label="Breedtegraad (lat)"  width="80px"  required="true" default="52.37"/>
        <param field="Mode2" label="Lengtegraad (lon)"   width="80px"  required="true" default="4.90"/>
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

def build_status(prefix: str, mm_now: float, mm_max: Optional[float]):
    html = f"{prefix} <font color='yellow'>{fmt(mm_now)} mm</font>"
    text = f"{prefix} {fmt(mm_now)} mm"
    if mm_max is not None and mm_max > mm_now:
        html += f" tot <font color='yellow'>{fmt(mm_max)} mm</font>"
        text += f" tot {fmt(mm_max)} mm"
    return html, text

def parse_buienradar(data: str):
    counter       = 0
    max_now_raw   = 0
    rain_now_sum  = 0.0
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

        if counter <= 1:
            if raw > max_now_raw:
                max_now_raw = raw
            if raw > 0:
                rain_now_sum += raw_to_mm(raw)
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
        "rain_now_avg":  rain_now_sum / 2,
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
        html = (f"<font color='yellow'>{fmt(p['mm_max'])} mm</font> regen verwacht om "
                f"<font color='yellow'>{p['first_rain_at']}</font>")
        text = f"{fmt(p['mm_max'])} mm regen verwacht om {p['first_rain_at']}"
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

        self._lat = Parameters["Mode1"].strip() or "52.37"
        self._lon = Parameters["Mode2"].strip() or "4.90"
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

        new_rate  = p["mm_now"] #* 12
        new_total = current_total + p["rain_now_avg"] / (60 / self._interval)

        new_svalue     = f"{new_rate:.2f};{new_total:.2f}"
        current_svalue = f"{current_rate:.2f};{current_total:.2f}"

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

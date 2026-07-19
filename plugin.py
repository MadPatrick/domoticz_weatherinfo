"""
<plugin key="WeatherInfo" name="Weather Info" author="MadPatrick" version="1.2.1" externallink="https://buienradar.nl" wikilink="https://github.com/MadPatrick/domoticz_rainforecast">
    <description>
        <h2>Weather Info (Buienradar + Open-Meteo)</h2>
        <p>Version 1.2.1</p>
        Retrieves the upcoming rainfall forecast from Buienradar and current weather
        conditions from Open-Meteo, and updates three Domoticz devices:
        <ul>
            <li><b>Rain sensor</b> - current rain rate and accumulated total.</li>
            <li><b>Text device</b> - configurable status line with rain status,
                temperature, weather description, wind (Beaufort + direction),
                and a weather icon (emoji).</li>
            <li><b>Temperature device</b> - current temperature from Open-Meteo.</li>
        </ul>
        Weather icons are resolved in order: WMO weather code (Open-Meteo) ->
        Buienradar icon code -> weather description text as a last fallback.
        Coordinates default to the Domoticz location settings when left blank.
    </description>    <params>
        <param field="Mode1" label="Latitude (lat)"  width="80px" default="">
            <description><br/>Leave LAT and LON blank for Domoticz settings<br/></description>
        </param>
        <param field="Mode2" label="Longitude (lon)" width="80px" default=""/>
        <param field="Mode3" label="Poll-interval (min)" width="80px"  required="true" default="5"/>
        <param field="Mode4" label="Language" width="75px">
            <options>
                <option label="NL" value="NL" default="true"/>
                <option label="EN" value="EN"/>
            </options>
        </param>
        <param field="Mode5" label="Text device" width="220px">
            <options>
                <option label="Status - temperature" value="temp"/>
                <option label="Status - temperature - logo" value="temp_logo"/>
                <option label="Status - temperature - wind - logo" value="temp_logo_wind"/>
                <option label="Status - temperature - description - wind - logo" value="temp_desc_logo_wind" default="true"/>
            </options>
        </param>
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
import json
import html
import urllib.request
import urllib.error
import threading
import queue
from typing import Optional, Tuple

BUIENRADAR_URL = "https://gpsgadget.buienradar.nl/data/raintext?lat={lat}&lon={lon}"
OPEN_METEO_URL = (
    "https://api.open-meteo.com/v1/forecast?"
    "latitude={lat}&longitude={lon}"
    "&current=temperature_2m,wind_speed_10m,wind_direction_10m,weather_code"
)
POLL_OPENMETEO = 15          # fetch Open-Meteo once every N minutes (independent of Mode3)
UNIT_RAIN = 1
UNIT_TEXT = 2
UNIT_TEMP = 3
ICON_ZIP = "weatherinfo_icons.zip"
ICON_NAME = "weatherinfo"
RAIN_STEP_MINUTES = 5
LANGUAGE_TEXTS = {
    "EN": {
        "raining_now": "Raining now",
        "rain_expected": "Rain expected",
        "rain_expected_at": "rain expected at",
        "dry_for_now": "Dry for now",
        "range_word": "to",
    },
    "NL": {
        "raining_now": "Het regent nu",
        "rain_expected": "Regen verwacht",
        "rain_expected_at": "regen verwacht om",
        "dry_for_now": "Voorlopig droog",
        "range_word": "tot",
    },
}

WEATHER_ICON_MAP = {
    "a": {"day": ("&#x2600;",  "#FFC107"), "night": ("&#x1F319;", "#4A6FA5")},  # onbewolkt/zonnig/helder
    "j": {"day": ("&#x26C5;",  "#FFC107"), "night": ("&#x1F319;&#x2601;", "#4A6FA5")},  # opklaringen + hoge bewolking
    "b": {"day": ("&#x26C5;",  "#FFC107"), "night": ("&#x1F319;&#x2601;", "#4A6FA5")},  # opklaringen + middelbare/lage bewolking
    "c": {"day": ("&#x2601;",  "#D3D3D3"), "night": ("&#x2601;",  "#D3D3D3")},  # zwaar bewolkt
    "d": {"day": ("&#x1F32B;", "#B0B0B0"), "night": ("&#x1F32B;", "#B0B0B0")},  # bewolkt + lokaal mist
    "f": {"day": ("&#x1F326;", "#5DADE2"), "night": ("&#x1F327;", "#5DADE2")},  # afwisselend bewolkt + lichte regen
    "g": {"day": ("&#x26A1;",  "#FFC107"), "night": ("&#x26A1;",  "#FFC107")},  # opklaringen + kans op onweersbuien
    "s": {"day": ("&#x26A1;",  "#FFC107"), "night": ("&#x26A1;",  "#FFC107")},  # bewolkt + kans op onweersbuien
    "t": {"day": ("&#x2744;",  "#E0F7FA"), "night": ("&#x2744;",  "#E0F7FA")},  # zware sneeuwval
    "m": {"day": ("&#x1F327;", "#4FC3F7"), "night": ("&#x1F327;", "#4FC3F7")},  # zwaar bewolkt + lichte regen
    "n": {"day": ("&#x1F32B;", "#B0B0B0"), "night": ("&#x1F32B;", "#B0B0B0")},  # opklaring + lokale nevel/mist
    "q": {"day": ("&#x1F327;", "#3B82C4"), "night": ("&#x1F327;", "#3B82C4")},  # zwaar bewolkt en regen
    "u": {"day": ("&#x2744;",  "#E0F7FA"), "night": ("&#x2744;",  "#E0F7FA")},  # afwisselend bewolkt + lichte sneeuw
    "v": {"day": ("&#x2744;",  "#E0F7FA"), "night": ("&#x2744;",  "#E0F7FA")},  # zwaar bewolkt + lichte sneeuw
    "w": {"day": ("&#x1F327;", "#7FB3D5"), "night": ("&#x1F327;", "#7FB3D5")},  # zwaar bewolkt + regen/winterse neerslag
}
DEFAULT_ICON = ("&#x2601;", "#D3D3D3")
GREEN_DOT = '<span style="color:green;">&#9679;</span>'

WMO_DESCRIPTIONS = {
    0:  "Onbewolkt",
    1:  "Hoofdzakelijk helder",
    2:  "Gedeeltelijk bewolkt",
    3:  "Bewolkt",
    45: "Mist",
    48: "IJsmist",
    51: "Motregen",
    53: "Motregen",
    55: "Motregen",
    56: "IJzel",
    57: "IJzel",
    61: "Lichte regen",
    63: "Regen",
    65: "Zware regen",
    66: "IJzel",
    67: "IJzel",
    71: "Lichte sneeuw",
    73: "Sneeuw",
    75: "Zware sneeuw",
    77: "Sneeuwkorrels",
    80: "Lichte bui",
    81: "Bui",
    82: "Zware bui",
    85: "Lichte sneeuwbui",
    86: "Zware sneeuwbui",
    95: "Onweer",
    96: "Onweer met hagel",
    99: "Onweer met zware hagel",
}

WMO_ICON_MAP = {
    0:  ("&#x2600;",  "#FFC107"),  # onbewolkt
    1:  ("&#x26C5;",  "#FFC107"),  # hoofdzakelijk helder
    2:  ("&#x26C5;",  "#FFC107"),  # gedeeltelijk bewolkt
    3:  ("&#x2601;",  "#D3D3D3"),  # bewolkt
    45: ("&#x1F32B;", "#B0B0B0"),  # mist
    48: ("&#x1F32B;", "#B0B0B0"),  # ijsmist
    51: ("&#x1F327;", "#4FC3F7"),  # motregen licht
    53: ("&#x1F327;", "#4FC3F7"),  # motregen matig
    55: ("&#x1F327;", "#4FC3F7"),  # motregen zwaar
    56: ("&#x1F327;", "#7FB3D5"),  # ijzel
    57: ("&#x1F327;", "#7FB3D5"),  # ijzel
    61: ("&#x1F327;", "#4FC3F7"),  # lichte regen
    63: ("&#x1F327;", "#3B82C4"),  # regen
    65: ("&#x1F327;", "#3B82C4"),  # zware regen
    66: ("&#x1F327;", "#7FB3D5"),  # ijzel
    67: ("&#x1F327;", "#7FB3D5"),  # ijzel
    71: ("&#x2744;",  "#E0F7FA"),  # lichte sneeuw
    73: ("&#x2744;",  "#E0F7FA"),  # sneeuw
    75: ("&#x2744;",  "#E0F7FA"),  # zware sneeuw
    77: ("&#x2744;",  "#E0F7FA"),  # sneeuwkorrels
    80: ("&#x1F327;", "#5DADE2"),  # lichte bui
    81: ("&#x1F327;", "#5DADE2"),  # bui
    82: ("&#x1F327;", "#3B82C4"),  # zware bui
    85: ("&#x2744;",  "#E0F7FA"),  # lichte sneeuwbui
    86: ("&#x2744;",  "#E0F7FA"),  # zware sneeuwbui
    95: ("&#x26A1;",  "#FFC107"),  # onweer
    96: ("&#x26A1;",  "#FFC107"),  # onweer met hagel
    99: ("&#x26A1;",  "#FFC107"),  # onweer met zware hagel
}

_BEAUFORT_THRESHOLDS = [1, 6, 12, 20, 29, 39, 50, 62, 75, 89, 103, 118]

def kmh_to_beaufort(kmh: float) -> int:
    for bft, threshold in enumerate(_BEAUFORT_THRESHOLDS):
        if kmh < threshold:
            return bft
    return 12

_COMPASS_DIRS = ["N", "NO", "O", "ZO", "Z", "ZW", "W", "NW"]

def degrees_to_compass(degrees: float) -> str:
    index = int((degrees + 22.5) / 45) % 8
    return _COMPASS_DIRS[index]

TEXT_DEVICE_MODES = {
    "temp": {
        "description": False,
        "icon": False,
        "wind": False,
    },
    "temp_logo": {
        "description": False,
        "icon": True,
        "wind": False,
    },
    "temp_logo_wind": {
        "description": False,
        "icon": True,
        "wind": True,
    },
    "temp_desc_logo_wind": {
        "description": True,
        "icon": True,
        "wind": True,
    },
}

def raw_to_mm(raw: float) -> float:
    if raw == 0:
        return 0.0
    return 10 ** ((raw - 109) / 32)

def fmt(value: float, decimals: int = 1) -> str:
    return f"{value:.{decimals}f}"

def fmt_display(value: float, decimals: int = 1) -> str:
    return fmt(value, decimals).replace(".", ",")

def normalize_coordinate(value: Optional[str]) -> Optional[str]:
    value = (value or "").strip().replace(",", ".")
    if not value:
        return None

    try:
        return f"{float(value):.2f}"
    except ValueError:
        return None

def parse_manual_coordinate(value: Optional[str], label: str) -> Tuple[Optional[str], Optional[str]]:
    normalized = normalize_coordinate(value)
    if (value or "").strip() and normalized is None:
        return None, f"Invalid {label} in hardware settings."
    return normalized, None

def build_status(prefix: str, mm_now: float, mm_max: Optional[float], range_word: str):
    if mm_max is not None and mm_max > mm_now:
        html = (f"{prefix} <font color='yellow'>{fmt(mm_now)}</font> {range_word} "
                f"<font color='yellow'>{fmt(mm_max)} mm/u</font>")
        text = f"{prefix} {fmt(mm_now)} {range_word} {fmt(mm_max)} mm/u"
    else:
        html = f"{prefix} <font color='yellow'>{fmt(mm_now)} mm/u</font>"
        text = f"{prefix} {fmt(mm_now)} mm/u"
    return html, text

def rain_amount_for_interval(rain_values, interval_minutes: int) -> float:
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

def build_wind_text(weather_info: dict) -> str:
    direction = str(weather_info.get("winddirection") or "").strip()
    force = weather_info.get("windspeed_bft")
    if not direction or force is None:
        return ""

    try:
        force_value = int(float(force))
    except (TypeError, ValueError):
        return direction

    return f"{direction}{force_value}"

def extract_icon_code(iconurl: str) -> str:
    if not iconurl:
        return ""
    filename = iconurl.rsplit("/", 1)[-1]
    return filename.split(".", 1)[0].strip().lower()

def map_icon_from_code(code: str) -> Optional[Tuple[str, str]]:
    if not code:
        return None
    letter = code[0]
    is_night = len(code) == 2 and code[1] == letter
    entry = WEATHER_ICON_MAP.get(letter)
    if not entry:
        return None
    return entry["night"] if is_night else entry["day"]

def map_weather_icon_entity(weatherdescription: str) -> Tuple[str, str]:
    desc = weatherdescription.lower()

    if "onweer" in desc or "bliksem" in desc:
        return "&#x26A1;", "#FFC107"
    if "hagel" in desc:
        return "&#x2744;", "#E0F7FA"
    if "sneeuw" in desc:
        return "&#x2744;", "#E0F7FA"
    if "mist" in desc or "nevel" in desc:
        return "&#x1F32B;", "#B0B0B0"
    if "bui" in desc:
        return "&#x1F327;", "#5DADE2"
    if "motregen" in desc or "regen" in desc:
        return "&#x1F327;", "#4FC3F7"
    if "onbewolkt" in desc or "zonnig" in desc or "helder" in desc:
        return "&#x2600;", "#FFC107"
    if "gedeeltelijk bewolkt" in desc or "opklaringen" in desc:
        return "&#x26C5;", "#FFC107"
    if "bewolkt" in desc:
        return "&#x2601;", "#D3D3D3"

    return DEFAULT_ICON

def build_weather_icon_html(weather_info: Optional[dict]) -> str:
    if not weather_info:
        return ""

    weatherdescription = str(weather_info.get("weatherdescription") or "").strip()
    wmo_code = weather_info.get("wmo_code")
    iconurl = str(weather_info.get("iconurl") or "").strip()

    icon_entity, color = (
        WMO_ICON_MAP.get(wmo_code)
        or map_icon_from_code(extract_icon_code(iconurl))
        or (map_weather_icon_entity(weatherdescription) if weatherdescription else DEFAULT_ICON)
    )
    alt = html.escape(weatherdescription or "weather", quote=True)

    return (f'<span title="{alt}" style="vertical-align: middle; color: {color}; '
            f'font-size: 2em; line-height: 1;">'
            f'{icon_entity}</span>')

def build_weather_suffix(weather_info: Optional[dict], text_mode: str) -> Tuple[str, str]:
    if not weather_info:
        return "", ""

    mode = TEXT_DEVICE_MODES.get(text_mode, TEXT_DEVICE_MODES["temp_desc_logo_wind"])
    html_sections = []
    text_sections = []

    temperature = weather_info.get("temperature")
    if temperature is not None:
        try:
            temp_value = float(temperature)
        except (TypeError, ValueError):
            temp_value = None
        if temp_value is not None:
            html_sections.append(f"{fmt_display(temp_value)}\u00b0C")
            text_sections.append(f"{fmt_display(temp_value)} C")

    weatherdescription = str(weather_info.get("weatherdescription") or "").strip()
    icon_html = build_weather_icon_html(weather_info)
    wind_text = build_wind_text(weather_info)

    if mode["description"] and weatherdescription:
        html_sections.append(html.escape(weatherdescription))
        text_sections.append(weatherdescription)

    if mode["wind"] and wind_text:
        html_sections.append(html.escape(wind_text))
        text_sections.append(wind_text)

    if mode["icon"] and icon_html:
        html_sections.append(icon_html)

    return f" {GREEN_DOT} ".join(html_sections), " - ".join(text_sections)

def append_weather_to_status(status_html: str, status_log: str, weather_info: Optional[dict], text_mode: str) -> Tuple[str, str]:
    suffix_html, suffix_log = build_weather_suffix(weather_info, text_mode)
    if suffix_html:
        status_html = f"{status_html}&nbsp; {GREEN_DOT} {suffix_html}"
    if suffix_log:
        status_log = f"{status_log} - {suffix_log}"
    return status_html, status_log

def build_status_text(p: dict, language: str):
    texts = LANGUAGE_TEXTS.get(language, LANGUAGE_TEXTS["NL"])

    if p["max_now_raw"] > 0:
        mm_max_arg = p["mm_max"] if p["mm_max"] > p["mm_now"] else None
        return build_status(texts["raining_now"], p["mm_now"], mm_max_arg, texts["range_word"])

    if p["max_soon_raw"] > 0:
        mm_max_arg = p["mm_max"] if p["mm_max"] > p["mm_soon"] else None
        return build_status(texts["rain_expected"], p["mm_soon"], mm_max_arg, texts["range_word"])

    if p["first_rain_at"]:
        html = (f"<font color='yellow'>{fmt(p['mm_max'])} mm/u</font> {texts['rain_expected_at']} "
                f"<font color='yellow'>{p['first_rain_at']}</font>")
        text = f"{fmt(p['mm_max'])} mm/u {texts['rain_expected_at']} {p['first_rain_at']}"
        return html, text

    return texts["dry_for_now"], texts["dry_for_now"]

class BasePlugin:

    def __init__(self):
        self._lat       = "52.37"
        self._lon       = "4.90"
        self._interval  = 10
        self._heartbeat = 30
        self._ticks     = 0
        self._openmeteo_ticks = 0
        self._openmeteo_ticks_needed = (POLL_OPENMETEO * 60) // self._heartbeat
        self._lat_source = "Domoticz"
        self._lon_source = "Domoticz"
        self._language  = "NL"
        self._text_mode = "temp_desc_logo_wind"
        self._debug     = False
        self._lock      = threading.Lock()
        self._weather_info = None
        self.imageID = 0
        self.message_queue = queue.Queue()

    def _plugin_version(self) -> str:
        match = re.search(r'version="([^"]+)"', __doc__ or "")
        return match.group(1) if match else "unknown"

    def _location_source_summary(self) -> str:
        if self._lat_source == self._lon_source:
            return self._lat_source
        return f"lat={self._lat_source}, lon={self._lon_source}"

    def _load_device_icon(self):
        creating_new_icon = ICON_NAME not in Images

        try:
            Domoticz.Image(ICON_ZIP).Create()
        except Exception as e:
            Domoticz.Error(f"Unable to load icon pack '{ICON_ZIP}': {e}")
            return

        if ICON_NAME in Images:
            self.imageID = Images[ICON_NAME].ID
            if creating_new_icon:
                Domoticz.Log("Icons created and loaded.")
            else:
                Domoticz.Log(f"Icons found in database (ImageID={self.imageID}).")
        else:
            Domoticz.Error(f"Unable to load icon pack '{ICON_ZIP}'")

    def _apply_device_icon(self):
        if not self.imageID:
            return

        for unit in (UNIT_RAIN, UNIT_TEXT, UNIT_TEMP):
            if unit in Devices and Devices[unit].Image != self.imageID:
                device = Devices[unit]
                device.Update(
                    nValue=device.nValue,
                    sValue=device.sValue,
                    Image=self.imageID,
                )
                Domoticz.Log(f"Icon applied to device '{device.Name}'.")

    def onStart(self):
        self._debug = (Parameters["Mode6"] == "Debug")
        self._language = Parameters.get("Mode4", "NL")
        if self._language not in LANGUAGE_TEXTS:
            self._language = "NL"
        self._text_mode = Parameters.get("Mode5", "temp_desc_logo_wind")
        if self._text_mode not in TEXT_DEVICE_MODES:
            self._text_mode = "temp_desc_logo_wind"
        if self._debug:
            Domoticz.Debugging(1)

        self._load_device_icon()

        if not self._resolve_location():
            return

        try:
            self._interval = max(1, int(Parameters["Mode3"]))
        except ValueError:
            self._interval = 10

        Domoticz.Heartbeat(self._heartbeat)

        if UNIT_RAIN not in Devices:
            Domoticz.Device(Name="Rainfall", Unit=UNIT_RAIN,
                            TypeName="Rain", Image=self.imageID, Used=1).Create()
            Domoticz.Log("Device 'Rainfall' created")

        if UNIT_TEXT not in Devices:
            Domoticz.Device(Name="Rain forecast", Unit=UNIT_TEXT,
                            Type=243, Subtype=19, Image=self.imageID, Used=1).Create()
            Domoticz.Log("Device 'Rain forecast' created")

        if UNIT_TEMP not in Devices:
            Domoticz.Device(Name="Temperature", Unit=UNIT_TEMP,
                            TypeName="Temperature", Image=self.imageID, Used=1).Create()
            Domoticz.Log("Device 'Temperature' created")

        self._apply_device_icon()

        Domoticz.Log(f"Plugin started - version {self._plugin_version()}")
        Domoticz.Log(f"lat={self._lat}, lon={self._lon} ({self._location_source_summary()})")

        self._fetch_async(fetch_openmeteo=True)

    def onStop(self):
        Domoticz.Log("Plugin stopped")

    def onHeartbeat(self):
        while not self.message_queue.empty():
            msg = self.message_queue.get()

            if msg["type"] == "error":
                Domoticz.Error(msg["msg"])

            elif msg["type"] == "data":
                weather_info = msg["weather_info"]
                if weather_info is not None:
                    self._weather_info = weather_info
                    if self._debug:
                        Domoticz.Debug(
                            "Weather info: "
                            f"temperature={weather_info.get('temperature', '')}, "
                            f"weatherdescription={weather_info.get('weatherdescription', '')}, "
                            f"winddirection={weather_info.get('winddirection', '')}, "
                            f"windspeed_bft={weather_info.get('windspeed_bft', '')}"
                        )

                self._process(msg["data"], self._weather_info)

        self._ticks += 1
        self._openmeteo_ticks += 1
        ticks_needed = (self._interval * 60) // self._heartbeat
        if self._ticks >= ticks_needed:
            self._ticks = 0
            fetch_openmeteo = self._openmeteo_ticks >= self._openmeteo_ticks_needed
            if fetch_openmeteo:
                self._openmeteo_ticks = 0
            self._fetch_async(fetch_openmeteo)

    def _resolve_location(self) -> bool:
        manual_lat_raw = Parameters.get("Mode1", "")
        manual_lon_raw = Parameters.get("Mode2", "")
        manual_lat, lat_error = parse_manual_coordinate(manual_lat_raw, "latitude (lat)")
        manual_lon, lon_error = parse_manual_coordinate(manual_lon_raw, "longitude (lon)")

        if lat_error:
            Domoticz.Error(lat_error)
            return False
        if lon_error:
            Domoticz.Error(lon_error)
            return False

        domoticz_lat, domoticz_lon = self._read_domoticz_location()
        self._lat = manual_lat or domoticz_lat
        self._lon = manual_lon or domoticz_lon
        self._lat_source = "manual" if manual_lat else "Domoticz"
        self._lon_source = "manual" if manual_lon else "Domoticz"

        if not self._lat or not self._lon:
            Domoticz.Error(
                "No valid location found. Check lat/lon in Domoticz or in the plugin settings."
            )
            return False

        return True

    def _read_domoticz_location(self) -> Tuple[Optional[str], Optional[str]]:
        try:
            location = Settings["Location"].strip()
        except (KeyError, TypeError, AttributeError):
            return None, None

        parts = [x.strip() for x in location.split(";", 1)]
        if len(parts) != 2:
            return None, None

        lat = normalize_coordinate(parts[0])
        lon = normalize_coordinate(parts[1])
        return lat, lon

    def _fetch_async(self, fetch_openmeteo: bool = True):
        t = threading.Thread(target=self._fetch_and_update, args=(fetch_openmeteo,), daemon=True)
        t.start()

    def _fetch_and_update(self, fetch_openmeteo: bool = True):
        url = BUIENRADAR_URL.format(lat=self._lat, lon=self._lon)
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            self.message_queue.put({"type": "error", "msg": f"Buienradar HTTP error (status code: {e.code})"})
            return
        except Exception as e:
            self.message_queue.put({"type": "error", "msg": f"Buienradar connection error: {e}"})
            return

        if not data or not data.strip():
            self.message_queue.put({"type": "error", "msg": "Received empty response from Buienradar"})
            return

        if not re.search(r"\d+\|\d+:\d+", data):
            self.message_queue.put({"type": "error", "msg": "Unexpected format in Buienradar response"})
            return

        # When fetch_openmeteo is False, send None so onHeartbeat reuses the
        # last cached self._weather_info value instead of fetching a fresh one.
        weather_info = self._fetch_weather_info() if fetch_openmeteo else None

        self.message_queue.put({
            "type": "data",
            "data": data,
            "weather_info": weather_info
        })

    def _fetch_weather_info(self) -> Optional[dict]:
        url = OPEN_METEO_URL.format(lat=self._lat, lon=self._lon)
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            self.message_queue.put({"type": "error", "msg": f"Open-Meteo HTTP error (status code: {e.code})"})
            return None
        except Exception as e:
            self.message_queue.put({"type": "error", "msg": f"Open-Meteo connection error: {e}"})
            return None

        try:
            json_data = json.loads(raw)
        except ValueError:
            self.message_queue.put({"type": "error", "msg": "Unexpected format in Open-Meteo response"})
            return None

        current = json_data.get("current")
        if not current:
            self.message_queue.put({"type": "error", "msg": "Missing 'current' data in Open-Meteo response"})
            return None

        weather_info = {}

        try:
            weather_info["temperature"] = float(current["temperature_2m"])
        except (KeyError, TypeError, ValueError):
            pass

        try:
            weather_info["windspeed_bft"] = kmh_to_beaufort(float(current["wind_speed_10m"]))
        except (KeyError, TypeError, ValueError):
            pass

        try:
            weather_info["winddirection"] = degrees_to_compass(float(current["wind_direction_10m"]))
        except (KeyError, TypeError, ValueError):
            pass

        try:
            wmo_code = int(current["weather_code"])
            weather_info["wmo_code"] = wmo_code
            weather_info["weatherdescription"] = WMO_DESCRIPTIONS.get(wmo_code, "")
        except (KeyError, TypeError, ValueError):
            pass

        return weather_info or None

    def _process(self, data: str, weather_info: Optional[dict]):
        p = parse_buienradar(data)
        status_html, status_log = build_status_text(p, self._language)
        status_html, status_log = append_weather_to_status(
            status_html,
            status_log,
            weather_info,
            self._text_mode
        )

        rain_dev = Devices[UNIT_RAIN]
        try:
            parts         = rain_dev.sValue.split(";") if rain_dev.sValue else []
            current_rate  = float(parts[0]) if len(parts) > 0 else 0.0
            current_total = float(parts[1]) if len(parts) > 1 else 0.0
        except ValueError:
            current_rate, current_total = 0.0, 0.0

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

        text_dev = Devices[UNIT_TEXT]
        if text_dev.sValue != status_html:
            text_dev.Update(nValue=0, sValue=status_html)

        if weather_info and weather_info.get("temperature") is not None:
            self._process_temperature(weather_info["temperature"])

    def _process_temperature(self, temperature: float):
        temp_dev = Devices[UNIT_TEMP]
        new_svalue = fmt(temperature, 1)
        if temp_dev.sValue != new_svalue:
            temp_dev.Update(nValue=0, sValue=new_svalue)
            if self._debug:
                Domoticz.Debug(f"Temperature updated: {new_svalue} C")

_plugin = BasePlugin()

def onStart():    _plugin.onStart()
def onStop():     _plugin.onStop()
def onHeartbeat(): _plugin.onHeartbeat()

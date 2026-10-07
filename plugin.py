"""
<plugin key="WeatherInfo" name="Weather Info" author="MadPatrick" version="1.4.0" externallink="https://buienradar.nl" wikilink="https://github.com/MadPatrick/domoticz_rainforecast">
    <description>
        <h2>Weather Info (Buienradar)</h2>
        <p><strong>Version:</strong> 1.4.0</p>
        <p>Retrieves the upcoming rainfall forecast and the current weather conditions
        (nearest weather station) from Buienradar, and updates three Domoticz devices:</p>
        <ul>
            <li><b>Rain sensor</b> - current rain rate and accumulated total.</li>
            <li><b>Text device</b> - configurable status line with rain status,
                temperature, weather description, wind (Beaufort + direction),
                and a weather icon (emoji).</li>
            <li><b>Temperature device</b> - current temperature of the nearest Buienradar weather station.</li>
        </ul>
        <p>Weather icons are resolved in order: Buienradar icon code -> weather
        description text as a last fallback. While the rain radar reports rain, a dry
        icon/description becomes rain. Coordinates default to the Domoticz location settings when left blank.</p>
    </description>
    <params>
        <param field="Latitude" label="Latitude (lat)"  width="80px" default="">
            <description>
                <h4 style="margin:4px 0 6px 0;">Location</h4>
                <br/>Leave LAT and LON blank for Domoticz settings<br/>
            </description>
        </param>
        <param field="Longitude" label="Longitude (lon)" width="80px" default=""/>
        <param field="PollInterval" label="Poll-interval (min)" width="80px"  required="true" default="5">
            <description>
                <h4 style="margin:14px 0 6px 0; border-top:1px solid #ccc; padding-top:8px;">Polling</h4>
            </description>
        </param>
        <param field="Language" label="Language" width="75px">
            <description>
                <h4 style="margin:14px 0 6px 0; border-top:1px solid #ccc; padding-top:8px;">Display</h4>
            </description>
            <options>
                <option label="NL" value="NL" default="true"/>
                <option label="EN" value="EN"/>
            </options>
        </param>
        <param field="TextDeviceFormat" label="Text device" width="220px">
            <options>
                <option label="Status - temperature" value="temp"/>
                <option label="Status - temperature - logo" value="temp_logo"/>
                <option label="Status - temperature - wind - logo" value="temp_logo_wind"/>
                <option label="Status - temperature - description - wind - logo" value="temp_desc_logo_wind" default="true"/>
            </options>
        </param>
        <param field="EnableDebug" type="boolean" label="Debug" default="false">
            <description>
                <h4 style="margin:14px 0 6px 0; border-top:1px solid #ccc; padding-top:8px;">Logging</h4>
            </description>
        </param>
    </params>
</plugin>
"""

import Domoticz
import re
import json
import html
import time
import urllib.request
import urllib.error
import math
import threading
import queue
from typing import Optional, Tuple

BUIENRADAR_URL = "https://gpsgadget.buienradar.nl/data/raintext?lat={lat}&lon={lon}"
BUIENRADAR_FEED_URL = "https://data.buienradar.nl/2.0/feed/json"
POLL_WEATHER = 10            # fetch the station feed once every N minutes (stations report every 10 min)
MAX_STATION_KM = 75          # use the nearest station within this distance
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

# Values are (shape_key, color) pairs; shape_key indexes into ICON_ENTITIES
# below. Domoticz's Text device strips <img>/data-URI content from the
# value, so icons have to stay plain Unicode - see ICON_ENTITIES for how
# consistent sizing is achieved without images.
WEATHER_ICON_MAP = {
    "a": {"day": ("sun",            "#FFC107"), "night": ("moon",       "#4A6FA5")},  # onbewolkt/zonnig/helder
    "j": {"day": ("sun_cloud",      "#FFC107"), "night": ("moon_cloud", "#4A6FA5")},  # opklaringen + hoge bewolking
    "b": {"day": ("sun_cloud",      "#FFC107"), "night": ("moon_cloud", "#4A6FA5")},  # opklaringen + middelbare/lage bewolking
    "c": {"day": ("cloud",          "#D3D3D3"), "night": ("cloud",      "#D3D3D3")},  # zwaar bewolkt
    "d": {"day": ("fog",            "#B0B0B0"), "night": ("fog",        "#B0B0B0")},  # bewolkt + lokaal mist
    "f": {"day": ("sun_rain_cloud", "#5DADE2"), "night": ("rain_cloud", "#5DADE2")},  # afwisselend bewolkt + lichte regen
    "g": {"day": ("lightning",      "#FFC107"), "night": ("lightning",  "#FFC107")},  # opklaringen + kans op onweersbuien
    "s": {"day": ("lightning",      "#FFC107"), "night": ("lightning",  "#FFC107")},  # bewolkt + kans op onweersbuien
    "t": {"day": ("snow",           "#E0F7FA"), "night": ("snow",       "#E0F7FA")},  # zware sneeuwval
    "m": {"day": ("rain_cloud",     "#4FC3F7"), "night": ("rain_cloud", "#4FC3F7")},  # zwaar bewolkt + lichte regen
    "n": {"day": ("fog",            "#B0B0B0"), "night": ("fog",        "#B0B0B0")},  # opklaring + lokale nevel/mist
    "q": {"day": ("rain_cloud",     "#3B82C4"), "night": ("rain_cloud", "#3B82C4")},  # zwaar bewolkt en regen
    "u": {"day": ("snow",           "#E0F7FA"), "night": ("snow",       "#E0F7FA")},  # afwisselend bewolkt + lichte sneeuw
    "v": {"day": ("snow",           "#E0F7FA"), "night": ("snow",       "#E0F7FA")},  # zwaar bewolkt + lichte sneeuw
    "w": {"day": ("rain_cloud",     "#7FB3D5"), "night": ("rain_cloud", "#7FB3D5")},  # zwaar bewolkt + regen/winterse neerslag
}
DEFAULT_ICON = ("cloud", "#D3D3D3")
GREEN_DOT = '<span style="color:green;">&#9679;</span>'

# U+FE0F (VARIATION SELECTOR-16) forces full-color "emoji presentation" for
# codepoints that otherwise default to a small monochrome "text presentation"
# glyph in most fonts (sun/cloud/lightning/snowflake are legacy dingbat
# symbols, unlike the moon/rain-cloud/fog pictographs which are already
# emoji-only). Without it, the moon rendered noticeably larger than the sun.
ICON_ENTITIES = {
    "sun":            "&#x2600;&#xFE0F;",
    "moon":           "&#x1F319;&#xFE0F;",
    "cloud":          "&#x2601;&#xFE0F;",
    "sun_cloud":      "&#x26C5;&#xFE0F;",
    "moon_cloud":     "&#x1F319;&#xFE0F;&#x2601;&#xFE0F;",
    "fog":            "&#x1F32B;&#xFE0F;",
    "rain_cloud":     "&#x1F327;&#xFE0F;",
    "sun_rain_cloud": "&#x1F326;&#xFE0F;",
    "snow":           "&#x2744;&#xFE0F;",
    "lightning":      "&#x26A1;&#xFE0F;",
}

# English descriptions by Buienradar icon letter (the feed text is Dutch).
WEATHER_DESCRIPTIONS_EN = {
    "a": "Clear", "b": "Partly cloudy", "j": "Partly cloudy", "c": "Cloudy",
    "d": "Fog", "n": "Fog", "f": "Light rain", "m": "Light rain",
    "q": "Rain", "w": "Rain", "g": "Thunderstorms possible",
    "s": "Thunderstorms possible", "t": "Heavy snow", "u": "Light snow",
    "v": "Light snow",
}
RAIN_DESCRIPTIONS = {
    "NL": ("Lichte regen", "Regen", "Zware regen"),
    "EN": ("Light rain", "Rain", "Heavy rain"),
}
DRY_SHAPES = ("sun", "moon", "sun_cloud", "moon_cloud", "cloud", "fog")
RAIN_ICON = ("rain_cloud", "#4FC3F7")

_COMPASS_DIRS = ["N", "NO", "O", "ZO", "Z", "ZW", "W", "NW"]
_COMPASS_DIRS_EN = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
_COMPASS_DIRS_BY_LANG = {
    "NL": _COMPASS_DIRS,
    "EN": _COMPASS_DIRS_EN,
}

def degrees_to_compass(degrees: float, language: str = "NL") -> str:
    dirs = _COMPASS_DIRS_BY_LANG.get(language, _COMPASS_DIRS)
    index = int((degrees + 22.5) // 45) % 8
    return dirs[index]

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

def http_get_with_retry(url: str, timeout: int = 10, retries: int = 3, retry_delay: float = 3.0) -> str:
    """GET a URL, retrying on transient server errors (5xx) and connection issues.

    The Buienradar feeds occasionally return 502/503/504 for a few seconds.
    A short retry with
    backoff resolves those without needing to wait for the next poll cycle.
    """
    attempt = 1
    while True:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt >= retries:
                raise
        except urllib.error.URLError:
            if attempt >= retries:
                raise
        time.sleep(retry_delay * attempt)
        attempt += 1

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

def parse_station_feed(raw: str) -> list:
    """Buienradar JSON feed -> list of weather stations that have a position."""
    data = json.loads(raw)
    measurements = (data.get("actual") or {}).get("stationmeasurements")
    if not isinstance(measurements, list):
        raise ValueError("no stationmeasurements")
    stations = []
    for item in measurements:
        if not isinstance(item, dict):
            continue
        try:
            station = {"name": re.sub(r"^Meetstation\s+", "", str(item.get("stationname") or "")),
                       "lat": float(item["lat"]), "lon": float(item["lon"])}
        except (KeyError, TypeError, ValueError):
            continue
        code = extract_icon_code(str(item.get("iconurl") or ""))
        station["icon_code"] = code if re.fullmatch(r"[a-z]{1,2}", code) else ""
        station["description"] = str(item.get("weatherdescription") or "").strip()
        try:
            station["temperature"] = float(item["temperature"])
        except (KeyError, TypeError, ValueError):
            pass
        try:
            station["windspeed_bft"] = max(0, min(12, int(item["windspeedBft"])))
            station["winddegrees"] = float(item["winddirectiondegrees"])
        except (KeyError, TypeError, ValueError):
            pass
        stations.append(station)
    return stations

def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    rad = math.pi / 180
    a = (math.sin((lat2 - lat1) * rad / 2) ** 2
         + math.cos(lat1 * rad) * math.cos(lat2 * rad) * math.sin((lon2 - lon1) * rad / 2) ** 2)
    return 6371 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def pick_weather_info(stations: list, lat: float, lon: float, language: str,
                      max_km: float = MAX_STATION_KM) -> Optional[dict]:
    """Current weather from the nearest station within max_km.

    The nearest station gives description and icon; a value it does not
    measure (temperature, wind) comes from the nearest station that does.
    """
    ranked = sorted(
        ((distance_km(lat, lon, s["lat"], s["lon"]), s) for s in stations),
        key=lambda item: item[0],
    )
    ranked = [item for item in ranked if item[0] <= max_km]
    if not ranked:
        return None
    nearest = ranked[0][1]
    code = nearest["icon_code"]
    letter = code[:1]
    description = nearest["description"]
    if language == "EN":
        description = WEATHER_DESCRIPTIONS_EN.get(letter, description)
    info = {
        "station": nearest["name"],
        "icon_code": code,
        "weatherdescription": description,
        "weatherdescription_nl": nearest["description"],
    }
    if code:
        # A doubled letter is the night icon.
        info["is_day"] = not (len(code) == 2 and code[0] == code[1])
    for _, station in ranked:
        if "temperature" not in info and "temperature" in station:
            info["temperature"] = station["temperature"]
        if "windspeed_bft" not in info and "windspeed_bft" in station:
            info["windspeed_bft"] = station["windspeed_bft"]
            info["winddirection"] = degrees_to_compass(station["winddegrees"], language)
    return info

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

def map_weather_icon_shape(weatherdescription: str, is_day: bool = True) -> Tuple[str, str]:
    desc = weatherdescription.lower()

    if "onweer" in desc or "bliksem" in desc:
        return "lightning", "#FFC107"
    if "hagel" in desc:
        return "snow", "#E0F7FA"
    if "sneeuw" in desc:
        return "snow", "#E0F7FA"
    if "mist" in desc or "nevel" in desc:
        return "fog", "#B0B0B0"
    if "bui" in desc:
        return "rain_cloud", "#5DADE2"
    if "motregen" in desc or "regen" in desc:
        return "rain_cloud", "#4FC3F7"
    if "onbewolkt" in desc or "zonnig" in desc or "helder" in desc:
        return ("sun", "#FFC107") if is_day else ("moon", "#4A6FA5")
    if "gedeeltelijk bewolkt" in desc or "opklaringen" in desc:
        return ("sun_cloud", "#FFC107") if is_day else ("moon_cloud", "#4A6FA5")
    if "bewolkt" in desc:
        return "cloud", "#D3D3D3"

    return DEFAULT_ICON

def resolve_weather_icon(weather_info: dict) -> Tuple[str, str]:
    """(shape, colour) from the Buienradar icon code, else from the description."""
    override = weather_info.get("icon_override")
    if override:
        return override
    weatherdescription = str(weather_info.get("weatherdescription_nl") or weather_info.get("weatherdescription") or "").strip()
    is_day = weather_info.get("is_day", True)
    return (
        map_icon_from_code(str(weather_info.get("icon_code") or ""))
        or (map_weather_icon_shape(weatherdescription, is_day) if weatherdescription else DEFAULT_ICON)
    )

def apply_rain_override(weather_info: Optional[dict], mm_now: float, language: str) -> Optional[dict]:
    """Make a dry icon/description agree with the rain radar.

    The weather station can be some km away and reports every 10 minutes, the
    radar shows the rain at the exact location. While the radar reports rain
    right now and the station still says clear, cloudy or fog, show a rain
    cloud and light rain / rain / heavy rain (by intensity). Snow and
    thunderstorms are kept.
    """
    if not weather_info or mm_now <= 0:
        return weather_info
    if resolve_weather_icon(weather_info)[0] not in DRY_SHAPES:
        return weather_info
    level = 0 if mm_now < 2.5 else 1 if mm_now < 7.6 else 2
    texts = RAIN_DESCRIPTIONS.get(language, RAIN_DESCRIPTIONS["NL"])
    return dict(weather_info, icon_override=RAIN_ICON, weatherdescription=texts[level])

def build_weather_icon_html(weather_info: Optional[dict]) -> str:
    if not weather_info:
        return ""

    weatherdescription = str(weather_info.get("weatherdescription") or "").strip()
    icon_shape, color = resolve_weather_icon(weather_info)
    icon_entity = ICON_ENTITIES.get(icon_shape)
    if not icon_entity:
        return ""
    alt = html.escape(weatherdescription or "weather", quote=True)

    return (f'<span title="{alt}" style="vertical-align: middle; color: {color}; '
            f'font-size: 1.5em; line-height: 1;">'
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
        self._weather_ticks = 0
        self._weather_ticks_needed = (POLL_WEATHER * 60) // self._heartbeat
        self._location_retry_ticks = 0
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

    def _read_migrated_parameter(self, field, legacy_field, default=""):
        """Read a named setting, falling back to its former ModeX field.

        Empty defaults on the new settings make existing Domoticz hardware
        configurations continue to work until they are saved with the new
        field names.
        """
        raw = Parameters.get(field, "")
        if raw is None or str(raw).strip() == "":
            raw = Parameters.get(legacy_field, "")
        if raw is None or str(raw).strip() == "":
            return default
        return raw

    def _read_migrated_boolean_parameter(self, field, legacy_field, default=False, extra_truthy=()):
        raw = self._read_migrated_parameter(field, legacy_field, "true" if default else "false")
        truthy = {"true", "1", "yes", "on"} | {v.lower() for v in extra_truthy}
        return str(raw).strip().lower() in truthy

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
        self._debug = self._read_migrated_boolean_parameter("EnableDebug", "Mode6", False, extra_truthy=("Debug",))
        self._language = str(self._read_migrated_parameter("Language", "Mode4", "NL"))
        if self._language not in LANGUAGE_TEXTS:
            self._language = "NL"
        self._text_mode = str(self._read_migrated_parameter("TextDeviceFormat", "Mode5", "temp_desc_logo_wind"))
        if self._text_mode not in TEXT_DEVICE_MODES:
            self._text_mode = "temp_desc_logo_wind"
        if self._debug:
            Domoticz.Debugging(1)

        self._load_device_icon()

        if not self._resolve_location():
            Domoticz.Log(
                "Location could not be resolved yet - will keep retrying "
                "periodically and start once it becomes available."
            )
            return

        self._start_polling()

    def _create_devices(self):
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

    def _start_polling(self):
        try:
            self._interval = max(1, int(self._read_migrated_parameter("PollInterval", "Mode3", "10")))
        except ValueError:
            self._interval = 10

        Domoticz.Heartbeat(self._heartbeat)

        self._create_devices()
        self._apply_device_icon()

        Domoticz.Log(f"Plugin started - version {self._plugin_version()}")
        Domoticz.Log(f"lat={self._lat}, lon={self._lon} ({self._location_source_summary()})")

        self._fetch_async(fetch_weather=True)

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

        if self._lat is None or self._lon is None:
            # Location isn't known yet (e.g. Domoticz Settings["Location"] was
            # blank at startup). Don't hammer the weather APIs with
            # lat=None&lon=None - periodically retry resolving the location
            # instead, and resume normal operation once it succeeds.
            self._location_retry_ticks += 1
            retry_ticks_needed = max(1, (self._interval * 60) // self._heartbeat)
            if self._location_retry_ticks < retry_ticks_needed:
                return
            self._location_retry_ticks = 0
            if not self._resolve_location():
                return
            Domoticz.Log("Location resolved - resuming normal operation.")
            self._start_polling()
            return

        self._ticks += 1
        self._weather_ticks += 1
        ticks_needed = (self._interval * 60) // self._heartbeat
        if self._ticks >= ticks_needed:
            self._ticks = 0
            fetch_weather = self._weather_ticks >= self._weather_ticks_needed
            if fetch_weather:
                self._weather_ticks = 0
            self._fetch_async(fetch_weather)

    def _resolve_location(self) -> bool:
        manual_lat_raw = self._read_migrated_parameter("Latitude", "Mode1", "")
        manual_lon_raw = self._read_migrated_parameter("Longitude", "Mode2", "")
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

    def _fetch_async(self, fetch_weather: bool = True):
        t = threading.Thread(target=self._fetch_and_update, args=(fetch_weather,), daemon=True)
        t.start()

    def _fetch_and_update(self, fetch_weather: bool = True):
        url = BUIENRADAR_URL.format(lat=self._lat, lon=self._lon)
        try:
            data = http_get_with_retry(url, timeout=10)
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

        # When fetch_weather is False, send None so onHeartbeat reuses the
        # last cached self._weather_info value instead of fetching a fresh one.
        weather_info = self._fetch_weather_info() if fetch_weather else None

        self.message_queue.put({
            "type": "data",
            "data": data,
            "weather_info": weather_info
        })

    def _fetch_weather_info(self) -> Optional[dict]:
        try:
            raw = http_get_with_retry(BUIENRADAR_FEED_URL, timeout=10)
        except urllib.error.HTTPError as e:
            self.message_queue.put({"type": "error", "msg": f"Buienradar weather feed HTTP error (status code: {e.code})"})
            return None
        except Exception as e:
            self.message_queue.put({"type": "error", "msg": f"Buienradar weather feed connection error: {e}"})
            return None

        try:
            stations = parse_station_feed(raw)
        except (ValueError, AttributeError):
            self.message_queue.put({"type": "error", "msg": "Unexpected format in Buienradar weather feed"})
            return None

        weather_info = pick_weather_info(stations, float(self._lat), float(self._lon), self._language)
        if weather_info is None:
            self.message_queue.put({"type": "error", "msg": f"No Buienradar weather station within {MAX_STATION_KM} km of this location"})
        return weather_info

    def _process(self, data: str, weather_info: Optional[dict]):
        p = parse_buienradar(data)
        status_html, status_log = build_status_text(p, self._language)
        status_html, status_log = append_weather_to_status(
            status_html,
            status_log,
            apply_rain_override(weather_info, p["mm_now"], self._language),
            self._text_mode
        )

        if UNIT_RAIN in Devices:
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
        elif self._debug:
            Domoticz.Debug(f"Skipping rain update - device unit {UNIT_RAIN} not found.")

        if UNIT_TEXT in Devices:
            text_dev = Devices[UNIT_TEXT]
            if text_dev.sValue != status_html:
                text_dev.Update(nValue=0, sValue=status_html)
        elif self._debug:
            Domoticz.Debug(f"Skipping text update - device unit {UNIT_TEXT} not found.")

        if weather_info and weather_info.get("temperature") is not None:
            self._process_temperature(weather_info["temperature"])

    def _process_temperature(self, temperature: float):
        if UNIT_TEMP not in Devices:
            if self._debug:
                Domoticz.Debug(f"Skipping temperature update - device unit {UNIT_TEMP} not found.")
            return

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

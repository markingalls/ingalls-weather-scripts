import argparse
import json
import os
import re
import statistics
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

import holidays
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
from matplotlib.patches import FancyBboxPatch

# ---------- fonts ----------
FONT_DIR = "/usr/share/fonts/truetype/google-fonts/"
f_bold = fm.FontProperties(fname=FONT_DIR + "Poppins-Bold.ttf")
f_reg = fm.FontProperties(fname=FONT_DIR + "Poppins-Regular.ttf")
f_med = fm.FontProperties(fname=FONT_DIR + "Poppins-Medium.ttf")

ICON_FONT = fm.FontProperties(fname="fonts/easy_weather_icons_font.ttf")

US_HOLIDAYS = holidays.US()


def is_weekend_or_holiday(date):
    return date.weekday() >= 5 or date in US_HOLIDAYS


def short_tz_abbr(tzname):
    """'PDT'/'PST' -> 'PT', 'AKDT'/'AKST' -> 'AKT', etc -- collapses the
    standard/daylight distinction a %Z abbreviation carries, since a TV-style
    graphic doesn't need to distinguish them. Non-DST abbreviations without
    that S/D pattern (e.g. 'UTC') pass through unchanged."""
    if len(tzname) >= 3 and tzname[-1] == "T" and tzname[-2] in "SD":
        return tzname[:-2] + "T"
    return tzname


# ---------- palette ----------
BG = "#f7f6f2"
INK = "#2b2a26"
INK_SECONDARY = "#5a584f"
CARD_FILL = "#ffffff"
CARD_EDGE = "#d8d5cc"
HIGHLIGHT_EDGE = "#164f29"  # forest green, in the spirit of the logo's pine tree

# icon color by condition category
COLOR_SUN = "#e8a33d"
COLOR_CLOUD = "#8a887c"
COLOR_RAIN = "#2f6fb0"
COLOR_SNOW = "#5aa9d6"
COLOR_STORM = "#5b4b8a"
COLOR_MUTED = "#9a9483"  # fog/haze/smoke/dust
COLOR_WIND = "#3f8f8f"
COLOR_SEVERE = "#c0392b"

# ---------- easy-weather-icons-font glyph names -> codepoints ----------
# Subset of https://github.com/boxbot6/easy-weather-icons-font relevant to
# NWS forecast icon codes, "day" variants only (see easy_weather_icons_font.json
# for the full IcoMoon glyph set -- MIT licensed, see fonts/LICENSE-easy-weather-icons-font.txt).
GLYPHS = {
    "UNKNOWNday": 0xe901,
    "CLEARday": 0xe96d,
    "FAIRday": 0xe970,
    "PARTLY_CLOUDYday": 0xe967,
    "PCLOUDYday": 0xe96a,
    "MOSTLY_CLOUDYday": 0xe961,
    "CLOUDYday": 0xe95e,
    "WINDYday": 0xe95b,
    "WINDY_CLOUDYday": 0xe9b5,
    "SNOWday": 0xe940,
    "MIXED_RAIN_SNOWday": 0xe916,
    "MIXED_RAIN_SLEETday": 0xe919,
    "MIXED_SNOW_SLEETday": 0xe91c,
    "FREEZING_RAINday": 0xe925,
    "SLEETday": 0xe946,
    "RAINday": 0xe92e,
    "SHOWERSday": 0xe928,
    "SCATTERED_SHOWERSday": 0xe979,
    "THUNDERSTORMSday": 0xe910,
    "THUNDERSHOWERSday": 0xe982,
    "ISOLATED_THUNDERSTORMSday": 0xe976,
    "TORNADOday": 0xe904,
    "HURRICANEday": 0xe90a,
    "TROPICAL_STORMday": 0xe907,
    "DUSTday": 0xe949,
    "SMOKYday": 0xe955,
    "HAZEday": 0xe952,
    "FOGGYday": 0xe94c,
    "BLOWING_SNOWday": 0xe93d,
    "DRIZZLEday": 0xe922,
    "HEAVY_SHOWERSday": 0xe931,
    "SNOW_FLURRIESday": 0xe934,
    "HEAVY_SNOWday": 0xe97c,
    "SNOW_SHOWERSday": 0xe988,
    "SEVERE_THUNDERSTORMSday": 0xe90d,
    "RAINDROPday": 0xea0c,
    "SNOWFLAKEday": 0xe9a6,
}

# ---------- precip indicator (chance-of-precip icon + probability + P25-75 total) ----------
# See fetch_ecmwf_ensemble_forecast.py -- WM-6's own precip variable has no
# percentiles/raw members, so this is sourced from Open-Meteo's 50-member
# ECMWF ensemble instead.
POP_THRESHOLD_MM = 0.5    # per-member daily total above which a member "has precip"
POP_DISPLAY_THRESHOLD = 0.20  # only show the indicator at all above this chance
LOW_POP_THRESHOLD = 0.5   # "low chance" for sun-backing purposes (see main())
# Above this, override NWS's own condition icon with a plain rain/snow icon
# entirely -- NWS's icon reflects its own forecast text, which can undersell
# the chance our ensemble-derived probability shows.
SIGNIFICANT_POP_THRESHOLD = 0.70
MM_PER_INCH = 25.4
CM_PER_INCH = 2.54

# Only give a chance-of-precip for the 05:00-23:59 local stretch of the day
# (excludes the 00:00-04:59 hours, which read more like "overnight" than
# "today" on a TV-style forecast). Also used to split into an AM/PM half for
# precip_timing() below.
PRECIP_DAY_START_HOUR = 5
MIDDAY_HOUR = 12
# AM/PM only gets labeled when the day's precip signal is lopsided toward
# one half; a 50/50-ish split (spans midday, or runs most of the day) gets
# no label at all.
TIMING_DOMINANT_FRAC = 0.75

# NWS forecast icon code (from the last path segment of the "icon" URL,
# e.g. https://api.weather.gov/icons/land/day/tsra,40 -> "tsra") -> (glyph, color)
NWS_ICON_MAP = {
    "skc": ("CLEARday", COLOR_SUN),
    "few": ("FAIRday", COLOR_SUN),
    "sct": ("PCLOUDYday", COLOR_SUN),
    "bkn": ("MOSTLY_CLOUDYday", COLOR_CLOUD),
    "ovc": ("CLOUDYday", COLOR_CLOUD),
    "wind_skc": ("WINDYday", COLOR_WIND),
    "wind_few": ("WINDYday", COLOR_WIND),
    "wind_sct": ("WINDY_CLOUDYday", COLOR_WIND),
    "wind_bkn": ("WINDY_CLOUDYday", COLOR_WIND),
    "wind_ovc": ("WINDY_CLOUDYday", COLOR_WIND),
    "snow": ("SNOWday", COLOR_SNOW),
    "rain_snow": ("MIXED_RAIN_SNOWday", COLOR_SNOW),
    "rain_sleet": ("MIXED_RAIN_SLEETday", COLOR_SNOW),
    "snow_sleet": ("MIXED_SNOW_SLEETday", COLOR_SNOW),
    "fzra": ("FREEZING_RAINday", COLOR_SNOW),
    "rain_fzra": ("FREEZING_RAINday", COLOR_SNOW),
    "snow_fzra": ("FREEZING_RAINday", COLOR_SNOW),
    "sleet": ("SLEETday", COLOR_SNOW),
    "rain": ("RAINday", COLOR_RAIN),
    "rain_showers": ("SHOWERSday", COLOR_RAIN),
    "rain_showers_hi": ("SCATTERED_SHOWERSday", COLOR_RAIN),
    "tsra": ("THUNDERSTORMSday", COLOR_STORM),
    "tsra_sct": ("THUNDERSHOWERSday", COLOR_STORM),
    "tsra_hi": ("ISOLATED_THUNDERSTORMSday", COLOR_STORM),
    "tornado": ("TORNADOday", COLOR_SEVERE),
    "hurricane": ("HURRICANEday", COLOR_SEVERE),
    "tropical_storm": ("TROPICAL_STORMday", COLOR_SEVERE),
    "dust": ("DUSTday", COLOR_MUTED),
    "smoke": ("SMOKYday", COLOR_MUTED),
    "haze": ("HAZEday", COLOR_MUTED),
    "hot": ("CLEARday", COLOR_SUN),
    "cold": ("CLEARday", COLOR_WIND),
    "blizzard": ("BLOWING_SNOWday", COLOR_SNOW),
    "fog": ("FOGGYday", COLOR_MUTED),
}


def icon_code_from_url(url):
    """https://api.weather.gov/icons/land/day/tsra,40?size=medium -> 'tsra'
    (drops the query string, the percent-chance suffix, and any second
    slash-separated condition -- we only show the dominant/first one)."""
    path = url.split("?")[0]
    after_day_night = path.split("land/")[-1].split("/", 1)[-1]
    first_condition = after_day_night.split("/")[0]
    return first_condition.split(",")[0]


# NWS codes (and WMO codes below) for precip icons with no native sun in
# their own glyph art -- used to decide whether stacking a sun glyph behind
# the main condition icon makes sense (see the sun-backing logic in main()'s
# render loop). skc/few/sct are deliberately excluded even though they're
# "chance of sun" conditions: CLEARday/FAIRday/PCLOUDYday already draw their
# own sun, so stacking another one behind them just doubles up (confirmed
# visually -- a skc day with a low/partial precip chance produced two
# overlapping suns). Also excludes persistent/guaranteed precip (rain, tsra)
# -- only the isolated/scattered "chance of" storm variants qualify.
SUN_RELEVANT_NWS_CODES = {"tsra_hi", "tsra_sct", "rain_showers_hi"}


def glyph_for(icon_url):
    code = icon_code_from_url(icon_url)
    name, color = NWS_ICON_MAP.get(code, ("UNKNOWNday", INK_SECONDARY))
    return chr(GLYPHS[name]), color, code in SUN_RELEVANT_NWS_CODES


# Open-Meteo's daily "weathercode" -> (glyph, color). Standard WMO weather
# interpretation codes (https://open-meteo.com/en/docs -> WMO Weather
# interpretation codes). Only used to backfill a condition icon for the one
# day beyond NWS's ~7-day coverage (see the after-3pm window shift below).
WMO_ICON_MAP = {
    0: ("CLEARday", COLOR_SUN),
    1: ("FAIRday", COLOR_SUN),
    2: ("PARTLY_CLOUDYday", COLOR_CLOUD),
    3: ("CLOUDYday", COLOR_CLOUD),
    45: ("FOGGYday", COLOR_MUTED),
    48: ("FOGGYday", COLOR_MUTED),
    51: ("DRIZZLEday", COLOR_RAIN),
    53: ("DRIZZLEday", COLOR_RAIN),
    55: ("DRIZZLEday", COLOR_RAIN),
    56: ("FREEZING_RAINday", COLOR_SNOW),
    57: ("FREEZING_RAINday", COLOR_SNOW),
    61: ("RAINday", COLOR_RAIN),
    63: ("RAINday", COLOR_RAIN),
    65: ("HEAVY_SHOWERSday", COLOR_RAIN),
    66: ("FREEZING_RAINday", COLOR_SNOW),
    67: ("FREEZING_RAINday", COLOR_SNOW),
    71: ("SNOWday", COLOR_SNOW),
    73: ("SNOWday", COLOR_SNOW),
    75: ("HEAVY_SNOWday", COLOR_SNOW),
    77: ("SNOW_FLURRIESday", COLOR_SNOW),
    80: ("SHOWERSday", COLOR_RAIN),
    81: ("SHOWERSday", COLOR_RAIN),
    82: ("HEAVY_SHOWERSday", COLOR_RAIN),
    85: ("SNOW_SHOWERSday", COLOR_SNOW),
    86: ("HEAVY_SNOWday", COLOR_SNOW),
    95: ("THUNDERSTORMSday", COLOR_STORM),
    96: ("SEVERE_THUNDERSTORMSday", COLOR_STORM),
    99: ("SEVERE_THUNDERSTORMSday", COLOR_STORM),
}


# Same reasoning as SUN_RELEVANT_NWS_CODES: only thunderstorm codes (no
# native sun in THUNDERSTORMSday/SEVERE_THUNDERSTORMSday) qualify, not
# clear/mainly-clear/partly-cloudy (0/1/2), which already draw their own sun.
SUN_RELEVANT_WMO_CODES = {95, 96, 99}


def glyph_for_wmo(weathercode):
    name, color = WMO_ICON_MAP.get(weathercode, ("UNKNOWNday", INK_SECONDARY))
    return chr(GLYPHS[name]), color, weathercode in SUN_RELEVANT_WMO_CODES


def daily_columns(periods, drop_today=False):
    """Pairs sequential (daytime, following-night) periods into up to 7 day
    columns: label/date/glyph from the daytime period, plus each period's
    own start/end so the caller can reduce a separate temperature series
    (MetaMesh's) over the same windows instead of using NWS's own
    temperature. If the feed starts overnight (fetched after sunset, before
    a Today period exists), that leading night period is dropped -- it has
    no daytime pair to lead a column.

    drop_today additionally drops the Today/Tonight pair, so the window
    starts tomorrow (renders after 3pm local -- see README). This only
    actually drops something if NWS's own feed still has a "Today" period;
    if the feed was fetched late enough that NWS has already moved past
    today on its own (periods[0] is already tomorrow, because today's day
    period no longer exists in the feed once it's over), there's nothing
    further to drop."""
    if periods and not periods[0]["isDaytime"]:
        periods = periods[1:]

    if drop_today and periods and periods[0]["name"] == "Today":
        periods = periods[2:]

    columns = []
    i = 0
    while i < len(periods) and len(columns) < 7:
        day = periods[i]
        night = periods[i + 1] if i + 1 < len(periods) and not periods[i + 1]["isDaytime"] else None
        glyph, color, sun_relevant = glyph_for(day["icon"])
        columns.append({
            "label": day["name"],
            "date": datetime.fromisoformat(day["startTime"]),
            "day_start": datetime.fromisoformat(day["startTime"]),
            "day_end": datetime.fromisoformat(day["endTime"]),
            "night_start": datetime.fromisoformat(night["startTime"]) if night else None,
            "night_end": datetime.fromisoformat(night["endTime"]) if night else None,
            "glyph": glyph,
            "glyph_color": color,
            "sun_relevant": sun_relevant,
        })
        i += 2
    return columns


# NWS's own day/night split for future (non-current) days -- confirmed
# against real fetched data (e.g. "Wednesday" 06:00-18:00, "Wednesday
# Night" 18:00-06:00 local). Reused for the synthetic day added beyond
# NWS's own coverage so every column reduces temperature over the same
# local-hour convention. The actual local timezone is resolved per-location
# from forecast.json's NWS-provided "timezone" (see main()), not hardcoded.
DAY_START_HOUR, DAY_END_HOUR = 6, 18


def local_day_window(date, local_tz):
    """(day_start, day_end, night_start, night_end) tz-aware datetimes for
    one calendar date, using NWS's own 6am-6pm/6pm-6am local split."""
    day_start = datetime.combine(date, dtime(DAY_START_HOUR), tzinfo=local_tz)
    day_end = datetime.combine(date, dtime(DAY_END_HOUR), tzinfo=local_tz)
    night_start = day_end
    night_end = datetime.combine(date + timedelta(days=1), dtime(DAY_START_HOUR), tzinfo=local_tz)
    return day_start, day_end, night_start, night_end


def openmeteo_weathercode_for_date(data, date):
    daily = data["daily"]
    idx = daily["time"].index(date.isoformat())
    return daily["weathercode"][idx]


def synthetic_column(date, openmeteo_data, local_tz):
    """A day/night column beyond NWS's own coverage: condition icon from
    Open-Meteo's daily weathercode (temperature gets filled in by
    attach_metamesh_temps() same as every other column, since MetaMesh's
    15-day horizon already reaches this far)."""
    day_start, day_end, night_start, night_end = local_day_window(date, local_tz)
    glyph, color, sun_relevant = glyph_for_wmo(openmeteo_weathercode_for_date(openmeteo_data, date))
    return {
        "label": date.strftime("%A"),
        "date": datetime.combine(date, dtime(0), tzinfo=local_tz),
        "day_start": day_start,
        "day_end": day_end,
        "night_start": night_start,
        "night_end": night_end,
        "glyph": glyph,
        "glyph_color": color,
        "sun_relevant": sun_relevant,
    }


def metamesh_temp_series(data):
    """(time, temperature_2m °C) pairs from a MetaMesh point-forecast
    response, sorted chronologically. MetaMesh is a deterministic
    multi-model blend rather than an ensemble, so there's a single value
    per timestep, not a distribution to reduce. Handles both a flat list
    of per-timestep records and a WM-6-style nested list (one inner list
    per requested station), since MetaMesh's exact response envelope isn't
    documented publicly and this was reverse-engineered against the API."""
    records = data.get("forecasts", [])
    if records and isinstance(records[0], list):
        records = records[0]
    series = [(datetime.fromisoformat(p["time"].replace("Z", "+00:00")), p["temperature_2m"])
              for p in records]
    series.sort(key=lambda item: item[0])
    return series


def reduce_temp_window(series, start, end, fn):
    """fn (max/min) over every sample whose time falls in [start, end).
    None if the window and the fetched series don't overlap (e.g.
    metamesh_forecast.json wasn't fetched far enough out)."""
    if start is None or end is None:
        return None
    values = [v for t, v in series if start <= t < end]
    return fn(values) if values else None


def c_to_f(celsius):
    return round(celsius * 9 / 5 + 32)


def attach_metamesh_temps(columns, temp_series):
    for col in columns:
        high_c = reduce_temp_window(temp_series, col["day_start"], col["day_end"], max)
        low_c = reduce_temp_window(temp_series, col["night_start"], col["night_end"], min)
        col["high"] = c_to_f(high_c) if high_c is not None else None
        col["low"] = c_to_f(low_c) if low_c is not None else None



# ---------- wind indicator (NWS gridpoints windSpeed/windGust/windDirection) ----------
# The human-readable periods forecast has a windSpeed range per period but no
# windGust field at all, so this is sourced from the raw gridpoints feed
# instead (see fetch_forecast.py), which carries proper time-series data for
# all three. Only shown when the day's conditions are notable enough to call
# out on a TV-style graphic.
WIND_SPEED_DISPLAY_THRESHOLD = 15  # mph -- show the section if sustained wind exceeds this
WIND_GUST_DISPLAY_THRESHOLD = 20   # mph -- ...and/or gusts exceed this

COMPASS_8 = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

_DURATION_RE = re.compile(r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?)?$")


def parse_iso8601_duration(duration_str):
    m = _DURATION_RE.match(duration_str)
    days = int(m.group("days") or 0)
    hours = int(m.group("hours") or 0)
    minutes = int(m.group("minutes") or 0)
    return timedelta(days=days, hours=hours, minutes=minutes)


def parse_valid_time(valid_time_str):
    """NWS gridpoints data's 'start/duration' format (e.g.
    '2026-07-28T12:00:00+00:00/PT4H') -> (start, end) tz-aware datetimes."""
    start_str, duration_str = valid_time_str.split("/")
    start = datetime.fromisoformat(start_str)
    return start, start + parse_iso8601_duration(duration_str)


def grid_interval_series(values):
    """(start, end, value) tuples from a NWS gridpoints value list, sorted
    chronologically. Skips null entries (e.g. windGust is omitted for calm
    stretches rather than given as 0)."""
    series = []
    for entry in values:
        if entry["value"] is None:
            continue
        start, end = parse_valid_time(entry["validTime"])
        series.append((start, end, entry["value"]))
    series.sort(key=lambda item: item[0])
    return series


def reduce_grid_window(series, start, end, fn):
    """fn (max/min) over every interval overlapping [start, end). None if
    the window and the fetched series don't overlap at all."""
    if start is None or end is None:
        return None
    values = [v for s, e, v in series if s < end and e > start]
    return fn(values) if values else None


def compass_letters(degrees):
    return COMPASS_8[round(degrees / 45) % 8]


def dominant_wind_direction(direction_series, start, end):
    """The compass direction that covers the most hours of [start, end),
    rather than a single sample -- wind direction typically shifts over a
    day, and this picks the one that best characterizes it."""
    if start is None or end is None:
        return None
    weights = {}
    for s, e, deg in direction_series:
        overlap_start, overlap_end = max(s, start), min(e, end)
        if overlap_start >= overlap_end:
            continue
        hours = (overlap_end - overlap_start).total_seconds() / 3600
        letter = compass_letters(deg)
        weights[letter] = weights.get(letter, 0) + hours
    return max(weights, key=weights.get) if weights else None


def round_to_5_mph(mph):
    return round(mph / 5) * 5


def attach_wind(columns, wind_data):
    speed_series = grid_interval_series(wind_data["speed"])
    gust_series = grid_interval_series(wind_data["gust"])
    direction_series = grid_interval_series(wind_data["direction"])

    for col in columns:
        start, end = col["day_start"], col["night_end"]
        speed_lo = reduce_grid_window(speed_series, start, end, min)
        speed_hi = reduce_grid_window(speed_series, start, end, max)
        gust_hi = reduce_grid_window(gust_series, start, end, max)

        col["wind"] = None
        speed_flagged = speed_hi is not None and speed_hi > WIND_SPEED_DISPLAY_THRESHOLD
        gust_flagged = gust_hi is not None and gust_hi > WIND_GUST_DISPLAY_THRESHOLD
        if speed_flagged or gust_flagged:
            col["wind"] = {
                "dir": dominant_wind_direction(direction_series, start, end),
                "lo": round_to_5_mph(speed_lo) if speed_lo is not None else None,
                "hi": round_to_5_mph(speed_hi) if speed_hi is not None else None,
                "gust": round_to_5_mph(gust_hi) if gust_hi is not None else None,
            }


def ensemble_member_daily_totals(hourly, variable, date, start_hour=0):
    """Each ensemble member's total for `variable` (precipitation or
    snowfall) summed over one local calendar date's hourly values from
    start_hour onward. Open-Meteo's ensemble times are plain local strings
    (no offset) since the fetch requests timezone=auto, so a date-prefix
    string match is enough -- no timezone parsing needed."""
    day_prefix = date.isoformat()
    idxs = [i for i, t in enumerate(hourly["time"])
            if t.startswith(day_prefix) and int(t[11:13]) >= start_hour]
    member_keys = sorted(k for k in hourly if k.startswith(variable + "_member"))
    return [sum(hourly[key][i] for i in idxs) for key in member_keys]


def precip_timing(hourly, date):
    """'AM' if the day's PRECIP_DAY_START_HOUR-23:59 precip signal (each
    hour's precipitation averaged across ensemble members) is concentrated
    before noon, 'PM' if concentrated at/after noon, None if it's split
    roughly evenly (spans midday, or runs through most of the day) -- no
    clean label in that case."""
    member_keys = sorted(k for k in hourly if k.startswith("precipitation_member"))
    day_prefix = date.isoformat()
    morning = afternoon = 0.0
    for i, t in enumerate(hourly["time"]):
        if not t.startswith(day_prefix):
            continue
        hour = int(t[11:13])
        if hour < PRECIP_DAY_START_HOUR:
            continue
        mean_mm = sum(hourly[k][i] for k in member_keys) / len(member_keys)
        if hour < MIDDAY_HOUR:
            morning += mean_mm
        else:
            afternoon += mean_mm

    total = morning + afternoon
    if total <= 0:
        return None
    morning_frac = morning / total
    if morning_frac >= TIMING_DOMINANT_FRAC:
        return "AM"
    if morning_frac <= 1 - TIMING_DOMINANT_FRAC:
        return "PM"
    return None


def round_rain_inches(inches):
    if inches < 0.3:
        return round(round(inches / 0.1) * 0.1, 1)
    return round(round(inches / 0.25) * 0.25, 2)


def round_snow_inches(inches):
    return round(round(inches / 0.5) * 0.5, 1)


def precip_summary(ecmwf_data, date):
    """None if there's nothing worth showing: chance of precip (fraction of
    ensemble members whose PRECIP_DAY_START_HOUR-23:59 daily total exceeds
    POP_THRESHOLD_MM) below POP_DISPLAY_THRESHOLD, or the rounded P25-P75
    total would just display as zero anyway. Otherwise a dict: pop (0-1),
    is_snow (day classified as snow if at least half the members show
    measurable snowfall), rounded p25_in/p75_in for whichever of rain/snow
    applies, and timing ('AM'/'PM'/None, see precip_timing())."""
    hourly = ecmwf_data["hourly"]
    precip_mm = ensemble_member_daily_totals(hourly, "precipitation", date, PRECIP_DAY_START_HOUR)
    snow_cm = ensemble_member_daily_totals(hourly, "snowfall", date, PRECIP_DAY_START_HOUR)

    pop = sum(1 for v in precip_mm if v > POP_THRESHOLD_MM) / len(precip_mm)
    if pop < POP_DISPLAY_THRESHOLD:
        return None

    is_snow = statistics.median(snow_cm) > 0
    if is_snow:
        totals_in = [v / CM_PER_INCH for v in snow_cm]
        round_inches = round_snow_inches
    else:
        totals_in = [v / MM_PER_INCH for v in precip_mm]
        round_inches = round_rain_inches

    p25_in = round_inches(float(np.percentile(totals_in, 25)))
    p75_in = round_inches(float(np.percentile(totals_in, 75)))
    if p75_in == 0:
        # the interquartile range rounds to nothing worth printing (e.g. a
        # 25% chance where even the 75th percentile is still ~dry) -- a
        # probability with "0.00" under it reads as broken, not informative.
        return None

    return {
        "pop": pop,
        "is_snow": is_snow,
        "p25_in": p25_in,
        "p75_in": p75_in,
        "timing": precip_timing(hourly, date),
    }


def attach_precip(columns, ecmwf_data):
    for col in columns:
        precip = precip_summary(ecmwf_data, col["date"].date())
        col["precip"] = precip
        if precip and precip["pop"] >= SIGNIFICANT_POP_THRESHOLD:
            name = "SNOWday" if precip["is_snow"] else "RAINday"
            col["glyph"] = chr(GLYPHS[name])
            col["glyph_color"] = COLOR_SNOW if precip["is_snow"] else COLOR_RAIN
            # a plain rain/snow icon is persistent/guaranteed precip, not
            # "chance of" -- no sun to show behind it (same reasoning as
            # excluding rain/tsra from SUN_RELEVANT_NWS_CODES).
            col["sun_relevant"] = False


# ---------- wildfire smoke override (NOAA HRRR VIS -- vertically-integrated smoke) ----------
# May-Oct only (wildfire smoke season) -- see fetch_hrrr_smoke_forecast.py.
# HRRR only runs 48h out, so in practice this only ever has data for the
# first day or two of the strip; later columns are simply left alone.
SMOKE_SEASON_MONTHS = {5, 6, 7, 8, 9, 10}
SMOKE_SUSTAINED_THRESHOLD_MG = 50   # mg/m^2 sustained for 3+ hours
SMOKE_SUSTAINED_HOURS = 3
SMOKE_SPIKE_THRESHOLD_MG = 200      # mg/m^2 in any single hour
PRECIP_GLYPH_COLORS = {COLOR_RAIN, COLOR_SNOW, COLOR_STORM}


def smoke_daytime_values(hourly, day_start, day_end):
    """(time, vis_smoke_mg_m2) pairs whose valid_time falls within a
    column's daytime window, sorted chronologically."""
    values = []
    for entry in hourly:
        t = datetime.strptime(entry["valid_time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=ZoneInfo("UTC"))
        if day_start <= t < day_end:
            values.append((t, entry["vis_smoke_mg_m2"]))
    values.sort(key=lambda item: item[0])
    return values


def smoke_triggered(values):
    if any(v > SMOKE_SPIKE_THRESHOLD_MG for _, v in values):
        return True
    for i in range(len(values) - SMOKE_SUSTAINED_HOURS + 1):
        window = values[i:i + SMOKE_SUSTAINED_HOURS]
        if all(v > SMOKE_SUSTAINED_THRESHOLD_MG for _, v in window):
            return True
    return False


def attach_smoke(columns, smoke_data):
    for col in columns:
        if col["date"].date().month not in SMOKE_SEASON_MONTHS:
            continue
        if col["glyph_color"] in PRECIP_GLYPH_COLORS:
            continue
        values = smoke_daytime_values(smoke_data["hourly"], col["day_start"], col["day_end"])
        if smoke_triggered(values):
            col["glyph"] = chr(GLYPHS["SMOKYday"])
            col["glyph_color"] = COLOR_MUTED
            col["sun_relevant"] = False


def parse_args():
    ap = argparse.ArgumentParser(description="Render the Tri-Cities TV-style 7-day forecast graphic.")
    ap.add_argument("--forecast", default="forecast.json",
                     help="NWS forecast (day/night periods, condition icons) from fetch_forecast.py")
    ap.add_argument("--metamesh-forecast", default="metamesh_forecast.json",
                     help="MetaMesh point temperature forecast (high/low source) from fetch_metamesh_forecast.py")
    ap.add_argument("--openmeteo-forecast", default="openmeteo_forecast.json",
                     help="Open-Meteo daily weathercode forecast, from fetch_openmeteo_forecast.py -- only "
                          "read when the window shift (see main()) needs a 7th day beyond NWS's coverage")
    ap.add_argument("--ecmwf-ensemble-forecast", default="ecmwf_ensemble_forecast.json",
                     help="Open-Meteo ECMWF ensemble forecast (chance-of-precip source), "
                          "from fetch_ecmwf_ensemble_forecast.py")
    ap.add_argument("--hrrr-smoke-forecast", default="hrrr_smoke_forecast.json",
                     help="NOAA HRRR vertically-integrated smoke forecast, from "
                          "fetch_hrrr_smoke_forecast.py -- only read May-Oct, and only if present "
                          "(HRRR only reaches 48h out, so most columns never use it anyway)")
    ap.add_argument("--output", default="tri_cities_7day_forecast.png")
    return ap.parse_args()


def main():
    args = parse_args()
    data = json.load(open(args.forecast))
    props = data["properties"]
    # Resolved per-location by fetch_forecast.py from NWS's own /points
    # response (properties.timeZone) -- not hardcoded, so this works
    # anywhere NWS covers, not just the Pacific time zone Tri-Cities sits in.
    local_tz = ZoneInfo(data["timezone"])

    # Local-time-of-day policy for what "today" means in the graphic:
    #  - before 7am: today's high hasn't happened yet and its low (tonight's,
    #    per the day/night pairing above) is still ahead too -- show both.
    #  - 7am-3pm: this morning's low already happened (the pre-dawn trough
    #    lands ~6-7am -- see the trough/peak timing check earlier in this
    #    project's history) and tonight's low is still hours off, so showing
    #    a "low" here would be neither a completed nor a near-term forecast
    #    -- blank it instead.
    #  - after 3pm: today's high has already happened or is happening (the
    #    peak lands ~3-5pm), so today stops being a forward-looking forecast
    #    at all -- drop it and start the window tomorrow, backfilling the
    #    resulting 7th day (beyond NWS's ~7-day coverage) from Open-Meteo.
    now_local = datetime.now(local_tz)
    drop_today = now_local.hour >= 15
    suppress_today_low = 7 <= now_local.hour < 15

    columns = daily_columns(props["periods"], drop_today=drop_today)

    if drop_today and len(columns) < 7:
        last_date = columns[-1]["date"].date() if columns else now_local.date()
        openmeteo_data = json.load(open(args.openmeteo_forecast))
        columns.append(synthetic_column(last_date + timedelta(days=1), openmeteo_data, local_tz))

    temp_series = metamesh_temp_series(json.load(open(args.metamesh_forecast)))
    attach_metamesh_temps(columns, temp_series)

    ecmwf_data = json.load(open(args.ecmwf_ensemble_forecast))
    attach_precip(columns, ecmwf_data)

    attach_wind(columns, data.get("wind", {"speed": [], "gust": [], "direction": []}))

    # Per-column month gating happens inside attach_smoke() itself (not here),
    # so a strip spanning a season boundary (e.g. late Oct into early Nov)
    # still gets the right columns checked -- this just skips the file
    # entirely on the (common) days it won't exist at all.
    if os.path.exists(args.hrrr_smoke_forecast):
        attach_smoke(columns, json.load(open(args.hrrr_smoke_forecast)))

    if suppress_today_low and columns:
        columns[0]["low"] = None

    fig = plt.figure(figsize=(12, 8.3), dpi=200)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    LEFT, RIGHT = 0.055, 0.965
    CARD_TOP, CARD_BOTTOM = 0.775, 0.135
    GUTTER = 0.012
    n = len(columns)
    card_w = (RIGHT - LEFT - (n - 1) * GUTTER) / n

    # Vertical zones within each card, top to bottom: day-of-week, date,
    # condition icon, precip chance, precip range, wind speed, wind gust,
    # high, low.
    DAY_Y = CARD_TOP - 0.045
    DATE_Y = CARD_TOP - 0.086
    ICON_Y = 0.565
    PRECIP_CHANCE_Y = 0.45
    PRECIP_RANGE_Y = 0.425
    WIND_SPEED_Y = 0.35
    WIND_GUST_Y = 0.325
    HIGH_Y = CARD_BOTTOM + 0.085
    LOW_Y = CARD_BOTTOM + 0.03

    for idx, col in enumerate(columns):
        x0 = LEFT + idx * (card_w + GUTTER)
        x1 = x0 + card_w
        cx = (x0 + x1) / 2
        is_highlighted = is_weekend_or_holiday(col["date"].date())

        card = FancyBboxPatch(
            (x0, CARD_BOTTOM), card_w, CARD_TOP - CARD_BOTTOM,
            boxstyle="round,pad=0,rounding_size=0.012",
            facecolor=CARD_FILL, edgecolor=HIGHLIGHT_EDGE if is_highlighted else CARD_EDGE,
            linewidth=1.8 if is_highlighted else 1.0, zorder=2)
        ax.add_patch(card)

        day_label = col["date"].strftime("%a").upper()
        ax.text(cx, DAY_Y, day_label, ha="center", va="top",
                 fontproperties=f_bold, fontsize=17,
                 color=HIGHLIGHT_EDGE if is_highlighted else INK, zorder=3)
        ax.text(cx, DATE_Y, col["date"].strftime("%b %-d"), ha="center", va="top",
                 fontproperties=f_reg, fontsize=10.5, color=INK_SECONDARY, zorder=3)

        precip = col.get("precip")
        is_partial_day = bool(precip and precip["timing"] is not None)
        is_low_chance = bool(precip and precip["pop"] < LOW_POP_THRESHOLD)

        # Sun peeking out from behind the main condition icon when that
        # condition is fundamentally "chance of/isolated/scattered X" (e.g.
        # NWS's tsra_hi -- isolated t-storms -- which our icon font can only
        # render as a plain storm cloud, no sun) and the precip itself is
        # either a low-confidence chance or confined to part of the day --
        # i.e. "still mostly a sunny day," not "count on getting rained on."
        show_sun_backing = precip and col.get("sun_relevant") and (is_low_chance or is_partial_day)
        if show_sun_backing:
            sun_text = ax.text(cx - 0.016, ICON_Y + 0.016, chr(GLYPHS["CLEARday"]), ha="center", va="center",
                                fontproperties=ICON_FONT, fontsize=48, color=COLOR_SUN, zorder=2.6)
            sun_text.set_path_effects([pe.withStroke(linewidth=2.2, foreground=COLOR_SUN)])

            # Solid white disc between the sun and the real icon, sized to
            # fully cover the icon's footprint. The icon font is thin-line
            # outline art -- mostly negative space inside the glyph -- so a
            # thickened copy of the glyph itself still leaves gaps the sun
            # shows through; a solid disc blocks it cleanly instead. Marker
            # size is in points (not data units), so it stays circular
            # regardless of the axes' non-square aspect ratio.
            ax.plot([cx], [ICON_Y], marker="o", markersize=34, markerfacecolor="white",
                     markeredgewidth=0, zorder=2.8)

        icon_text = ax.text(cx, ICON_Y, col["glyph"], ha="center", va="center",
                             fontproperties=ICON_FONT, fontsize=46, color=col["glyph_color"], zorder=3)
        # the icon font is a thin-stroke outline face with no bold weight of
        # its own -- stroking each glyph in its own fill color fattens the
        # outline so it reads as bold instead of drawing it twice.
        icon_text.set_path_effects([pe.withStroke(linewidth=1.8, foreground=col["glyph_color"])])

        if precip and precip["timing"]:
            ax.text(cx + 0.022, ICON_Y - 0.032, precip["timing"], ha="left", va="top",
                     fontproperties=f_bold, fontsize=10, color=INK_SECONDARY, zorder=3.1)

        if precip:
            precip_glyph = chr(GLYPHS["SNOWFLAKEday" if precip["is_snow"] else "RAINDROPday"])
            precip_color = COLOR_SNOW if precip["is_snow"] else COLOR_RAIN
            precip_icon_x = cx - 0.011

            pop_pct = round(precip["pop"] * 100 / 5) * 5
            ax.text(precip_icon_x, PRECIP_CHANCE_Y, precip_glyph, ha="right", va="center",
                     fontproperties=ICON_FONT, fontsize=15, color=precip_color, zorder=3)
            ax.text(cx - 0.005, PRECIP_CHANCE_Y, f"{pop_pct:.0f}%", ha="left", va="center",
                     fontproperties=f_med, fontsize=11.5, color=precip_color, zorder=3)

            p25_in, p75_in = precip["p25_in"], precip["p75_in"]
            amount_fmt = "{:.1f}" if precip["is_snow"] else "{:.2f}"
            amount_text = (f'{amount_fmt.format(p75_in)}"' if p25_in == p75_in
                           else f'{amount_fmt.format(p25_in)}"–{amount_fmt.format(p75_in)}"')
            ax.text(cx, PRECIP_RANGE_Y, amount_text, ha="center", va="center",
                     fontproperties=f_reg, fontsize=10.5, color=INK_SECONDARY, zorder=3)

        wind = col.get("wind")
        if wind:
            speed_lo, speed_hi = wind["lo"], wind["hi"]
            if speed_lo is None or speed_hi is None:
                speed_text = "—"
            elif speed_lo == speed_hi:
                speed_text = f"{speed_hi} mph"
            else:
                speed_text = f"{speed_lo}-{speed_hi} mph"
            wind_text = f"{wind['dir']} {speed_text}" if wind["dir"] else speed_text
            ax.text(cx, WIND_SPEED_Y, wind_text, ha="center", va="center",
                     fontproperties=f_med, fontsize=9.5, color=COLOR_WIND, zorder=3)

            if wind["gust"] is not None:
                ax.text(cx, WIND_GUST_Y, f"Gusts: {wind['gust']} mph", ha="center", va="center",
                         fontproperties=f_reg, fontsize=9.5, color=INK_SECONDARY, zorder=3)

        high_text = f"{col['high']}°" if col["high"] is not None else "—"
        ax.text(cx, HIGH_Y, high_text, ha="center", va="bottom",
                 fontproperties=f_bold, fontsize=20, color=INK, zorder=3)
        low_text = f"{col['low']}°" if col["low"] is not None else "—"
        ax.text(cx, LOW_Y, low_text, ha="center", va="bottom",
                 fontproperties=f_med, fontsize=15, color=INK_SECONDARY, zorder=3)

    # ---------- logo (top-left, sized to the title block) + title / subtitle ----------
    TITLE_BLOCK_TOP, TITLE_BLOCK_BOTTOM = 0.965, 0.878
    title_x = LEFT

    LOGO_PATH = "../assets/ingalls_weather_logo.png"
    if os.path.exists(LOGO_PATH):
        logo_img = plt.imread(LOGO_PATH)
        img_h, img_w = logo_img.shape[0], logo_img.shape[1]
        fig_w_in, fig_h_in = fig.get_size_inches()

        logo_height_fig = TITLE_BLOCK_TOP - TITLE_BLOCK_BOTTOM
        logo_height_in = logo_height_fig * fig_h_in
        logo_width_in = logo_height_in * (img_w / img_h)
        logo_width_fig = logo_width_in / fig_w_in

        # nudged up from TITLE_BLOCK_BOTTOM -- the title+subtitle text doesn't
        # fill the full reserved block (there's dead space below the
        # subtitle's descender), so top-aligning the logo to the block reads
        # as sitting low; this centers it on the text's actual visual span.
        logo_y0 = TITLE_BLOCK_BOTTOM + 0.012
        logo_ax = fig.add_axes([LEFT, logo_y0, logo_width_fig, logo_height_fig], zorder=20)
        logo_ax.imshow(logo_img)
        logo_ax.axis("off")

        title_x = LEFT + logo_width_fig + 0.018
    else:
        print(f"NOTE: no logo found at {LOGO_PATH} -- skipping logo placement.")

    generated = datetime.fromisoformat(props["generatedAt"]).astimezone(local_tz)
    fig.text(title_x, 0.935, f"{data.get('label', 'Tri-Cities')} 7-Day Forecast",
              fontproperties=f_bold, fontsize=24, color=INK)
    fig.text(title_x, 0.895, f"Updated {generated.strftime('%d %B %Y %H:%M')} {short_tz_abbr(generated.strftime('%Z'))}",
              fontproperties=f_reg, fontsize=12, color=INK_SECONDARY)

    # ---------- attribution ----------
    fig.text((LEFT + RIGHT) / 2, 0.045, "NWS/ECMWF/WM-6 • Ingalls Weather",
              fontproperties=f_reg, fontsize=9, color=INK_SECONDARY, ha="center")

    plt.savefig(args.output, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
    print(f"saved {args.output}")


if __name__ == "__main__":
    main()

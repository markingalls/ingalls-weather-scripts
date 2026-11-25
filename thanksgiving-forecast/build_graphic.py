import argparse
import json
import math
import os
import statistics
from datetime import date as ddate, datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
from matplotlib.patches import Circle, Ellipse, FancyBboxPatch, Polygon, Rectangle

# ---------- fonts ----------
# Same Poppins-with-Montserrat-fallback as tri-cities-7day-forecast/build_graphic.py.
FONT_DIR = "/usr/share/fonts/truetype/google-fonts/"
FALLBACK_FONT_DIR = "/usr/share/fonts/truetype/montserrat/"


def _load_font(poppins_name, fallback_name):
    poppins_path = FONT_DIR + poppins_name
    if os.path.exists(poppins_path):
        return fm.FontProperties(fname=poppins_path)
    return fm.FontProperties(fname=FALLBACK_FONT_DIR + fallback_name)


f_bold = _load_font("Poppins-Bold.ttf", "Montserrat-Bold.ttf")
f_reg = _load_font("Poppins-Regular.ttf", "Montserrat-Regular.ttf")
f_med = _load_font("Poppins-Medium.ttf", "Montserrat-Medium.ttf")

# Shared with the 7-day forecast rather than vendored a second time.
ICON_FONT = fm.FontProperties(fname="../tri-cities-7day-forecast/fonts/easy_weather_icons_font.ttf")


def short_tz_abbr(tzname):
    """'PDT'/'PST' -> 'PT' -- see tri-cities-7day-forecast/build_graphic.py."""
    if len(tzname) >= 3 and tzname[-1] == "T" and tzname[-2] in "SD":
        return tzname[:-2] + "T"
    return tzname


def clock_label(dt):
    return dt.strftime("%H:%M")



# ---------- palette (autumn harvest, in place of the 7-day's light theme) ----------
BG = "#2f1d14"              # deep roasted brown
TITLE_INK = "#fff6e8"
SUB_INK = "#e8cfae"
INK = "#3a2416"             # on-card text
INK_SECONDARY = "#7a5c45"
CARD_FILL = "#fffaf2"
CARD_EDGE = "#ead9c0"
ACCENT = "#c4501b"          # burnt orange
GOLD = "#e3a42b"
CRANBERRY = "#9e1f32"
LEAF_COLORS = [ACCENT, GOLD, CRANBERRY, "#d9772b", "#7d8b2e"]
TURKEY_BODY = "#8a5530"
TURKEY_HEAD = "#b5865a"
WATTLE = "#c8243a"
BEAK = "#f0b43c"
CRUST = "#d9a35a"
CRUST_DARK = "#a8732f"
PIE_FILLING = "#c8702a"
CREAM = "#fff6e8"

# icon color by condition category -- the 7-day's own palette, since the
# cards are near-white like the 7-day's
COLOR_SUN = "#e8a33d"
COLOR_MOON = "#7e6fb3"
COLOR_CLOUD = "#8a887c"
COLOR_RAIN = "#2f6fb0"
COLOR_SNOW = "#5aa9d6"
COLOR_STORM = "#5b4b8a"
COLOR_MUTED = "#9a9483"
COLOR_WIND = "#3f8f8f"
COLOR_SEVERE = "#c0392b"

# ---------- easy-weather-icons-font glyph names -> codepoints ----------
# "day" codepoints, same as tri-cities-7day-forecast/build_graphic.py. Every
# day glyph's night twin (moon in place of the sun) sits at the very next
# codepoint (CLEARday 0xe96d -> 0xe96e, FAIRday 0xe970 -> 0xe971, ...) --
# confirmed by rendering the font's full glyph sheet -- so night_glyph()
# just adds one rather than duplicating this table.
GLYPHS = {
    "UNKNOWNday": 0xe901,
    "CLEARday": 0xe96d,
    "FAIRday": 0xe970,
    "PCLOUDYday": 0xe96a,
    "MOSTLY_CLOUDYday": 0xe961,
    "CLOUDYday": 0xe95e,
    "OVERCAST": 0xe95d,
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
    "DUSTday": 0xe949,
    "SMOKYday": 0xe955,
    "HAZEday": 0xe952,
    "FOGGYday": 0xe94c,
    "BLOWING_SNOWday": 0xe93d,
    "RAINDROPday": 0xea0c,
    "SNOWFLAKEday": 0xe9a6,
}

# NWS forecast icon code -> (glyph, color). Same mapping as the 7-day.
NWS_ICON_MAP = {
    "skc": ("CLEARday", COLOR_SUN),
    "few": ("FAIRday", COLOR_SUN),
    "sct": ("PCLOUDYday", COLOR_SUN),
    "bkn": ("MOSTLY_CLOUDYday", COLOR_CLOUD),
    # plain cloud, no sun/moon -- CLOUDYday (the 7-day's choice) has a sun
    # peeking out, which reads wrong next to a "Cloudy" label at night
    "ovc": ("OVERCAST", COLOR_CLOUD),
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
    "dust": ("DUSTday", COLOR_MUTED),
    "smoke": ("SMOKYday", COLOR_MUTED),
    "haze": ("HAZEday", COLOR_MUTED),
    "hot": ("CLEARday", COLOR_SUN),
    "cold": ("CLEARday", COLOR_WIND),
    "blizzard": ("BLOWING_SNOWday", COLOR_SNOW),
    "fog": ("FOGGYday", COLOR_MUTED),
}

# Glyphs whose day art has a sun in it -- only these have a moon-swapped
# night twin worth using (a plain rain/snow/fog glyph's +1 is a different
# variant, not a night version).
GLYPHS_WITH_NIGHT_TWIN = {"CLEARday", "FAIRday", "PCLOUDYday", "MOSTLY_CLOUDYday"}


def icon_code_from_url(url):
    """https://api.weather.gov/icons/land/night/bkn,20?size=small -> 'bkn'"""
    path = url.split("?")[0]
    after_day_night = path.split("land/")[-1].split("/", 1)[-1]
    first_condition = after_day_night.split("/")[0]
    return first_condition.split(",")[0]


def glyph_for(icon_url, is_daytime):
    name, color = NWS_ICON_MAP.get(icon_code_from_url(icon_url), ("UNKNOWNday", INK_SECONDARY))
    codepoint = GLYPHS[name]
    if not is_daytime and name in GLYPHS_WITH_NIGHT_TWIN:
        codepoint += 1
        if color == COLOR_SUN:
            color = COLOR_MOON
    return chr(codepoint), color




# ---------- sunrise/sunset (NOAA's general solar position equations) ----------
def sun_times(day, lat, lon, local_tz):
    """Official (-0.833°) (sunrise, sunset) for a date, from NOAA's solar
    equations (https://gml.noaa.gov/grad/solcalc/solareqns.PDF) -- good to
    about a minute. Same math as halloween-trick-or-treat-forecast's
    sunset_local(), with sunrise added."""
    g = 2 * math.pi / 365 * (day.timetuple().tm_yday - 1)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                       - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    lat_r = math.radians(lat)
    ha = math.degrees(math.acos(math.cos(math.radians(90.833)) / (math.cos(lat_r) * math.cos(decl))
                                - math.tan(lat_r) * math.tan(decl)))
    solar_noon_utc_min = 720 - 4 * lon - eqtime
    midnight_utc = datetime.combine(day, dtime(0), tzinfo=timezone.utc)
    sunrise = midnight_utc + timedelta(minutes=solar_noon_utc_min - 4 * ha)
    sunset = midnight_utc + timedelta(minutes=solar_noon_utc_min + 4 * ha)
    return sunrise.astimezone(local_tz), sunset.astimezone(local_tz)


def round_to_minute(dt):
    return dt.replace(second=0, microsecond=0) + timedelta(minutes=dt.second >= 30)


# Civil twilight is ~30-35 minutes either side of sunrise/sunset this far
# north in November.
TWILIGHT_MINUTES = 35


def light_label(frame_time, sunrise, sunset):
    twilight = timedelta(minutes=TWILIGHT_MINUTES)
    if frame_time < sunrise - twilight or frame_time >= sunset + twilight:
        return "AFTER DARK" if frame_time >= sunset else "BEFORE DAWN"
    if frame_time < sunrise:
        return "DAWN"
    if frame_time >= sunset:
        return "DUSK"
    return "DAYLIGHT"


def nws_hour(hourly, frame_time):
    for period in hourly:
        if datetime.fromisoformat(period["startTime"]) <= frame_time < datetime.fromisoformat(period["endTime"]):
            return period
    return None


def parse_valid_time(valid_time_str):
    """NWS gridpoints 'start/duration' (e.g. '2026-10-31T23:00:00+00:00/PT3H')
    -> (start, end). Only hours/days ever show up in practice."""
    start_str, duration_str = valid_time_str.split("/")
    start = datetime.fromisoformat(start_str)
    days, _, rest = duration_str[1:].partition("D") if "D" in duration_str else ("0", "", duration_str[1:])
    hours = int(rest.strip("T").rstrip("H") or 0) if rest else 0
    return start, start + timedelta(days=int(days or 0), hours=hours)


def grid_value_at(values, frame_time):
    for entry in values:
        if entry["value"] is None:
            continue
        start, end = parse_valid_time(entry["validTime"])
        if start <= frame_time < end:
            return entry["value"]
    return None


def metamesh_value_at(data, frame_time, key):
    """A MetaMesh field (temperature_2m / apparent_temperature, °C) at
    exactly frame_time, or None. Handles
    both a flat and a WM-6-style nested record list, same as the 7-day's
    metamesh_temp_series()."""
    if not data:
        return None
    records = data.get("forecasts", [])
    if records and isinstance(records[0], list):
        records = records[0]
    for rec in records:
        if datetime.fromisoformat(rec["time"].replace("Z", "+00:00")) == frame_time:
            return rec.get(key)
    return None


# Chance of precip for a frame is over the 2 hours centered on it (the
# stretch around that point in the day someone would actually be out in),
# from the same 50 raw ECMWF members the 7-day uses. Open-Meteo's hourly
# precipitation is the sum over the *preceding* hour, so the frame hour's
# own value plus the next hour's covers [T-1h, T+1h).
PRECIP_WINDOW_HOURS = (0, 1)
POP_THRESHOLD_MM = 0.25         # a measurable ~0.01" in that 2h window
POP_DISPLAY_THRESHOLD = 0.20    # same display cutoff as the 7-day
SIGNIFICANT_POP_THRESHOLD = 0.70  # same icon-override cutoff as the 7-day


def precip_chance(ensemble, frame_time):
    hourly = ensemble["hourly"]
    wanted = {(frame_time + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in PRECIP_WINDOW_HOURS}
    idxs = [i for i, t in enumerate(hourly["time"]) if t in wanted]
    if len(idxs) != len(wanted):
        return None
    precip_keys = sorted(k for k in hourly if k.startswith("precipitation_member"))
    snow_keys = sorted(k for k in hourly if k.startswith("snowfall_member"))
    totals = [sum(hourly[k][i] or 0 for i in idxs) for k in precip_keys]
    snow = [sum(hourly[k][i] or 0 for i in idxs) for k in snow_keys]
    pop = sum(1 for v in totals if v > POP_THRESHOLD_MM) / len(totals)
    if pop < POP_DISPLAY_THRESHOLD:
        return None
    return {"pop": pop, "is_snow": statistics.median(snow) > 0}


def parse_nws_wind(period):
    """'5 to 10 mph' / '8 mph' -> top of the range as an int, or None."""
    nums = [int(tok) for tok in period["windSpeed"].split() if tok.isdigit()]
    return max(nums) if nums else None


def round_to_5_mph(mph):
    return round(mph / 5) * 5


WIND_GUST_DISPLAY_THRESHOLD = 20  # mph -- same as the 7-day's gust cutoff



WIND_TIP_THRESHOLD = 15  # mph sustained -- "careful with the turkey fryer" territory


def holiday_tips(frame):
    """Up to two short lines: what to wear, keyed to feels-like (or rain/snow
    gear at a likely precip chance), then one nudge for the day -- fog on
    the roads (common in the Tri-Cities' late-November inversions), a
    lower precip chance, wind for anyone frying a turkey outdoors, or
    headlights once it's dark."""
    tips = []
    feels = frame["feels_like"] if frame["feels_like"] is not None else frame["temp"]
    precip = frame["precip"]
    if precip and precip["pop"] >= 0.5:
        tips.append("Snow: slick roads, go slow" if precip["is_snow"] else "Rain: umbrella + jacket")
    elif feels is not None:
        if feels < 25:
            tips.append("Heavy coat, hat + gloves")
        elif feels < 35:
            tips.append("Winter coat + hat")
        elif feels < 45:
            tips.append("Warm jacket")
        elif feels < 55:
            tips.append("Light jacket")
        elif feels < 65:
            tips.append("Sweater weather")
        else:
            tips.append("Short sleeves!")
    is_foggy = "fog" in frame["condition"].lower()
    wind = max(frame["wind"] or 0, frame["gust"] or 0)
    if is_foggy:
        tips.append("Freezing fog: icy roads" if frame["temp"] is not None and frame["temp"] <= 32
                    else "Fog: low beams + extra time")
    elif precip and precip["pop"] < 0.5:
        tips.append("Chance of snow: watch roads" if precip["is_snow"] else "Umbrella, just in case")
    elif wind >= WIND_TIP_THRESHOLD:
        tips.append("Breezy: mind the turkey fryer")
    elif frame["light"] in ("DAWN", "DUSK"):
        tips.append("Low light: headlights on")
    elif frame["light"] != "DAYLIGHT":
        tips.append("Dark out: headlights on")
    return tips[:2]


def build_frame(data, frame_time, sunrise, sunset):
    period = nws_hour(data["hourly"], frame_time)
    if period is None:
        raise SystemExit(f"NWS hourly feed doesn't cover {frame_time.isoformat()} -- re-run fetch_forecast.py.")

    glyph, color = glyph_for(period["icon"], period["isDaytime"])
    mm_c = metamesh_value_at(data.get("metamesh"), frame_time, "temperature_2m")
    temp = round(mm_c * 9 / 5 + 32) if mm_c is not None else period["temperature"]
    # feels-like from the same source as the temperature it sits under (see
    # halloween-trick-or-treat-forecast/build_graphic.py's build_frame()).
    mm_feels_c = metamesh_value_at(data.get("metamesh"), frame_time, "apparent_temperature") if mm_c is not None else None
    feels = (mm_feels_c * 9 / 5 + 32 if mm_feels_c is not None
             else grid_value_at(data["apparent_temperature_f"], frame_time))
    # RRFS gusts when fetch_forecast.py got them (see its docstring), else
    # NWS's gridded windGust
    rrfs_gusts = (data.get("rrfs") or {}).get("gust_mph", {})
    rrfs_gust = rrfs_gusts.get(frame_time.astimezone(timezone.utc).isoformat())
    gust = rrfs_gust if rrfs_gust is not None else grid_value_at(data["wind_gust_mph"], frame_time)
    precip = precip_chance(data["ensemble"], frame_time)

    if precip and precip["pop"] >= SIGNIFICANT_POP_THRESHOLD:
        glyph = chr(GLYPHS["SNOWday" if precip["is_snow"] else "RAINday"])
        color = COLOR_SNOW if precip["is_snow"] else COLOR_RAIN

    wind = parse_nws_wind(period)
    frame = {
        "time": frame_time,
        "light": light_label(frame_time, sunrise, sunset),
        "glyph": glyph,
        "glyph_color": color,
        "condition": period["shortForecast"],
        "temp": temp,
        "temp_source": "metamesh" if mm_c is not None else "nws",
        "gust_source": "rrfs" if rrfs_gust is not None else "nws",
        "feels_like": round(feels) if feels is not None else None,
        "wind_dir": period.get("windDirection") or None,
        "wind": round_to_5_mph(wind) if wind is not None else None,
        "gust": round_to_5_mph(gust) if gust is not None and gust > WIND_GUST_DISPLAY_THRESHOLD else None,
        "precip": precip,
    }
    frame["tips"] = holiday_tips(frame)
    return frame


# ---------- decorations ----------
def _rotate(points, cx, cy, angle_deg, aspect):
    """Rotates (x, y) offsets about the origin, then places them at (cx, cy)
    with x squeezed by aspect (fig height / fig width) so shapes drawn in
    0-1 axes coordinates keep their proportions."""
    a = math.radians(angle_deg)
    return [(cx + (x * math.cos(a) - y * math.sin(a)) * aspect, cy + x * math.sin(a) + y * math.cos(a))
            for x, y in points]




# Right half of a maple leaf in unit coordinates (top tip at y=1, stem notch
# at the origin) -- mirrored for the left half in draw_leaf().
_MAPLE_HALF = [(0.0, 1.00), (0.12, 0.74), (0.27, 0.82), (0.22, 0.48), (0.46, 0.68), (0.53, 0.56),
               (0.82, 0.64), (0.68, 0.40), (0.88, 0.32), (0.50, 0.08), (0.58, -0.06), (0.30, -0.02),
               (0.24, -0.24), (0.06, -0.08), (0.0, -0.10)]
_MAPLE = _MAPLE_HALF + [(-x, y) for x, y in reversed(_MAPLE_HALF[1:-1])]
_MAPLE_CENTER_Y = 0.38  # midpoint of the leaf's own height, so (cx, cy) is its middle


def draw_leaf(ax, cx, cy, size, aspect, color, angle_deg=0):
    """A maple leaf with a short stem. size is roughly the leaf's height in
    axes units."""
    scale = size / 1.24
    points = [(x * scale, (y - _MAPLE_CENTER_Y) * scale) for x, y in _MAPLE]
    ax.add_patch(Polygon(_rotate(points, cx, cy, angle_deg, aspect), closed=True,
                         facecolor=color, edgecolor="none", zorder=1.4))
    stem = [(0, (-0.10 - _MAPLE_CENTER_Y) * scale), (0, (-0.42 - _MAPLE_CENTER_Y) * scale)]
    (x0, y0), (x1, y1) = _rotate(stem, cx, cy, angle_deg, aspect)
    ax.plot([x0, x1], [y0, y1], color=color, linewidth=1.2, solid_capstyle="round", zorder=1.4)


def draw_turkey(ax, cx, cy, h, aspect):
    """A front-facing cartoon turkey: fanned tail feathers in two rings,
    a round body, head with eyes, beak, and wattle, and little feet. (cx,
    cy) is the body's center; h is roughly the body height in axes units."""
    body_r = h / 2
    for ring_len, ring_w, z, colors in [(2.15, 0.55, 1.20, [CRANBERRY, ACCENT, GOLD]),
                                         (1.65, 0.50, 1.25, [GOLD, CRANBERRY, ACCENT])]:
        angles = range(-75, 76, 25)
        for i, a in enumerate(angles):
            length = body_r * ring_len
            t = math.radians(90 + a)
            fx, fy = math.cos(t) * length * 0.55, math.sin(t) * length * 0.55 + body_r * 0.15
            # each feather is an ellipse drawn as a polygon, since Ellipse's own
            # angle= would skew under the aspect squeeze
            feather = [(body_r * ring_w * math.cos(u), length / 2 * math.sin(u)) for u in
                       [math.radians(d) for d in range(0, 360, 15)]]
            ax.add_patch(Polygon(_rotate(feather, cx + fx * aspect, cy + fy, a, aspect), closed=True,
                                 facecolor=colors[i % 3], edgecolor=BG, linewidth=1.0, zorder=z))
    ax.add_patch(Ellipse((cx, cy), 2 * body_r * aspect, 2 * body_r * 1.05,
                         facecolor=TURKEY_BODY, edgecolor=BG, linewidth=1.0, zorder=1.3))
    head_y = cy + body_r * 0.95
    head_r = body_r * 0.48
    ax.add_patch(Ellipse((cx, head_y), 2 * head_r * aspect, 2 * head_r,
                         facecolor=TURKEY_HEAD, edgecolor=BG, linewidth=1.0, zorder=1.35))
    for side in (-1, 1):
        ax.add_patch(Ellipse((cx + side * head_r * 0.38 * aspect, head_y + head_r * 0.2),
                             head_r * 0.32 * aspect, head_r * 0.32, facecolor="white", edgecolor="none", zorder=1.4))
        ax.add_patch(Ellipse((cx + side * head_r * 0.38 * aspect, head_y + head_r * 0.18),
                             head_r * 0.15 * aspect, head_r * 0.15, facecolor=BG, edgecolor="none", zorder=1.41))
    ax.add_patch(Polygon([(cx - head_r * 0.22 * aspect, head_y - head_r * 0.05),
                          (cx + head_r * 0.22 * aspect, head_y - head_r * 0.05),
                          (cx, head_y - head_r * 0.45)], facecolor=BEAK, edgecolor="none", zorder=1.42))
    ax.add_patch(Ellipse((cx + head_r * 0.16 * aspect, head_y - head_r * 0.62), head_r * 0.28 * aspect,
                         head_r * 0.55, facecolor=WATTLE, edgecolor="none", zorder=1.41))
    for side in (-1, 1):
        fx = cx + side * body_r * 0.35 * aspect
        ax.plot([fx, fx], [cy - body_r * 1.0, cy - body_r * 1.3], color=BEAK, linewidth=2.2,
                 solid_capstyle="round", zorder=1.2)


def draw_pie(ax, cx, cy, r, aspect):
    """Pumpkin pie seen from above: crimped crust ring, filling, slice
    lines, and a dollop of whipped cream."""
    crimp = [((r * (1 + 0.06 * math.cos(math.radians(d) * 16))) * math.cos(math.radians(d)),
              (r * (1 + 0.06 * math.cos(math.radians(d) * 16))) * math.sin(math.radians(d)))
             for d in range(0, 360, 4)]
    ax.add_patch(Polygon(_rotate(crimp, cx, cy, 0, aspect), closed=True,
                         facecolor=CRUST, edgecolor=CRUST_DARK, linewidth=1.2, zorder=1.4))
    ax.add_patch(Ellipse((cx, cy), 2 * r * 0.78 * aspect, 2 * r * 0.78,
                         facecolor=PIE_FILLING, edgecolor="none", zorder=1.45))
    for d in range(0, 360, 60):
        (x0, y0), (x1, y1) = _rotate([(0, 0), (r * 0.78 * math.cos(math.radians(d)),
                                               r * 0.78 * math.sin(math.radians(d)))], cx, cy, 0, aspect)
        ax.plot([x0, x1], [y0, y1], color=CRUST_DARK, linewidth=1.0, alpha=0.6, zorder=1.5)
    for dx, dy, rr in [(0, 0, 0.26), (-0.10, 0.08, 0.16), (0.10, 0.07, 0.15)]:
        ax.add_patch(Ellipse((cx + dx * r * aspect, cy + dy * r), 2 * rr * r * aspect, 2 * rr * r,
                             facecolor=CREAM, edgecolor="none", zorder=1.55))


def center_text_row(fig, texts, cx, gap):
    """Lays left-aligned Text objects out side by side, gap apart, with the
    whole row centered on cx (axes/figure fraction -- the main axes fills
    the figure). Widths come from the rendered extents, since the icon
    glyph and the label are in different fonts."""
    renderer = fig.canvas.get_renderer()
    fig_w_px = fig.bbox.width
    widths = [t.get_window_extent(renderer).width / fig_w_px for t in texts]
    x = cx - (sum(widths) + gap * (len(texts) - 1)) / 2
    for text, width in zip(texts, widths):
        text.set_x(x)
        x += width + gap


def thanksgiving(year):
    """US Thanksgiving: the fourth Thursday of November."""
    first = ddate(year, 11, 1)
    first_thursday = first + timedelta(days=(3 - first.weekday()) % 7)
    return first_thursday + timedelta(weeks=3)


def default_date(today):
    day = thanksgiving(today.year)
    return day if day >= today else thanksgiving(today.year + 1)


DEFAULT_LABELS = ["TURKEY TROT", "TRAVEL + PREP", "DINNER TIME", "PIE + LEFTOVERS"]


def parse_args():
    ap = argparse.ArgumentParser(description="Render the Thanksgiving forecast at fixed hours through the day.")
    ap.add_argument("--forecast", default="forecast.json", help="from fetch_forecast.py")
    ap.add_argument("--date", help="Local date, YYYY-MM-DD (default: this year's Thanksgiving, or next year's once it's passed)")
    ap.add_argument("--hours", type=int, nargs="+", default=[7, 11, 15, 19], help="Local hours (24h) for each card")
    ap.add_argument("--labels", nargs="+", default=DEFAULT_LABELS,
                     help="Label above each card's time, one per --hours entry")
    ap.add_argument("--output", default="thanksgiving_forecast.png")
    args = ap.parse_args()
    if len(args.labels) != len(args.hours):
        ap.error("--labels needs one label per --hours entry")
    return args


def main():
    args = parse_args()
    data = json.load(open(args.forecast))
    local_tz = ZoneInfo(data["timezone"])
    now_local = datetime.now(local_tz)
    day = ddate.fromisoformat(args.date) if args.date else default_date(now_local.date())

    sunrise, sunset = sun_times(day, data["lat"], data["lon"], local_tz)
    frames = []
    for hour, label in zip(args.hours, args.labels):
        frame = build_frame(data, datetime.combine(day, dtime(hour), tzinfo=local_tz), sunrise, sunset)
        frame["role"] = label.upper()
        frames.append(frame)

    fig = plt.figure(figsize=(12, 8.3), dpi=200)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    fig_w_in, fig_h_in = fig.get_size_inches()
    aspect = fig_h_in / fig_w_in

    # top-right: a turkey with leaves drifting around it
    draw_turkey(ax, 0.905, 0.880, 0.072, aspect)
    for (lx, ly, size, angle), color in zip([(0.795, 0.945, 0.040, -20), (0.985, 0.960, 0.034, 25),
                                             (0.775, 0.855, 0.030, 40), (0.990, 0.815, 0.032, -35),
                                             (0.735, 0.915, 0.024, 10)], LEAF_COLORS):
        draw_leaf(ax, lx, ly, size, aspect, color, angle)

    LEFT, RIGHT = 0.055, 0.965
    CARD_TOP, CARD_BOTTOM = 0.775, 0.135
    GUTTER = 0.016
    n = len(frames)
    card_w = (RIGHT - LEFT - (n - 1) * GUTTER) / n

    # Vertical zones within each card, top to bottom: label, clock time,
    # light label, condition icon, condition text, temperature, feels-like,
    # precip/wind detail rows, divider, tips.
    ROLE_Y = CARD_TOP - 0.032
    TIME_Y = CARD_TOP - 0.062
    LIGHT_Y = CARD_TOP - 0.135
    ICON_Y = 0.540
    COND_Y = 0.462
    TEMP_Y = 0.395
    FEELS_Y = 0.345
    DETAIL_1_Y = 0.298
    DETAIL_2_Y = 0.268
    DIVIDER_Y = 0.238
    TIP_1_Y = 0.205
    TIP_2_Y = 0.170

    for idx, frame in enumerate(frames):
        x0 = LEFT + idx * (card_w + GUTTER)
        cx = x0 + card_w / 2

        ax.add_patch(FancyBboxPatch(
            (x0, CARD_BOTTOM), card_w, CARD_TOP - CARD_BOTTOM,
            boxstyle="round,pad=0,rounding_size=0.014",
            facecolor=CARD_FILL, edgecolor=CARD_EDGE, linewidth=1.0, zorder=2))

        ax.text(cx, ROLE_Y, frame["role"], ha="center", va="top",
                 fontproperties=f_bold, fontsize=10.5, color=ACCENT, zorder=3)
        ax.text(cx, TIME_Y, clock_label(frame["time"]), ha="center", va="top",
                 fontproperties=f_bold, fontsize=27, color=BG, zorder=3)
        ax.text(cx, LIGHT_Y, frame["light"], ha="center", va="top",
                 fontproperties=f_med, fontsize=10, color=INK_SECONDARY, zorder=3)

        icon_text = ax.text(cx, ICON_Y, frame["glyph"], ha="center", va="center",
                             fontproperties=ICON_FONT, fontsize=54, color=frame["glyph_color"], zorder=3)
        # same fake-bold stroke as the 7-day -- the icon font has no bold weight
        icon_text.set_path_effects([pe.withStroke(linewidth=2.0, foreground=frame["glyph_color"])])

        ax.text(cx, COND_Y, frame["condition"], ha="center", va="center",
                 fontproperties=f_reg, fontsize=11.5, color=INK, zorder=3)

        temp_text = f"{frame['temp']}°" if frame["temp"] is not None else "—"
        ax.text(cx, TEMP_Y, temp_text, ha="center", va="center",
                 fontproperties=f_bold, fontsize=36, color=INK, zorder=3)
        if frame["feels_like"] is not None:
            ax.text(cx, FEELS_Y, f"Feels like {frame['feels_like']}°", ha="center", va="center",
                     fontproperties=f_med, fontsize=11.5, color=INK_SECONDARY, zorder=3)

        # precip chance on its own row (blank when there's none) and wind
        # always on the row below, so wind sits on the same line across
        # every card whether or not the card has a precip chance
        precip = frame["precip"]
        if precip:
            precip_color = COLOR_SNOW if precip["is_snow"] else COLOR_RAIN
            precip_glyph = chr(GLYPHS["SNOWFLAKEday" if precip["is_snow"] else "RAINDROPday"])
            pop_pct = round(precip["pop"] * 100 / 5) * 5
            icon = ax.text(0, DETAIL_1_Y, precip_glyph, ha="left", va="center",
                            fontproperties=ICON_FONT, fontsize=14, color=precip_color, zorder=3)
            label = ax.text(0, DETAIL_1_Y, f"{pop_pct:.0f}% {'snow' if precip['is_snow'] else 'rain'}",
                             ha="left", va="center", fontproperties=f_med, fontsize=10.5,
                             color=precip_color, zorder=3)
            center_text_row(fig, [icon, label], cx, gap=0.004)
        if frame["wind"] is not None:
            y = DETAIL_2_Y
            wind_text = "Calm" if frame["wind"] == 0 else f"{frame['wind_dir'] or ''} {frame['wind']} mph".strip()
            if frame["gust"] is not None:
                wind_text += f" · Gusts {frame['gust']}"
            ax.text(cx, y, wind_text, ha="center", va="center",
                     fontproperties=f_med, fontsize=10.5, color=COLOR_WIND, zorder=3)

        ax.plot([x0 + card_w * 0.18, x0 + card_w * 0.82], [DIVIDER_Y, DIVIDER_Y],
                 color=CARD_EDGE, linewidth=1.0, zorder=3)
        for tip, y in zip(frame["tips"], [TIP_1_Y, TIP_2_Y]):
            ax.text(cx, y, tip, ha="center", va="center",
                     fontproperties=f_med, fontsize=10, color=ACCENT if y == TIP_1_Y else INK_SECONDARY,
                     zorder=3)

    # ---------- logo (top-left, round badge) + title / subtitle ----------
    TITLE_BLOCK_TOP, TITLE_BLOCK_BOTTOM = 0.965, 0.878
    title_x = LEFT

    LOGO_PATH = "../assets/ingalls_weather_logo.png"
    if os.path.exists(LOGO_PATH):
        logo_img = plt.imread(LOGO_PATH)
        img_h, img_w = logo_img.shape[0], logo_img.shape[1]
        logo_height_fig = TITLE_BLOCK_TOP - TITLE_BLOCK_BOTTOM
        logo_width_fig = logo_height_fig * fig_h_in * (img_w / img_h) / fig_w_in

        logo_ax = fig.add_axes([LEFT, TITLE_BLOCK_BOTTOM + 0.012, logo_width_fig, logo_height_fig], zorder=20)
        im = logo_ax.imshow(logo_img)
        # round badge, same as the Halloween and Crunchwrap versions -- the
        # logo's square light backdrop would read as a pasted-on box here
        im.set_clip_path(Circle((img_w / 2, img_h / 2), min(img_w, img_h) / 2, transform=logo_ax.transData))
        logo_ax.axis("off")

        title_x = LEFT + logo_width_fig + 0.018
    else:
        print(f"NOTE: no logo found at {LOGO_PATH} -- skipping logo placement.")

    fig.text(title_x, 0.935, "Thanksgiving Forecast",
              fontproperties=f_bold, fontsize=24, color=TITLE_INK)
    fig.text(title_x, 0.895,
              f"{data.get('label', 'Tri-Cities, WA')}  •  {day.strftime('%A, %B %-d')}  •  "
              f"Sunrise {clock_label(round_to_minute(sunrise))}  •  Sunset {clock_label(round_to_minute(sunset))}",
              fontproperties=f_reg, fontsize=12, color=SUB_INK)

    # ---------- attribution + pies + a row of fallen leaves ----------
    draw_pie(ax, LEFT + 0.035, 0.072, 0.036, aspect)
    draw_pie(ax, RIGHT - 0.035, 0.072, 0.036, aspect)
    for i in range(33):
        lx = 0.02 + i * 0.03
        draw_leaf(ax, lx, 0.014 + 0.006 * math.sin(i * 1.7), 0.022, aspect,
                  LEAF_COLORS[i % len(LEAF_COLORS)], angle_deg=(i * 47) % 90 - 45)
    uses_metamesh = all(f["temp_source"] == "metamesh" for f in frames)
    sources = "NWS/ECMWF/MetaMesh" if uses_metamesh else "NWS/ECMWF"
    if any(f["gust_source"] == "rrfs" for f in frames):
        sources += "/RRFS"
    fig.text((LEFT + RIGHT) / 2, 0.088,
              f"Updated {now_local.strftime('%d %B %Y %H:%M')} {short_tz_abbr(now_local.strftime('%Z'))}",
              fontproperties=f_reg, fontsize=9.5, color=SUB_INK, ha="center")
    fig.text((LEFT + RIGHT) / 2, 0.060, f"{sources} • Ingalls Weather • Happy Thanksgiving!",
              fontproperties=f_reg, fontsize=9.5, color=SUB_INK, ha="center")

    plt.savefig(args.output, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
    print(f"saved {args.output}")
    for f in frames:
        print(f"  {f['role']} {clock_label(f['time'])}: {f['temp']}° ({f['temp_source']}), feels {f['feels_like']}°, "
              f"{f['condition']}, {f['light']}, precip {f['precip']}, wind {f['wind_dir']} {f['wind']} "
              f"gust {f['gust']}, tips {f['tips']}")


if __name__ == "__main__":
    main()

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


def elapsed_label(td):
    """timedelta(hours=4, minutes=59, seconds=24) -> '4:59:24' -- race-clock style."""
    seconds = round(td.total_seconds())
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def parse_race_time(text):
    """'4:59:24' / '12:00:00' / '5:00' (H:MM) -> timedelta."""
    parts = [int(p) for p in text.split(":")]
    hours, minutes, seconds = (parts + [0, 0])[:3]
    return timedelta(hours=hours, minutes=minutes, seconds=seconds)


# ---------- palette (fast-food purple in place of the 7-day's light theme) ----------
# Taco-shop colors only -- no restaurant logos or slogans, which are
# trademarked and would read as an official/sponsored graphic.
BG = "#2b0f47"              # deep purple
TITLE_INK = "#ffffff"
SUB_INK = "#d9c8ee"
INK = "#2a1640"             # on-card text
INK_SECONDARY = "#6e5a85"
CARD_FILL = "#ffffff"
CARD_EDGE = "#e3d6f0"
MAGENTA = "#d6187a"
CHEESE = "#ffc629"
TORTILLA = "#e8b86a"
TORTILLA_DARK = "#c98f3c"
GRILL = "#8a5a22"
LETTUCE = "#7cc242"
TOMATO = "#e2412e"
SAUCE_COLORS = ["#f28c28", "#d7262e", MAGENTA, CHEESE]

# icon color by condition category -- the 7-day's own palette, since the
# cards are white like the 7-day's
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


# Chance of precip for a frame is over the 2 hours centered on it (what a
# runner actually moves through around that point in the race),
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



def runner_tips(frame):
    """Up to two short lines of what-to-wear advice for runners, keyed to
    feels-like. Runners warm up fast, so these run a good 15-20° lighter
    than what you'd tell someone standing around -- then one extra nudge
    (a light shell, wind, a headlamp after dark, a throwaway layer at a
    cold start)."""
    tips = []
    feels = frame["feels_like"] if frame["feels_like"] is not None else frame["temp"]
    precip = frame["precip"]
    if precip and precip["pop"] >= 0.5:
        tips.append("Traction + waterproof layers" if precip["is_snow"] else "Rain shell + dry socks")
    elif feels is not None:
        if feels < 25:
            tips.append("Tights, hat, gloves, layers")
        elif feels < 35:
            tips.append("Tights, hat + gloves")
        elif feels < 45:
            tips.append("Long sleeves + gloves")
        elif feels < 55:
            tips.append("Long sleeves or a tee")
        elif feels < 65:
            tips.append("Tee + shorts weather")
        elif feels < 75:
            tips.append("Singlet + sip often")
        else:
            tips.append("Hot: extra water + ice")
    if precip and precip["pop"] < 0.5:
        tips.append("Pack a light shell")
    elif frame["gust"] is not None and frame["gust"] >= 25:
        tips.append("Gusty: tuck in behind a pack")
    elif frame["light"] in ("AFTER DARK", "BEFORE DAWN", "DUSK", "DAWN"):
        tips.append("Headlamp + reflective gear")
    elif frame["is_start"] and feels is not None and feels < 45:
        tips.append("Throwaway layer for the start")
    return tips[:2]


def build_frame(data, clock_time, sunrise, sunset, is_start):
    # The card shows the real clock time (12:59:24 -> "12:59"), but every
    # feed here is hourly and MetaMesh/the ensemble only match on the hour,
    # so the weather comes from the nearest top of the hour.
    frame_time = (clock_time + timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0)
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
    gust = grid_value_at(data["wind_gust_mph"], frame_time)
    precip = precip_chance(data["ensemble"], frame_time)

    if precip and precip["pop"] >= SIGNIFICANT_POP_THRESHOLD:
        glyph = chr(GLYPHS["SNOWday" if precip["is_snow"] else "RAINday"])
        color = COLOR_SNOW if precip["is_snow"] else COLOR_RAIN

    wind = parse_nws_wind(period)
    frame = {
        "time": clock_time,
        "is_start": is_start,
        "light": light_label(clock_time, sunrise, sunset),
        "glyph": glyph,
        "glyph_color": color,
        "condition": period["shortForecast"],
        "temp": temp,
        "temp_source": "metamesh" if mm_c is not None else "nws",
        "feels_like": round(feels) if feels is not None else None,
        "wind_dir": period.get("windDirection") or None,
        "wind": round_to_5_mph(wind) if wind is not None else None,
        "gust": round_to_5_mph(gust) if gust is not None and gust > WIND_GUST_DISPLAY_THRESHOLD else None,
        "precip": precip,
    }
    frame["tips"] = runner_tips(frame)
    return frame


# ---------- decorations ----------
def _rotate(points, cx, cy, angle_deg, aspect):
    """Rotates (x, y) offsets about the origin, then places them at (cx, cy)
    with x squeezed by aspect (fig height / fig width) so shapes drawn in
    0-1 axes coordinates keep their proportions."""
    a = math.radians(angle_deg)
    return [(cx + (x * math.cos(a) - y * math.sin(a)) * aspect, cy + x * math.sin(a) + y * math.cos(a))
            for x, y in points]


def draw_crunchwrap(ax, cx, cy, r, aspect, angle_deg=0):
    """A grilled, folded hexagon: tortilla body, six pinwheel folds meeting
    in the middle, and a few grill marks."""
    hexagon = [(r * math.cos(math.radians(60 * i + 30)), r * math.sin(math.radians(60 * i + 30))) for i in range(6)]
    ax.add_patch(Polygon(_rotate(hexagon, cx, cy, angle_deg, aspect), closed=True,
                         facecolor=TORTILLA, edgecolor=TORTILLA_DARK, linewidth=2.0, zorder=1.4))
    for i in range(6):
        vx, vy = hexagon[i]
        nx, ny = hexagon[(i + 1) % 6]
        # each fold runs from a vertex to a point partway toward the center,
        # nudged toward the next vertex -- the pinwheel a folded wrap makes
        fx, fy = 0.30 * vx + 0.12 * nx, 0.30 * vy + 0.12 * ny
        (x0, y0), (x1, y1) = _rotate([(vx, vy), (fx, fy)], cx, cy, angle_deg, aspect)
        ax.plot([x0, x1], [y0, y1], color=TORTILLA_DARK, linewidth=1.6, solid_capstyle="round", zorder=1.5)
    for off in (-0.35, 0.0, 0.35):
        (x0, y0), (x1, y1) = _rotate([(off * r - 0.28 * r, -0.28 * r), (off * r + 0.28 * r, 0.28 * r)],
                                     cx, cy, angle_deg, aspect)
        ax.plot([x0, x1], [y0, y1], color=GRILL, linewidth=2.6, alpha=0.55, solid_capstyle="round", zorder=1.5)


def draw_sauce_packet(ax, cx, cy, h, aspect, color, angle_deg=0):
    w = h * 0.62
    body = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
    band = [(-w / 2, h / 2 - h * 0.22), (w / 2, h / 2 - h * 0.22), (w / 2, h / 2), (-w / 2, h / 2)]
    ax.add_patch(Polygon(_rotate(body, cx, cy, angle_deg, aspect), closed=True,
                         facecolor=color, edgecolor="none", zorder=1.4, joinstyle="round"))
    ax.add_patch(Polygon(_rotate(band, cx, cy, angle_deg, aspect), closed=True,
                         facecolor="white", edgecolor="none", alpha=0.35, zorder=1.45))


def draw_taco(ax, cx, cy, w, aspect):
    """A hard-shell taco lying on its side: domed shell on top, with
    lettuce, tomato, and cheese spilling out along the open edge below."""
    h = w * 0.55
    # lettuce fringe -- a scalloped band just under the shell's open edge
    xs = [w * 0.49 * (i / 20 - 1) for i in range(41)]
    fringe = ([(x, -0.10 * h - 0.06 * h * math.cos(x / w * 14 * math.pi)) for x in xs]
              + [(w * 0.49, 0.02 * h), (-w * 0.49, 0.02 * h)])
    ax.add_patch(Polygon(_rotate(fringe, cx, cy, 0, aspect), closed=True,
                         facecolor=LETTUCE, edgecolor="none", zorder=1.9))
    for dx in (-0.30, -0.02, 0.26):
        ax.add_patch(Ellipse((cx + dx * w * aspect, cy - 0.12 * h), 0.11 * w * aspect, 0.11 * w,
                             facecolor=TOMATO, edgecolor="none", zorder=1.95))
    for dx in (-0.16, 0.12, 0.38):
        ax.add_patch(Rectangle((cx + dx * w * aspect, cy - 0.20 * h), 0.035 * w * aspect, 0.16 * h,
                               facecolor=CHEESE, edgecolor="none", zorder=1.97))
    shell = [(w / 2 * math.cos(math.radians(t)), h * math.sin(math.radians(t))) for t in range(0, 181, 6)]
    ax.add_patch(Polygon(_rotate(shell, cx, cy, 0, aspect), closed=True,
                         facecolor=TORTILLA, edgecolor=TORTILLA_DARK, linewidth=1.5, zorder=2))
    # the shell's inner fold, a smaller arc inside the dome
    inner = _rotate([(w * 0.36 * math.cos(math.radians(t)), h * 0.72 * math.sin(math.radians(t)))
                     for t in range(10, 171, 8)], cx, cy, 0, aspect)
    ax.plot([x for x, _ in inner], [y for _, y in inner], color=TORTILLA_DARK, linewidth=1.2, zorder=2.05)


def draw_checkered_strip(ax, y0, square_in, fig_w_in, fig_h_in):
    """A two-row finish-line band across the full width of the canvas, with
    true squares (sized in inches, since the canvas isn't square)."""
    sq_w = square_in / fig_w_in
    sq_h = square_in / fig_h_in
    n = math.ceil(1 / sq_w)
    for row in range(2):
        for i in range(n):
            if (i + row) % 2 == 0:
                ax.add_patch(Rectangle((i * sq_w, y0 + row * sq_h), sq_w, sq_h,
                                       facecolor="white", edgecolor="none", alpha=0.9, zorder=1))


def next_saturday(today):
    return today + timedelta(days=(5 - today.weekday()) % 7)


def parse_args():
    ap = argparse.ArgumentParser(description="Render the Crunchwrap Crawl race-day forecast: start, last year's winner, and cutoff.")
    ap.add_argument("--forecast", default="forecast.json", help="from fetch_forecast.py")
    ap.add_argument("--date", help="Local race date, YYYY-MM-DD (default: the coming Saturday)")
    ap.add_argument("--start", default="08:00", help="Local start time, HH:MM")
    ap.add_argument("--winner", default="4:59:24",
                     help="Last year's winning time, H:MM:SS -- the middle card")
    ap.add_argument("--limit", default="12:00:00", help="Time limit, H:MM:SS -- the cutoff card")
    ap.add_argument("--output", default="crunchwrap_crawl_forecast.png")
    return ap.parse_args()


def main():
    args = parse_args()
    data = json.load(open(args.forecast))
    local_tz = ZoneInfo(data["timezone"])
    now_local = datetime.now(local_tz)
    race_day = ddate.fromisoformat(args.date) if args.date else next_saturday(now_local.date())

    sunrise, sunset = sun_times(race_day, data["lat"], data["lon"], local_tz)
    start = datetime.combine(race_day, dtime.fromisoformat(args.start), tzinfo=local_tz)
    winner = parse_race_time(args.winner)
    limit = parse_race_time(args.limit)
    stages = [
        ("START", start, True),
        (f"LAST YEAR WINNER - {elapsed_label(winner)}", start + winner, False),
        (f"CUTOFF - {elapsed_label(limit)}", start + limit, False),
    ]
    frames = []
    for role, frame_time, is_start in stages:
        frame = build_frame(data, frame_time, sunrise, sunset, is_start)
        frame["role"] = role
        frames.append(frame)

    fig = plt.figure(figsize=(12, 8.3), dpi=200)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    fig_w_in, fig_h_in = fig.get_size_inches()
    aspect = fig_h_in / fig_w_in

    # top-right: a big crunchwrap with sauce packets scattered around it, in
    # the spot the Halloween version's moon sits
    draw_crunchwrap(ax, 0.905, 0.905, 0.062, aspect, angle_deg=12)
    for (px, py, ph, angle), color in zip([(0.815, 0.935, 0.042, -22), (0.985, 0.835, 0.038, 18),
                                           (0.835, 0.848, 0.034, 30), (0.972, 0.965, 0.032, -12)],
                                          SAUCE_COLORS):
        draw_sauce_packet(ax, px, py, ph, aspect, color, angle)

    LEFT, RIGHT = 0.055, 0.965
    CARD_TOP, CARD_BOTTOM = 0.775, 0.135
    GUTTER = 0.022
    n = len(frames)
    card_w = (RIGHT - LEFT - (n - 1) * GUTTER) / n

    # Vertical zones within each card, top to bottom: race stage, clock
    # time, light label, condition icon, condition text, temperature,
    # feels-like, precip/wind detail rows, divider, runner tips.
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
                 fontproperties=f_bold, fontsize=12.5, color=MAGENTA, zorder=3)
        ax.text(cx, TIME_Y, clock_label(frame["time"]), ha="center", va="top",
                 fontproperties=f_bold, fontsize=30, color=BG, zorder=3)
        ax.text(cx, LIGHT_Y, frame["light"], ha="center", va="top",
                 fontproperties=f_med, fontsize=10.5, color=INK_SECONDARY, zorder=3)

        icon_text = ax.text(cx, ICON_Y, frame["glyph"], ha="center", va="center",
                             fontproperties=ICON_FONT, fontsize=60, color=frame["glyph_color"], zorder=3)
        # same fake-bold stroke as the 7-day -- the icon font has no bold weight
        icon_text.set_path_effects([pe.withStroke(linewidth=2.0, foreground=frame["glyph_color"])])

        ax.text(cx, COND_Y, frame["condition"], ha="center", va="center",
                 fontproperties=f_reg, fontsize=12.5, color=INK, zorder=3)

        temp_text = f"{frame['temp']}°" if frame["temp"] is not None else "—"
        ax.text(cx, TEMP_Y, temp_text, ha="center", va="center",
                 fontproperties=f_bold, fontsize=40, color=INK, zorder=3)
        if frame["feels_like"] is not None:
            ax.text(cx, FEELS_Y, f"Feels like {frame['feels_like']}°", ha="center", va="center",
                     fontproperties=f_med, fontsize=12.5, color=INK_SECONDARY, zorder=3)

        # precip chance (if any) then wind, packed into the two detail rows
        detail_ys = iter([DETAIL_1_Y, DETAIL_2_Y])
        precip = frame["precip"]
        if precip:
            y = next(detail_ys)
            precip_color = COLOR_SNOW if precip["is_snow"] else COLOR_RAIN
            precip_glyph = chr(GLYPHS["SNOWFLAKEday" if precip["is_snow"] else "RAINDROPday"])
            pop_pct = round(precip["pop"] * 100 / 5) * 5
            ax.text(cx - 0.006, y, precip_glyph, ha="right", va="center",
                     fontproperties=ICON_FONT, fontsize=15, color=precip_color, zorder=3)
            ax.text(cx, y, f"{pop_pct:.0f}% {'snow' if precip['is_snow'] else 'rain'}", ha="left", va="center",
                     fontproperties=f_med, fontsize=11.5, color=precip_color, zorder=3)
        if frame["wind"] is not None:
            y = next(detail_ys)
            wind_text = "Calm" if frame["wind"] == 0 else f"{frame['wind_dir'] or ''} {frame['wind']} mph".strip()
            if frame["gust"] is not None:
                wind_text += f" · Gusts {frame['gust']}"
            ax.text(cx, y, wind_text, ha="center", va="center",
                     fontproperties=f_med, fontsize=11, color=COLOR_WIND, zorder=3)

        ax.plot([x0 + card_w * 0.18, x0 + card_w * 0.82], [DIVIDER_Y, DIVIDER_Y],
                 color=CARD_EDGE, linewidth=1.0, zorder=3)
        for tip, y in zip(frame["tips"], [TIP_1_Y, TIP_2_Y]):
            ax.text(cx, y, tip, ha="center", va="center",
                     fontproperties=f_med, fontsize=11.5, color=MAGENTA if y == TIP_1_Y else INK_SECONDARY,
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
        # round badge, same as the Halloween version -- the logo's square
        # light backdrop would read as a pasted-on box against the purple
        im.set_clip_path(Circle((img_w / 2, img_h / 2), min(img_w, img_h) / 2, transform=logo_ax.transData))
        logo_ax.axis("off")

        title_x = LEFT + logo_width_fig + 0.018
    else:
        print(f"NOTE: no logo found at {LOGO_PATH} -- skipping logo placement.")

    fig.text(title_x, 0.935, "Crunchwrap Crawl Race-Day Forecast",
              fontproperties=f_bold, fontsize=24, color=TITLE_INK)
    fig.text(title_x, 0.895,
              f"{data.get('label', 'Tri-Cities, WA')}  •  {race_day.strftime('%A, %B %-d')}  •  "
              f"Sunrise {clock_label(round_to_minute(sunrise))}  •  Sunset {clock_label(round_to_minute(sunset))}",
              fontproperties=f_reg, fontsize=12, color=SUB_INK)

    # ---------- attribution + tacos + finish line ----------
    draw_taco(ax, LEFT + 0.035, 0.070, 0.075, aspect)
    draw_taco(ax, RIGHT - 0.035, 0.070, 0.075, aspect)
    draw_checkered_strip(ax, 0.0, 0.14, fig_w_in, fig_h_in)
    uses_metamesh = all(f["temp_source"] == "metamesh" for f in frames)
    sources = "NWS/ECMWF/MetaMesh" if uses_metamesh else "NWS/ECMWF"
    fig.text((LEFT + RIGHT) / 2, 0.088,
              f"Updated {now_local.strftime('%d %B %Y %H:%M')} {short_tz_abbr(now_local.strftime('%Z'))}",
              fontproperties=f_reg, fontsize=9.5, color=SUB_INK, ha="center")
    fig.text((LEFT + RIGHT) / 2, 0.060, f"{sources} • Ingalls Weather • Crawl on!",
              fontproperties=f_reg, fontsize=9.5, color=SUB_INK, ha="center")

    plt.savefig(args.output, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
    print(f"saved {args.output}")
    for f in frames:
        print(f"  {f['role']} {clock_label(f['time'])}: {f['temp']}° ({f['temp_source']}), feels {f['feels_like']}°, "
              f"{f['condition']}, {f['light']}, precip {f['precip']}, wind {f['wind_dir']} {f['wind']} gust {f['gust']}")


if __name__ == "__main__":
    main()

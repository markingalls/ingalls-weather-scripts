import argparse
import json
import math
import os
import statistics
from datetime import date as ddate, datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
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
    """16:00 -> '4 PM', 18:30 -> '6:30 PM' -- TV-style, since this is aimed at
    parents planning an evening rather than at a forecast desk."""
    hour12 = dt.hour % 12 or 12
    suffix = "AM" if dt.hour < 12 else "PM"
    return f"{hour12} {suffix}" if dt.minute == 0 else f"{hour12}:{dt.minute:02d} {suffix}"


# ---------- palette (Halloween night, in place of the 7-day's light theme) ----------
BG = "#17111f"            # near-black purple night sky
INK = "#f4ece1"           # bone white
INK_SECONDARY = "#b6a7c6" # dusty lavender
CARD_FILL = "#231a30"
CARD_EDGE = "#3c2c50"
PUMPKIN = "#f28c28"
PUMPKIN_DARK = "#c4621a"
CANDLE = "#ffd54a"        # jack-o'-lantern glow
STEM = "#5b7a2e"
MOON = "#f3e6b0"
MOON_SHADOW = "#ddcf95"
BAT = "#0c0812"         # silhouetted against the moon
BAT_SKY = "#4b3966"     # away from the moon, where black would vanish

# icon color by condition category -- the 7-day's hues, lifted for a dark background
COLOR_SUN = "#f5b942"
COLOR_MOON = MOON
COLOR_CLOUD = "#bdb5cc"
COLOR_RAIN = "#5fa8e8"
COLOR_SNOW = "#a3d8f4"
COLOR_STORM = "#a98ee3"
COLOR_MUTED = "#a99f8c"
COLOR_WIND = "#5fc2c2"
COLOR_SEVERE = "#ef5a4a"

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


# ---------- sunset (NOAA's general solar position equations) ----------
def sunset_local(day, lat, lon, local_tz):
    """Official (-0.833°) sunset for a date, from NOAA's solar equations
    (https://gml.noaa.gov/grad/solcalc/solareqns.PDF) -- good to about a
    minute, plenty for a "before/after dark" label, without pulling in a
    whole astronomy package for one number."""
    g = 2 * math.pi / 365 * (day.timetuple().tm_yday - 1)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                       - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    lat_r = math.radians(lat)
    ha = math.degrees(math.acos(math.cos(math.radians(90.833)) / (math.cos(lat_r) * math.cos(decl))
                                - math.tan(lat_r) * math.tan(decl)))
    sunset_utc_min = 720 - 4 * lon - eqtime + 4 * ha
    midnight_utc = datetime.combine(day, dtime(0), tzinfo=timezone.utc)
    return (midnight_utc + timedelta(minutes=sunset_utc_min)).astimezone(local_tz)


# Civil twilight runs ~30-35 minutes past sunset this far north in late
# October -- a frame inside that stretch is "dusk", anything later is dark.
DUSK_MINUTES = 35


def light_label(frame_time, sunset):
    if frame_time < sunset:
        return "DAYLIGHT"
    if frame_time < sunset + timedelta(minutes=DUSK_MINUTES):
        return "DUSK"
    return "AFTER DARK"


# ---------- per-frame data ----------
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


def metamesh_temp_at(data, frame_time):
    """MetaMesh temperature_2m (°C) at exactly frame_time, or None. Handles
    both a flat and a WM-6-style nested record list, same as the 7-day's
    metamesh_temp_series()."""
    if not data:
        return None
    records = data.get("forecasts", [])
    if records and isinstance(records[0], list):
        records = records[0]
    for rec in records:
        if datetime.fromisoformat(rec["time"].replace("Z", "+00:00")) == frame_time:
            return rec["temperature_2m"]
    return None


# Chance of precip for a frame is over the 2 hours centered on it (an hour
# either side of "6 PM" is what a trick-or-treater actually walks through),
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


def costume_tips(frame):
    """Up to two short lines of what-to-wear-over-the-costume advice,
    weather first, then a safety nudge once it's dark out."""
    tips = []
    feels = frame["feels_like"] if frame["feels_like"] is not None else frame["temp"]
    precip = frame["precip"]
    if precip and precip["pop"] >= 0.5:
        tips.append("Snow boots + warm layers" if precip["is_snow"] else "Rain gear over costumes")
    elif feels is not None:
        if feels < 32:
            tips.append("Bundle up: winter coats")
        elif feels < 42:
            tips.append("Coat over the costume")
        elif feels < 52:
            tips.append("Bring a jacket")
        elif feels < 62:
            tips.append("Light layer handy")
        else:
            tips.append("Costume-only weather!")
    if precip and precip["pop"] < 0.5:
        tips.append("Hood or umbrella, just in case")
    elif frame["gust"] is not None and frame["gust"] >= 25:
        tips.append("Hold onto your witch hats")
    elif frame["light"] != "DAYLIGHT":
        tips.append("Glow sticks + flashlights")
    return tips[:2]


def build_frame(data, frame_time, sunset):
    period = nws_hour(data["hourly"], frame_time)
    if period is None:
        raise SystemExit(f"NWS hourly feed doesn't cover {frame_time.isoformat()} -- re-run fetch_forecast.py.")

    glyph, color = glyph_for(period["icon"], period["isDaytime"])
    mm_c = metamesh_temp_at(data.get("metamesh"), frame_time)
    temp = round(mm_c * 9 / 5 + 32) if mm_c is not None else period["temperature"]
    feels = grid_value_at(data["apparent_temperature_f"], frame_time)
    gust = grid_value_at(data["wind_gust_mph"], frame_time)
    precip = precip_chance(data["ensemble"], frame_time)

    if precip and precip["pop"] >= SIGNIFICANT_POP_THRESHOLD:
        glyph = chr(GLYPHS["SNOWday" if precip["is_snow"] else "RAINday"])
        color = COLOR_SNOW if precip["is_snow"] else COLOR_RAIN

    wind = parse_nws_wind(period)
    frame = {
        "time": frame_time,
        "light": light_label(frame_time, sunset),
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
    frame["tips"] = costume_tips(frame)
    return frame


# ---------- decorations ----------
def draw_moon(ax, cx, cy, r, aspect):
    """Full moon with a soft glow and a few craters. aspect = fig height /
    fig width, so circles drawn in 0-1 axes coordinates stay round."""
    for scale in np.linspace(1.75, 1.05, 8):
        alpha = 0.035
        ax.add_patch(Ellipse((cx, cy), 2 * r * scale * aspect, 2 * r * scale,
                             facecolor=MOON, edgecolor="none", alpha=alpha, zorder=1))
    ax.add_patch(Ellipse((cx, cy), 2 * r * aspect, 2 * r, facecolor=MOON, edgecolor="none", zorder=1.2))
    for dx, dy, cr in [(-0.30, 0.25, 0.22), (0.32, -0.10, 0.16), (-0.05, -0.40, 0.12), (0.15, 0.42, 0.09)]:
        ax.add_patch(Ellipse((cx + dx * r * aspect, cy + dy * r), 2 * cr * r * aspect, 2 * cr * r,
                             facecolor=MOON_SHADOW, edgecolor="none", zorder=1.3))


# Right half of a bat silhouette in unit coordinates (head at the origin,
# wingtip at x=1) -- mirrored for the left half in draw_bat().
_BAT_HALF = [(0.0, 0.10), (0.04, 0.24), (0.07, 0.12), (0.12, 0.10), (0.30, 0.26), (0.62, 0.30),
             (1.00, 0.46), (0.84, 0.10), (0.70, 0.16), (0.58, -0.04), (0.44, 0.08), (0.30, -0.12),
             (0.16, 0.0), (0.06, -0.20), (0.0, -0.28)]


def draw_bat(ax, cx, cy, span, aspect, angle_deg=0, color=BAT):
    half = _BAT_HALF + [(-x, y) for x, y in reversed(_BAT_HALF)]
    a = math.radians(angle_deg)
    pts = []
    for x, y in half:
        rx, ry = x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)
        pts.append((cx + rx * span / 2 * aspect, cy + ry * span / 2))
    ax.add_patch(Polygon(pts, closed=True, facecolor=color, edgecolor="none", zorder=1.5))


def draw_jack_o_lantern(ax, cx, cy, h, aspect):
    """A small carved pumpkin: three overlapping lobes, a stem, and a
    candle-lit face. h is the body height in axes units."""
    w = h * 1.25
    for dx, lobe_w, shade in [(-0.30, 0.62, PUMPKIN_DARK), (0.30, 0.62, PUMPKIN_DARK), (0.0, 0.62, PUMPKIN)]:
        ax.add_patch(Ellipse((cx + dx * w * aspect, cy), lobe_w * w * aspect, h,
                             facecolor=shade, edgecolor=BG, linewidth=0.8, zorder=2))
    ax.add_patch(Rectangle((cx - 0.05 * w * aspect, cy + h * 0.42), 0.10 * w * aspect, h * 0.18,
                           facecolor=STEM, edgecolor="none", zorder=1.9))
    s = h / 2
    for side in (-1, 1):
        ex = cx + side * 0.17 * w * aspect
        ax.add_patch(Polygon([(ex - 0.08 * w * aspect, cy + 0.08 * s), (ex + 0.08 * w * aspect, cy + 0.08 * s),
                              (ex, cy + 0.40 * s)], facecolor=CANDLE, edgecolor="none", zorder=2.1))
    mouth = [(-0.32, -0.16), (-0.20, -0.26), (-0.10, -0.18), (0.0, -0.28), (0.10, -0.18), (0.20, -0.26),
             (0.32, -0.16), (0.22, -0.46), (0.0, -0.54), (-0.22, -0.46)]
    ax.add_patch(Polygon([(cx + mx * w * aspect, cy + my * s) for mx, my in mouth],
                         facecolor=CANDLE, edgecolor="none", zorder=2.1))


def draw_stars(ax, rng, n, y_min):
    xs = rng.uniform(0.0, 1.0, n)
    ys = rng.uniform(y_min, 1.0, n)
    sizes = rng.uniform(0.6, 2.4, n)
    ax.scatter(xs, ys, s=sizes, color=INK, alpha=0.55, linewidths=0, zorder=0.5)


def parse_args():
    ap = argparse.ArgumentParser(description="Render a Halloween trick-or-treat forecast: three time frames, one location.")
    ap.add_argument("--location", default="tri-cities",
                     help="Location key from fetch_forecast.py -- picks forecast_<location>.json")
    ap.add_argument("--forecast", help="defaults to forecast_<location>.json")
    ap.add_argument("--date", help="Local date to forecast, YYYY-MM-DD (default: tomorrow, local time)")
    ap.add_argument("--hours", type=int, nargs="+", default=[16, 18, 20],
                     help="Local hours (24h) for each frame")
    ap.add_argument("--output", help="defaults to <location>_trick_or_treat_forecast.png")
    return ap.parse_args()


def main():
    args = parse_args()
    data = json.load(open(args.forecast or f"forecast_{args.location}.json"))
    local_tz = ZoneInfo(data["timezone"])
    now_local = datetime.now(local_tz)
    target = ddate.fromisoformat(args.date) if args.date else now_local.date() + timedelta(days=1)

    sunset = sunset_local(target, data["lat"], data["lon"], local_tz)
    frames = [build_frame(data, datetime.combine(target, dtime(h), tzinfo=local_tz), sunset) for h in args.hours]

    fig = plt.figure(figsize=(12, 8.3), dpi=200)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    fig_w_in, fig_h_in = fig.get_size_inches()
    aspect = fig_h_in / fig_w_in

    # fixed seed -- the same sky every render, not new stars each update
    draw_stars(ax, np.random.default_rng(1031), 70, 0.80)
    draw_moon(ax, 0.905, 0.905, 0.050, aspect)
    for bx, by, span, angle, color in [(0.893, 0.918, 0.040, -10, BAT), (0.922, 0.878, 0.024, 12, BAT),
                                        (0.815, 0.950, 0.036, 8, BAT_SKY), (0.975, 0.960, 0.026, -14, BAT_SKY),
                                        (0.790, 0.860, 0.022, -6, BAT_SKY)]:
        draw_bat(ax, bx, by, span, aspect, angle, color)

    LEFT, RIGHT = 0.055, 0.965
    CARD_TOP, CARD_BOTTOM = 0.775, 0.135
    GUTTER = 0.022
    n = len(frames)
    card_w = (RIGHT - LEFT - (n - 1) * GUTTER) / n

    # Vertical zones within each card, top to bottom: time, light label,
    # condition icon, condition text, temperature, feels-like, precip/wind
    # detail row, divider, costume tips.
    TIME_Y = CARD_TOP - 0.035
    LIGHT_Y = CARD_TOP - 0.098
    ICON_Y = 0.560
    COND_Y = 0.470
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
        is_dark = frame["light"] != "DAYLIGHT"

        ax.add_patch(FancyBboxPatch(
            (x0, CARD_BOTTOM), card_w, CARD_TOP - CARD_BOTTOM,
            boxstyle="round,pad=0,rounding_size=0.014",
            facecolor=CARD_FILL, edgecolor=PUMPKIN if is_dark else CARD_EDGE,
            linewidth=1.8 if is_dark else 1.2, zorder=2))

        ax.text(cx, TIME_Y, clock_label(frame["time"]), ha="center", va="top",
                 fontproperties=f_bold, fontsize=28, color=PUMPKIN, zorder=3)
        ax.text(cx, LIGHT_Y, frame["light"], ha="center", va="top",
                 fontproperties=f_med, fontsize=11, color=INK_SECONDARY, zorder=3)

        icon_text = ax.text(cx, ICON_Y, frame["glyph"], ha="center", va="center",
                             fontproperties=ICON_FONT, fontsize=64, color=frame["glyph_color"], zorder=3)
        # same fake-bold stroke as the 7-day -- the icon font has no bold weight
        icon_text.set_path_effects([pe.withStroke(linewidth=2.2, foreground=frame["glyph_color"])])

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
                     fontproperties=f_med, fontsize=11.5, color=PUMPKIN if y == TIP_1_Y else INK_SECONDARY,
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
        # the logo's square light backdrop would read as a pasted-on box
        # against the night sky -- clip it to a round badge instead.
        im.set_clip_path(Circle((img_w / 2, img_h / 2), min(img_w, img_h) / 2, transform=logo_ax.transData))
        logo_ax.axis("off")

        title_x = LEFT + logo_width_fig + 0.018
    else:
        print(f"NOTE: no logo found at {LOGO_PATH} -- skipping logo placement.")

    fig.text(title_x, 0.935, f"{data.get('label', 'Tri-Cities')} Trick-or-Treat Forecast",
              fontproperties=f_bold, fontsize=24, color=INK)
    sunset_text = clock_label(sunset.replace(second=0, microsecond=0) + timedelta(minutes=sunset.second >= 30))
    fig.text(title_x, 0.895,
              f"{target.strftime('%A, %B %-d')}  •  Sunset {sunset_text}  •  "
              f"Updated {now_local.strftime('%d %B %Y %H:%M')} {short_tz_abbr(now_local.strftime('%Z'))}",
              fontproperties=f_reg, fontsize=12, color=INK_SECONDARY)

    # ---------- attribution + pumpkins ----------
    draw_jack_o_lantern(ax, LEFT + 0.035, 0.068, 0.062, aspect)
    draw_jack_o_lantern(ax, RIGHT - 0.035, 0.068, 0.062, aspect)
    temp_src = "WM-6" if all(f["temp_source"] == "metamesh" for f in frames) else "NWS"
    sources = "NWS/ECMWF" if temp_src == "NWS" else "NWS/ECMWF/WM-6"
    fig.text((LEFT + RIGHT) / 2, 0.06, f"{sources} • Ingalls Weather • Happy Halloween!",
              fontproperties=f_reg, fontsize=9.5, color=INK_SECONDARY, ha="center")

    output = args.output or f"{data.get('location', args.location).replace('-', '_')}_trick_or_treat_forecast.png"
    plt.savefig(output, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
    print(f"saved {output}")
    for f in frames:
        print(f"  {clock_label(f['time'])}: {f['temp']}° ({f['temp_source']}), feels {f['feels_like']}°, "
              f"{f['condition']}, precip {f['precip']}, wind {f['wind_dir']} {f['wind']} gust {f['gust']}")


if __name__ == "__main__":
    main()

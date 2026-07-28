import argparse
import json
import os
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

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

# ---------- palette ----------
BG = "#f7f6f2"
INK = "#2b2a26"
INK_SECONDARY = "#5a584f"
CARD_FILL = "#ffffff"
CARD_EDGE = "#d8d5cc"
TODAY_EDGE = "#164f29"  # forest green, in the spirit of the logo's pine tree

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
}

# NWS forecast icon code (from the last path segment of the "icon" URL,
# e.g. https://api.weather.gov/icons/land/day/tsra,40 -> "tsra") -> (glyph, color)
NWS_ICON_MAP = {
    "skc": ("CLEARday", COLOR_SUN),
    "few": ("FAIRday", COLOR_SUN),
    "sct": ("PARTLY_CLOUDYday", COLOR_CLOUD),
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


def glyph_for(icon_url):
    code = icon_code_from_url(icon_url)
    name, color = NWS_ICON_MAP.get(code, ("UNKNOWNday", INK_SECONDARY))
    return chr(GLYPHS[name]), color


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


def glyph_for_wmo(weathercode):
    name, color = WMO_ICON_MAP.get(weathercode, ("UNKNOWNday", INK_SECONDARY))
    return chr(GLYPHS[name]), color


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
        glyph, color = glyph_for(day["icon"])
        columns.append({
            "label": day["name"],
            "date": datetime.fromisoformat(day["startTime"]),
            "day_start": datetime.fromisoformat(day["startTime"]),
            "day_end": datetime.fromisoformat(day["endTime"]),
            "night_start": datetime.fromisoformat(night["startTime"]) if night else None,
            "night_end": datetime.fromisoformat(night["endTime"]) if night else None,
            "glyph": glyph,
            "glyph_color": color,
        })
        i += 2
    return columns


# NWS's own day/night split for future (non-current) days -- confirmed
# against real fetched data (e.g. "Wednesday" 06:00-18:00, "Wednesday
# Night" 18:00-06:00 local). Reused for the synthetic day added beyond
# NWS's own coverage so every column reduces temperature over the same
# local-hour convention.
DAY_START_HOUR, DAY_END_HOUR = 6, 18
LOCAL_TZ = ZoneInfo("America/Los_Angeles")


def local_day_window(date):
    """(day_start, day_end, night_start, night_end) tz-aware datetimes for
    one calendar date, using NWS's own 6am-6pm/6pm-6am local split."""
    day_start = datetime.combine(date, dtime(DAY_START_HOUR), tzinfo=LOCAL_TZ)
    day_end = datetime.combine(date, dtime(DAY_END_HOUR), tzinfo=LOCAL_TZ)
    night_start = day_end
    night_end = datetime.combine(date + timedelta(days=1), dtime(DAY_START_HOUR), tzinfo=LOCAL_TZ)
    return day_start, day_end, night_start, night_end


def openmeteo_weathercode_for_date(data, date):
    daily = data["daily"]
    idx = daily["time"].index(date.isoformat())
    return daily["weathercode"][idx]


def synthetic_column(date, openmeteo_data):
    """A day/night column beyond NWS's own coverage: condition icon from
    Open-Meteo's daily weathercode (temperature gets filled in by
    attach_metamesh_temps() same as every other column, since MetaMesh's
    15-day horizon already reaches this far)."""
    day_start, day_end, night_start, night_end = local_day_window(date)
    glyph, color = glyph_for_wmo(openmeteo_weathercode_for_date(openmeteo_data, date))
    return {
        "label": date.strftime("%A"),
        "date": datetime.combine(date, dtime(0), tzinfo=LOCAL_TZ),
        "day_start": day_start,
        "day_end": day_end,
        "night_start": night_start,
        "night_end": night_end,
        "glyph": glyph,
        "glyph_color": color,
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


def parse_args():
    ap = argparse.ArgumentParser(description="Render the Tri-Cities TV-style 7-day forecast graphic.")
    ap.add_argument("--forecast", default="forecast.json",
                     help="NWS forecast (day/night periods, condition icons) from fetch_forecast.py")
    ap.add_argument("--metamesh-forecast", default="metamesh_forecast.json",
                     help="MetaMesh point temperature forecast (high/low source) from fetch_metamesh_forecast.py")
    ap.add_argument("--openmeteo-forecast", default="openmeteo_forecast.json",
                     help="Open-Meteo daily weathercode forecast, from fetch_openmeteo_forecast.py -- only "
                          "read when the window shift (see main()) needs a 7th day beyond NWS's coverage")
    ap.add_argument("--output", default="tri_cities_7day_forecast.png")
    return ap.parse_args()


def main():
    args = parse_args()
    data = json.load(open(args.forecast))
    props = data["properties"]

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
    now_local = datetime.now(LOCAL_TZ)
    drop_today = now_local.hour >= 15
    suppress_today_low = 7 <= now_local.hour < 15

    columns = daily_columns(props["periods"], drop_today=drop_today)

    if drop_today and len(columns) < 7:
        last_date = columns[-1]["date"].date() if columns else now_local.date()
        openmeteo_data = json.load(open(args.openmeteo_forecast))
        columns.append(synthetic_column(last_date + timedelta(days=1), openmeteo_data))

    temp_series = metamesh_temp_series(json.load(open(args.metamesh_forecast)))
    attach_metamesh_temps(columns, temp_series)

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

    for idx, col in enumerate(columns):
        x0 = LEFT + idx * (card_w + GUTTER)
        x1 = x0 + card_w
        cx = (x0 + x1) / 2
        is_today = col["label"] == "Today"

        card = FancyBboxPatch(
            (x0, CARD_BOTTOM), card_w, CARD_TOP - CARD_BOTTOM,
            boxstyle="round,pad=0,rounding_size=0.012",
            facecolor=CARD_FILL, edgecolor=TODAY_EDGE if is_today else CARD_EDGE,
            linewidth=1.8 if is_today else 1.0, zorder=2)
        ax.add_patch(card)

        day_label = col["date"].strftime("%a").upper()
        ax.text(cx, CARD_TOP - 0.05, day_label, ha="center", va="top",
                 fontproperties=f_bold, fontsize=17,
                 color=TODAY_EDGE if is_today else INK, zorder=3)
        ax.text(cx, CARD_TOP - 0.093, col["date"].strftime("%b %-d"), ha="center", va="top",
                 fontproperties=f_reg, fontsize=10.5, color=INK_SECONDARY, zorder=3)

        icon_text = ax.text(cx, (CARD_TOP + CARD_BOTTOM) / 2 + 0.045, col["glyph"], ha="center", va="center",
                             fontproperties=ICON_FONT, fontsize=46, color=col["glyph_color"], zorder=3)
        # the icon font is a thin-stroke outline face with no bold weight of
        # its own -- stroking each glyph in its own fill color fattens the
        # outline so it reads as bold instead of drawing it twice.
        icon_text.set_path_effects([pe.withStroke(linewidth=1.8, foreground=col["glyph_color"])])

        high_text = f"{col['high']}°" if col["high"] is not None else "—"
        ax.text(cx, CARD_BOTTOM + 0.085, high_text, ha="center", va="bottom",
                 fontproperties=f_bold, fontsize=20, color=INK, zorder=3)
        low_text = f"{col['low']}°" if col["low"] is not None else "—"
        ax.text(cx, CARD_BOTTOM + 0.03, low_text, ha="center", va="bottom",
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

    generated = datetime.fromisoformat(props["generatedAt"])
    fig.text(title_x, 0.935, f"{data.get('label', 'Tri-Cities')} 7-Day Forecast",
              fontproperties=f_bold, fontsize=24, color=INK)
    fig.text(title_x, 0.895, f"Updated {generated.strftime('%A, %B %-d')} at {generated.strftime('%-I:%M %p %Z')}",
              fontproperties=f_reg, fontsize=12, color=INK_SECONDARY)

    # ---------- attribution ----------
    fig.text((LEFT + RIGHT) / 2, 0.045, "National Weather Service — Ingalls Weather",
              fontproperties=f_reg, fontsize=9, color=INK_SECONDARY, ha="center")

    plt.savefig(args.output, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
    print(f"saved {args.output}")


if __name__ == "__main__":
    main()

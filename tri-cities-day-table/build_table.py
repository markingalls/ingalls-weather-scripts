"""
Renders forecast.json (from fetch_forecast.py) into a single-day forecast
table for the Tri-Cities: one column per time of day, one row of
temperature and one row of chance of precip. Same canvas footprint, fonts,
palette, and logo/title treatment as tri-cities-7day-forecast/build_graphic.py.
"""
import argparse
import json
import os
import statistics
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
from matplotlib.patches import FancyBboxPatch

# ---------- fonts (same Poppins-with-Montserrat-fallback as the 7-day graphic) ----------
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

ICON_FONT = fm.FontProperties(fname="fonts/easy_weather_icons_font.ttf")
RAINDROP = chr(0xea0c)
SNOWFLAKE = chr(0xe9a6)

# ---------- palette (shared with tri-cities-7day-forecast) ----------
BG = "#f7f6f2"
INK = "#2b2a26"
INK_SECONDARY = "#5a584f"
CARD_FILL = "#ffffff"
CARD_EDGE = "#d8d5cc"
COLOR_RAIN = "#2f6fb0"
COLOR_SNOW = "#5aa9d6"

# ---------- table layout ----------
# Each column is a time of day; its chance of precip covers the three
# hourly ECMWF steps labeled hour-1, hour, hour+1 (Open-Meteo's hourly
# precipitation is a preceding-hour accumulation, matching the 7-day
# graphic's own string-label handling). 6 AM-9 PM every 3 hours tiles the
# 05:00-22:59 labels, lining up with the 7-day's PRECIP_DAY_START_HOUR.
COLUMN_HOURS = [6, 9, 12, 15, 18, 21]

# Measurable precip (0.01") in a 3-hour window -- the 7-day graphic's 0.5mm
# is a whole-day threshold and would be too strict over just 3 hours.
POP_THRESHOLD_MM = 0.254

# Chance-of-precip cells get a snowflake instead of a raindrop when that
# column's temperature is below this.
FREEZING_F = 32

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def short_tz_abbr(tzname):
    if len(tzname) >= 3 and tzname[-1] == "T" and tzname[-2] in "SD":
        return tzname[:-2] + "T"
    return tzname


def hour_label(h):
    if h == 0:
        return "Midnight"
    if h == 12:
        return "Noon"
    return f"{h % 12} {'AM' if h < 12 else 'PM'}"


def next_weekday(today, weekday_name):
    """The next date (today included) falling on weekday_name."""
    target = WEEKDAYS.index(weekday_name.lower())
    return today + timedelta(days=(target - today.weekday()) % 7)


def nws_temp_at(hourly, when_local):
    """NWS hourly temperature whose period starts exactly at when_local, or
    None if the feed doesn't cover it."""
    for p in hourly:
        if datetime.fromisoformat(p["start"]) == when_local:
            return p["temperature_f"]
    return None


def precip_chance(ensemble, date, hour):
    """(pop, is_snow) for the three hourly steps labeled hour-1..hour+1 on
    date, or None if the ensemble doesn't cover them. pop is the fraction of
    members whose window total exceeds POP_THRESHOLD_MM; is_snow if at least
    half the members show measurable snowfall (same rule as the 7-day)."""
    hourly = ensemble["hourly"]
    wanted = {f"{date.isoformat()}T{h:02d}:00" for h in (hour - 1, hour, hour + 1)}
    idxs = [i for i, t in enumerate(hourly["time"]) if t in wanted]
    if len(idxs) != len(wanted):
        return None
    precip_keys = sorted(k for k in hourly if k.startswith("precipitation_member"))
    snow_keys = sorted(k for k in hourly if k.startswith("snowfall_member"))
    totals = [sum(hourly[k][i] or 0 for i in idxs) for k in precip_keys]
    snow = [sum(hourly[k][i] or 0 for i in idxs) for k in snow_keys]
    pop = sum(1 for v in totals if v > POP_THRESHOLD_MM) / len(totals)
    return pop, statistics.median(snow) > 0


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--forecast", default="forecast.json")
    ap.add_argument("--day", default="wednesday",
                     help="Weekday to show (the next one, today included)")
    ap.add_argument("--output", default=None,
                     help="Defaults to tri_cities_<day>_table.png")
    return ap.parse_args()


def main():
    args = parse_args()
    data = json.load(open(args.forecast))
    local_tz = ZoneInfo(data["timezone"])
    now_local = datetime.now(local_tz)
    date = next_weekday(now_local.date(), args.day)
    output = args.output or f"tri_cities_{args.day.lower()}_table.png"

    cols = []
    for h in COLUMN_HOURS:
        when = datetime(date.year, date.month, date.day, h, tzinfo=local_tz)
        cols.append({
            "label": hour_label(h),
            "temp": nws_temp_at(data["nws_hourly"], when),
            "precip": precip_chance(data["ecmwf_ensemble"], date, h),
        })

    fig = plt.figure(figsize=(12, 8.3), dpi=200)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    LEFT, RIGHT = 0.055, 0.965
    LABEL_W = 0.165           # row-label column
    GUTTER = 0.012
    n = len(cols)
    cell_x0 = LEFT + LABEL_W + GUTTER
    cell_w = (RIGHT - cell_x0 - (n - 1) * GUTTER) / n

    HEADER_Y = 0.80           # time-of-day header row
    ROW_H = 0.30
    ROW_GAP = 0.025
    TEMP_TOP = 0.765
    TEMP_BOTTOM = TEMP_TOP - ROW_H
    POP_TOP = TEMP_BOTTOM - ROW_GAP
    POP_BOTTOM = POP_TOP - ROW_H

    def card(x, y0, w, h):
        ax.add_patch(FancyBboxPatch(
            (x, y0), w, h, boxstyle="round,pad=0,rounding_size=0.012",
            facecolor=CARD_FILL, edgecolor=CARD_EDGE, linewidth=1.0, zorder=2))

    # ---------- row labels ----------
    for top, bottom, title in [
        (TEMP_TOP, TEMP_BOTTOM, "Temperature"),
        (POP_TOP, POP_BOTTOM, "Chance of\nPrecip"),
    ]:
        mid = (top + bottom) / 2
        ax.text(LEFT, mid + 0.012, title, ha="left", va="center", fontproperties=f_bold,
                 fontsize=15, color=INK, linespacing=1.05, zorder=3)
    ax.text(LEFT, (TEMP_TOP + TEMP_BOTTOM) / 2 - 0.045, "NWS hourly", ha="left", va="center",
             fontproperties=f_reg, fontsize=9.5, color=INK_SECONDARY, zorder=3)
    ax.text(LEFT, (POP_TOP + POP_BOTTOM) / 2 - 0.06, "≥0.01\" in a 3-hr\nwindow (ECMWF ens.)",
             ha="left", va="center", fontproperties=f_reg, fontsize=9.5, color=INK_SECONDARY,
             linespacing=1.1, zorder=3)

    for idx, col in enumerate(cols):
        x0 = cell_x0 + idx * (cell_w + GUTTER)
        cx = x0 + cell_w / 2

        ax.text(cx, HEADER_Y, col["label"], ha="center", va="center",
                 fontproperties=f_bold, fontsize=17, color=INK, zorder=3)

        # temperature cell
        card(x0, TEMP_BOTTOM, cell_w, ROW_H)
        if col["temp"] is not None:
            ax.text(cx, (TEMP_TOP + TEMP_BOTTOM) / 2, f"{col['temp']}°", ha="center",
                     va="center", fontproperties=f_bold, fontsize=40,
                     color=INK, zorder=3)
        else:
            ax.text(cx, (TEMP_TOP + TEMP_BOTTOM) / 2, "—", ha="center", va="center",
                     fontproperties=f_bold, fontsize=34, color=INK_SECONDARY, zorder=3)

        # chance-of-precip cell
        card(x0, POP_BOTTOM, cell_w, ROW_H)
        pop_mid = (POP_TOP + POP_BOTTOM) / 2
        if col["precip"] is None:
            ax.text(cx, pop_mid, "—", ha="center", va="center",
                     fontproperties=f_bold, fontsize=30, color=INK_SECONDARY, zorder=3)
            continue
        pop, ens_snow = col["precip"]
        # below freezing -> snowflake; the ensemble's own rain/snow call is
        # only the fallback when there's no NWS temperature for the column
        is_snow = col["temp"] < FREEZING_F if col["temp"] is not None else ens_snow
        pop_pct = round(pop * 100 / 5) * 5
        color = COLOR_SNOW if is_snow else COLOR_RAIN
        glyph = ax.text(cx, pop_mid + 0.045, SNOWFLAKE if is_snow else RAINDROP, ha="center",
                         va="center", fontproperties=ICON_FONT, fontsize=30, color=color,
                         alpha=1.0 if pop_pct >= 20 else 0.35, zorder=3)
        glyph.set_path_effects([pe.withStroke(linewidth=1.2, foreground=color)])
        ax.text(cx, pop_mid - 0.04, f"{pop_pct:.0f}%", ha="center", va="center",
                 fontproperties=f_bold, fontsize=26,
                 color=color if pop_pct >= 20 else INK_SECONDARY, zorder=3)

    # ---------- logo + title / subtitle (same treatment as the 7-day graphic) ----------
    TITLE_BLOCK_TOP, TITLE_BLOCK_BOTTOM = 0.965, 0.878
    title_x = LEFT
    LOGO_PATH = "../assets/ingalls_weather_logo.png"
    if os.path.exists(LOGO_PATH):
        logo_img = plt.imread(LOGO_PATH)
        img_h, img_w = logo_img.shape[0], logo_img.shape[1]
        fig_w_in, fig_h_in = fig.get_size_inches()
        logo_height_fig = TITLE_BLOCK_TOP - TITLE_BLOCK_BOTTOM
        logo_width_fig = logo_height_fig * fig_h_in * (img_w / img_h) / fig_w_in
        logo_ax = fig.add_axes([LEFT, TITLE_BLOCK_BOTTOM + 0.012, logo_width_fig, logo_height_fig], zorder=20)
        logo_ax.imshow(logo_img)
        logo_ax.axis("off")
        title_x = LEFT + logo_width_fig + 0.018
    else:
        print(f"NOTE: no logo found at {LOGO_PATH} -- skipping logo placement.")

    fig.text(title_x, 0.935, f"{data.get('label', 'Tri-Cities')} Forecast: {date.strftime('%A, %B %-d')}",
              fontproperties=f_bold, fontsize=24, color=INK)
    fig.text(title_x, 0.895, f"Updated {now_local.strftime('%d %B %Y %H:%M')} {short_tz_abbr(now_local.strftime('%Z'))}",
              fontproperties=f_reg, fontsize=12, color=INK_SECONDARY)

    fig.text((LEFT + RIGHT) / 2, 0.075, "NWS/ECMWF • Ingalls Weather",
              fontproperties=f_reg, fontsize=9, color=INK_SECONDARY, ha="center")

    plt.savefig(output, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
    print(f"saved {output}")
    for col in cols:
        p = col["precip"]
        print(f"  {col['label']:>5}: {col['temp']}°F, "
              f"{'—' if p is None else f'{p[0]:.0%} ' + ('snow' if p[1] else 'rain')}")


if __name__ == "__main__":
    main()

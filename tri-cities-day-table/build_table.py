"""
Renders forecast.json (from fetch_forecast.py) into a single-day forecast
table for the Tri-Cities: one column per time of day, one row of
temperature and one row of chance of precip. Same canvas footprint, fonts,
palette, and logo/title treatment as tri-cities-7day-forecast/build_graphic.py.
"""
import argparse
import json
import os
import re
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
HIGHLIGHT_EDGE = "#164f29"  # forest green, same as the 7-day's weekend/holiday accent
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
    ap.add_argument("--forecast", nargs="+", default=["forecast.json"],
                     help="One or more fetch_forecast.py outputs; each gets its own pair of "
                          "rows, stacked in the order given (e.g. forecast.json "
                          "forecast_hermiston.json for Tri-Cities + Hermiston on one graphic)")
    ap.add_argument("--day", default="wednesday",
                     help="Weekday to show (the next one, today included)")
    ap.add_argument("--output", default=None,
                     help="Defaults to <labels>_<day>_table.png, e.g. tri_cities_wednesday_table.png "
                          "or tri_cities_hermiston_wednesday_table.png")
    return ap.parse_args()


def location_columns(data, date):
    local_tz = ZoneInfo(data["timezone"])
    cols = []
    for h in COLUMN_HOURS:
        when = datetime(date.year, date.month, date.day, h, tzinfo=local_tz)
        cols.append({
            "label": hour_label(h),
            "temp": nws_temp_at(data["nws_hourly"], when),
            "precip": precip_chance(data["ecmwf_ensemble"], date, h),
        })
    return cols


def main():
    args = parse_args()
    locations = [json.load(open(path)) for path in args.forecast]
    labels = [d.get("label", "Tri-Cities") for d in locations]
    # "today"/the target date and the Updated stamp follow the first
    # location's timezone (all the defaults are Pacific anyway)
    local_tz = ZoneInfo(locations[0]["timezone"])
    now_local = datetime.now(local_tz)
    date = next_weekday(now_local.date(), args.day)
    # named after the location label(s), so renders for different points
    # (Tri-Cities, Hermiston, both, ...) don't overwrite each other
    slug = "_".join(re.sub(r"[^a-z0-9]+", "_", lbl.split(",")[0].lower()).strip("_") for lbl in labels)
    output = args.output or f"{slug}_{args.day.lower()}_table.png"

    groups = [(lbl, location_columns(d, date)) for lbl, d in zip(labels, locations)]
    multi = len(groups) > 1

    fig = plt.figure(figsize=(12, 8.3), dpi=200)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    LEFT, RIGHT = 0.055, 0.965
    LABEL_W = 0.165           # row-label column
    GUTTER = 0.012
    n = len(COLUMN_HOURS)
    cell_x0 = LEFT + LABEL_W + GUTTER
    cell_w = (RIGHT - cell_x0 - (n - 1) * GUTTER) / n

    # Vertical budget: the time-of-day header, then per location an
    # (optional, multi-location only) section title and its two rows, with
    # row heights shrinking to fit however many locations are stacked.
    HEADER_Y = 0.80
    TABLE_TOP, TABLE_BOTTOM = 0.765, 0.12
    SECTION_H = 0.05 if multi else 0.0
    ROW_GAP = 0.015 if multi else 0.025
    GROUP_GAP = 0.03
    n_loc = len(groups)
    ROW_H = ((TABLE_TOP - TABLE_BOTTOM) - n_loc * (SECTION_H + ROW_GAP)
             - (n_loc - 1) * GROUP_GAP) / (2 * n_loc)
    compact = ROW_H < 0.2     # short cells: precip icon beside the number, not above it
    temp_fs = 40 if not compact else 30
    pop_fs = 26 if not compact else 22
    pop_icon_fs = 30 if not compact else 20

    def card(x, y0, w, h):
        ax.add_patch(FancyBboxPatch(
            (x, y0), w, h, boxstyle="round,pad=0,rounding_size=0.012",
            facecolor=CARD_FILL, edgecolor=CARD_EDGE, linewidth=1.0, zorder=2))

    for idx, h in enumerate(COLUMN_HOURS):
        cx = cell_x0 + idx * (cell_w + GUTTER) + cell_w / 2
        ax.text(cx, HEADER_Y, hour_label(h), ha="center", va="center",
                 fontproperties=f_bold, fontsize=17, color=INK, zorder=3)

    y = TABLE_TOP
    for g, (label, cols) in enumerate(groups):
        if g:
            y -= GROUP_GAP
        if multi:
            ax.text(LEFT, y - SECTION_H / 2, label, ha="left", va="center",
                     fontproperties=f_bold, fontsize=18, color=HIGHLIGHT_EDGE, zorder=3)
            ax.plot([cell_x0, RIGHT], [y - SECTION_H / 2] * 2, color=CARD_EDGE,
                     linewidth=1.0, zorder=1)
            y -= SECTION_H
        temp_top, temp_bottom = y, y - ROW_H
        pop_top = temp_bottom - ROW_GAP
        pop_bottom = pop_top - ROW_H
        y = pop_bottom
        temp_mid = (temp_top + temp_bottom) / 2
        pop_mid = (pop_top + pop_bottom) / 2

        # ---------- row labels ----------
        ax.text(LEFT, temp_mid, "Temperature", ha="left", va="center", fontproperties=f_bold,
                 fontsize=15, color=INK, zorder=3)
        ax.text(LEFT, pop_mid, "Chance of\nPrecip", ha="left", va="center", fontproperties=f_bold,
                 fontsize=15, color=INK, linespacing=1.05, zorder=3)

        for idx, col in enumerate(cols):
            x0 = cell_x0 + idx * (cell_w + GUTTER)
            cx = x0 + cell_w / 2

            # temperature cell
            card(x0, temp_bottom, cell_w, ROW_H)
            if col["temp"] is not None:
                ax.text(cx, temp_mid, f"{col['temp']}°", ha="center", va="center",
                         fontproperties=f_bold, fontsize=temp_fs, color=INK, zorder=3)
            else:
                ax.text(cx, temp_mid, "—", ha="center", va="center",
                         fontproperties=f_bold, fontsize=temp_fs, color=INK_SECONDARY, zorder=3)

            # chance-of-precip cell
            card(x0, pop_bottom, cell_w, ROW_H)
            if col["precip"] is None:
                ax.text(cx, pop_mid, "—", ha="center", va="center",
                         fontproperties=f_bold, fontsize=pop_fs, color=INK_SECONDARY, zorder=3)
                continue
            pop, ens_snow = col["precip"]
            # below freezing -> snowflake; the ensemble's own rain/snow call is
            # only the fallback when there's no NWS temperature for the column
            is_snow = col["temp"] < FREEZING_F if col["temp"] is not None else ens_snow
            pop_pct = round(pop * 100 / 5) * 5
            color = COLOR_SNOW if is_snow else COLOR_RAIN
            faint = pop_pct < 20
            if compact:
                icon_xy, icon_ha = (cx - 0.014, pop_mid), "right"
                num_xy, num_ha = (cx - 0.008, pop_mid), "left"
            else:
                icon_xy, icon_ha = (cx, pop_mid + 0.045), "center"
                num_xy, num_ha = (cx, pop_mid - 0.04), "center"
            glyph = ax.text(*icon_xy, SNOWFLAKE if is_snow else RAINDROP, ha=icon_ha,
                             va="center", fontproperties=ICON_FONT, fontsize=pop_icon_fs, color=color,
                             alpha=0.35 if faint else 1.0, zorder=3)
            glyph.set_path_effects([pe.withStroke(linewidth=1.2, foreground=color)])
            ax.text(*num_xy, f"{pop_pct:.0f}%", ha=num_ha, va="center",
                     fontproperties=f_bold, fontsize=pop_fs,
                     color=INK_SECONDARY if faint else color, zorder=3)

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

    fig.text(title_x, 0.935, f"{' & '.join(labels)} Forecast: {date.strftime('%A, %B %-d')}",
              fontproperties=f_bold, fontsize=24, color=INK)
    fig.text(title_x, 0.895, f"Updated {now_local.strftime('%d %B %Y %H:%M')} {short_tz_abbr(now_local.strftime('%Z'))}",
              fontproperties=f_reg, fontsize=12, color=INK_SECONDARY)

    fig.text((LEFT + RIGHT) / 2, 0.075,
              "Temperature: NWS hourly • Chance of precip: ≥0.01\" in the 3 hrs around each time, "
              "ECMWF ensemble • Ingalls Weather",
              fontproperties=f_reg, fontsize=9, color=INK_SECONDARY, ha="center")

    plt.savefig(output, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
    print(f"saved {output}")
    for label, cols in groups:
        print(f"  {label}:")
        for col in cols:
            p = col["precip"]
            print(f"    {col['label']:>5}: {col['temp']}°F, "
                  f"{'—' if p is None else f'{p[0]:.0%}'}")


if __name__ == "__main__":
    main()

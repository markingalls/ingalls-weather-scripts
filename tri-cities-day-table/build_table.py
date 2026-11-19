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
# --overnight: 6 PM on --day through 9 AM the next morning (e.g. Friday
# night/Saturday morning), as hour offsets from midnight starting --day.
OVERNIGHT_HOUR_OFFSETS = [18, 21, 24, 27, 30, 33]

# Measurable precip (0.01") in a 3-hour window -- the 7-day graphic's 0.5mm
# is a whole-day threshold and would be too strict over just 3 hours.
POP_THRESHOLD_MM = 0.254

# Chance-of-precip cells get a snowflake instead of a raindrop when that
# column's temperature is below this, and a raindrop+snowflake "mix" icon
# when it's at/above freezing but NWS's snow level is at or below the
# surface (snow reaching the ground through an above-freezing surface layer).
FREEZING_F = 32

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def short_tz_abbr(tzname):
    if len(tzname) >= 3 and tzname[-1] == "T" and tzname[-2] in "SD":
        return tzname[:-2] + "T"
    return tzname


def hour_label(h):
    """24-hour clock, same as the "Updated HH:MM" stamp (e.g. 06:00, 18:00)."""
    return f"{h:02d}:00"


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


def precip_chance(ensemble, when_local):
    """(pop, is_snow) for the three hourly steps labeled when-1h..when+1h
    (crossing midnight where needed), or None if the ensemble doesn't cover
    them. pop is the fraction of
    members whose window total exceeds POP_THRESHOLD_MM; is_snow if at least
    half the members show measurable snowfall (same rule as the 7-day)."""
    hourly = ensemble["hourly"]
    wanted = {(when_local + timedelta(hours=dh)).strftime("%Y-%m-%dT%H:00") for dh in (-1, 0, 1)}
    idxs = [i for i, t in enumerate(hourly["time"]) if t in wanted]
    if len(idxs) != len(wanted):
        return None
    precip_keys = sorted(k for k in hourly if k.startswith("precipitation_member"))
    snow_keys = sorted(k for k in hourly if k.startswith("snowfall_member"))
    totals = [sum(hourly[k][i] or 0 for i in idxs) for k in precip_keys]
    snow = [sum(hourly[k][i] or 0 for i in idxs) for k in snow_keys]
    pop = sum(1 for v in totals if v > POP_THRESHOLD_MM) / len(totals)
    return pop, statistics.median(snow) > 0


def parse_valid_time(valid_time):
    """NWS gridpoint '2026-11-21T09:00:00+00:00/PT3H' -> (start, end)
    datetimes. Only the H/D duration parts NWS actually uses are handled."""
    start_s, dur_s = valid_time.split("/")
    start = datetime.fromisoformat(start_s)
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?)?", dur_s)
    days, hours = (int(g) if g else 0 for g in m.groups())
    return start, start + timedelta(days=days, hours=hours)


def snow_level_at(snow_level, when_local):
    """Lowest NWS snow level (m) among intervals overlapping the column's
    3-hour precip window (when-2h..when+1h, the span its three
    preceding-hour precip steps cover), or None without data."""
    win_start, win_end = when_local - timedelta(hours=2), when_local + timedelta(hours=1)
    levels = []
    for v in snow_level.get("values", []):
        start, end = parse_valid_time(v["valid_time"])
        if start < win_end and end > win_start and v["snow_level_m"] is not None:
            levels.append(v["snow_level_m"])
    return min(levels) if levels else None


# WM-6 ensemble snow probability thresholds for an at/above-freezing
# column: at or above SNOW -> snowflake, at or above MIX -> mix icon.
WM6_SNOW_PROB = 0.70
WM6_MIX_PROB = 0.30


def wm6_p_snow_at(wm6_ptype, when_local):
    """WM-6 ensemble probability of snow at when_local, linearly
    interpolated between its 3-hourly steps (column times fall between
    them), or None if there's no data bracketing it."""
    if not wm6_ptype:
        return None
    recs = wm6_ptype["forecasts"][0] if isinstance(wm6_ptype["forecasts"][0], list) else wm6_ptype["forecasts"]
    pts = sorted((datetime.fromisoformat(r["time"].replace("Z", "+00:00")), r["distribution"]["p_snow"])
                 for r in recs if r.get("distribution") and r["distribution"].get("p_snow") is not None)
    for (t0, p0), (t1, p1) in zip(pts, pts[1:]):
        if t0 <= when_local <= t1:
            frac = (when_local - t0) / (t1 - t0) if t1 > t0 else 0
            return p0 + (p1 - p0) * frac
    return None


def text_width(fig, ax, text, fontprops, fontsize):
    """Rendered width of text in ax's data (0-1 figure-fraction) units."""
    t = ax.text(0, 0, text, fontproperties=fontprops, fontsize=fontsize)
    bbox = t.get_window_extent(renderer=fig.canvas.get_renderer())
    t.remove()
    return bbox.width / fig.bbox.width


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--forecast", nargs="+", default=["forecast.json"],
                     help="One or more fetch_forecast.py outputs; each gets its own pair of "
                          "rows, stacked in the order given (e.g. forecast.json "
                          "forecast_hermiston.json for Tri-Cities + Hermiston on one graphic)")
    ap.add_argument("--day", default="wednesday",
                     help="Weekday to show (the next one, today included)")
    ap.add_argument("--overnight", action="store_true",
                     help="Show --day's night into the next morning (6 PM-9 AM) instead of "
                          "its 6 AM-9 PM daytime, e.g. --day friday --overnight for "
                          "Friday night/Saturday morning")
    ap.add_argument("--output", default=None,
                     help="Defaults to <labels>_<day>_table.png, e.g. tri_cities_wednesday_table.png "
                          "or tri_cities_hermiston_wednesday_table.png")
    return ap.parse_args()


def column_times(date, local_tz, overnight):
    """Local datetimes for each column. Built by adding hours to local
    midnight via a naive datetime, so a column past midnight lands on the
    next calendar date at the right wall-clock hour."""
    offsets = OVERNIGHT_HOUR_OFFSETS if overnight else COLUMN_HOURS
    midnight = datetime(date.year, date.month, date.day)
    return [(midnight + timedelta(hours=o)).replace(tzinfo=local_tz) for o in offsets]


def location_columns(data, times):
    local_tz = ZoneInfo(data["timezone"])
    cols = []
    for when in times:
        when = when.replace(tzinfo=local_tz)
        snow = data.get("nws_snow_level", {})
        level = snow_level_at(snow, when) if snow else None
        surface = snow.get("surface_elevation_m")
        cols.append({
            "label": hour_label(when.hour),
            # snow reaching the surface: the snow level is at/below the
            # ground (i.e. the surface sits above the snow level)
            "snow_to_surface": level is not None and surface is not None and level <= surface,
            "wm6_p_snow": wm6_p_snow_at(data.get("wm6_ptype"), when),
            "temp": nws_temp_at(data["nws_hourly"], when),
            "precip": precip_chance(data["ecmwf_ensemble"], when),
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
    period = f"{args.day.lower()}_night" if args.overnight else args.day.lower()
    output = args.output or f"{slug}_{period}_table.png"

    times = column_times(date, local_tz, args.overnight)
    groups = [(lbl, location_columns(d, times)) for lbl, d in zip(labels, locations)]
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
    n = len(times)
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

    for idx, when in enumerate(times):
        cx = cell_x0 + idx * (cell_w + GUTTER) + cell_w / 2
        ax.text(cx, HEADER_Y, hour_label(when.hour), ha="center", va="center",
                 fontproperties=f_bold, fontsize=17, color=INK, zorder=3)
        if args.overnight:
            # the window spans two dates, so say which day each column is on
            ax.text(cx, HEADER_Y + 0.033, when.strftime("%a").upper(), ha="center", va="center",
                     fontproperties=f_med, fontsize=10.5, color=INK_SECONDARY, zorder=3)

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
            # Precip type, in priority order:
            #  - below freezing at the surface -> snow
            #  - WM-6 ensemble snow probability >= WM6_SNOW_PROB -> snow
            #  - snow level at/below the surface, or WM-6 snow probability
            #    >= WM6_MIX_PROB -> rain/snow mix
            #  - otherwise rain
            # The ensemble's own rain/snow call is only the fallback when
            # there's no NWS temperature for the column.
            if col["temp"] is None:
                ptype = "snow" if ens_snow else "rain"
            elif col["temp"] < FREEZING_F:
                ptype = "snow"
            elif col["wm6_p_snow"] is not None and col["wm6_p_snow"] >= WM6_SNOW_PROB:
                ptype = "snow"
            elif col["snow_to_surface"] or (col["wm6_p_snow"] is not None
                                            and col["wm6_p_snow"] >= WM6_MIX_PROB):
                ptype = "mix"
            else:
                ptype = "rain"
            pop_pct = round(pop * 100 / 5) * 5
            color = COLOR_RAIN if ptype == "rain" else COLOR_SNOW
            faint = pop_pct < 20
            # The mix icon is a raindrop (top-left) / snowflake (bottom-right)
            # split by a diagonal slash, in a box about as tall as a normal
            # single glyph -- it stays in the same drop/flake vocabulary as
            # the other cells (the icon font's own MIXED_RAIN_SNOW glyph is a
            # whole cloud).
            single_ch = SNOWFLAKE if ptype == "snow" else RAINDROP
            single_w = text_width(fig, ax, RAINDROP, ICON_FONT, pop_icon_fs)
            icon_w = single_w * 1.6 if ptype == "mix" else text_width(fig, ax, single_ch, ICON_FONT, pop_icon_fs)
            pop_text = f"{pop_pct:.0f}%"
            if compact:
                # icon beside the number: measure both and center the pair as
                # a unit, so a wide "100%" doesn't spill past the cell edge
                PAIR_GAP = 0.008
                num_w = text_width(fig, ax, pop_text, f_bold, pop_fs)
                icon_left = cx - (icon_w + PAIR_GAP + num_w) / 2
                icon_y = pop_mid
                num_xy, num_ha = (icon_left + icon_w + PAIR_GAP, pop_mid), "left"
            else:
                icon_left = cx - icon_w / 2
                icon_y = pop_mid + 0.045
                num_xy, num_ha = (cx, pop_mid - 0.04), "center"
            alpha = 0.35 if faint else 1.0
            if ptype == "mix":
                # glyph height in axes-y units (figure is 8.3in tall), so the
                # diagonal offsets scale with the icon size
                icon_h = pop_icon_fs / 72 / fig.get_size_inches()[1]
                icon_cx = icon_left + icon_w / 2
                for ch, part_color, part_fs, fx, fy in [
                        (RAINDROP, COLOR_RAIN, pop_icon_fs * 0.62, -0.27, 0.24),
                        (SNOWFLAKE, COLOR_SNOW, pop_icon_fs * 0.62, 0.27, -0.24)]:
                    glyph = ax.text(icon_cx + fx * icon_w, icon_y + fy * icon_h, ch, ha="center",
                                     va="center", fontproperties=ICON_FONT, fontsize=part_fs,
                                     color=part_color, alpha=alpha, zorder=3)
                    glyph.set_path_effects([pe.withStroke(linewidth=1.0, foreground=part_color)])
                ax.plot([icon_cx - 0.14 * icon_w, icon_cx + 0.14 * icon_w],
                         [icon_y - 0.42 * icon_h, icon_y + 0.42 * icon_h],
                         color=INK_SECONDARY, linewidth=1.6, solid_capstyle="round",
                         alpha=alpha, zorder=3)
            else:
                glyph = ax.text(icon_left, icon_y, single_ch, ha="left", va="center",
                                 fontproperties=ICON_FONT, fontsize=pop_icon_fs, color=color,
                                 alpha=alpha, zorder=3)
                glyph.set_path_effects([pe.withStroke(linewidth=1.2, foreground=color)])
            ax.text(*num_xy, pop_text, ha=num_ha, va="center",
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

    updated = f"Updated {now_local.strftime('%d %B %Y %H:%M')} {short_tz_abbr(now_local.strftime('%Z'))}"
    if args.overnight:
        next_day = date + timedelta(days=1)
        title = f"{' & '.join(labels)}: {date.strftime('%A')} Night–{next_day.strftime('%A')} Morning"
        subtitle = f"{date.strftime('%B %-d')}–{next_day.strftime('%-d') if next_day.month == date.month else next_day.strftime('%B %-d')} • {updated}"
    else:
        title = f"{' & '.join(labels)} Forecast: {date.strftime('%A, %B %-d')}"
        subtitle = updated
    fig.text(title_x, 0.935, title,
              fontproperties=f_bold, fontsize=24, color=INK)
    fig.text(title_x, 0.895, subtitle,
              fontproperties=f_reg, fontsize=12, color=INK_SECONDARY)

    fig.text((LEFT + RIGHT) / 2, 0.075,
              "Temperature: NWS hourly • Chance of precip: ≥0.01\" in the 3 hrs around each time, "
              "ECMWF ensemble"
              + (" • Rain/snow: WM-6 ensemble" if any(d.get("wm6_ptype") for d in locations) else "")
              + " • Ingalls Weather",
              fontproperties=f_reg, fontsize=9, color=INK_SECONDARY, ha="center")

    plt.savefig(output, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
    print(f"saved {output}")
    for label, cols in groups:
        print(f"  {label}:")
        for col in cols:
            p = col["precip"]
            ps = col.get("wm6_p_snow")
            print(f"    {col['label']:>5}: {col['temp']}°F, "
                  f"{'—' if p is None else f'{p[0]:.0%}'}"
                  f"{'' if ps is None else f', WM-6 snow {ps:.0%}'}")


if __name__ == "__main__":
    main()

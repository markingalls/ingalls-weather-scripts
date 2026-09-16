import argparse
import calendar
import json
import os
from datetime import date

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patches as mpatches
import matplotlib.patheffects as pe
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.cm import ScalarMappable

# ---------- fonts (same family as the other charts) ----------
FONT_DIR = "/usr/share/fonts/truetype/google-fonts/"
f_bold = fm.FontProperties(fname=FONT_DIR + "Poppins-Bold.ttf")
f_reg = fm.FontProperties(fname=FONT_DIR + "Poppins-Regular.ttf")
f_med = fm.FontProperties(fname=FONT_DIR + "Poppins-Medium.ttf")

# ---------- palette (same canvas/style as the other Tri-Cities charts) ----------
BG = "#f7f6f2"
INK = "#2b2a26"
INK_SECONDARY = "#5a584f"
GRID_COLOR = "#000000"
MISSING_COLOR = "#d8d6d0"

MONTHS = [6, 7, 8]
MONTH_NAMES = {6: "June", 7: "July", 8: "August"}
WEEKDAY_LETTERS = ["S", "M", "T", "W", "T", "F", "S"]  # Sunday-first

# Departure-from-normal spectrum: purple (-15F) -> blue -> no shade (0F,
# white) -> orange -> red -> maroon (+15F). Anchored so 0F lands exactly on
# white -- "no shade" -- rather than splitting the range into even steps,
# since a departure of zero having no color at all is the point of the
# scale. The warm half packs three named colors (orange/red/maroon) into
# its upper reach so maroon is reserved for the most extreme heat, mirroring
# how purple alone marks the most extreme cold.
DEPARTURE_STOPS = [
    (0.000, "#5b2c83"),  # -15F, purple
    (0.250, "#3f6fb3"),  # -7.5F, blue
    (0.500, "#ffffff"),  #  0F, no shade
    (0.667, "#e5822a"),  # +5F, orange
    (0.833, "#c0272d"),  # +10F, red
    (1.000, "#6e1423"),  # +15F, maroon
]
DEPARTURE_CMAP = LinearSegmentedColormap.from_list("departure_purple_maroon", DEPARTURE_STOPS)
DEPARTURE_VMAX = 15.0
DEPARTURE_NORM = Normalize(vmin=-DEPARTURE_VMAX, vmax=DEPARTURE_VMAX, clip=True)


def parse_args():
    ap = argparse.ArgumentParser(description="Render a JJA daily-high calendar, color-coded by departure from normal.")
    ap.add_argument("--data", default="jja_highs.json")
    ap.add_argument("--output", default=None, help="defaults to output/tri_cities_jja_calendar_<year>.png")
    return ap.parse_args()


def cell_text_style(face_rgba):
    """Foreground + halo color for text drawn on a cell of this color. A
    fixed dark-ink-on-white-halo pairing reads fine on the pale middle of
    the departure scale, but on its darkest ends (deep purple/maroon) dark
    text has too little contrast against the cell itself for a thin halo
    to fully rescue -- so flip to white text with a dark halo once the
    cell's own luminance drops below the point where dark ink stops
    working, rather than leaning harder on the halo alone."""
    r, g, b = face_rgba[:3]
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return (INK, "white") if luminance >= 0.55 else ("white", INK)


def draw_month(ax, year, month, days_by_date, fixed_rows):
    weeks = calendar.Calendar(firstweekday=6).monthdayscalendar(year, month)  # Sunday-first
    n_weeks = len(weeks)

    # ylim height is fixed_rows (the most weeks any of the three months
    # needs) across every axes, not each month's own n_weeks -- with
    # set_aspect("equal"), a differing data-unit height per axes would
    # scale each month's cells (and everything placed via data
    # coordinates) by a different factor, throwing off both cell size and
    # title alignment between months. A month with fewer weeks (e.g. a
    # 5-week June next to 6-week July/August) just leaves its unused
    # trailing row blank, like a real wall calendar.
    ax.set_xlim(0, 7)
    ax.set_ylim(0, fixed_rows + 1)
    ax.invert_yaxis()
    ax.axis("off")
    ax.set_aspect("equal")
    # set_aspect("equal") shrinks the drawn plot to fit the axes' box while
    # preserving x/y scale, then centers it in that box by default -- pin
    # it to the box's top edge instead so the grid actually starts where
    # its bounding box (and the fig.text title placed from that box's own
    # position, below) says it does.
    ax.set_anchor("N")

    # weekday header row
    for col, letter in enumerate(WEEKDAY_LETTERS):
        ax.text(col + 0.5, 0.5, letter, ha="center", va="center",
                 fontproperties=f_med, fontsize=11, color=INK_SECONDARY)

    month_deps = []
    for row, week in enumerate(weeks):
        for col, day in enumerate(week):
            if day == 0:
                continue
            y0 = row + 1
            d = days_by_date.get(date(year, month, day).isoformat())
            maxt = d["maxt_f"] if d else None
            departure = d["departure_f"] if d else None

            if maxt is None:
                face = MISSING_COLOR
                fg, halo = INK_SECONDARY, "white"
            else:
                face = DEPARTURE_CMAP(DEPARTURE_NORM(departure))
                month_deps.append(departure)
                fg, halo = cell_text_style(face)

            ax.add_patch(mpatches.Rectangle((col, y0), 1, 1, facecolor=face,
                                             edgecolor=GRID_COLOR, linewidth=0.6))

            # Halo widths stay small (sized to each glyph, not just the
            # cell's darkness) -- once text color itself contrasts against
            # the cell, the halo only has to soften the edge, not carry the
            # whole job of separating text from background.
            day_txt = ax.text(col + 0.09, y0 + 0.10, str(day), ha="left", va="top",
                               fontproperties=f_reg, fontsize=8.5, color=fg)
            day_txt.set_path_effects([pe.withStroke(linewidth=1.3, foreground=halo)])

            if maxt is None:
                m_txt = ax.text(col + 0.5, y0 + 0.55, "M", ha="center", va="center",
                                 fontproperties=f_med, fontsize=13, color=fg)
                m_txt.set_path_effects([pe.withStroke(linewidth=2.0, foreground=halo)])
                continue

            hi_txt = ax.text(col + 0.5, y0 + 0.5, f"{maxt:.0f}°", ha="center", va="center",
                              fontproperties=f_bold, fontsize=13, color=fg)
            hi_txt.set_path_effects([pe.withStroke(linewidth=2.0, foreground=halo)])

            dep_str = "0" if departure == 0 else f"{departure:+.0f}"
            dep_txt = ax.text(col + 0.5, y0 + 0.82, dep_str, ha="center", va="center",
                               fontproperties=f_reg, fontsize=8.5, color=fg)
            dep_txt.set_path_effects([pe.withStroke(linewidth=1.3, foreground=halo)])

    return month_deps


def main():
    args = parse_args()
    data = json.load(open(args.data))
    year = data["year"]
    days_by_date = {d["date"]: d for d in data["days"]}

    output = args.output or f"output/tri_cities_jja_calendar_{year}.png"
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)

    fig = plt.figure(figsize=(16, 9), dpi=200)
    fig.patch.set_facecolor(BG)

    fixed_rows = max(len(calendar.Calendar(firstweekday=6).monthdayscalendar(year, m)) for m in MONTHS)

    axes = []
    left, width, gap = 0.03, 0.30, 0.015
    bottom, height = 0.10, 0.64
    for i, month in enumerate(MONTHS):
        x0 = left + i * (width + gap)
        ax = fig.add_axes([x0, bottom, width, height])
        ax.set_facecolor(BG)
        axes.append(ax)

    all_deps = []
    month_deps_by_month = {}
    for ax, month in zip(axes, MONTHS):
        month_deps = draw_month(ax, year, month, days_by_date, fixed_rows)
        month_deps_by_month[month] = month_deps
        all_deps += month_deps

    # ---------- month titles ("June", "avg +1.7°F") ----------
    # Placed via figure-fraction coordinates from each axes' own bbox
    # (fixed after fig.canvas.draw()), not axes data coordinates -- with
    # set_aspect("equal"), a title placed above the grid in data space
    # would shift depending on that axes' own unit-to-inch scale factor.
    fig.canvas.draw()
    for ax, month in zip(axes, MONTHS):
        month_deps = month_deps_by_month[month]
        avg_dep = sum(month_deps) / len(month_deps) if month_deps else None
        subtitle = f"avg {avg_dep:+.1f}°F" if avg_dep is not None else "no data"

        axpos = ax.get_position()
        cx = (axpos.x0 + axpos.x1) / 2
        fig.text(cx, axpos.y1 + 0.058, MONTH_NAMES[month], ha="center", va="baseline",
                  fontproperties=f_bold, fontsize=16, color=INK)
        fig.text(cx, axpos.y1 + 0.025, subtitle, ha="center", va="baseline",
                  fontproperties=f_reg, fontsize=10.5, color=INK_SECONDARY)

    # ---------- color-scale legend (horizontal strip under the calendars) ----------
    cbar_ax = fig.add_axes([0.32, 0.135, 0.36, 0.02])
    sm = ScalarMappable(norm=DEPARTURE_NORM, cmap=DEPARTURE_CMAP)
    cb = fig.colorbar(sm, cax=cbar_ax, orientation="horizontal")
    cb.set_ticks([-15, -10, -5, 0, 5, 10, 15])
    cb.ax.tick_params(labelsize=9.5, colors=INK_SECONDARY, length=3)
    for tick in cb.ax.get_xticklabels():
        tick.set_fontproperties(f_reg)
    cb.outline.set_edgecolor(GRID_COLOR)
    cb.outline.set_linewidth(0.6)
    fig.text(0.32 + 0.18, 0.165, f"Daily high departure from {data['normals_period']} average (°F)",
              ha="center", fontproperties=f_med, fontsize=10.5, color=INK_SECONDARY)

    # ---------- logo (bottom-right) ----------
    LOGO_PATH = "../assets/ingalls_weather_logo.png"
    if os.path.exists(LOGO_PATH):
        logo_img = plt.imread(LOGO_PATH)
        img_h, img_w = logo_img.shape[0], logo_img.shape[1]
        fig_w_in, fig_h_in = fig.get_size_inches()
        dpi = fig.get_dpi()
        inset_px = 22
        inset_x = inset_px / (fig_w_in * dpi)
        inset_y = inset_px / (fig_h_in * dpi)

        logo_width_fig = 0.07
        logo_width_in = logo_width_fig * fig_w_in
        logo_height_in = logo_width_in * (img_h / img_w)
        logo_height_fig = logo_height_in / fig_h_in

        logo_x0 = 0.97 - logo_width_fig
        logo_y0 = 0.02
        logo_ax = fig.add_axes([logo_x0, logo_y0, logo_width_fig, logo_height_fig], zorder=20)
        logo_ax.imshow(logo_img)
        logo_ax.axis("off")
    else:
        print(f"NOTE: no logo found at {LOGO_PATH} -- skipping logo placement.")

    # ---------- title / subtitle ----------
    n_with_data = len(all_deps)
    season_avg = sum(all_deps) / n_with_data if n_with_data else None
    # va="top" anchors the title to its own top edge, so the margin above
    # it is exactly the number below -- unlike baseline placement, it
    # doesn't shrink or grow with the font's own ascender metrics.
    title = f"Tri-Cities Summer (JJA) Daily High Temperature — {year}"
    fig.text(0.03, 0.965, title, va="top", fontproperties=f_bold, fontsize=24, color=INK)
    subtitle = (f"{data['label']} ({data['station']}) • ACIS/xmACIS Observed • "
                f"{data['normals_period']} average"
                + (f" • Summer averaged {season_avg:+.1f}°F vs. normal" if season_avg is not None else ""))
    fig.text(0.03, 0.905, subtitle, va="top", fontproperties=f_reg, fontsize=13, color=INK_SECONDARY)

    # ---------- attribution ----------
    fig.text(0.5, 0.055, "ACIS/xmACIS (observed & 1991-2020 normals) — Ingalls Weather",
              fontproperties=f_reg, fontsize=9, color=INK_SECONDARY, ha="center")

    plt.savefig(output, facecolor=fig.get_facecolor())
    print(f"saved {output}")


if __name__ == "__main__":
    main()

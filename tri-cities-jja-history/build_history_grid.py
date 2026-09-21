import argparse
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patches as mpatches
import matplotlib.patheffects as pe
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.cm import ScalarMappable

# ---------- fonts (same family as the other Tri-Cities charts) ----------
FONT_DIR = "/usr/share/fonts/truetype/google-fonts/"
f_bold = fm.FontProperties(fname=FONT_DIR + "Poppins-Bold.ttf")
f_reg = fm.FontProperties(fname=FONT_DIR + "Poppins-Regular.ttf")
f_med = fm.FontProperties(fname=FONT_DIR + "Poppins-Medium.ttf")

# ---------- palette (same canvas/style as tri-cities-jja-calendar) ----------
BG = "#f7f6f2"
INK = "#2b2a26"
INK_SECONDARY = "#5a584f"
GRID_COLOR = "#000000"
MISSING_COLOR = "#d8d6d0"

ROW_KEYS = ["june", "july", "august", "season"]
ROW_LABELS = {"june": "June", "july": "July", "august": "August", "season": "Season (JJA)"}

# Same purple-blue-white-orange-red-maroon spectrum as the calendar
# (tri-cities-jja-calendar/build_calendar.py), but scaled to a much
# narrower +-10F -- these are monthly/seasonal *averages*, not single-day
# highs, so they rarely approach the +-15F that makes sense for one day;
# at that scale nearly every cell here would land pale and washed out.
DEPARTURE_STOPS = [
    (0.000, "#5b2c83"),  # purple
    (0.250, "#3f6fb3"),  # blue
    (0.500, "#ffffff"),  # no shade
    (0.667, "#e5822a"),  # orange
    (0.833, "#c0272d"),  # red
    (1.000, "#6e1423"),  # maroon
]
DEPARTURE_CMAP = LinearSegmentedColormap.from_list("departure_purple_maroon", DEPARTURE_STOPS)
DEPARTURE_VMAX = 10.0
DEPARTURE_NORM = Normalize(vmin=-DEPARTURE_VMAX, vmax=DEPARTURE_VMAX, clip=True)


def parse_args():
    ap = argparse.ArgumentParser(description="Render a year-over-year JJA departure grid (June/July/August/Season x year).")
    ap.add_argument("--data", default="jja_history.json")
    ap.add_argument("--output", default=None, help="defaults to output/tri_cities_jja_history_<start>-<end>.png")
    return ap.parse_args()


def cell_text_style(face_rgba):
    """Same background-aware text color as the calendar's cell_text_style
    (tri-cities-jja-calendar/build_calendar.py) -- a fixed dark-ink-on-
    white-halo pairing loses contrast on this scale's darkest ends."""
    r, g, b = face_rgba[:3]
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return (INK, "white") if luminance >= 0.55 else ("white", INK)


def flow_text(fig, fig_h_in, x, y_top, text, fontsize, fontproperties, color, ha="left", gap_after_in=0.0):
    """Top-anchored text that returns the cursor y for whatever comes
    next -- see tri-cities-jja-calendar/build_calendar.py for why this
    beats hand-tuned fixed coordinates."""
    fig.text(x, y_top, text, ha=ha, va="top", fontproperties=fontproperties, fontsize=fontsize, color=color)
    line_height_in = fontsize / 72.0 * 1.25
    return y_top - (line_height_in + gap_after_in) / fig_h_in


def main():
    args = parse_args()
    data = json.load(open(args.data))
    start_year, end_year = data["start_year"], data["end_year"]
    years = list(range(start_year, end_year + 1))
    n_years = len(years)

    output = args.output or f"output/tri_cities_jja_history_{start_year}-{end_year}.png"
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)

    FIG_W, FIG_H = 16.0, 9.0
    MARGIN_X = 0.05
    LABEL_W = 0.10  # reserved for row labels ("August", "Season (JJA)") left of the grid
    GAP_ROWS = 0.6  # blank row-units between August and Season, in grid data-coordinates

    fig = plt.figure(figsize=(FIG_W, FIG_H), dpi=200)
    fig.patch.set_facecolor(BG)

    grid_x0 = MARGIN_X + LABEL_W
    grid_width = 1 - grid_x0 - MARGIN_X
    total_row_units = 1 + 3 + GAP_ROWS + 1  # header + June/July/August + gap + Season

    # ---------- vertical flow, top to bottom ----------
    cursor = 1.0 - 0.35 / FIG_H
    title = f"Tri-Cities JJA High Temperature Departure — {start_year}-{end_year}"
    cursor = flow_text(fig, FIG_H, MARGIN_X, cursor, title, 24, f_bold, INK, gap_after_in=0.08)
    subtitle = f"{data['label']} ({data['station']}) • ACIS/xmACIS Observed • {data['normals_period']} average"
    cursor = flow_text(fig, FIG_H, MARGIN_X, cursor, subtitle, 13, f_reg, INK_SECONDARY, gap_after_in=0.3)

    grid_top = cursor
    row_h_in = 1.0
    grid_height = (total_row_units * row_h_in) / FIG_H
    ax = fig.add_axes([grid_x0, grid_top - grid_height, grid_width, grid_height])
    ax.set_facecolor(BG)
    ax.set_xlim(0, n_years)
    ax.set_ylim(0, total_row_units)
    ax.invert_yaxis()
    ax.axis("off")

    # year header row (row 0), no fill -- same idea as the calendar's
    # weekday-letter header row.
    for col, year in enumerate(years):
        ax.text(col + 0.5, 0.5, str(year), ha="center", va="center",
                 fontproperties=f_bold, fontsize=14, color=INK)

    row_y0 = {"june": 1, "july": 2, "august": 3, "season": 4 + GAP_ROWS}
    for key in ROW_KEYS:
        y0 = row_y0[key]
        ax.text(-0.15, y0 + 0.5, ROW_LABELS[key], ha="right", va="center", clip_on=False,
                 fontproperties=f_med, fontsize=13, color=INK_SECONDARY)

        for col, year in enumerate(years):
            dep = data["years"].get(str(year), {}).get(key)

            if dep is None:
                face = MISSING_COLOR
                fg, halo = INK_SECONDARY, "white"
                text = "N/A"
            else:
                face = DEPARTURE_CMAP(DEPARTURE_NORM(dep))
                fg, halo = cell_text_style(face)
                text = f"{dep:+.1f}°F"

            ax.add_patch(mpatches.Rectangle((col, y0), 1, 1, facecolor=face,
                                             edgecolor=GRID_COLOR, linewidth=0.6))
            txt = ax.text(col + 0.5, y0 + 0.5, text, ha="center", va="center",
                           fontproperties=f_bold, fontsize=15, color=fg)
            txt.set_path_effects([pe.withStroke(linewidth=2.0, foreground=halo)])

    cursor = grid_top - grid_height - 0.2 / FIG_H

    # ---------- color-scale legend ----------
    cursor = flow_text(fig, FIG_H, 0.5, cursor,
                        f"Monthly/seasonal average daily-high departure from {data['normals_period']} average (°F)",
                        10.5, f_med, INK_SECONDARY, ha="center", gap_after_in=0.08)

    cbar_width, cbar_height_in = 0.36, 0.16
    cbar_bottom = cursor - cbar_height_in / FIG_H
    cbar_ax = fig.add_axes([(1 - cbar_width) / 2, cbar_bottom, cbar_width, cbar_height_in / FIG_H])
    sm = ScalarMappable(norm=DEPARTURE_NORM, cmap=DEPARTURE_CMAP)
    cb = fig.colorbar(sm, cax=cbar_ax, orientation="horizontal")
    cb.set_ticks([-10, -5, 0, 5, 10])
    cb.ax.tick_params(labelsize=9.5, colors=INK_SECONDARY, length=3)
    for tick in cb.ax.get_xticklabels():
        tick.set_fontproperties(f_reg)
    cb.outline.set_edgecolor(GRID_COLOR)
    cb.outline.set_linewidth(0.6)
    cursor = cbar_bottom - 0.3 / FIG_H

    # ---------- logo (bottom-right) ----------
    LOGO_PATH = "../assets/ingalls_weather_logo.png"
    if os.path.exists(LOGO_PATH):
        logo_img = plt.imread(LOGO_PATH)
        img_h, img_w = logo_img.shape[0], logo_img.shape[1]
        dpi = fig.get_dpi()
        inset_px = 22
        inset_x = inset_px / (FIG_W * dpi)
        inset_y = inset_px / (FIG_H * dpi)

        logo_width_fig = 0.06
        logo_width_in = logo_width_fig * FIG_W
        logo_height_in = logo_width_in * (img_h / img_w)
        logo_height_fig = logo_height_in / FIG_H

        logo_x0 = 1.0 - inset_x - logo_width_fig
        logo_y0 = inset_y
        logo_ax = fig.add_axes([logo_x0, logo_y0, logo_width_fig, logo_height_fig], zorder=20)
        logo_ax.imshow(logo_img)
        logo_ax.axis("off")
    else:
        print(f"NOTE: no logo found at {LOGO_PATH} -- skipping logo placement.")

    # ---------- attribution ----------
    flow_text(fig, FIG_H, 0.5, cursor, "ACIS/xmACIS (observed & 1991-2020 normals) — Ingalls Weather",
              9, f_reg, INK_SECONDARY, ha="center")

    plt.savefig(output, facecolor=fig.get_facecolor())
    print(f"saved {output}")


if __name__ == "__main__":
    main()

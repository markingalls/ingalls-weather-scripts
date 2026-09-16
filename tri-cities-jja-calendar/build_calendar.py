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


def flow_text(fig, fig_h_in, x, y_top, text, fontsize, fontproperties, color, ha="left", gap_after_in=0.0):
    """Draws top-anchored text at y_top and returns the cursor y for
    whatever comes next, advanced by this text's own line height plus
    gap_after_in. A hand-tuned fixed offset for each line (the previous
    approach) has to be re-guessed by eye every time a size or a figure
    dimension changes; flowing the cursor down by each element's actual
    height keeps every block correctly spaced regardless."""
    fig.text(x, y_top, text, ha=ha, va="top", fontproperties=fontproperties, fontsize=fontsize, color=color)
    line_height_in = fontsize / 72.0 * 1.25
    return y_top - (line_height_in + gap_after_in) / fig_h_in


def draw_month(ax, year, month, days_by_date, fixed_rows):
    weeks = calendar.Calendar(firstweekday=6).monthdayscalendar(year, month)  # Sunday-first

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


def month_avg_departure(data, month):
    deps = [d["departure_f"] for d in data["days"]
            if d["departure_f"] is not None and date.fromisoformat(d["date"]).month == month]
    return sum(deps) / len(deps) if deps else None


def main():
    args = parse_args()
    data = json.load(open(args.data))
    year = data["year"]
    days_by_date = {d["date"]: d for d in data["days"]}

    output = args.output or f"output/tri_cities_jja_calendar_{year}.png"
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)

    # Two rows -- June/July side by side, August centered below -- rather
    # than all three in one row, so each month gets a bigger grid on a
    # taller canvas instead of being squeezed to fit three across.
    ROW_MONTHS = [[6, 7], [8]]
    FIG_W, FIG_H = 11.5, 14.0
    MARGIN_X, GAP_X = 0.07, 0.03

    fig = plt.figure(figsize=(FIG_W, FIG_H), dpi=200)
    fig.patch.set_facecolor(BG)

    fixed_rows = max(len(calendar.Calendar(firstweekday=6).monthdayscalendar(year, m)) for m in MONTHS)
    month_width = (1 - 2 * MARGIN_X - GAP_X) / 2
    month_width_in = month_width * FIG_W
    # Visible grid height once set_aspect("equal") locks it to this width
    # (see draw_month) -- same for every month, since they all share one
    # width and one fixed_rows.
    visible_grid_h = (month_width_in * (fixed_rows + 1) / 7) / FIG_H
    month_x0 = {6: MARGIN_X, 7: MARGIN_X + month_width + GAP_X, 8: (1 - month_width) / 2}

    all_deps = [d["departure_f"] for d in data["days"] if d["departure_f"] is not None]
    season_avg = sum(all_deps) / len(all_deps) if all_deps else None

    # ---------- vertical flow, top to bottom ----------
    # Each block is placed from a running cursor advanced by that block's
    # own height plus a gap, rather than at hand-tuned fixed coordinates --
    # so row/figure-size changes don't require re-guessing offsets by eye.
    cursor = 1.0 - 0.35 / FIG_H

    title = f"Tri-Cities Summer (JJA) Daily High Temperature — {year}"
    cursor = flow_text(fig, FIG_H, MARGIN_X, cursor, title, 24, f_bold, INK, gap_after_in=0.08)
    subtitle = (f"{data['label']} ({data['station']}) • ACIS/xmACIS Observed • "
                f"{data['normals_period']} average"
                + (f" • Summer averaged {season_avg:+.1f}°F vs. normal" if season_avg is not None else ""))
    cursor = flow_text(fig, FIG_H, MARGIN_X, cursor, subtitle, 13, f_reg, INK_SECONDARY, gap_after_in=0.35)

    for row_months in ROW_MONTHS:
        title_cursor = cursor
        for m in row_months:
            fig.text(month_x0[m] + month_width / 2, title_cursor, MONTH_NAMES[m], ha="center", va="top",
                      fontproperties=f_bold, fontsize=16, color=INK)
        cursor = title_cursor - (16 / 72.0 * 1.25 + 0.05) / FIG_H

        avg_cursor = cursor
        for m in row_months:
            avg_dep = month_avg_departure(data, m)
            avg_text = f"avg {avg_dep:+.1f}°F" if avg_dep is not None else "no data"
            fig.text(month_x0[m] + month_width / 2, avg_cursor, avg_text, ha="center", va="top",
                      fontproperties=f_reg, fontsize=10.5, color=INK_SECONDARY)
        cursor = avg_cursor - (10.5 / 72.0 * 1.25 + 0.06) / FIG_H

        row_axes_top = cursor
        # A little taller than the visible grid, not exactly equal to it --
        # set_aspect("equal") only anchors cleanly to this box's own width
        # (see draw_month) if the box has at least the height that width
        # implies; anchor("N") leaves any extra as blank space below.
        row_box_height = visible_grid_h * 1.08
        for m in row_months:
            ax = fig.add_axes([month_x0[m], row_axes_top - row_box_height, month_width, row_box_height])
            ax.set_facecolor(BG)
            draw_month(ax, year, m, days_by_date, fixed_rows)

        cursor = row_axes_top - visible_grid_h - 0.15 / FIG_H

    # ---------- color-scale legend (horizontal strip under the calendars) ----------
    cursor = flow_text(fig, FIG_H, 0.5, cursor, f"Daily high departure from {data['normals_period']} average (°F)",
                        10.5, f_med, INK_SECONDARY, ha="center", gap_after_in=0.08)

    cbar_width, cbar_height_in = 0.5, 0.16
    cbar_bottom = cursor - cbar_height_in / FIG_H
    cbar_ax = fig.add_axes([(1 - cbar_width) / 2, cbar_bottom, cbar_width, cbar_height_in / FIG_H])
    sm = ScalarMappable(norm=DEPARTURE_NORM, cmap=DEPARTURE_CMAP)
    cb = fig.colorbar(sm, cax=cbar_ax, orientation="horizontal")
    cb.set_ticks([-15, -10, -5, 0, 5, 10, 15])
    cb.ax.tick_params(labelsize=9.5, colors=INK_SECONDARY, length=3)
    for tick in cb.ax.get_xticklabels():
        tick.set_fontproperties(f_reg)
    cb.outline.set_edgecolor(GRID_COLOR)
    cb.outline.set_linewidth(0.6)
    # room for the colorbar's own tick labels below it, then the attribution line
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

        logo_width_fig = 0.08
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

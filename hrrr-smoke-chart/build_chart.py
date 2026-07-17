import argparse
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.dates as mdates
import numpy as np

# ---------- fonts ----------
FONT_DIR = "/usr/share/fonts/truetype/google-fonts/"
f_bold = fm.FontProperties(fname=FONT_DIR + "Poppins-Bold.ttf")
f_reg = fm.FontProperties(fname=FONT_DIR + "Poppins-Regular.ttf")
f_med = fm.FontProperties(fname=FONT_DIR + "Poppins-Medium.ttf")

# ---------- palette ----------
BG = "#f7f6f2"
INK = "#2b2a26"
INK_SECONDARY = "#5a584f"
GRID_COLOR = "#000000"
AXIS_COLOR = "#000000"

# Same two accents as ../850-700-temp-chart/build_chart.py: forest green
# (the logo's pine tree) for the first location, climatology orange for
# the second, so a multi-line chart still reads as this brand's palette.
LINE_COLORS = ["#164f29", "#c9531c"]

Z_GRID = 2
Z_LINE = 3

PACIFIC = ZoneInfo("America/Los_Angeles")


def parse_args():
    ap = argparse.ArgumentParser(description="Render the HRRR near-surface smoke chart.")
    ap.add_argument("--data", default="smoke.json")
    ap.add_argument("--output", default="hrrr_near_surface_smoke.png")
    return ap.parse_args()


def main():
    args = parse_args()
    data = json.load(open(args.data))

    times = [datetime.fromisoformat(t.replace("Z", "+00:00")) for t in data["times"]]
    init_time = datetime.fromisoformat(data["initialization_time"].replace("Z", "+00:00"))
    locations = data["locations"]
    series = data["series"]

    all_values = [v for vals in series.values() for v in vals]
    y_max = max(max(all_values) * 1.25, 10.0)

    # ---------- figure (same footprint as the alerts map / temp chart) ----------
    fig = plt.figure(figsize=(12, 8.3), dpi=200)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0.075, 0.10, 0.87, 0.65])
    ax.set_facecolor("white")

    for i, loc in enumerate(locations):
        color = LINE_COLORS[i % len(LINE_COLORS)]
        vals = series[loc["label"]]
        ax.plot(times, vals, color=color, linewidth=2.4, zorder=Z_LINE, label=loc["label"])

    ax.set_ylim(0, y_max)

    # ---------- axes styling ----------
    ax.set_ylabel("Near-Surface Smoke (µg/m³)", fontproperties=f_med, fontsize=12, color=INK)
    ax.set_axisbelow(False)
    ax.grid(axis="y", color=GRID_COLOR, alpha=0.25, linewidth=0.9, zorder=Z_GRID)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(AXIS_COLOR)
        ax.spines[spine].set_linewidth(1.0)

    ax.xaxis.set_major_locator(mdates.HourLocator(interval=6, tz=PACIFIC))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%-m/%-d %-I%p", tz=PACIFIC))
    ax.set_xlim(times[0], times[-1])
    ax.tick_params(axis="both", colors=AXIS_COLOR, labelsize=10, length=4)
    for tick in ax.get_xticklabels():
        tick.set_fontproperties(f_reg)
        tick.set_color(INK_SECONDARY)
        tick.set_fontsize(10)
    for tick in ax.get_yticklabels():
        tick.set_fontproperties(f_reg)
        tick.set_color(INK_SECONDARY)
        tick.set_fontsize(10)

    fig.canvas.draw()
    axpos = ax.get_position()
    left_x, right_x, top_y = axpos.x0, axpos.x1, axpos.y1
    center_x = (axpos.x0 + axpos.x1) / 2

    # ---------- legend (horizontal strip above the plot, out of the data's way) ----------
    handles, labels = ax.get_legend_handles_labels()
    leg = fig.legend(handles, labels,
                      loc="lower left", bbox_to_anchor=(left_x, top_y + 0.012),
                      bbox_transform=fig.transFigure, ncol=len(labels), frameon=False,
                      prop=f_reg, fontsize=10.5, handlelength=1.6, columnspacing=1.6)
    for text in leg.get_texts():
        text.set_color(INK_SECONDARY)

    # ---------- logo (bottom-right, matching the alerts map placement) ----------
    LOGO_PATH = "../assets/ingalls_weather_logo.png"
    if os.path.exists(LOGO_PATH):
        logo_img = plt.imread(LOGO_PATH)
        img_h, img_w = logo_img.shape[0], logo_img.shape[1]
        fig_w_in, fig_h_in = fig.get_size_inches()
        dpi = fig.get_dpi()
        inset_px = 22
        inset_x = inset_px / (fig_w_in * dpi)
        inset_y = inset_px / (fig_h_in * dpi)

        logo_width_fig = 0.08 * (axpos.x1 - axpos.x0)
        logo_width_in = logo_width_fig * fig_w_in
        logo_height_in = logo_width_in * (img_h / img_w)
        logo_height_fig = logo_height_in / fig_h_in

        logo_x0 = axpos.x1 - inset_x - logo_width_fig
        logo_y0 = axpos.y0 + inset_y
        logo_ax = fig.add_axes([logo_x0, logo_y0, logo_width_fig, logo_height_fig], zorder=20)
        logo_ax.imshow(logo_img)
        logo_ax.axis("off")
    else:
        print(f"NOTE: no logo found at {LOGO_PATH} -- skipping logo placement.")

    # ---------- title / subtitle ----------
    subtitle_y = top_y + 0.058
    title_y = subtitle_y + 0.035
    title = "Near-Surface Smoke"
    fig.text(left_x, title_y, title, fontproperties=f_bold, fontsize=22, color=INK)
    subtitle = (f"NOAA HRRR Init {init_time.strftime('%Y-%m-%d')} {init_time.strftime('%H')}z"
                f" • 48-hour forecast • Times Pacific")
    fig.text(left_x, subtitle_y, subtitle, fontproperties=f_reg, fontsize=12, color=INK_SECONDARY)

    # ---------- attribution ----------
    fig.text(center_x, 0.02, "NOAA HRRR — Ingalls Weather",
              fontproperties=f_reg, fontsize=9, color=INK_SECONDARY, ha="center")

    plt.savefig(args.output, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
    print(f"saved {args.output}")


if __name__ == "__main__":
    main()

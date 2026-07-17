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
import matplotlib.patheffects as pe
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
# Both lines get a white halo (see LINE_HALO below) since they now sit on
# top of colored AQI bands, some of which are close in hue to these two.
LINE_COLORS = ["#164f29", "#c9531c"]
LINE_HALO = [pe.withStroke(linewidth=4, foreground="white")]

Z_BANDS = 1
Z_GRID = 2
Z_LINE = 3
Z_BAND_LABEL = 4

PACIFIC = ZoneInfo("America/Los_Angeles")

# EPA AQI breakpoints for PM2.5 (24-hr, ug/m3), per the May 2024 revised
# table. HRRR's near-surface smoke field is a smoke mass density, not a
# regulatory PM2.5 measurement -- treating it as PM2.5 to derive an AQI is
# the same approximation NOAA/AirNow smoke-forecast tools make, good for
# a "how smoky will it feel" read rather than an official index.
AQI_BREAKPOINTS = [
    # (conc_lo, conc_hi, aqi_lo, aqi_hi, label, color)
    (0.0, 9.0, 0, 50, "Good", "#00e400"),
    (9.1, 35.4, 51, 100, "Moderate", "#ffff00"),
    (35.5, 55.4, 101, 150, "USG", "#ff7e00"),
    (55.5, 125.4, 151, 200, "Unhealthy", "#ff0000"),
    (125.5, 225.4, 201, 300, "Very Unhealthy", "#8f3f97"),
    (225.5, 325.4, 301, 500, "Hazardous", "#7e0023"),
]


def pm25_to_aqi(conc_ugm3):
    """Piecewise-linear EPA AQI conversion from a PM2.5-equivalent
    concentration (ug/m3). Clamps above the top of the published scale
    (325.4 ug/m3, AQI 500) instead of extrapolating."""
    c = max(0.0, conc_ugm3)
    for conc_lo, conc_hi, aqi_lo, aqi_hi, _, _ in AQI_BREAKPOINTS:
        if c <= conc_hi:
            return (aqi_hi - aqi_lo) / (conc_hi - conc_lo) * (c - conc_lo) + aqi_lo
    return 500.0


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
    series = {label: [pm25_to_aqi(v) for v in vals] for label, vals in data["series"].items()}

    all_values = [v for vals in series.values() for v in vals]
    y_max = max(max(all_values) * 1.25, 100.0)

    # ---------- figure (same footprint as the alerts map / temp chart) ----------
    fig = plt.figure(figsize=(12, 8.3), dpi=200)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0.075, 0.14, 0.87, 0.65])
    ax.set_facecolor("white")

    # ---------- AQI category bands, back to front ----------
    # Drawn edge-to-edge (next band's aqi_lo, not this band's own aqi_hi) so
    # the 1-point gaps baked into the official breakpoints (e.g. 50 vs. 51)
    # don't show up as stray white seams between bands.
    for i, (conc_lo, conc_hi, aqi_lo, aqi_hi, label, color) in enumerate(AQI_BREAKPOINTS):
        if aqi_lo > y_max:
            break
        draw_top = AQI_BREAKPOINTS[i + 1][2] if i + 1 < len(AQI_BREAKPOINTS) else aqi_hi
        ax.axhspan(aqi_lo, draw_top, color=color, alpha=0.35, linewidth=0, zorder=Z_BANDS,
                   antialiased=False)
        band_top = min(aqi_hi, y_max)
        if band_top - aqi_lo < 0.06 * y_max:
            continue  # band sliver too thin at this scale to carry a label
        ax.text(0.985, (aqi_lo + band_top) / 2, label, ha="right", va="center",
                 transform=ax.get_yaxis_transform(),
                 fontproperties=f_med, fontsize=9, color=INK, alpha=0.8,
                 path_effects=[pe.withStroke(linewidth=2.5, foreground="white")],
                 zorder=Z_BAND_LABEL)

    for i, loc in enumerate(locations):
        color = LINE_COLORS[i % len(LINE_COLORS)]
        vals = series[loc["label"]]
        ax.plot(times, vals, color=color, linewidth=2.4, zorder=Z_LINE,
                 path_effects=LINE_HALO, label=loc["label"])

    ax.set_ylim(0, y_max)

    # ---------- axes styling ----------
    ax.set_ylabel("AQI (PM2.5-equivalent)", fontproperties=f_med, fontsize=12, color=INK)
    ax.set_xlabel("Date/Time (Pacific)", fontproperties=f_med, fontsize=12, color=INK)
    ax.set_axisbelow(False)
    ax.grid(axis="y", color=GRID_COLOR, alpha=0.25, linewidth=0.9, zorder=Z_GRID)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(AXIS_COLOR)
        ax.spines[spine].set_linewidth(1.0)

    ax.xaxis.set_major_locator(mdates.HourLocator(interval=6, tz=PACIFIC))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%-m/%-d %H:%M", tz=PACIFIC))
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

    # ---------- title / subtitle ----------
    subtitle_y = top_y + 0.058
    title_y = subtitle_y + 0.035
    title = "Near-Surface Smoke"
    fig.text(left_x, title_y, title, fontproperties=f_bold, fontsize=22, color=INK)
    subtitle = (f"NOAA HRRR Init {init_time.strftime('%Y-%m-%d')} {init_time.strftime('%H')}z"
                f" • 48-hour forecast")
    fig.text(left_x, subtitle_y, subtitle, fontproperties=f_reg, fontsize=12, color=INK_SECONDARY)

    # ---------- logo (top-right, spanning the title/subtitle/legend header) ----------
    LOGO_PATH = "../assets/ingalls_weather_logo.png"
    if os.path.exists(LOGO_PATH):
        logo_img = plt.imread(LOGO_PATH)
        img_h, img_w = logo_img.shape[0], logo_img.shape[1]
        fig_w_in, fig_h_in = fig.get_size_inches()
        dpi = fig.get_dpi()
        inset_px = 22
        inset_x = inset_px / (fig_w_in * dpi)
        inset_y = inset_px / (fig_h_in * dpi)

        logo_top = title_y + 0.048
        logo_bottom = top_y + inset_y
        logo_height_fig = logo_top - logo_bottom
        logo_height_in = logo_height_fig * fig_h_in
        logo_width_in = logo_height_in * (img_w / img_h)
        logo_width_fig = logo_width_in / fig_w_in

        logo_x1 = right_x
        logo_x0 = logo_x1 - logo_width_fig
        logo_ax = fig.add_axes([logo_x0, logo_bottom, logo_width_fig, logo_height_fig], zorder=20)
        logo_ax.imshow(logo_img)
        logo_ax.axis("off")
    else:
        print(f"NOTE: no logo found at {LOGO_PATH} -- skipping logo placement.")

    # ---------- attribution ----------
    fig.text(center_x, 0.02, "NOAA HRRR — Ingalls Weather",
              fontproperties=f_reg, fontsize=9, color=INK_SECONDARY, ha="center")

    plt.savefig(args.output, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
    print(f"saved {args.output}")


if __name__ == "__main__":
    main()

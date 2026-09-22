import argparse
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.ticker as mticker
import numpy as np

# ---------- fonts (same family as the other Tri-Cities charts) ----------
FONT_DIR = "/usr/share/fonts/truetype/google-fonts/"
f_bold = fm.FontProperties(fname=FONT_DIR + "Poppins-Bold.ttf")
f_reg = fm.FontProperties(fname=FONT_DIR + "Poppins-Regular.ttf")
f_med = fm.FontProperties(fname=FONT_DIR + "Poppins-Medium.ttf")

# ---------- palette (same canvas/style as the other Tri-Cities charts) ----------
BG = "#f7f6f2"
INK = "#2b2a26"
INK_SECONDARY = "#5a584f"
GRID_COLOR = "#000000"
AXIS_COLOR = "#000000"

# Forest green for the raw mean-high line -- same hue the other Tri-Cities
# charts use for their primary data series. Warm amber, dashed, for the
# 1991-2020 normal reference line -- same convention as
# tri-cities-temp-chart's climatology line. Fill tints (not the departure
# grid's purple-to-maroon spectrum -- one line crossing one reference
# value just needs "above" vs. "below", not a 6-stop spectrum) mark years
# above/below that reference.
TEMP_COLOR = "#164f29"
NORMAL_LINE_COLOR = "#c9531c"
ABOVE_FILL = "#e8a3a3"
BELOW_FILL = "#a9c6e8"
TREND_COLOR = "#5a584f"
FILL_ALPHA = 0.55

MIN_SEASON_DAYS = 80  # a year needs at least this many of JJA's 92 days to count as usable


def parse_args():
    ap = argparse.ArgumentParser(description="Render the full-period-of-record JJA mean-high trend chart.")
    ap.add_argument("--data", default="jja_history_full.json")
    ap.add_argument("--output", default=None, help="defaults to output/tri_cities_jja_trend_<start>-<end>.png")
    return ap.parse_args()


def main():
    args = parse_args()
    data = json.load(open(args.data))
    start_year, end_year = data["start_year"], data["end_year"]
    normal_mean = data["normal_mean_high"]

    years, means = [], []
    for y in range(start_year, end_year + 1):
        v = data["years"].get(str(y))
        if v and v["maxt_mean"] is not None and v["n_days"] >= MIN_SEASON_DAYS:
            years.append(y)
            means.append(v["maxt_mean"])
    years = np.array(years)
    means = np.array(means)

    output = args.output or f"output/tri_cities_jja_trend_{years[0]}-{years[-1]}.png"
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)

    slope, intercept = np.polyfit(years, means, 1)
    trend = slope * years + intercept
    slope_per_decade = slope * 10

    fig = plt.figure(figsize=(16, 9), dpi=200)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0.06, 0.14, 0.90, 0.62])
    ax.set_facecolor("white")

    ax.fill_between(years, means, normal_mean, where=means >= normal_mean, interpolate=True,
                     color=ABOVE_FILL, alpha=FILL_ALPHA, linewidth=0, zorder=1)
    ax.fill_between(years, means, normal_mean, where=means < normal_mean, interpolate=True,
                     color=BELOW_FILL, alpha=FILL_ALPHA, linewidth=0, zorder=1)

    ax.axhline(normal_mean, color=NORMAL_LINE_COLOR, linewidth=2.0, linestyle="--", dashes=(6, 3),
               zorder=3, label=f"{data['normals_period']} average ({normal_mean:.1f}°F)")

    ax.plot(years, trend, color=TREND_COLOR, linewidth=1.8, linestyle=":", dashes=(1, 2),
            zorder=3, label=f"Linear trend ({slope_per_decade:+.2f}°F/decade)")

    ax.plot(years, means, color=TEMP_COLOR, linewidth=2.4, marker="o", markersize=5.5,
            zorder=4, label="JJA mean high (observed)")

    ax.set_ylabel("JJA Mean High Temperature (°F)", fontproperties=f_med, fontsize=12, color=INK)
    ax.set_axisbelow(False)
    ax.grid(axis="y", color=GRID_COLOR, alpha=0.2, linewidth=0.9, zorder=2)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(AXIS_COLOR)
        ax.spines[spine].set_linewidth(1.0)

    ax.set_xlim(years[0] - 0.5, years[-1] + 0.5)
    ax.xaxis.set_major_locator(mticker.MultipleLocator(2))
    ax.tick_params(axis="both", colors=AXIS_COLOR, labelsize=10, length=4)
    for tick in ax.get_xticklabels():
        tick.set_fontproperties(f_reg)
        tick.set_color(INK_SECONDARY)
        tick.set_fontsize(10)
        tick.set_rotation(45)
    for tick in ax.get_yticklabels():
        tick.set_fontproperties(f_reg)
        tick.set_color(INK_SECONDARY)
        tick.set_fontsize(10)

    fig.canvas.draw()
    axpos = ax.get_position()
    left_x, right_x, top_y = axpos.x0, axpos.x1, axpos.y1
    center_x = (axpos.x0 + axpos.x1) / 2

    handles, labels = ax.get_legend_handles_labels()
    order = ["JJA mean high (observed)", f"{data['normals_period']} average ({normal_mean:.1f}°F)",
             f"Linear trend ({slope_per_decade:+.2f}°F/decade)"]
    by_label = dict(zip(labels, handles))
    handles = [by_label[l] for l in order if l in by_label]
    leg = fig.legend(handles, [l for l in order if l in by_label],
                      loc="lower left", bbox_to_anchor=(left_x, top_y + 0.012),
                      bbox_transform=fig.transFigure, ncol=3, frameon=False,
                      prop=f_reg, fontsize=11, handlelength=1.8, columnspacing=1.8)
    for text in leg.get_texts():
        text.set_color(INK_SECONDARY)

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

        logo_width_fig = 0.06 * (axpos.x1 - axpos.x0)
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
    title = f"Tri-Cities JJA Mean High Temperature — {years[0]}-{years[-1]}"
    fig.text(left_x, title_y, title, fontproperties=f_bold, fontsize=22, color=INK)
    subtitle = (f"{data['label']} ({data['station']}) • ACIS/xmACIS Observed, full usable period of record • "
                f"vs. {data['normals_period']} average")
    fig.text(left_x, subtitle_y, subtitle, fontproperties=f_reg, fontsize=12, color=INK_SECONDARY)

    # ---------- attribution ----------
    fig.text(center_x, 0.02, "ACIS/xmACIS (observed & 1991-2020 normals) — Ingalls Weather",
              fontproperties=f_reg, fontsize=9, color=INK_SECONDARY, ha="center")

    plt.savefig(output, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
    print(f"saved {output}")


if __name__ == "__main__":
    main()

import argparse
import json
import os
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.dates as mdates
import matplotlib.patheffects as pe
import numpy as np

# ---------- fonts ----------
# Poppins comes from setup.sh (it isn't packaged for apt); fall back to
# Montserrat, same as tri-cities-7day-forecast, so a bare environment still
# renders instead of crashing.
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

# ---------- palette (same canvas/style as 850-700-temp-chart / tri-cities-temp-chart) ----------
BG = "#f7f6f2"
INK = "#2b2a26"
INK_SECONDARY = "#5a584f"
GRID_COLOR = "#000000"
AXIS_COLOR = "#000000"

# Forest green for "this year" -- the same primary-data-line hue the other
# charts use (the pine tree in the Ingalls Weather logo).
SWE_COLOR = "#164f29"
SWE_FILL_ALPHA = 0.14

# Warm amber for the climatology line, as in the other charts, over a soft
# neutral fill so the shape of a normal season reads at a glance.
CLIMO_LINE = "#c9531c"
CLIMO_FILL = "#c7c5c0"
CLIMO_FILL_ALPHA = 0.45

# z-order layering, back to front: average fill -> gridlines -> this
# year's fill -> average line -> this year's line -> labels.
Z_SHADING = 1
Z_GRID = 2
Z_SWE_FILL = 3
Z_AVG = 4
Z_SWE = 5


def parse_args():
    ap = argparse.ArgumentParser(description="Render the Pacific Northwest snowpack chart.")
    ap.add_argument("--input", default="snowpack.json")
    ap.add_argument("--output", default="pnw_snowpack_chart.png")
    return ap.parse_args()


def main():
    args = parse_args()
    data = json.load(open(args.input))

    avg_dates = [datetime.fromisoformat(r["date"]) for r in data["average"]]
    avg_vals = np.array([r["avg_swe_in"] for r in data["average"]])

    obs = data["observed"]
    obs_dates = [datetime.fromisoformat(r["date"]) for r in obs]
    obs_vals = np.array([np.nan if r["swe_in"] is None else r["swe_in"] for r in obs])

    wy = data["water_year"]
    latest = obs[-1]
    latest_date = obs_dates[-1]
    peak = data["average_peak"]
    peak_date = datetime.fromisoformat(peak["date"])

    # ---------- figure (same footprint as the other charts) ----------
    fig = plt.figure(figsize=(12, 8.3), dpi=200)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0.075, 0.10, 0.87, 0.65])
    ax.set_facecolor("white")

    avg_label = f"Average ({data['normals_period']})"
    obs_label = f"WY{wy} (Oct 1 – {latest_date.strftime('%b %-d')})"

    ax.fill_between(avg_dates, 0, avg_vals, color=CLIMO_FILL, alpha=CLIMO_FILL_ALPHA,
                     linewidth=0, zorder=Z_SHADING)
    ax.plot(avg_dates, avg_vals, color=CLIMO_LINE, linewidth=2.2, linestyle="--",
            dashes=(6, 3), zorder=Z_AVG, label=avg_label)

    ax.fill_between(obs_dates, 0, obs_vals, color=SWE_COLOR, alpha=SWE_FILL_ALPHA,
                     linewidth=0, zorder=Z_SWE_FILL)
    ax.plot(obs_dates, obs_vals, color=SWE_COLOR, linewidth=2.8, zorder=Z_SWE,
            solid_capstyle="round", label=obs_label)
    ax.plot([latest_date], [obs_vals[-1]], marker="o", markersize=7, color=SWE_COLOR,
            markeredgecolor="white", markeredgewidth=1.4, zorder=Z_SWE + 1)

    # dotted vertical marker at the latest day, like the observed/forecast
    # divider in tri-cities-temp-chart
    ax.axvline(latest_date, color=AXIS_COLOR, linewidth=1.0, linestyle=":", zorder=Z_GRID)

    # ---------- y-axis: 0 .. a bit above the taller of the two curves ----------
    ymax = float(np.nanmax(np.concatenate([avg_vals, obs_vals])))
    ax.set_ylim(0, ymax * 1.14)

    # ---------- labels ----------
    label_stroke = [pe.withStroke(linewidth=3, foreground="white")]

    # latest value + percent of average, offset up-and-right of the point
    # (flipped to the left once the season is far enough along that the
    # label would run off the right edge)
    pct = latest.get("pct_of_avg")
    latest_text = f"{obs_vals[-1]:.1f}\" SWE"
    if pct is not None:
        latest_text += f"\n{pct:.0f}% of average"
    season_frac = (latest_date - avg_dates[0]) / (avg_dates[-1] - avg_dates[0])
    on_right = season_frac < 0.8
    # sit the label well above the point (clear of the rising average curve)
    # while there's room; once the line is in the top half of the plot,
    # hang it below instead so it can't collide with the legend strip.
    above = obs_vals[-1] < 0.5 * ymax
    txt = ax.annotate(latest_text, xy=(latest_date, obs_vals[-1]),
                       xytext=(10 if on_right else -10, 100 if above else -60), textcoords="offset points",
                       ha="left" if on_right else "right", va="bottom" if above else "top",
                       fontproperties=f_med, fontsize=11.5, color=SWE_COLOR,
                       linespacing=1.25, zorder=Z_SWE + 2,
                       arrowprops=dict(arrowstyle="-", color=SWE_COLOR, lw=0.9, shrinkA=2, shrinkB=5))
    txt.set_path_effects(label_stroke)

    # average-peak callout
    ax.plot([peak_date], [peak["avg_swe_in"]], marker="o", markersize=5.5, color=CLIMO_LINE,
            markeredgecolor="white", markeredgewidth=1.2, zorder=Z_AVG + 0.5)
    ptxt = ax.annotate(f"Avg peak {peak['avg_swe_in']:.1f}\" ({peak_date.strftime('%b %-d')})",
                        xy=(peak_date, peak["avg_swe_in"]), xytext=(0, 10), textcoords="offset points",
                        ha="center", va="bottom", fontproperties=f_med, fontsize=10,
                        color=CLIMO_LINE, zorder=Z_AVG + 0.5)
    ptxt.set_path_effects(label_stroke)

    # ---------- axes styling ----------
    ax.set_ylabel("Snow Water Equivalent (in)", fontproperties=f_med, fontsize=12, color=INK)
    ax.set_axisbelow(False)
    ax.grid(axis="y", color=GRID_COLOR, alpha=0.25, linewidth=0.9, zorder=Z_GRID)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(AXIS_COLOR)
        ax.spines[spine].set_linewidth(1.0)

    # full water year on the x-axis, Oct 1 .. Sep 30, month ticks
    ax.set_xlim(avg_dates[0], avg_dates[-1])
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %-d"))
    ax.tick_params(axis="both", colors=AXIS_COLOR, labelsize=10, length=4)
    for tick in ax.get_xticklabels():
        tick.set_fontproperties(f_reg)
        tick.set_color(INK_SECONDARY)
        tick.set_fontsize(10)
        tick.set_rotation(0)
    for tick in ax.get_yticklabels():
        tick.set_fontproperties(f_reg)
        tick.set_color(INK_SECONDARY)
        tick.set_fontsize(10)

    fig.canvas.draw()
    axpos = ax.get_position()
    left_x, top_y = axpos.x0, axpos.y1
    center_x = (axpos.x0 + axpos.x1) / 2

    # ---------- legend (horizontal strip above the plot, out of the data's way) ----------
    handles, labels = ax.get_legend_handles_labels()
    order = [obs_label, avg_label]
    by_label = dict(zip(labels, handles))
    leg = fig.legend([by_label[l] for l in order], order,
                      loc="lower left", bbox_to_anchor=(left_x, top_y + 0.012),
                      bbox_transform=fig.transFigure, ncol=len(order), frameon=False,
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
    title = f"{data['label']} Snowpack — Water Year {wy}"
    fig.text(left_x, title_y, title, fontproperties=f_bold, fontsize=22, color=INK)
    subtitle = (f"NRCS SNOTEL regional mean SWE • {data['n_stations']} stations in "
                f"{', '.join(data['states'])} • through {latest_date.strftime('%b %-d, %Y')}")
    fig.text(left_x, subtitle_y, subtitle, fontproperties=f_reg, fontsize=12, color=INK_SECONDARY)

    # ---------- attribution ----------
    fig.text(center_x, 0.02,
              "USDA NRCS SNOTEL / Air and Water Database (observed & 1991–2020 average) — Ingalls Weather",
              fontproperties=f_reg, fontsize=9, color=INK_SECONDARY, ha="center")

    plt.savefig(args.output, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
    print(f"saved {args.output}")


if __name__ == "__main__":
    main()

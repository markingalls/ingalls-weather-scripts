import argparse
import json
import os
from datetime import datetime

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
GRID_COLOR = "#e1e0d9"
AXIS_COLOR = "#c3c2b7"

ENSEMBLE_OUTER = "#cde2fb"   # p01-p99
ENSEMBLE_WIDE = "#9ec5f4"    # p10-p90
ENSEMBLE_MID = "#5598e7"     # p25-p75
ENSEMBLE_MEAN = "#184f95"

CLIMO_LINE = "#c9531c"
CLIMO_BAND = "#f6c19f"

DAYS_IN_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def build_climo_series(monthly, times):
    """Interpolates the 12 monthly climatology values (assigned to the 15th
    of each month) to a smooth day-of-year curve, evaluated at each forecast
    valid time. Wraps around the year boundary."""
    anchor_doy, cum = [], 0
    for days in DAYS_IN_MONTH:
        anchor_doy.append(cum + 15)
        cum += days
    means = [row["mean"] for row in monthly]
    stds = [row["std"] for row in monthly]

    ext_doy = [anchor_doy[-1] - 365.25] + anchor_doy + [anchor_doy[0] + 365.25]
    ext_mean = [means[-1]] + means + [means[0]]
    ext_std = [stds[-1]] + stds + [stds[0]]

    out_mean, out_std = [], []
    for t in times:
        doy = t.timetuple().tm_yday + t.hour / 24 + t.minute / 1440
        idx = int(np.searchsorted(ext_doy, doy)) - 1
        idx = max(0, min(idx, len(ext_doy) - 2))
        d0, d1 = ext_doy[idx], ext_doy[idx + 1]
        frac = (doy - d0) / (d1 - d0)
        out_mean.append(ext_mean[idx] + frac * (ext_mean[idx + 1] - ext_mean[idx]))
        out_std.append(ext_std[idx] + frac * (ext_std[idx + 1] - ext_std[idx]))
    return np.array(out_mean), np.array(out_std)


def parse_args():
    ap = argparse.ArgumentParser(description="Render the WM-6 ensemble spread vs. climatology chart.")
    ap.add_argument("--forecast", default="forecast.json")
    ap.add_argument("--climatology", default="climatology.json")
    ap.add_argument("--output", default="wm6_ensemble_spread.png")
    return ap.parse_args()


def main():
    args = parse_args()
    fdata = json.load(open(args.forecast))
    cdata = json.load(open(args.climatology))

    points = fdata["forecasts"][0]
    times = [datetime.fromisoformat(p["time"].replace("Z", "+00:00")) for p in points]
    dist = lambda key: np.array([p["distribution"][key] for p in points])
    mean, p01, p10, p25, p75, p90, p99 = (
        dist("mean"), dist("p01"), dist("p10"), dist("p25"), dist("p75"), dist("p90"), dist("p99"))

    climo_mean, climo_std = build_climo_series(cdata["monthly"], times)
    climo_lo, climo_hi = climo_mean - climo_std, climo_mean + climo_std

    level = fdata.get("level", cdata.get("level", 850))
    station = fdata.get("station", "")
    label = fdata.get("label")
    title_loc = f"{station} ({label})" if label else station

    init_time = datetime.fromisoformat(fdata["initialization_time"].replace("Z", "+00:00"))
    max_hour = round((times[-1] - datetime.fromisoformat(fdata["forecast_zero"].replace("Z", "+00:00")))
                      .total_seconds() / 3600)

    # ---------- figure (same footprint as the alerts map) ----------
    fig = plt.figure(figsize=(12, 8.3), dpi=200)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0.075, 0.10, 0.87, 0.65])
    ax.set_facecolor("white")

    ax.fill_between(times, climo_lo, climo_hi, color=CLIMO_BAND, alpha=0.5, linewidth=0, zorder=2)
    ax.plot(times, climo_mean, color=CLIMO_LINE, linewidth=2.0, linestyle="--",
             dashes=(6, 3), zorder=3, label=f"Climatological normal ({cdata['period']})")

    ax.fill_between(times, p01, p99, color=ENSEMBLE_OUTER, alpha=0.55, linewidth=0, zorder=4)
    ax.fill_between(times, p10, p90, color=ENSEMBLE_WIDE, alpha=0.75, linewidth=0,
                     zorder=5, label="10–90th percentile")
    ax.fill_between(times, p25, p75, color=ENSEMBLE_MID, alpha=0.85, linewidth=0,
                     zorder=6, label="25–75th percentile")
    ax.plot(times, mean, color=ENSEMBLE_MEAN, linewidth=2.6, zorder=7, label="Ensemble mean")

    ax.axvline(init_time, color=AXIS_COLOR, linewidth=1.0, linestyle=":", zorder=1)

    # ---------- axes styling ----------
    ax.set_ylabel(f"{level} mb Temperature (°C)", fontproperties=f_med, fontsize=12, color=INK)
    ax.grid(axis="y", color=GRID_COLOR, linewidth=0.9, zorder=0)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(AXIS_COLOR)
        ax.spines[spine].set_linewidth(1.0)

    ax.xaxis.set_major_locator(mdates.DayLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %-d"))
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
    order = ["Ensemble mean", "25–75th percentile", "10–90th percentile",
             f"Climatological normal ({cdata['period']})"]
    by_label = dict(zip(labels, handles))
    handles = [by_label[l] for l in order if l in by_label]
    leg = fig.legend(handles, [l for l in order if l in by_label],
                      loc="lower left", bbox_to_anchor=(left_x, top_y + 0.012),
                      bbox_transform=fig.transFigure, ncol=4, frameon=False,
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
    title = f"WM-6 Ensemble: {level} mb Temperature — {title_loc}"
    fig.text(left_x, title_y, title, fontproperties=f_bold, fontsize=22, color=INK)
    subtitle = (f"Ensemble spread vs. climatology — run {init_time.strftime('%b %-d, %Y %H'):s}Z, "
                f"3-hourly out to +{max_hour}h")
    fig.text(left_x, subtitle_y, subtitle, fontproperties=f_reg, fontsize=12, color=INK_SECONDARY)

    # ---------- attribution ----------
    fig.text(center_x, 0.02,
              "WindBorne WeatherMesh-6 (ensemble) / NOAA NCEP–NCAR Reanalysis (climatology) — Ingalls Weather",
              fontproperties=f_reg, fontsize=9, color=INK_SECONDARY, ha="center")

    plt.savefig(args.output, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
    print(f"saved {args.output}")


if __name__ == "__main__":
    main()

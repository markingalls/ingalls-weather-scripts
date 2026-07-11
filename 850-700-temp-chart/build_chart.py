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
GRID_COLOR = "#000000"
AXIS_COLOR = "#000000"

# Forest green, in the spirit of the pine tree in the Ingalls Weather logo
# (the logo's own pine color is a dark navy-teal that reads as blue once
# lightened -- this is shifted a bit further into true green so tinting/
# tapering it still reads as green rather than drifting blue).
ENSEMBLE_BASE = "#164f29"
ENSEMBLE_MEAN = ENSEMBLE_BASE
ENSEMBLE_OUTER_ALPHA = 0.14   # p01-p99
ENSEMBLE_WIDE_ALPHA = 0.28    # p10-p90
ENSEMBLE_MID_ALPHA = 0.46     # p25-p75

CLIMO_LINE = "#c9531c"

# z-order layering, back to front: ensemble shading -> gridlines ->
# climatology line -> ensemble mean line.
Z_SHADING = 1
Z_GRID = 2
Z_CLIMO = 3
Z_MEAN = 4

# Harmonic terms used to smooth the raw 6-hourly climatology: annual +
# semiannual capture the seasonal trend, diurnal + semidiurnal capture the
# daily heating/cooling bumps riding on top of it. Fitting all of them at
# once on the full-precision series is what lets the smoothed curve keep
# the modest daily bumps instead of flattening them out along with the noise.
SEASONAL_HARMONICS = 2
DIURNAL_HARMONICS = 2


def fit_climatology_harmonics(cdata):
    """Fits smooth seasonal+diurnal harmonics through the raw 6-hourly
    long-term-mean climatology series (full precision in, smoothed function
    out). Returns coeffs for eval_climatology_harmonics()."""
    t = np.array(cdata["t_days"], dtype=float)
    y = np.array(cdata["mean_c"], dtype=float)
    w_season = 2 * np.pi / 365.25
    w_day = 2 * np.pi / 1.0

    cols = [np.ones_like(t)]
    for k in range(1, SEASONAL_HARMONICS + 1):
        cols += [np.cos(k * w_season * t), np.sin(k * w_season * t)]
    for k in range(1, DIURNAL_HARMONICS + 1):
        cols += [np.cos(k * w_day * t), np.sin(k * w_day * t)]
    design = np.column_stack(cols)

    coeffs, *_ = np.linalg.lstsq(design, y, rcond=None)
    return coeffs


def eval_climatology_harmonics(coeffs, times):
    t = np.array([(dt.timetuple().tm_yday - 1) + dt.hour / 24 + dt.minute / 1440 for dt in times])
    w_season = 2 * np.pi / 365.25
    w_day = 2 * np.pi / 1.0

    out = np.full_like(t, coeffs[0])
    i = 1
    for k in range(1, SEASONAL_HARMONICS + 1):
        out = out + coeffs[i] * np.cos(k * w_season * t) + coeffs[i + 1] * np.sin(k * w_season * t)
        i += 2
    for k in range(1, DIURNAL_HARMONICS + 1):
        out = out + coeffs[i] * np.cos(k * w_day * t) + coeffs[i + 1] * np.sin(k * w_day * t)
        i += 2
    return out


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

    harmonic_coeffs = fit_climatology_harmonics(cdata)
    climo_mean = eval_climatology_harmonics(harmonic_coeffs, times)

    level = fdata.get("level", cdata.get("level", 850))
    title_loc = fdata.get("label") or fdata.get("station", "")

    init_time = datetime.fromisoformat(fdata["initialization_time"].replace("Z", "+00:00"))
    lat, lon = fdata.get("lat"), fdata.get("lon")
    ns, ew = ("N" if lat >= 0 else "S"), ("E" if lon >= 0 else "W")

    # ---------- figure (same footprint as the alerts map) ----------
    fig = plt.figure(figsize=(12, 8.3), dpi=200)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0.075, 0.10, 0.87, 0.65])
    ax.set_facecolor("white")

    # ensemble shading sits behind gridlines and the climatology line
    ax.fill_between(times, p01, p99, color=ENSEMBLE_BASE, alpha=ENSEMBLE_OUTER_ALPHA,
                     linewidth=0, zorder=Z_SHADING)
    ax.fill_between(times, p10, p90, color=ENSEMBLE_BASE, alpha=ENSEMBLE_WIDE_ALPHA,
                     linewidth=0, zorder=Z_SHADING, label="10–90th percentile")
    ax.fill_between(times, p25, p75, color=ENSEMBLE_BASE, alpha=ENSEMBLE_MID_ALPHA,
                     linewidth=0, zorder=Z_SHADING, label="25–75th percentile")

    ax.axvline(init_time, color=AXIS_COLOR, linewidth=1.0, linestyle=":", zorder=Z_GRID)

    ax.plot(times, climo_mean, color=CLIMO_LINE, linewidth=2.0, linestyle="--",
             dashes=(6, 3), zorder=Z_CLIMO, label=f"Climo ({cdata['period']})")

    ax.plot(times, mean, color=ENSEMBLE_MEAN, linewidth=2.6, zorder=Z_MEAN, label="Ensemble mean")

    # ---------- y-axis: fixed to the ensemble's own p10-5 / p90+5 window,
    # so the display doesn't rescale to chase p01/p99 outliers ----------
    ax.set_ylim(float(np.min(p10)) - 5, float(np.max(p90)) + 5)

    # ---------- axes styling ----------
    ax.set_ylabel(f"{level} mb Temperature (°C)", fontproperties=f_med, fontsize=12, color=INK)
    ax.set_axisbelow(False)
    ax.grid(axis="y", color=GRID_COLOR, alpha=0.25, linewidth=0.9, zorder=Z_GRID)
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
             f"Climo ({cdata['period']})"]
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
    title = f"{level} mb Temperature at {title_loc}"
    fig.text(left_x, title_y, title, fontproperties=f_bold, fontsize=22, color=INK)
    subtitle = (f"WeatherMesh-6 Init {init_time.strftime('%Y-%m-%d')} {init_time.strftime('%H')}z"
                f" • {ns}{abs(lat):.2f}°, {ew}{abs(lon):.2f}°")
    fig.text(left_x, subtitle_y, subtitle, fontproperties=f_reg, fontsize=12, color=INK_SECONDARY)

    # ---------- attribution ----------
    fig.text(center_x, 0.02,
              "WindBorne WeatherMesh-6 (ensemble) / NOAA NCEP–NCAR Reanalysis (climatology) — Ingalls Weather",
              fontproperties=f_reg, fontsize=9, color=INK_SECONDARY, ha="center")

    plt.savefig(args.output, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
    print(f"saved {args.output}")


if __name__ == "__main__":
    main()

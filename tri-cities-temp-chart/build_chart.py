import argparse
import json
import os
from datetime import datetime, timedelta

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

# ---------- palette (same canvas/style as 850-700-temp-chart) ----------
BG = "#f7f6f2"
INK = "#2b2a26"
INK_SECONDARY = "#5a584f"
GRID_COLOR = "#000000"
AXIS_COLOR = "#000000"

# Forest green for the "actual temperature" series (observed + forecast),
# in the spirit of the pine tree in the Ingalls Weather logo -- same hue
# 850-700-temp-chart uses for its primary data line.
TEMP_COLOR = "#164f29"

# Warm amber for the normal line -- same hue 850-700-temp-chart uses for
# its climatology line. The three percentile bands get their own distinct
# colors instead (cool-to-warm: below-normal tercile light blue, the
# middle tercile neutral gray, above-normal tercile light red), so each
# band reads as its own thing rather than as a single gradient.
CLIMO_LINE = "#c9531c"
BAND_P10_P25 = "#a9c6e8"
BAND_P25_P75 = "#c7c5c0"
BAND_P75_P90 = "#e8a3a3"
BAND_ALPHA = 0.55

RECORD_COLOR = "#a3242b"

# z-order layering, back to front: climatology shading -> gridlines ->
# normal line -> record points -> observed/forecast lines.
Z_SHADING = 1
Z_GRID = 2
Z_NORMAL = 3
Z_RECORD = 4
Z_TEMP = 5


def parse_args():
    ap = argparse.ArgumentParser(description="Render the Tri-Cities high-temperature chart.")
    ap.add_argument("--observed", default="observed.json")
    ap.add_argument("--forecast", default="forecast.json")
    ap.add_argument("--climatology", default="climatology.json")
    ap.add_argument("--output", default="tri_cities_temp_chart.png")
    return ap.parse_args()


def day_key(date_str):
    """'2026-07-27' -> '07-27', to look up a climatology.json calendar day."""
    return date_str[5:]


def climo_lookup(cdata, date_str, field):
    entry = cdata["days"].get(day_key(date_str))
    if entry is None:
        return np.nan
    return entry.get(field, np.nan)


def main():
    args = parse_args()
    odata = json.load(open(args.observed))
    fdata = json.load(open(args.forecast))
    cdata = json.load(open(args.climatology))

    obs_dates = [datetime.fromisoformat(d["date"]) for d in odata["days"]]
    obs_vals = np.array([np.nan if d["maxt_f"] is None else d["maxt_f"] for d in odata["days"]])

    fc_dates = [datetime.fromisoformat(d["date"]) for d in fdata["days"]]
    fc_vals = np.array([d["maxt_f"] for d in fdata["days"]])

    all_dates = obs_dates + fc_dates
    p10 = np.array([climo_lookup(cdata, d.strftime("%Y-%m-%d"), "p10") for d in all_dates])
    p25 = np.array([climo_lookup(cdata, d.strftime("%Y-%m-%d"), "p25") for d in all_dates])
    p75 = np.array([climo_lookup(cdata, d.strftime("%Y-%m-%d"), "p75") for d in all_dates])
    p90 = np.array([climo_lookup(cdata, d.strftime("%Y-%m-%d"), "p90") for d in all_dates])
    normal = np.array([climo_lookup(cdata, d.strftime("%Y-%m-%d"), "p50") for d in all_dates])
    record = np.array([climo_lookup(cdata, d.strftime("%Y-%m-%d"), "record_f") for d in all_dates])

    today_boundary = fc_dates[0] if fc_dates else obs_dates[-1] + timedelta(days=1)

    title_loc = fdata.get("label") or odata.get("label") or fdata.get("station", "")
    init_time = datetime.fromisoformat(fdata["initialization_time"].replace("Z", "+00:00"))
    lat, lon = fdata.get("lat"), fdata.get("lon")

    # ---------- figure (same footprint as 850-700-temp-chart / the alerts map) ----------
    fig = plt.figure(figsize=(12, 8.3), dpi=200)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0.075, 0.10, 0.87, 0.65])
    ax.set_facecolor("white")

    # climatology shading sits behind gridlines and the normal line -- three
    # adjacent bands (not two nested/overlapping ones), each its own color.
    ax.fill_between(all_dates, p10, p25, color=BAND_P10_P25, alpha=BAND_ALPHA,
                     linewidth=0, zorder=Z_SHADING, label="10th–25th percentile")
    ax.fill_between(all_dates, p25, p75, color=BAND_P25_P75, alpha=BAND_ALPHA,
                     linewidth=0, zorder=Z_SHADING, label="25th–75th percentile")
    ax.fill_between(all_dates, p75, p90, color=BAND_P75_P90, alpha=BAND_ALPHA,
                     linewidth=0, zorder=Z_SHADING, label="75th–90th percentile")

    ax.axvline(today_boundary, color=AXIS_COLOR, linewidth=1.0, linestyle=":", zorder=Z_GRID)

    ax.plot(all_dates, normal, color=CLIMO_LINE, linewidth=2.0, linestyle="--",
            dashes=(6, 3), zorder=Z_NORMAL, label=f"Daily normal (P50, {cdata['percentile_years']})")

    ax.scatter(all_dates, record, color=RECORD_COLOR, marker="*", s=110,
               zorder=Z_RECORD, label="Record high", edgecolors="white", linewidths=0.6)

    ax.plot(obs_dates, obs_vals, color=TEMP_COLOR, linewidth=2.6, marker="o", markersize=5.5,
            zorder=Z_TEMP, label="Observed high (xmACIS)")
    ax.plot(fc_dates, fc_vals, color=TEMP_COLOR, linewidth=2.6, linestyle="--", dashes=(5, 2.5),
            marker="o", markersize=5.5, markerfacecolor="white", markeredgewidth=1.6,
            zorder=Z_TEMP, label="Forecast high (WM-6)")

    # value labels on every observed/forecast point -- a white halo keeps
    # them legible over both the white axes background and the percentile
    # shading.
    label_stroke = [pe.withStroke(linewidth=2.5, foreground="white")]
    for d, v in zip(obs_dates + fc_dates, np.concatenate([obs_vals, fc_vals])):
        if np.isnan(v):
            continue
        txt = ax.annotate(f"{v:.0f}°", xy=(d, v), xytext=(0, 9), textcoords="offset points",
                           ha="center", va="bottom", fontproperties=f_med, fontsize=9.5,
                           color=TEMP_COLOR, zorder=Z_TEMP + 1)
        txt.set_path_effects(label_stroke)

    # ---------- y-axis: fixed to the plotted series' own range, so a couple
    # of record-high spikes don't stretch the axis too far ----------
    lows = np.concatenate([p10, obs_vals, fc_vals])
    highs = np.concatenate([p90, obs_vals, fc_vals, record])
    ax.set_ylim(float(np.nanmin(lows)) - 5, float(np.nanmax(highs)) + 3)

    # ---------- axes styling ----------
    ax.set_ylabel("High Temperature (°F)", fontproperties=f_med, fontsize=12, color=INK)
    ax.set_axisbelow(False)
    ax.grid(axis="y", color=GRID_COLOR, alpha=0.25, linewidth=0.9, zorder=Z_GRID)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(AXIS_COLOR)
        ax.spines[spine].set_linewidth(1.0)

    ax.xaxis.set_major_locator(mdates.DayLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %-d"))
    ax.set_xlim(all_dates[0], all_dates[-1])
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
    left_x, right_x, top_y = axpos.x0, axpos.x1, axpos.y1
    center_x = (axpos.x0 + axpos.x1) / 2

    # ---------- legend (horizontal strip above the plot, out of the data's way) ----------
    handles, labels = ax.get_legend_handles_labels()
    order = ["Observed high (xmACIS)", "Forecast high (WM-6)",
             f"Daily normal (P50, {cdata['percentile_years']})", "Record high",
             "10th–25th percentile", "25th–75th percentile", "75th–90th percentile"]
    by_label = dict(zip(labels, handles))
    handles = [by_label[l] for l in order if l in by_label]
    leg = fig.legend(handles, [l for l in order if l in by_label],
                      loc="lower left", bbox_to_anchor=(left_x, top_y + 0.012),
                      bbox_transform=fig.transFigure, ncol=4, frameon=False,
                      prop=f_reg, fontsize=10.5, handlelength=1.6, columnspacing=1.6,
                      labelspacing=0.6)
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
    # More vertical clearance than a single-row legend needs (850-700-temp-chart
    # uses top_y + 0.058) since this chart's 7-item legend wraps to two rows.
    subtitle_y = top_y + 0.104
    title_y = subtitle_y + 0.035
    title = f"Tri-Cities Daily High Temperature at {title_loc}"
    fig.text(left_x, title_y, title, fontproperties=f_bold, fontsize=22, color=INK)
    ns, ew = ("N" if lat >= 0 else "S"), ("E" if lon >= 0 else "W")
    subtitle = (f"xmACIS Observed + Climatology ({cdata['n_percentile_years']} yrs, {cdata['percentile_years']}) • "
                f"WeatherMesh-6 Forecast Init {init_time.strftime('%Y-%m-%d')} {init_time.strftime('%H')}z"
                f" • {ns}{abs(lat):.2f}°, {ew}{abs(lon):.2f}°")
    fig.text(left_x, subtitle_y, subtitle, fontproperties=f_reg, fontsize=12, color=INK_SECONDARY)

    # ---------- attribution ----------
    fig.text(center_x, 0.02,
              "ACIS/xmACIS (observed & climatology) / WindBorne WeatherMesh-6 (forecast) — Ingalls Weather",
              fontproperties=f_reg, fontsize=9, color=INK_SECONDARY, ha="center")

    plt.savefig(args.output, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
    print(f"saved {args.output}")


if __name__ == "__main__":
    main()

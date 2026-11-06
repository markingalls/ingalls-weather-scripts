import argparse
import json
import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
import numpy as np

from sites import SITES

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

SNOW_LINE = "#1d4f86"       # WM-6 snow level
SNOW_FILL = "#1d4f86"       # tint above the snow level (where precip falls as snow)
SNOW_FILL_ALPHA = 0.10
NWS_LINE = "#c9531c"        # NWS gridpoint snow level, for comparison
REF_LINE = INK              # dotted pass / town / ski-area lines

# z-order layering, back to front: snow tint -> gridlines -> reference lines
# -> NWS line -> WM-6 line -> reference labels.
Z_FILL = 1
Z_GRID = 2
Z_REF = 3
Z_NWS = 4
Z_SNOW = 5
Z_LABEL = 6

LOCAL_TZ = ZoneInfo("America/Los_Angeles")
M_TO_FT = 3.28084
G = 9.80665

# Snow level = the highest height where the air is still at least this warm.
# 1.6 C is where precip is ~50% snow by mass in the air-temperature snow
# fraction curve (Cascades-tuned); the 0 C freezing level is typically
# ~1,000 ft above it.
SNOW_LEVEL_T_C = 1.6


def snow_level_m(z_m, t_c, threshold=SNOW_LEVEL_T_C):
    """Highest height (m) where the profile is >= threshold, linearly
    interpolated between pressure levels. Scans from the top down so that a
    shallow warm layer aloft (or a cold pool in the lowest levels) still
    resolves to the top of the warm air -- the elevation above which it snows.
    Returns 0 if the whole column is colder than the threshold."""
    order = np.argsort(z_m)
    z, t = np.asarray(z_m)[order], np.asarray(t_c)[order]
    if t[-1] >= threshold:
        return float(z[-1])
    for i in range(len(z) - 2, -1, -1):
        if t[i] >= threshold:
            frac = (t[i] - threshold) / (t[i] - t[i + 1])
            return float(z[i] + frac * (z[i + 1] - z[i]))
    return 0.0


def parse_time(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def parse_duration(s):
    """ISO-8601 durations as NWS uses them, e.g. PT3H, P1D, P1DT6H."""
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?", s)
    d, h, mi = (int(x) if x else 0 for x in m.groups())
    return timedelta(days=d, hours=h, minutes=mi)


def nws_series(nws, t0, t1):
    """Step series (times, feet) from NWS validTime intervals, clipped to the
    WM-6 window."""
    if not nws:
        return None, None
    scale = M_TO_FT if nws.get("uom", "wmoUnit:m").endswith(":m") else 1.0
    times, vals = [], []
    for v in nws["values"]:
        start_s, dur_s = v["validTime"].split("/")
        start = parse_time(start_s)
        end = start + parse_duration(dur_s)
        if end <= t0 or start >= t1 or v["value"] is None:
            continue
        start, end = max(start, t0), min(end, t1)
        ft = v["value"] * scale
        times += [start, end]
        vals += [ft, ft]
    if not times:
        return None, None
    return times, np.array(vals)


def parse_args():
    ap = argparse.ArgumentParser(description="Render a 5-day snow level chart for one site.")
    ap.add_argument("--site", choices=sorted(SITES), required=True)
    ap.add_argument("--forecast", default=None, help="Defaults to forecast_<site>.json")
    ap.add_argument("--output", default=None, help="Defaults to snow_level_<site>.png")
    ap.add_argument("--days", type=float, default=5)
    ap.add_argument("--no-nws", action="store_true", help="Leave the NWS comparison line off")
    return ap.parse_args()


def main():
    args = parse_args()
    site = SITES[args.site]
    fdata = json.load(open(args.forecast or f"forecast_{args.site}.json"))
    output = args.output or f"snow_level_{args.site}.png"

    # ---------- WM-6 profile -> snow level ----------
    levels = sorted(fdata["levels"], key=int)
    times = [parse_time(p["time"]) for p in fdata["levels"][levels[0]]]
    t0 = times[0]
    t1 = t0 + timedelta(days=args.days)
    keep = [i for i, t in enumerate(times) if t <= t1]
    times = [times[i] for i in keep]

    snow_ft = []
    for i in keep:
        z = [fdata["levels"][L][i]["geopotential"] / G for L in levels]
        t = [fdata["levels"][L][i]["temperature"] for L in levels]
        snow_ft.append(snow_level_m(z, t) * M_TO_FT)
    snow_ft = np.array(snow_ft)

    nws_t, nws_ft = (None, None) if args.no_nws else nws_series(fdata.get("nws"), t0, times[-1])

    init_time = parse_time(fdata["initialization_time"])
    lat, lon = fdata["lat"], fdata["lon"]
    ns, ew = ("N" if lat >= 0 else "S"), ("E" if lon >= 0 else "W")

    # ---------- figure (same footprint as the alerts map) ----------
    fig = plt.figure(figsize=(12, 8.3), dpi=200)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0.075, 0.10, 0.87, 0.65])
    ax.set_facecolor("white")

    # ---------- y-axis: 0 up to the highest of data / reference lines,
    # rounded up to the next 1,000 ft with a little headroom ----------
    ref_max = max((r["elev_ft"] for r in site["refs"]), default=0)
    data_max = max(float(np.max(snow_ft)), float(np.max(nws_ft)) if nws_ft is not None else 0)
    y_top = np.ceil((max(ref_max, data_max) + 800) / 1000) * 1000
    ax.set_ylim(0, y_top)

    # tint everything above the snow level -- "it snows up here"
    ax.fill_between(times, snow_ft, y_top, color=SNOW_FILL, alpha=SNOW_FILL_ALPHA,
                    linewidth=0, zorder=Z_FILL, label="Snow")

    # ---------- reference lines (dotted) with labels sitting on them ----------
    for ref in site["refs"]:
        ax.axhline(ref["elev_ft"], color=REF_LINE, linewidth=1.3, linestyle=(0, (1, 2.2)),
                   zorder=Z_REF)
        # nudged a few points above the line so the label's backing box
        # doesn't hide the dotted line itself
        ax.annotate(f"{ref['label']} ({ref['elev_ft']:,} ft)",
                    xy=(0.008, ref["elev_ft"]), xycoords=ax.get_yaxis_transform(),
                    xytext=(0, 3.5), textcoords="offset points", ha="left", va="bottom",
                    fontproperties=f_med, fontsize=10, color=INK, zorder=Z_LABEL,
                    bbox=dict(boxstyle="square,pad=0.1", facecolor="white", edgecolor="none", alpha=0.8))

    if nws_t is not None:
        ax.plot(nws_t, nws_ft, color=NWS_LINE, linewidth=2.0, linestyle="--", dashes=(6, 3),
                zorder=Z_NWS, label=f"NWS {fdata['nws']['office']} forecast")

    ax.plot(times, snow_ft, color=SNOW_LINE, linewidth=2.8, zorder=Z_SNOW,
            label="WeatherMesh-6 snow level")

    # ---------- axes styling ----------
    ax.set_ylabel("Snow Level (ft)", fontproperties=f_med, fontsize=12, color=INK)
    ax.yaxis.set_major_locator(mticker.MultipleLocator(1000))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v):,}"))
    ax.set_axisbelow(False)
    ax.grid(axis="y", color=GRID_COLOR, alpha=0.18, linewidth=0.9, zorder=Z_GRID)
    ax.grid(axis="x", color=GRID_COLOR, alpha=0.10, linewidth=0.9, zorder=Z_GRID)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(AXIS_COLOR)
        ax.spines[spine].set_linewidth(1.0)

    # local-time x-axis: a labelled tick at each local midnight, minor ticks
    # every 6 hours
    ax.xaxis.set_major_locator(mdates.DayLocator(tz=LOCAL_TZ))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%a %b %-d", tz=LOCAL_TZ))
    ax.xaxis.set_minor_locator(mdates.HourLocator(byhour=[6, 12, 18], tz=LOCAL_TZ))
    ax.set_xlim(times[0], times[-1])
    ax.tick_params(axis="both", colors=AXIS_COLOR, labelsize=10, length=4)
    ax.tick_params(axis="x", which="minor", length=2.5)
    for tick in ax.get_xticklabels() + ax.get_yticklabels():
        tick.set_fontproperties(f_reg)
        tick.set_color(INK_SECONDARY)
        tick.set_fontsize(10)

    fig.canvas.draw()
    axpos = ax.get_position()
    left_x, top_y = axpos.x0, axpos.y1
    center_x = (axpos.x0 + axpos.x1) / 2

    # ---------- legend (horizontal strip above the plot) ----------
    handles, labels = ax.get_legend_handles_labels()
    order = ["WeatherMesh-6 snow level"] + [l for l in labels if l.startswith("NWS")] + ["Snow"]
    by_label = dict(zip(labels, handles))
    leg = fig.legend([by_label[l] for l in order if l in by_label],
                     [("Snow above this level" if l == "Snow" else l) for l in order if l in by_label],
                     loc="lower left", bbox_to_anchor=(left_x, top_y + 0.012),
                     bbox_transform=fig.transFigure, ncol=3, frameon=False,
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
    fig.text(left_x, title_y, f"{site['title']} Snow Level — Next {args.days:g} Days",
             fontproperties=f_bold, fontsize=22, color=INK)
    subtitle = (f"WeatherMesh-6 Init {init_time.strftime('%Y-%m-%d')} {init_time.strftime('%H')}z"
                f" • {ns}{abs(lat):.2f}°, {ew}{abs(lon):.2f}° • Pacific time")
    fig.text(left_x, subtitle_y, subtitle, fontproperties=f_reg, fontsize=12, color=INK_SECONDARY)

    # ---------- attribution ----------
    source = "WindBorne WeatherMesh-6"
    if nws_t is not None:
        source += f" / NWS {fdata['nws']['office']} gridpoint forecast"
    fig.text(center_x, 0.02, f"{source} — Ingalls Weather",
             fontproperties=f_reg, fontsize=9, color=INK_SECONDARY, ha="center")

    plt.savefig(output, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
    print(f"saved {output}")
    print("  snow level range: {:,.0f}-{:,.0f} ft".format(snow_ft.min(), snow_ft.max()))


if __name__ == "__main__":
    main()

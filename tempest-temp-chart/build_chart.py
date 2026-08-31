import argparse
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.dates as mdates
import matplotlib.patheffects as pe

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

# Forest green, same hue the other temp charts (850-700-temp-chart,
# tri-cities-temp-chart) use for their primary observed-temperature line.
TEMP_COLOR = "#164f29"

# Deep blue for the daily-low callout, distinct from the temperature line
# itself so the circled point reads as an annotation, not just more data.
LOW_COLOR = "#0b3d91"

Z_GRID = 2
Z_TEMP = 4
Z_LOW = 5


def parse_args():
    ap = argparse.ArgumentParser(description="Render today's Tempest station temperature chart.")
    ap.add_argument("--data", default="tempest_obs.json")
    ap.add_argument("--forecast", default="forecast.json",
                     help="Optional forecast.json from fetch_forecast.py -- if present and for "
                          "the same date, its forecast high extends the y-axis past the observed "
                          "high for the part of the day not observed yet")
    ap.add_argument("--output", default="tempest_temp_chart.png")
    ap.add_argument("--mark-low", action="store_true",
                     help="Circle and label the day's lowest observation")
    return ap.parse_args()


def main():
    args = parse_args()
    data = json.load(open(args.data))
    tz = ZoneInfo(data["timezone"])

    times = [datetime.fromisoformat(o["time"]) for o in data["observations"]]
    temps = [o["air_temp_f"] for o in data["observations"]]

    day_start = datetime.fromisoformat(data["date"]).replace(tzinfo=tz)
    day_end = day_start + timedelta(days=1)

    forecast_high = None
    if os.path.exists(args.forecast):
        fdata = json.load(open(args.forecast))
        if fdata.get("date") == data["date"]:
            forecast_high = fdata.get("forecast_high_f")
        else:
            print(f"NOTE: {args.forecast} is for {fdata.get('date')}, not {data['date']} "
                  f"-- ignoring it for axis scaling.")
    else:
        print(f"NOTE: no forecast file at {args.forecast} -- axis scaled to observed data only. "
              f"Run fetch_forecast.py to also cover today's forecast high.")

    # ---------- figure (same footprint as the other temp charts) ----------
    fig = plt.figure(figsize=(12, 8.3), dpi=200)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0.075, 0.10, 0.87, 0.65])
    ax.set_facecolor("white")

    if times:
        ax.plot(times, temps, color=TEMP_COLOR, linewidth=2.6, zorder=Z_TEMP, label="Air temperature")

        # The line legitimately stops partway through the day on a same-day
        # chart -- a dotted marker at the last observation makes that read
        # as current, not as missing data.
        ax.axvline(times[-1], color=AXIS_COLOR, linewidth=1.0, linestyle=":", zorder=Z_GRID)

        if args.mark_low:
            low_idx = min(range(len(temps)), key=lambda i: temps[i])
            low_time, low_temp = times[low_idx], temps[low_idx]
            ax.scatter([low_time], [low_temp], s=160, facecolors="none", edgecolors=LOW_COLOR,
                       linewidths=2.2, zorder=Z_LOW)
            label_stroke = [pe.withStroke(linewidth=2.5, foreground="white")]
            # A small offset -- the y-axis's bottom padding is a flat 3°F
            # regardless of how far a forecast high (see below) stretches
            # the top, so a large stretch leaves little room below the low
            # for the label; va="center" keeps its footprint within that.
            txt = ax.annotate(f"Low: {low_temp:.1f}°F at {low_time.strftime('%H:%M')}",
                               xy=(low_time, low_temp), xytext=(10, -8), textcoords="offset points",
                               ha="left", va="center", fontproperties=f_bold, fontsize=12,
                               color=LOW_COLOR, zorder=Z_LOW)
            txt.set_path_effects(label_stroke)

        # Day's high is the observed max so far, extended to the forecast
        # high (if fetch_forecast.py's forecast.json is present) so the
        # axis has headroom for the afternoon high before it's actually
        # been observed -- once it has, the observed max takes over since
        # it'll be the larger of the two. Fixed 3°F padding both directions
        # rather than a proportional one, so the line never crowds the axis
        # edges.
        day_low, day_high = min(temps), max(temps)
        if forecast_high is not None:
            day_high = max(day_high, forecast_high)
        ax.set_ylim(day_low - 3, day_high + 3)
    else:
        ax.text(0.5, 0.5, "No observations yet today", transform=ax.transAxes,
                 ha="center", va="center", fontproperties=f_med, fontsize=13, color=INK_SECONDARY)
        ax.set_ylim(0, 1)

    # ---------- axes styling ----------
    ax.set_ylabel("Air Temperature (°F)", fontproperties=f_med, fontsize=12, color=INK)
    ax.set_xlabel("Time", fontproperties=f_med, fontsize=12, color=INK)
    ax.set_axisbelow(False)
    ax.grid(axis="y", color=GRID_COLOR, alpha=0.25, linewidth=0.9, zorder=Z_GRID)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(AXIS_COLOR)
        ax.spines[spine].set_linewidth(1.0)

    ax.xaxis.set_major_locator(mdates.HourLocator(interval=3, tz=tz))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=tz))
    ax.set_xlim(day_start, day_end)
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

    # ---------- logo (bottom-right, matching the other temp chart placement) ----------
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
    date_str = day_start.strftime("%B %-d, %Y")
    fig.text(left_x, title_y, f"Today's Temperature — {data['label']}",
              fontproperties=f_bold, fontsize=22, color=INK)
    subtitle = date_str
    fig.text(left_x, subtitle_y, subtitle, fontproperties=f_reg, fontsize=12, color=INK_SECONDARY)

    # ---------- attribution ----------
    fig.text(center_x, 0.02, "Ingalls Weather",
              fontproperties=f_reg, fontsize=9, color=INK_SECONDARY, ha="center")

    plt.savefig(args.output, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
    print(f"saved {args.output}")


if __name__ == "__main__":
    main()

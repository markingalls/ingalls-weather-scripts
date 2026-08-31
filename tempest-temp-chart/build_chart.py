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
from matplotlib.transforms import Bbox

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

# Dark red for the daily-high callout -- same hue tri-cities-temp-chart
# uses for its record-high markers.
HIGH_COLOR = "#a3242b"

Z_GRID = 2
Z_TEMP = 4
Z_MARKER = 5

# The Tempest hub reports roughly once a minute -- a gap much longer than
# that means the station (or its internet connection) was actually down,
# not just a skipped sample. Used to break the plotted line rather than
# drawing a straight segment across a period with no real data.
MAX_GAP = timedelta(minutes=6)

# ---------- current-conditions stat boxes ----------
# Background color tables for the two stat boxes, each a list of (Kelvin,
# (R, G, B)) control points sorted by K -- interp_color() linearly
# interpolates between them. Alpha is uniformly opaque in both source
# tables, so it's dropped here.
TEMP_COLOR_TABLE = [
    (205.53962824635747, (20, 1, 11)),
    (220.54105933801642, (72, 2, 42)),
    (223.30970412365585, (114, 5, 69)),
    (226.07834890929527, (156, 7, 95)),
    (228.8469936949347, (190, 31, 133)),
    (231.61563848057412, (216, 33, 184)),
    (234.38428326621354, (224, 94, 226)),
    (237.15292805185297, (208, 143, 208)),
    (239.9215728374924, (198, 174, 206)),
    (242.71111221757047, (177, 149, 200)),
    (245.48274194527255, (153, 122, 186)),
    (248.25437167297463, (120, 90, 160)),
    (251.02600140067673, (95, 67, 136)),
    (253.7976311283788, (75, 44, 128)),
    (256.5692608560809, (52, 34, 130)),
    (259.2740222360249, (44, 54, 150)),
    (262.11252031148507, (62, 73, 174)),
    (264.88415003918715, (79, 90, 198)),
    (267.13811875987665, (90, 128, 206)),
    (269.1251668409579, (100, 165, 214)),
    (271.1122149220392, (94, 194, 212)),
    (273.0992630031204, (40, 142, 160)),
    (275.0863110842017, (24, 105, 120)),
    (279.0604072463642, (28, 108, 79)),
    (283.03450340852675, (39, 132, 85)),
    (286.97216346781227, (60, 150, 83)),
    (289.741977590991, (112, 172, 91)),
    (292.5117917141697, (159, 190, 91)),
    (295.2816058373485, (208, 200, 84)),
    (298.0514199605272, (204, 172, 70)),
    (300.8212340837059, (212, 146, 61)),
    (303.5910482068847, (218, 121, 35)),
    (306.3608623300634, (208, 90, 31)),
    (309.13067645324213, (216, 59, 32)),
    (311.9004905764209, (182, 32, 7)),
    (314.6703046995996, (142, 36, 19)),
    (317.44011882277835, (102, 23, 10)),
    (320.20993294595706, (142, 15, 54)),
    (322.9797470691358, (194, 50, 94)),
    (325.74956119231456, (216, 120, 149)),
    (332.71070543555834, (204, 16, 171)),
]

DEW_POINT_COLOR_TABLE = [
    (183, (0, 0, 0)),
    (213, (59, 35, 0)),
    (253, (66, 50, 34)),
    (273, (122, 107, 95)),
    (280, (204, 201, 199)),
    (283, (108, 176, 99)),
    (291, (16, 99, 16)),
    (296, (0, 64, 18)),
    (301, (143, 143, 0)),
    (308, (179, 107, 0)),
]


def fahrenheit_to_kelvin(f):
    return (f - 32) * 5 / 9 + 273.15


def interp_color(value_k, table):
    """Linearly interpolates an (R, G, B) 0-255 triple from a sorted
    (K, (R, G, B)) table, clamping to the end colors outside its range."""
    if value_k <= table[0][0]:
        return table[0][1]
    if value_k >= table[-1][0]:
        return table[-1][1]
    for (k0, c0), (k1, c1) in zip(table, table[1:]):
        if k0 <= value_k <= k1:
            frac = (value_k - k0) / (k1 - k0)
            return tuple(c0[i] + frac * (c1[i] - c0[i]) for i in range(3))
    return table[-1][1]


def text_color_for_bg(rgb):
    """Black or white, whichever reads better against an (R, G, B) 0-255
    background -- ITU-R BT.601 perceptual luminance, the standard
    black/white text contrast heuristic."""
    r, g, b = rgb
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return "black" if luminance > 140 else "white"


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
    ap.add_argument("--mark-high", action="store_true",
                     help="Circle and label the day's highest observation")
    return ap.parse_args()


def insert_gaps(times, temps, max_gap):
    """Returns (times, temps) with a NaN-valued point inserted at the
    midpoint of any consecutive pair more than max_gap apart -- matplotlib
    breaks a line at a NaN y-value rather than drawing a straight segment
    across it, so a real data outage shows as a visible gap instead of
    reading as continuous data. Extrema/axis-limit logic should keep using
    the original times/temps, not this -- the inserted points aren't real
    observations."""
    if not times:
        return times, temps
    out_times, out_temps = [times[0]], [temps[0]]
    for i in range(1, len(times)):
        if times[i] - times[i - 1] > max_gap:
            out_times.append(times[i - 1] + (times[i] - times[i - 1]) / 2)
            out_temps.append(float("nan"))
        out_times.append(times[i])
        out_temps.append(temps[i])
    return out_times, out_temps


def main():
    args = parse_args()
    data = json.load(open(args.data))
    tz = ZoneInfo(data["timezone"])

    times = [datetime.fromisoformat(o["time"]) for o in data["observations"]]
    temps = [o["air_temp_f"] for o in data["observations"]]
    dew_points = [o.get("dew_point_f") for o in data["observations"]]

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
    # Shorter than the other temp charts' 0.65 -- the current-conditions
    # stat boxes below take the freed vertical space, in the band between
    # here and the (now fig-position-fixed, not axes-derived) subtitle.
    ax = fig.add_axes([0.075, 0.10, 0.87, 0.56])
    ax.set_facecolor("white")

    axpos = ax.get_position()
    left_x, right_x, top_y = axpos.x0, axpos.x1, axpos.y1
    center_x = (axpos.x0 + axpos.x1) / 2

    temp_line = None
    if times:
        plot_times, plot_temps = insert_gaps(times, temps, MAX_GAP)
        temp_line = ax.plot(plot_times, plot_temps, color=TEMP_COLOR, linewidth=2.6, zorder=Z_TEMP,
                             label="Air temperature")[0]

        # The line legitimately stops partway through the day on a same-day
        # chart -- a dotted marker at the last observation makes that read
        # as current, not as missing data.
        ax.axvline(times[-1], color=AXIS_COLOR, linewidth=1.0, linestyle=":", zorder=Z_GRID)

        # Day's high is the observed max so far, extended to the forecast
        # high (if fetch_forecast.py's forecast.json is present) so the
        # axis has headroom for the afternoon high before it's actually
        # been observed -- once it has, the observed max takes over since
        # it'll be the larger of the two (max() itself is the override: a
        # forecast is only ever a floor on the axis, never a ceiling that
        # could clip an observation that runs hotter). Fixed 3°F padding
        # both directions rather than a proportional one, so the line never
        # crowds the axis edges. Set here (rather than down in "axes
        # styling") so the logo-placement and --mark-low/--mark-high logic
        # below can both work against the final plot bounds.
        #
        # NOTE for future reference: if a forecast *low* is ever wired in
        # here too (there's currently only a forecast high, from NWS's
        # daytime period -- see fetch_forecast.py), apply the same
        # observed-wins rule symmetrically: day_low = min(day_low,
        # forecast_low), not the reverse. An actual observation should
        # always be able to override a forecast in whichever direction it
        # turns out to be more extreme, above or below.
        day_low, day_high = min(temps), max(temps)
        if forecast_high is not None:
            day_high = max(day_high, forecast_high)
        ax.set_ylim(day_low - 3, day_high + 3)
        ax.set_xlim(day_start, day_end)
    else:
        ax.text(0.5, 0.5, "No observations yet today", transform=ax.transAxes,
                 ha="center", va="center", fontproperties=f_med, fontsize=13, color=INK_SECONDARY)
        ax.set_ylim(0, 1)
        ax.set_xlim(day_start, day_end)

    # ---------- logo ----------
    # Defaults bottom-right, matching the other temp charts. Checked against
    # the final axis bounds above, so it can tell whether the plotted line
    # actually passes through that corner (a late-day reading near the axis
    # floor can land right under it, especially once a forecast high has
    # stretched the axis a lot) and use the top-right corner instead when
    # it would otherwise sit on top of real data.
    LOGO_PATH = "../assets/ingalls_weather_logo.png"
    logo_ax = None
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
        bottom_y0 = axpos.y0 + inset_y
        top_y0 = axpos.y1 - inset_y - logo_height_fig
        logo_y0 = bottom_y0

        if temp_line is not None:
            # Checked against the line's actual drawn path (every segment,
            # via Path.intersects_bbox), not just the raw data points --
            # Tempest data is dense enough (1-minute samples) that the two
            # are equivalent in practice, but a segment between two widely
            # spaced points can cut through the corner without either
            # endpoint landing inside it.
            fig_w_px, fig_h_px = fig_w_in * dpi, fig_h_in * dpi
            pad = 6  # a little slack for line width, not just the bare path
            rect = Bbox.from_extents(logo_x0 * fig_w_px - pad, bottom_y0 * fig_h_px - pad,
                                      (logo_x0 + logo_width_fig) * fig_w_px + pad,
                                      (bottom_y0 + logo_height_fig) * fig_h_px + pad)
            display_path = temp_line.get_transform().transform_path(temp_line.get_path())
            if display_path.intersects_bbox(rect, filled=False):
                logo_y0 = top_y0

        logo_ax = fig.add_axes([logo_x0, logo_y0, logo_width_fig, logo_height_fig], zorder=20)
        logo_ax.imshow(logo_img)
        logo_ax.axis("off")
    else:
        print(f"NOTE: no logo found at {LOGO_PATH} -- skipping logo placement.")

    if times and (args.mark_low or args.mark_high):
        label_stroke = [pe.withStroke(linewidth=2.5, foreground="white")]
        # Circled markers already placed this render (starts with just the
        # logo, if any) -- each new one avoids all of these, and adds its
        # own final position to the list before the next one is placed, so
        # a low and a high shown together don't land on top of each other.
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        ax_box = ax.get_window_extent(renderer)
        occupied = [logo_ax.get_window_extent(renderer)] if logo_ax is not None else []

        def mark_extreme(idx, color, prefix):
            t_val, v_val = times[idx], temps[idx]
            ax.scatter([t_val], [v_val], s=160, facecolors="none", edgecolors=color,
                       linewidths=2.2, zorder=Z_MARKER)
            label_text = f"{prefix}: {v_val:.1f}°F at {t_val.strftime('%H:%M')}"

            def place(ha, va, x_off, y_off):
                a = ax.annotate(label_text, xy=(t_val, v_val), xytext=(x_off, y_off),
                                 textcoords="offset points", ha=ha, va=va,
                                 fontproperties=f_bold, fontsize=12, color=color, zorder=Z_MARKER)
                a.set_path_effects(label_stroke)
                return a

            # Below-right is the preferred placement; fall back through
            # above-right, below-left, above-left in that order, keeping
            # the first whose actual rendered extent stays inside the plot
            # and clear of the logo/other marker -- rather than guess a
            # threshold, since a forecast-driven axis can leave very
            # little room below the low (its bottom padding is a flat
            # 3°F regardless of how tall the axis gets above it), and
            # either point can in principle land anywhere in the day,
            # including right in the logo's corner or near each other.
            candidates = [
                ("left", "center", 10, -8),
                ("left", "bottom", 10, 10),
                ("right", "center", -10, -8),
                ("right", "bottom", -10, 10),
            ]
            txt = None
            for ha, va, x_off, y_off in candidates:
                if txt is not None:
                    txt.remove()
                txt = place(ha, va, x_off, y_off)
                fig.canvas.draw()
                txt_box = txt.get_window_extent(renderer)
                fits = (ax_box.xmin <= txt_box.xmin and txt_box.xmax <= ax_box.xmax
                        and ax_box.ymin <= txt_box.ymin and txt_box.ymax <= ax_box.ymax)
                clear = not any(txt_box.overlaps(b) for b in occupied)
                if fits and clear:
                    break
            occupied.append(txt.get_window_extent(renderer))

        if args.mark_low:
            mark_extreme(min(range(len(temps)), key=lambda i: temps[i]), LOW_COLOR, "Low")
        if args.mark_high:
            mark_extreme(max(range(len(temps)), key=lambda i: temps[i]), HIGH_COLOR, "High")

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
    ax.tick_params(axis="both", colors=AXIS_COLOR, labelsize=10, length=4)
    for tick in ax.get_xticklabels():
        tick.set_fontproperties(f_reg)
        tick.set_color(INK_SECONDARY)
        tick.set_fontsize(10)
    for tick in ax.get_yticklabels():
        tick.set_fontproperties(f_reg)
        tick.set_color(INK_SECONDARY)
        tick.set_fontsize(10)

    # ---------- title / subtitle ----------
    # Fixed rather than derived from top_y (axpos.y1) -- now that the axes
    # is shorter than the other temp charts, the stat boxes below sit in
    # the freed band at their own fixed height, not one that scales with
    # wherever the (now shorter) axes' own top happens to land.
    subtitle_y = 0.815
    title_y = subtitle_y + 0.035
    date_str = day_start.strftime("%B %-d, %Y")
    fig.text(left_x, title_y, f"Today's Temperature — {data['label']}",
              fontproperties=f_bold, fontsize=22, color=INK)
    subtitle = f"{date_str} • Updated: {times[-1].strftime('%H:%M')} PT" if times else date_str
    fig.text(left_x, subtitle_y, subtitle, fontproperties=f_reg, fontsize=12, color=INK_SECONDARY)

    # ---------- current-conditions stat boxes ----------
    # Sit in the band freed up by shrinking the axes above, between the
    # plot's top and the subtitle: a two-line regular-weight label
    # ("Current" / "Temperature") to the left of a bold value readout,
    # whose own small colored backdrop (not the whole row) comes from the
    # current reading's color-table lookup (temp/dew point converted to
    # Kelvin, interpolated); the bold text itself is black or white,
    # whichever contrasts against that particular background.
    if times:
        current_temp_f = temps[-1]
        current_dew_point_f = dew_points[-1]

        stat_center_y = 0.685 + 0.105 / 2
        stat_gap = 0.02
        col_width = (right_x - left_x - stat_gap) / 2
        label_fontsize = 14

        def draw_stat_pair(label_x, number_x, label_text, value_f, table):
            label_artist = fig.text(label_x, stat_center_y, label_text, fontproperties=f_reg,
                                     fontsize=label_fontsize, color=INK, ha="left", va="center",
                                     linespacing=1.2)
            fig.canvas.draw()
            renderer = fig.canvas.get_renderer()
            label_height_px = label_artist.get_window_extent(renderer).height

            value_text = f"{value_f:.1f}°F" if value_f is not None else "N/A"

            # The number's fontsize is picked so its own rendered text
            # height matches the two-line label's, not guessed -- render
            # once at a probe size, measure, then rescale proportionally.
            probe_size = 24
            probe = fig.text(0, 0, value_text, fontproperties=f_bold, fontsize=probe_size)
            fig.canvas.draw()
            probe_height_px = probe.get_window_extent(renderer).height
            probe.remove()
            number_fontsize = probe_size * (label_height_px / probe_height_px)

            if value_f is not None:
                rgb = interp_color(fahrenheit_to_kelvin(value_f), table)
                text_color = text_color_for_bg(rgb)
                chip_color = tuple(c / 255 for c in rgb)
            else:
                text_color = INK_SECONDARY
                chip_color = BG

            fig.text(number_x, stat_center_y, value_text, fontproperties=f_bold,
                      fontsize=number_fontsize, color=text_color, ha="left", va="center",
                      bbox=dict(boxstyle="round,pad=0.35", facecolor=chip_color, edgecolor="none"),
                      zorder=15)

        draw_stat_pair(left_x, left_x + col_width * 0.5,
                        "Current\nTemperature", current_temp_f, TEMP_COLOR_TABLE)
        draw_stat_pair(left_x + col_width + stat_gap, left_x + col_width + stat_gap + col_width * 0.5,
                        "Current\nDew Point", current_dew_point_f, DEW_POINT_COLOR_TABLE)

    # ---------- attribution ----------
    fig.text(center_x, 0.02, "Ingalls Weather",
              fontproperties=f_reg, fontsize=9, color=INK_SECONDARY, ha="center")

    plt.savefig(args.output, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
    print(f"saved {args.output}")


if __name__ == "__main__":
    main()

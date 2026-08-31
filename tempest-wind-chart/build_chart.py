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
from matplotlib.transforms import Bbox

# ---------- fonts ----------
FONT_DIR = "/usr/share/fonts/truetype/google-fonts/"
f_bold = fm.FontProperties(fname=FONT_DIR + "Poppins-Bold.ttf")
f_reg = fm.FontProperties(fname=FONT_DIR + "Poppins-Regular.ttf")
f_med = fm.FontProperties(fname=FONT_DIR + "Poppins-Medium.ttf")

# ---------- palette (same canvas/style as tempest-temp-chart) ----------
BG = "#f7f6f2"
INK = "#2b2a26"
INK_SECONDARY = "#5a584f"
GRID_COLOR = "#000000"
AXIS_COLOR = "#000000"

# Teal for the sustained wind speed line -- calm/steady, paired against
# gust's warmer, more attention-grabbing color below.
WIND_SPEED_COLOR = "#0e7c86"

# Amber for the gust line -- a burst of wind reads as the "hotter" of the
# two, so it gets the warmer color, same pairing logic as e.g. a low/high
# callout using a cool/warm split elsewhere in this repo.
GUST_COLOR = "#d97706"

Z_GRID = 2
Z_WIND = 4

# The Tempest hub reports roughly once a minute -- a gap much longer than
# that means the station (or its internet connection) was actually down,
# not just a skipped sample. Used to break the plotted line rather than
# drawing a straight segment across a period with no real data.
MAX_GAP = timedelta(minutes=6)

# ---------- current-conditions stat boxes ----------
# Background color table for both stat boxes (wind speed and gust each
# look themselves up against it, independently) -- (m/s, (R, G, B))
# control points sorted by m/s -- interp_color() linearly interpolates
# between them. Alpha is uniformly opaque in the source table, so it's
# dropped here. Keyed by m/s (not Kelvin, the way the temp chart's own
# tables are) since that's the source table's own unit -- interp_color()
# itself is unit-agnostic, so no analog to the temp chart's
# fahrenheit_to_kelvin() is needed; mph_to_ms() below converts the
# display value back to this table's units at the call site instead.
WIND_COLOR_TABLE = [
    (0, (101, 99, 99)),
    (3.0023985091248635, (89, 89, 89)),
    (6.004797018249727, (167, 157, 81)),
    (9.00719552737459, (124, 105, 39)),
    (14.763362259768375, (86, 69, 13)),
    (15.645832230884011, (185, 140, 44)),
    (24.549356223175963, (225, 24, 33)),
    (32.13733905579399, (137, 33, 33)),
    (33.922746781115876, (62, 0, 71)),
    (44.77275228348189, (165, 71, 179)),
    (66.86709040243753, (225, 209, 227)),
    (89.29880316110201, (187, 199, 118)),
    (134.10713340757724, (223, 251, 68)),
]

# 16-point compass, matching WeatherFlow's own wind_dir_deg resolution --
# each name covers a 22.5 degree wedge centered on its own heading.
CARDINAL_DIRECTIONS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def degrees_to_cardinal(deg):
    return CARDINAL_DIRECTIONS[round(deg / 22.5) % 16]


def mph_to_ms(mph):
    return mph * 0.44704


def interp_color(value, table):
    """Linearly interpolates an (R, G, B) 0-255 triple from a sorted
    (x, (R, G, B)) table, clamping to the end colors outside its range."""
    if value <= table[0][0]:
        return table[0][1]
    if value >= table[-1][0]:
        return table[-1][1]
    for (x0, c0), (x1, c1) in zip(table, table[1:]):
        if x0 <= value <= x1:
            frac = (value - x0) / (x1 - x0)
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
    ap = argparse.ArgumentParser(description="Render today's Tempest station wind chart.")
    ap.add_argument("--data", default="tempest_wind_obs.json")
    ap.add_argument("--output", default="tempest_wind_chart.png")
    return ap.parse_args()


def insert_gaps(times, values, max_gap):
    """Returns (times, values) with a NaN-valued point inserted at the
    midpoint of any consecutive pair more than max_gap apart -- matplotlib
    breaks a line at a NaN y-value rather than drawing a straight segment
    across it, so a real data outage shows as a visible gap instead of
    reading as continuous data. Extrema/axis-limit logic should keep using
    the original times/values, not this -- the inserted points aren't real
    observations."""
    if not times:
        return times, values
    out_times, out_values = [times[0]], [values[0]]
    for i in range(1, len(times)):
        if times[i] - times[i - 1] > max_gap:
            out_times.append(times[i - 1] + (times[i] - times[i - 1]) / 2)
            out_values.append(float("nan"))
        out_times.append(times[i])
        out_values.append(values[i])
    return out_times, out_values


def main():
    args = parse_args()
    data = json.load(open(args.data))
    tz = ZoneInfo(data["timezone"])

    times = [datetime.fromisoformat(o["time"]) for o in data["observations"]]
    wind_speeds = [o["wind_speed_mph"] for o in data["observations"]]
    wind_gusts = [o.get("wind_gust_mph") for o in data["observations"]]
    wind_dirs = [o.get("wind_dir_deg") for o in data["observations"]]

    day_start = datetime.fromisoformat(data["date"]).replace(tzinfo=tz)
    day_end = day_start + timedelta(days=1)

    # ---------- figure (same footprint as tempest-temp-chart) ----------
    fig = plt.figure(figsize=(12, 8.3), dpi=200)
    fig.patch.set_facecolor(BG)
    # Shorter than a full-height chart -- the current-conditions stat
    # boxes below take the freed vertical space, in the band between here
    # and the (fig-position-fixed, not axes-derived) subtitle. Same
    # proportions as tempest-temp-chart's own single-stat-row layout.
    ax = fig.add_axes([0.075, 0.10, 0.87, 0.56])
    ax.set_facecolor("white")

    axpos = ax.get_position()
    left_x, right_x, top_y = axpos.x0, axpos.x1, axpos.y1
    center_x = (axpos.x0 + axpos.x1) / 2

    wind_speed_line = None
    gust_line = None
    if times:
        plot_times, plot_speeds = insert_gaps(times, wind_speeds, MAX_GAP)
        wind_speed_line = ax.plot(plot_times, plot_speeds, color=WIND_SPEED_COLOR, linewidth=2.6,
                                   zorder=Z_WIND, label="Wind speed")[0]

        # Gust is plotted the same way as wind speed: missing readings
        # already come through as None from fetch_tempest.py, substituted
        # with NaN here so matplotlib skips them the same way insert_gaps()
        # skips a real time gap, then run through insert_gaps() itself for
        # actual outages.
        gust_values = [g if g is not None else float("nan") for g in wind_gusts]
        plot_times_gust, plot_gusts = insert_gaps(times, gust_values, MAX_GAP)
        gust_line = ax.plot(plot_times_gust, plot_gusts, color=GUST_COLOR, linewidth=2.0,
                             zorder=Z_WIND - 1, label="Gust")[0]

        # The line legitimately stops partway through the day on a same-day
        # chart -- a dotted marker at the last observation makes that read
        # as current, not as missing data.
        ax.axvline(times[-1], color=AXIS_COLOR, linewidth=1.0, linestyle=":", zorder=Z_GRID)

        # Wind speed can't go negative, so the axis floor is a flat 0
        # rather than a padded-below-the-low the way the temp chart pads
        # both directions -- there's no meaningful "3 mph below calm."
        # The ceiling is the day's highest reading across both lines (gust
        # is almost always >= wind speed, but checking both rather than
        # assuming it holds for every single sample), padded the same
        # fixed +3 mph the temp chart uses so the line never crowds the
        # axis edge.
        valid_gusts = [g for g in wind_gusts if g is not None]
        day_high = max(wind_speeds + valid_gusts) if valid_gusts else max(wind_speeds)
        ax.set_ylim(0, day_high + 3)
        ax.set_xlim(day_start, day_end)

        legend = ax.legend(loc="upper left", frameon=True, fontsize=10.5, prop=f_reg,
                            handlelength=1.6, borderaxespad=0.8)
        legend.get_frame().set_facecolor("white")
        legend.get_frame().set_edgecolor("none")
        legend.set_zorder(Z_WIND + 1)
        for text in legend.get_texts():
            text.set_color(INK_SECONDARY)
    else:
        ax.text(0.5, 0.5, "No observations yet today", transform=ax.transAxes,
                 ha="center", va="center", fontproperties=f_med, fontsize=13, color=INK_SECONDARY)
        ax.set_ylim(0, 1)
        ax.set_xlim(day_start, day_end)

    # ---------- logo ----------
    # Defaults bottom-right, matching tempest-temp-chart. Checked against
    # the final axis bounds above, so it can tell whether the plotted line
    # actually passes through that corner and use the top-right corner
    # instead when it would otherwise sit on top of real data.
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

        # Checked against both lines' actual drawn paths (every segment,
        # via Path.intersects_bbox), not just the raw data points -- a
        # segment between two widely spaced points can cut through the
        # corner without either endpoint landing inside it. Since the axis
        # floor is a flat 0, the bottom-right corner is only ever at risk
        # late in the day during a calm spell, but it can happen.
        for line in (wind_speed_line, gust_line):
            if line is None:
                continue
            fig_w_px, fig_h_px = fig_w_in * dpi, fig_h_in * dpi
            pad = 6  # a little slack for line width, not just the bare path
            rect = Bbox.from_extents(logo_x0 * fig_w_px - pad, bottom_y0 * fig_h_px - pad,
                                      (logo_x0 + logo_width_fig) * fig_w_px + pad,
                                      (bottom_y0 + logo_height_fig) * fig_h_px + pad)
            display_path = line.get_transform().transform_path(line.get_path())
            if display_path.intersects_bbox(rect, filled=False):
                logo_y0 = top_y0
                break

        logo_ax = fig.add_axes([logo_x0, logo_y0, logo_width_fig, logo_height_fig], zorder=20)
        logo_ax.imshow(logo_img)
        logo_ax.axis("off")
    else:
        print(f"NOTE: no logo found at {LOGO_PATH} -- skipping logo placement.")

    # ---------- axes styling ----------
    ax.set_ylabel("Wind Speed (mph)", fontproperties=f_med, fontsize=12, color=INK)
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
    # Fixed rather than derived from top_y (axpos.y1) -- the axes here is
    # shorter than a full-height chart, with the stat boxes below sitting
    # in the freed band at their own fixed height, not one that scales
    # with wherever the (shorter) axes' own top happens to land.
    subtitle_y = 0.815
    title_y = subtitle_y + 0.035
    date_str = day_start.strftime("%B %-d, %Y")
    fig.text(left_x, title_y, f"Today's Wind — {data['label']}",
              fontproperties=f_bold, fontsize=22, color=INK)
    subtitle = f"{date_str} • Updated: {times[-1].strftime('%H:%M')} PT" if times else date_str
    fig.text(left_x, subtitle_y, subtitle, fontproperties=f_reg, fontsize=12, color=INK_SECONDARY)

    # ---------- current-conditions stat boxes ----------
    # Sit in the band freed up by shrinking the axes above, between the
    # plot's top and the subtitle: a two-line regular-weight, right-aligned
    # label ("Current" / "Wind") immediately to the left of a bold value
    # readout, the pair centered as a unit within its own column (wind
    # centered in the left half, gust in the right half). The number's own
    # small colored backdrop (not the whole row) comes from interpolating
    # WIND_COLOR_TABLE (m/s -> RGB control points, linearly interpolated by
    # interp_color()) against the reading converted from mph to m/s, and
    # the bold text itself is black or white via text_color_for_bg()'s
    # ITU-R BT.601 luminance check. Wind speed and gust each look
    # themselves up against the same table independently -- there's only
    # one source table, covering both.
    if times:
        current_wind_mph = wind_speeds[-1]
        current_wind_dir_deg = wind_dirs[-1]
        current_gust_mph = wind_gusts[-1]

        stat_center_y = 0.685 + 0.105 / 2
        stat_gap = 0.02
        col_width = (right_x - left_x - stat_gap) / 2
        # A geometrically-centered pair still reads as sitting a bit right
        # of center -- the bold, colored chip carries more visual weight
        # than the plain label next to it, pulling the eye rightward -- so
        # nudge the centering target left by a small fixed amount.
        stat_visual_shift = 0.012
        label_fontsize = 14
        label_linespacing = 0.85
        fig_w_px = fig.get_size_inches()[0] * fig.get_dpi()
        label_number_gap_px = 0.012 * fig_w_px

        def draw_stat_pair(column_center_x, label_text, value_text, color_value):
            fig.canvas.draw()
            renderer = fig.canvas.get_renderer()

            # Label width at its actual (tight) line spacing.
            label_probe = fig.text(0, stat_center_y, label_text, fontproperties=f_reg,
                                     fontsize=label_fontsize, linespacing=label_linespacing)
            fig.canvas.draw()
            label_width_px = label_probe.get_window_extent(renderer).width
            label_probe.remove()

            # Number fontsize is matched to the label block's height at
            # linespacing=1.2 (a wider spacing than it's actually drawn
            # with) rather than the tighter spacing above -- keeps the
            # number a consistent size independent of the label's own
            # (tighter) line spacing.
            height_probe = fig.text(0, 0, label_text, fontproperties=f_reg,
                                      fontsize=label_fontsize, linespacing=1.2)
            fig.canvas.draw()
            label_height_px = height_probe.get_window_extent(renderer).height
            height_probe.remove()

            probe_size = 24
            num_probe = fig.text(0, 0, value_text, fontproperties=f_bold, fontsize=probe_size)
            fig.canvas.draw()
            probe_height_px = num_probe.get_window_extent(renderer).height
            num_probe.remove()
            number_fontsize = probe_size * (label_height_px / probe_height_px)

            if color_value is not None:
                rgb = interp_color(color_value, WIND_COLOR_TABLE)
                text_color = text_color_for_bg(rgb)
                chip_color = tuple(c / 255 for c in rgb)
            else:
                text_color = INK_SECONDARY
                chip_color = BG

            chip_pad = 0.35
            chip_kwargs = dict(fontproperties=f_bold, fontsize=number_fontsize, color=text_color,
                                va="center", bbox=dict(boxstyle=f"round,pad={chip_pad}",
                                                        facecolor=chip_color, edgecolor="none"))
            # get_window_extent() on bbox-styled text reports only the bare
            # text's box, ignoring the padded patch drawn behind it -- so
            # the patch's pad has to be added back in by hand. "pad" in a
            # boxstyle spec is in font-size units, i.e. chip_pad *
            # fontsize *points*, converted to pixels via dpi/72. See
            # tempest-temp-chart/README.md's stat-box section for how this
            # was originally diagnosed.
            num_probe2 = fig.text(0, stat_center_y, value_text, ha="left", **chip_kwargs)
            fig.canvas.draw()
            text_width_px = num_probe2.get_window_extent(renderer).width
            num_probe2.remove()
            pad_px = chip_pad * number_fontsize * (fig.get_dpi() / 72)
            chip_width_px = text_width_px + 2 * pad_px

            # Center the whole (label + gap + chip) unit on the column's
            # own midpoint, rather than pinning it to the column's left edge.
            total_width_px = label_width_px + label_number_gap_px + chip_width_px
            start_x_px = column_center_x * fig_w_px - total_width_px / 2
            label_right_px = start_x_px + label_width_px
            # anchor = desired visual left edge of the padded chip + pad_px,
            # since the chip's actual left edge sits pad_px left of the anchor.
            number_anchor_px = label_right_px + label_number_gap_px + pad_px

            fig.text(label_right_px / fig_w_px, stat_center_y, label_text, fontproperties=f_reg,
                      fontsize=label_fontsize, color=INK, ha="right", va="center",
                      linespacing=label_linespacing, multialignment="right")
            fig.text(number_anchor_px / fig_w_px, stat_center_y, value_text, ha="left",
                      zorder=15, **chip_kwargs)

        wind_column_center = left_x + col_width / 2 - stat_visual_shift
        gust_column_center = left_x + col_width + stat_gap + col_width / 2 - stat_visual_shift

        # Wind needs both speed and direction to mean anything -- a
        # direction with no speed (or vice versa) reads as N/A rather than
        # a half-formed value.
        if current_wind_mph is not None and current_wind_dir_deg is not None:
            wind_text = f"{degrees_to_cardinal(current_wind_dir_deg)} {current_wind_mph:.1f} mph"
            wind_color_value = mph_to_ms(current_wind_mph)
        else:
            wind_text, wind_color_value = "N/A", None
        draw_stat_pair(wind_column_center, "Current\nWind", wind_text, wind_color_value)

        gust_text = f"{current_gust_mph:.1f} mph" if current_gust_mph is not None else "N/A"
        gust_color_value = mph_to_ms(current_gust_mph) if current_gust_mph is not None else None
        draw_stat_pair(gust_column_center, "Current\nGusts", gust_text, gust_color_value)

    # ---------- attribution ----------
    fig.text(center_x, 0.02, "Ingalls Weather",
              fontproperties=f_reg, fontsize=9, color=INK_SECONDARY, ha="center")

    plt.savefig(args.output, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
    print(f"saved {args.output}")


if __name__ == "__main__":
    main()

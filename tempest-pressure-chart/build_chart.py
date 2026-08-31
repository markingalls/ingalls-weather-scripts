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
import matplotlib.ticker as mticker
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

# Same forest green tempest-temp-chart uses for its own secondary (dew
# point) line and tempest-wind-chart uses for its gust dots -- pressure
# has only the one series, so it just takes the family's green outright
# rather than needing its own new hue.
PRESSURE_COLOR = "#164f29"

Z_GRID = 2
Z_PRESSURE = 4

# The Tempest hub reports roughly once a minute -- a gap much longer than
# that means the station (or its internet connection) was actually down,
# not just a skipped sample. Used to break the plotted line rather than
# drawing a straight segment across a period with no real data.
MAX_GAP = timedelta(minutes=6)


def text_color_for_bg(rgb):
    """Black or white, whichever reads better against an (R, G, B) 0-255
    background -- ITU-R BT.601 perceptual luminance, the standard
    black/white text contrast heuristic."""
    r, g, b = rgb
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return "black" if luminance > 140 else "white"


def parse_args():
    ap = argparse.ArgumentParser(description="Render a Tempest station sea-level-pressure chart "
                                               "for whichever day --data holds observations for "
                                               "(today's, by default) -- see "
                                               "--no-current-conditions for a past, complete day.")
    ap.add_argument("--data", default="tempest_pressure_obs.json")
    ap.add_argument("--output", default="tempest_pressure_chart.png")
    ap.add_argument("--no-current-conditions", action="store_true",
                     help="Skip the current-conditions stat box and reclaim its vertical "
                          "space for the plot -- for a past, complete (archive) day, where "
                          "there's no 'current' reading to highlight, as opposed to today's "
                          "still-in-progress chart")
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
    pressures = [o["sea_level_pressure_inhg"] for o in data["observations"]]

    day_start = datetime.fromisoformat(data["date"]).replace(tzinfo=tz)
    day_end = day_start + timedelta(days=1)

    # ---------- figure (same footprint as tempest-temp-chart) ----------
    fig = plt.figure(figsize=(12, 8.3), dpi=200)
    fig.patch.set_facecolor(BG)
    # Shorter than a full-height chart whenever the current-conditions
    # stat box is shown -- it takes the freed vertical space, in the
    # band between here and the (fig-position-fixed, not axes-derived)
    # subtitle. Same proportions as tempest-temp-chart's own single-stat-
    # row layout. A --no-current-conditions (archive) day has no stat
    # box to make room for, so its axes uses the full 0.65 instead, same
    # as tempest-temp-chart's own archive-day layout.
    ax_height = 0.65 if args.no_current_conditions else 0.56
    ax = fig.add_axes([0.075, 0.10, 0.87, ax_height])
    ax.set_facecolor("white")

    axpos = ax.get_position()
    left_x, right_x, top_y = axpos.x0, axpos.x1, axpos.y1
    center_x = (axpos.x0 + axpos.x1) / 2

    pressure_line = None
    if times:
        plot_times, plot_pressures = insert_gaps(times, pressures, MAX_GAP)
        pressure_line = ax.plot(plot_times, plot_pressures, color=PRESSURE_COLOR, linewidth=2.6,
                                 zorder=Z_PRESSURE, label="Sea level pressure")[0]

        # The line legitimately stops partway through the day on a same-day
        # chart -- a dotted marker at the last observation makes that read
        # as current, not as missing data. Skipped for a
        # --no-current-conditions (complete, past) day: its line already
        # runs the full 24 hours (the last observation lands a minute
        # before midnight, not literally at it), so the same marker there
        # would misleadingly read as "cut short" rather than "complete" --
        # same reasoning as tempest-temp-chart's own archive-day charts.
        if not args.no_current_conditions:
            ax.axvline(times[-1], color=AXIS_COLOR, linewidth=1.0, linestyle=":", zorder=Z_GRID)

        # Pressure's whole-day range is usually tiny (a calm day might
        # only span ~0.1-0.2 inHg) compared to temperature's, so this uses
        # a much smaller flat pad than the temp chart's +-3 deg -- enough
        # to keep the line off the axis edges without flattening out the
        # day's actual diurnal wobble into an even thinner sliver of the
        # plot than it already is.
        day_low, day_high = min(pressures), max(pressures)
        pad = 0.05
        ax.set_ylim(day_low - pad, day_high + pad)
        ax.set_xlim(day_start, day_end)
    else:
        ax.text(0.5, 0.5, "No observations that day" if args.no_current_conditions
                 else "No observations yet today", transform=ax.transAxes,
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

        # Checked against the pressure line's actual drawn path (every
        # segment, via Path.intersects_bbox, not just the raw data points
        # -- a segment between two widely spaced points can cut through
        # the corner without either endpoint landing inside it).
        if pressure_line is not None:
            fig_w_px, fig_h_px = fig_w_in * dpi, fig_h_in * dpi
            pad_px = 6  # a little slack for line width, not just the bare path
            rect = Bbox.from_extents(logo_x0 * fig_w_px - pad_px, bottom_y0 * fig_h_px - pad_px,
                                      (logo_x0 + logo_width_fig) * fig_w_px + pad_px,
                                      (bottom_y0 + logo_height_fig) * fig_h_px + pad_px)
            display_path = pressure_line.get_transform().transform_path(pressure_line.get_path())
            if display_path.intersects_bbox(rect, filled=False):
                logo_y0 = top_y0

        logo_ax = fig.add_axes([logo_x0, logo_y0, logo_width_fig, logo_height_fig], zorder=20)
        logo_ax.imshow(logo_img)
        logo_ax.axis("off")
    else:
        print(f"NOTE: no logo found at {LOGO_PATH} -- skipping logo placement.")

    # ---------- axes styling ----------
    ax.set_ylabel("Sea Level Pressure (inHg)", fontproperties=f_med, fontsize=12, color=INK)
    ax.set_xlabel("Time", fontproperties=f_med, fontsize=12, color=INK)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f"))
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
    date_str = day_start.strftime("%B %-d, %Y")
    if args.no_current_conditions:
        # Derived from top_y (axpos.y1) same as tempest-temp-chart's own
        # archive-day charts -- there's no stat-box band below to reserve
        # a fixed gap for, since this axes already uses the same full
        # 0.65 height.
        subtitle_y = top_y + 0.058
        title_y = subtitle_y + 0.035
        title = f"Sea Level Pressure — {data['label']}"
        # No "Updated: HH:MM" clause -- that phrasing implies a still-live
        # reading, which doesn't apply to a complete, past calendar day.
        subtitle = date_str
    else:
        # Fixed rather than derived from top_y -- the axes here is
        # shorter than a full-height chart, with the stat box below
        # sitting in the freed band at their own fixed height, not one
        # that scales with wherever the (shorter) axes' own top happens
        # to land.
        subtitle_y = 0.815
        title_y = subtitle_y + 0.035
        title = f"Today's Sea Level Pressure — {data['label']}"
        subtitle = f"{date_str} • Updated: {times[-1].strftime('%H:%M')} PT" if times else date_str
    fig.text(left_x, title_y, title, fontproperties=f_bold, fontsize=22, color=INK)
    fig.text(left_x, subtitle_y, subtitle, fontproperties=f_reg, fontsize=12, color=INK_SECONDARY)

    # ---------- current-conditions stat box ----------
    # Sits in the band freed up by shrinking the axes above, between the
    # plot's top and the subtitle -- a single, centered pair (unlike the
    # temp/wind charts' two-column layout, there's only the one series
    # here): a two-line regular-weight, right-aligned label ("Current" /
    # "Pressure") immediately to the left of a bold value readout. The
    # chip's background is a fixed color (the same PRESSURE_COLOR as the
    # line itself) rather than a reading-driven color-table lookup the
    # way the other charts' stat boxes work -- no color table was
    # supplied for pressure, so this just carries the line's own color
    # through consistently instead of inventing a gradient.
    if times and not args.no_current_conditions:
        current_pressure_inhg = pressures[-1]

        stat_center_y = 0.685 + 0.105 / 2
        label_fontsize = 14
        label_linespacing = 0.85
        fig_w_px = fig.get_size_inches()[0] * fig.get_dpi()
        label_number_gap_px = 0.012 * fig_w_px

        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()

        label_text = "Current\nPressure"
        value_text = f"{current_pressure_inhg:.2f} in"

        # Label width at its actual (tight) line spacing.
        label_probe = fig.text(0, stat_center_y, label_text, fontproperties=f_reg,
                                 fontsize=label_fontsize, linespacing=label_linespacing)
        fig.canvas.draw()
        label_width_px = label_probe.get_window_extent(renderer).width
        label_probe.remove()

        # Number fontsize is matched to the label block's height at
        # linespacing=1.2 (a wider spacing than it's actually drawn with)
        # rather than the tighter spacing above -- keeps the number a
        # consistent size independent of the label's own (tighter) line
        # spacing.
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

        rgb = tuple(int(PRESSURE_COLOR[i:i + 2], 16) for i in (1, 3, 5))
        text_color = text_color_for_bg(rgb)
        chip_color = tuple(c / 255 for c in rgb)

        chip_pad = 0.35
        chip_kwargs = dict(fontproperties=f_bold, fontsize=number_fontsize, color=text_color,
                            va="center", bbox=dict(boxstyle=f"round,pad={chip_pad}",
                                                    facecolor=chip_color, edgecolor="none"))
        # get_window_extent() on bbox-styled text reports only the bare
        # text's box, ignoring the padded patch drawn behind it -- so the
        # patch's pad has to be added back in by hand. "pad" in a
        # boxstyle spec is in font-size units, i.e. chip_pad * fontsize
        # *points*, converted to pixels via dpi/72. See
        # tempest-temp-chart/README.md's stat-box section for how this
        # was originally diagnosed.
        num_probe2 = fig.text(0, stat_center_y, value_text, ha="left", **chip_kwargs)
        fig.canvas.draw()
        text_width_px = num_probe2.get_window_extent(renderer).width
        num_probe2.remove()
        pad_px = chip_pad * number_fontsize * (fig.get_dpi() / 72)
        chip_width_px = text_width_px + 2 * pad_px

        # Center the whole (label + gap + chip) unit on the figure's own
        # horizontal midpoint, rather than pinning it to a column.
        total_width_px = label_width_px + label_number_gap_px + chip_width_px
        start_x_px = center_x * fig_w_px - total_width_px / 2
        label_right_px = start_x_px + label_width_px
        # anchor = desired visual left edge of the padded chip + pad_px,
        # since the chip's actual left edge sits pad_px left of the anchor.
        number_anchor_px = label_right_px + label_number_gap_px + pad_px

        fig.text(label_right_px / fig_w_px, stat_center_y, label_text, fontproperties=f_reg,
                  fontsize=label_fontsize, color=INK, ha="right", va="center",
                  linespacing=label_linespacing, multialignment="right")
        fig.text(number_anchor_px / fig_w_px, stat_center_y, value_text, ha="left",
                  zorder=15, **chip_kwargs)

    # ---------- attribution ----------
    fig.text(center_x, 0.02, "Ingalls Weather",
              fontproperties=f_reg, fontsize=9, color=INK_SECONDARY, ha="center")

    plt.savefig(args.output, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
    print(f"saved {args.output}")


if __name__ == "__main__":
    main()

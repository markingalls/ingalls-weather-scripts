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

# Same red/blue high/low convention tempest-temp-chart uses for its own
# (opt-in) --mark-high/--mark-low callouts -- also the standard synoptic-
# map convention (red H, blue L), which happens to line up nicely here.
HIGH_COLOR = "#a3242b"
LOW_COLOR = "#0b3d91"

# ---------- current-conditions stat box ----------
# Background color table for the stat box -- (Pa, (R, G, B)) control
# points sorted by Pa -- interp_color() linearly interpolates between
# them. Alpha is uniformly opaque in the source table, so it's dropped
# here. Keyed by Pa (not mb, this chart's own display unit) since that's
# the source table's own unit -- interp_color() itself is unit-agnostic,
# so mb_to_pa() below converts the display value into the table's units
# at the call site, same pattern as the temp/wind charts' own
# fahrenheit_to_kelvin()/mph_to_ms().
PRESSURE_COLOR_TABLE = [
    (90000, (196, 37, 160)),
    (92000, (230, 60, 160)),
    (93000.16666666667, (230, 132, 236)),
    (94000.22222222222, (206, 82, 222)),
    (95000.27777777778, (147, 39, 160)),
    (96000.33333333333, (76, 2, 100)),
    (97000.38888888889, (111, 34, 216)),
    (98000.44444444444, (191, 164, 220)),
    (98800.48888888888, (34, 60, 176)),
    (99300, (113, 160, 196)),
    (99800, (165, 197, 226)),
    (100300, (130, 204, 135)),
    (100800, (21, 126, 24)),
    (101325, (226, 219, 123)),
    (101800, (184, 114, 51)),
    (102300, (106, 12, 12)),
    (102800, (80, 53, 25)),
    (103300, (156, 86, 86)),
    (104000.77777777778, (124, 25, 35)),
    (105000.83333333333, (82, 82, 82)),
    (106000.88888888889, (150, 145, 145)),
    (108001, (226, 220, 220)),
]

Z_GRID = 2
Z_PRESSURE = 4
Z_MARKER = 5

# The Tempest hub reports roughly once a minute -- a gap much longer than
# that means the station (or its internet connection) was actually down,
# not just a skipped sample. Used to break the plotted line rather than
# drawing a straight segment across a period with no real data.
MAX_GAP = timedelta(minutes=6)

# Pressure sensor noise between individual 1-minute samples is small in
# absolute terms but reads as a distracting staircase/jitter at this
# chart's scale (a whole day's real diurnal swing is often not much
# bigger than the noise itself) -- smoothed over a window this wide
# (samples, ~minutes at the hub's ~1/minute cadence) before plotting.
# Only the line is smoothed; the current-conditions stat box below still
# reads the single latest raw sample, same as the temp/wind charts'
# own "current" readouts.
SMOOTHING_WINDOW = 15


def text_color_for_bg(rgb):
    """Black or white, whichever reads better against an (R, G, B) 0-255
    background -- ITU-R BT.601 perceptual luminance, the standard
    black/white text contrast heuristic."""
    r, g, b = rgb
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return "black" if luminance > 140 else "white"


def mb_to_pa(mb):
    return mb * 100


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


def smooth(values, window):
    """Centered simple moving average, window in samples. Edges use
    whatever partial window is actually available (shrinking toward a
    single sample right at the very first/last point) rather than
    padding with NaN or truncating -- the line's start and end stay
    exactly as long as the data itself, just less averaged right at the
    tips."""
    n = len(values)
    half = window // 2
    smoothed = []
    for i in range(n):
        window_vals = values[max(0, i - half):min(n, i + half + 1)]
        smoothed.append(sum(window_vals) / len(window_vals))
    return smoothed


def main():
    args = parse_args()
    data = json.load(open(args.data))
    tz = ZoneInfo(data["timezone"])

    times = [datetime.fromisoformat(o["time"]) for o in data["observations"]]
    pressures = [o["sea_level_pressure_mb"] for o in data["observations"]]

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
        # Smoothed before gap-breaking, not after -- insert_gaps()'s
        # inserted NaNs would otherwise fall inside a smoothing window
        # and NaN-poison every average that touches them. Smoothing
        # across a real gap's edges blends a couple of samples from
        # before/after it as if they were continuous, but gaps are rare
        # and the window is short relative to what counts as a gap
        # (MAX_GAP), so the effect is minor and local to the break itself
        # -- the break still shows up as a visible break either way.
        smoothed_pressures = smooth(pressures, SMOOTHING_WINDOW)
        plot_times, plot_pressures = insert_gaps(times, smoothed_pressures, MAX_GAP)
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
        # only span ~3-7 mb) compared to temperature's, so this uses a
        # much smaller flat pad than the temp chart's +-3 deg -- enough
        # to keep the line off the axis edges without flattening out the
        # day's actual diurnal wobble into an even thinner sliver of the
        # plot than it already is. Off the raw (unsmoothed) readings, not
        # the smoothed line -- the axis should always cover what was
        # actually observed, even where smoothing pulls the drawn line
        # itself a little short of a real spike.
        day_low, day_high = min(pressures), max(pressures)
        pad = 1.5
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

    # ---------- high / low markers ----------
    # Always on (unlike tempest-temp-chart's opt-in --mark-high/--mark-low)
    # -- there's only the one series here, so a day's high and low pressure
    # are always worth calling out, on both a same-day and an archive
    # chart. Marked against the raw (unsmoothed) readings, same as the
    # y-axis padding above -- the actual observed extreme, not a value
    # smoothing may have pulled slightly toward the mean, even though that
    # can leave the circle a hair off the (smoothed) drawn line itself.
    if times:
        low_idx = min(range(len(pressures)), key=lambda i: pressures[i])
        high_idx = max(range(len(pressures)), key=lambda i: pressures[i])

        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        ax_box = ax.get_window_extent(renderer)
        occupied = [logo_ax.get_window_extent(renderer)] if logo_ax is not None else []

        def mark_extreme(idx, color, prefix):
            t_val, v_val = times[idx], pressures[idx]
            ax.scatter([t_val], [v_val], s=160, facecolors="none", edgecolors=color,
                       linewidths=2.2, zorder=Z_MARKER)
            label_text = f"{prefix}: {v_val:.1f} mb at {t_val.strftime('%H:%M')}"

            def place(ha, va, x_off, y_off):
                # A solid white backing patch, not a path-effects stroke --
                # a stroke only outlines the letters, leaving the gaps
                # between/inside them transparent, so a gridline crossing
                # the label would still show through. See
                # tempest-wind-chart/README.md's peak-gust-label writeup
                # for how this was originally diagnosed.
                return ax.annotate(label_text, xy=(t_val, v_val), xytext=(x_off, y_off),
                                    textcoords="offset points", ha=ha, va=va,
                                    fontproperties=f_bold, fontsize=12, color=color, zorder=Z_MARKER,
                                    bbox=dict(facecolor="white", edgecolor="none", pad=2))

            # Above-first, same fallback order and reasoning as
            # tempest-wind-chart's always-on peak-gust marker.
            candidates = [
                ("left", "bottom", 15, 10),
                ("right", "bottom", -15, 10),
                ("left", "center", 15, -8),
                ("right", "center", -15, -8),
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

        mark_extreme(low_idx, LOW_COLOR, "Low")
        mark_extreme(high_idx, HIGH_COLOR, "High")

    # ---------- axes styling ----------
    ax.set_ylabel("Sea Level Pressure (mb)", fontproperties=f_med, fontsize=12, color=INK)
    ax.set_xlabel("Time", fontproperties=f_med, fontsize=12, color=INK)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f"))
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
    # chip's small colored background comes from interpolating
    # PRESSURE_COLOR_TABLE (Pa -> RGB control points, linearly
    # interpolated by interp_color()) against the reading converted from
    # mb to Pa, and the bold text itself is black or white via
    # text_color_for_bg()'s ITU-R BT.601 luminance check -- same
    # mechanism as the temp/wind charts' own stat boxes.
    if times and not args.no_current_conditions:
        current_pressure_mb = pressures[-1]

        stat_center_y = 0.685 + 0.105 / 2
        label_fontsize = 14
        label_linespacing = 0.85
        fig_w_px = fig.get_size_inches()[0] * fig.get_dpi()
        label_number_gap_px = 0.012 * fig_w_px

        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()

        label_text = "Current\nPressure"
        value_text = f"{current_pressure_mb:.1f} mb"

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

        rgb = interp_color(mb_to_pa(current_pressure_mb), PRESSURE_COLOR_TABLE)
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

        # Center the value chip itself on the figure's own horizontal
        # midpoint -- not the (label + gap + chip) pair as a single unit,
        # which would leave the chip (the number people actually look at)
        # off-center by half the label's width.
        chip_center_px = center_x * fig_w_px
        chip_left_visual_px = chip_center_px - chip_width_px / 2
        label_right_px = chip_left_visual_px - label_number_gap_px
        # anchor = desired visual left edge of the padded chip + pad_px,
        # since the chip's actual left edge sits pad_px left of the anchor.
        number_anchor_px = chip_left_visual_px + pad_px

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

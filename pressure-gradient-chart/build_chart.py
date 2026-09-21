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
from matplotlib.transforms import Bbox, blended_transform_factory

# ---------- fonts (same family as tempest-pressure-chart) ----------
FONT_DIR = "/usr/share/fonts/truetype/google-fonts/"
f_bold = fm.FontProperties(fname=FONT_DIR + "Poppins-Bold.ttf")
f_reg = fm.FontProperties(fname=FONT_DIR + "Poppins-Regular.ttf")
f_med = fm.FontProperties(fname=FONT_DIR + "Poppins-Medium.ttf")

# ---------- palette (same canvas/style as tempest-pressure-chart) ----------
BG = "#f7f6f2"
INK = "#2b2a26"
INK_SECONDARY = "#5a584f"
GRID_COLOR = "#000000"
AXIS_COLOR = "#000000"
ZERO_LINE_COLOR = "#5a584f"

# A distinct color from the tempest-pressure-chart family's green -- this
# chart plots a difference between two stations, not one station's own
# reading, so it gets its own hue rather than borrowing the single-station
# charts' green.
GRADIENT_COLOR = "#2c3e6b"

# Same red/blue high/low convention every sibling chart in this family
# uses for its day-high/day-low callouts.
HIGH_COLOR = "#a3242b"
LOW_COLOR = "#0b3d91"

# y-axis is always symmetric around 0 -- the zero line (and so the
# onshore/offshore split) stays vertically centered no matter what the
# data does, rather than drifting off-center whenever only one side
# overflows. Half-range is +-DEFAULT_Y_RANGE_MB by default, or the
# observed min/max magnitude padded by OVERFLOW_PAD_MB if that's bigger
# (e.g. an actual high of +6.4 mb pushes both sides out to +-8.4, not
# just the top to +8.4 while the bottom stays at the -8 floor).
DEFAULT_Y_RANGE_MB = 8.0
OVERFLOW_PAD_MB = 2.0

Z_GRID = 2
Z_ZERO = 3
Z_GRADIENT = 4
Z_MARKER = 5

# Both stations report roughly every 5 minutes (NWS specials, not just the
# hourly METAR) -- a gap much longer than that means one of them (or its
# feed) was actually down, not just a skipped sample.
MAX_GAP = timedelta(minutes=15)

# A short smoothing window sized for this chart's ~5-minute-cadence data
# (window=3 samples ~= 15 minutes) -- much shorter than tempest-pressure-
# chart's 15-sample window, which is tuned for that chart's ~1/minute
# Tempest cadence. Smooths sensor/reporting jitter without flattening the
# gradient's real swings.
SMOOTHING_WINDOW = 3

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def parse_args():
    ap = argparse.ArgumentParser(description="Render a multi-day pressure-gradient chart "
                                               "(station A minus station B pressure) for "
                                               "whichever window --data holds observations for.")
    ap.add_argument("--data", default="gradient_obs.json")
    ap.add_argument("--output", default="gradient_chart.png")
    return ap.parse_args()


def insert_gaps(times, values, max_gap):
    """Returns (times, values) with a NaN-valued point inserted at the
    midpoint of any consecutive pair more than max_gap apart -- matplotlib
    breaks a line at a NaN y-value rather than drawing a straight segment
    across it, so a real data outage shows as a visible gap instead of
    reading as continuous data."""
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
    whatever partial window is actually available rather than padding
    with NaN or truncating."""
    n = len(values)
    half = window // 2
    smoothed = []
    for i in range(n):
        window_vals = values[max(0, i - half):min(n, i + half + 1)]
        smoothed.append(sum(window_vals) / len(window_vals))
    return smoothed


def gradient_ylim(values):
    """Symmetric +-half_range, where half_range is the larger of
    DEFAULT_Y_RANGE_MB and the observed min/max magnitude padded by
    OVERFLOW_PAD_MB -- so a lopsided window (e.g. a +6.4 mb high with only
    a -0.3 mb low) still pushes *both* sides out to +-8.4, not just the
    +8.4 top while the bottom stays pinned at the -8 floor."""
    half_range = max(DEFAULT_Y_RANGE_MB, abs(min(values)) + OVERFLOW_PAD_MB, abs(max(values)) + OVERFLOW_PAD_MB)
    return -half_range, half_range


def build_chart(data_path, output_path):
    data = json.load(open(data_path))
    tz = ZoneInfo(data["timezone"])
    label_a, label_b = data["station_a"]["label"], data["station_b"]["label"]

    times = [datetime.fromisoformat(o["time"]) for o in data["observations"]]
    gradients = [o["gradient_mb"] for o in data["observations"]]

    window_start = datetime.fromisoformat(data["window_start"])
    window_days = data["window_days"]
    window_end = window_start + timedelta(days=window_days)

    # ---------- figure (same footprint as tempest-pressure-chart) ----------
    # Full 0.65 height -- no current-conditions stat box here to reserve
    # room for (this chart only ever renders a several-day window, not a
    # single still-updating "today", so there's no single "current"
    # reading to headline), same height tempest-pressure-chart's own
    # --no-current-conditions archive layout uses.
    fig = plt.figure(figsize=(12, 8.3), dpi=200)
    fig.patch.set_facecolor(BG)
    ax_height = 0.65
    ax = fig.add_axes([0.075, 0.10, 0.87, ax_height])
    ax.set_facecolor("white")

    axpos = ax.get_position()
    left_x, right_x, top_y = axpos.x0, axpos.x1, axpos.y1
    center_x = (axpos.x0 + axpos.x1) / 2

    gradient_line = None
    if times:
        smoothed_gradients = smooth(gradients, SMOOTHING_WINDOW)
        plot_times, plot_gradients = insert_gaps(times, smoothed_gradients, MAX_GAP)
        gradient_line = ax.plot(plot_times, plot_gradients, color=GRADIENT_COLOR, linewidth=2.6,
                                 zorder=Z_GRADIENT, label="Pressure gradient")[0]

        y_low, y_high = gradient_ylim(gradients)
        ax.set_ylim(y_low, y_high)
        # Right edge is the last observation itself, not the window's
        # calendar boundary -- the data runs all the way to the edge of
        # the plot, with "now" simply being wherever that edge falls,
        # rather than a dotted marker partway through empty space.
        ax.set_xlim(window_start, times[-1])
    else:
        ax.text(0.5, 0.5, "No observations in this window", transform=ax.transAxes,
                 ha="center", va="center", fontproperties=f_med, fontsize=13, color=INK_SECONDARY)
        y_low, y_high = -DEFAULT_Y_RANGE_MB, DEFAULT_Y_RANGE_MB
        ax.set_ylim(y_low, y_high)
        ax.set_xlim(window_start, window_end)

    # ---------- zero line + onshore/offshore labels ----------
    # A dotted reference line at 0 mb -- above it, station A (the west/
    # coastal side, PDX by default) is higher pressure than station B,
    # pushing air onshore through the gap between them; below it, station
    # B is higher, pushing air offshore. Pinned near the plot's left edge
    # (axes-fraction x, data-coordinate y) so the labels stay in the same
    # spot regardless of where the line itself happens to sit that day.
    ax.axhline(0, color=ZERO_LINE_COLOR, linewidth=1.3, linestyle=":", zorder=Z_ZERO)
    label_trans = blended_transform_factory(ax.transAxes, ax.transData)
    # A fixed mb offset, not a fraction of the y-range -- with the range
    # now generally +-8 mb (DEFAULT_Y_RANGE_MB) rather than scaling down
    # to the day's own tighter swing, a range-proportional offset would
    # push these labels much farther from the line than intended.
    label_offset = 0.2
    onshore_label = ax.text(0.014, label_offset, "Onshore Flow", transform=label_trans, ha="left", va="bottom",
                              fontproperties=f_med, fontsize=11, color=INK_SECONDARY, style="italic", zorder=Z_ZERO)
    offshore_label = ax.text(0.014, -label_offset, "Offshore Flow", transform=label_trans, ha="left", va="top",
                               fontproperties=f_med, fontsize=11, color=INK_SECONDARY, style="italic", zorder=Z_ZERO)

    # ---------- logo ----------
    # Same placement logic as tempest-pressure-chart: bottom-right by
    # default, moving to top-right if the gradient line's actual drawn
    # path would pass behind it there.
    LOGO_PATH = os.path.join(SCRIPT_DIR, "..", "assets", "ingalls_weather_logo.png")
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

        if gradient_line is not None:
            fig_w_px, fig_h_px = fig_w_in * dpi, fig_h_in * dpi
            pad_px = 6
            rect = Bbox.from_extents(logo_x0 * fig_w_px - pad_px, bottom_y0 * fig_h_px - pad_px,
                                      (logo_x0 + logo_width_fig) * fig_w_px + pad_px,
                                      (bottom_y0 + logo_height_fig) * fig_h_px + pad_px)
            display_path = gradient_line.get_transform().transform_path(gradient_line.get_path())
            if display_path.intersects_bbox(rect, filled=False):
                logo_y0 = top_y0

        logo_ax = fig.add_axes([logo_x0, logo_y0, logo_width_fig, logo_height_fig], zorder=20)
        logo_ax.imshow(logo_img)
        logo_ax.axis("off")
    else:
        print(f"NOTE: no logo found at {LOGO_PATH} -- skipping logo placement.")

    # ---------- high / low markers ----------
    # Always on, same reasoning as tempest-pressure-chart -- there's only
    # the one series here, so the day's most-onshore and most-offshore
    # reading are always worth calling out. Marked against the raw
    # (unsmoothed) readings, same as the y-axis padding above.
    if times:
        low_idx = min(range(len(gradients)), key=lambda i: gradients[i])
        high_idx = max(range(len(gradients)), key=lambda i: gradients[i])

        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        ax_box = ax.get_window_extent(renderer)
        occupied = [onshore_label.get_window_extent(renderer), offshore_label.get_window_extent(renderer)]
        if logo_ax is not None:
            occupied.append(logo_ax.get_window_extent(renderer))
        # The line's own drawn path, not just other labels/the logo -- an
        # extreme is a point ON the line, so the line keeps running right
        # past it in both directions, and a label offset that clears every
        # other label can still land right on top of (or hugging right up
        # against) the line itself a little further along.
        line_paths = [gradient_line.get_transform().transform_path(gradient_line.get_path())] \
            if gradient_line is not None else []

        def mark_extreme(idx, color, prefix):
            t_val, v_val = times[idx], gradients[idx]
            ax.scatter([t_val], [v_val], s=160, facecolors="none", edgecolors=color,
                       linewidths=2.2, zorder=Z_MARKER)
            label_text = f"{prefix}: {v_val:+.1f} mb at {t_val.strftime('%H:%M')}"

            def place(ha, va, x_off, y_off):
                return ax.annotate(label_text, xy=(t_val, v_val), xytext=(x_off, y_off),
                                    textcoords="offset points", ha=ha, va=va,
                                    fontproperties=f_bold, fontsize=12, color=color, zorder=Z_MARKER,
                                    bbox=dict(facecolor="white", edgecolor="none", pad=2))

            # Larger offsets than tempest-pressure-chart's own four -- that
            # chart's single-station line is far smoother, so a modest
            # offset almost always clears it; this chart's noisier,
            # closer-together wiggles need more clearance to reliably miss
            # the line on the first few tries.
            candidates = [
                ("left", "bottom", 15, 12),
                ("right", "bottom", -15, 12),
                ("left", "top", 15, -12),
                ("right", "top", -15, -12),
                ("left", "bottom", 15, 30),
                ("right", "bottom", -15, 30),
                ("left", "top", 15, -30),
                ("right", "top", -15, -30),
            ]
            txt = None
            best_placement, best_overlap = None, None
            for ha, va, x_off, y_off in candidates:
                if txt is not None:
                    txt.remove()
                txt = place(ha, va, x_off, y_off)
                fig.canvas.draw()
                txt_box = txt.get_window_extent(renderer)
                fits = (ax_box.xmin <= txt_box.xmin and txt_box.xmax <= ax_box.xmax
                        and ax_box.ymin <= txt_box.ymin and txt_box.ymax <= ax_box.ymax)
                on_line = any(p.intersects_bbox(txt_box, filled=False) for p in line_paths)
                overlap = sum(max(0, min(txt_box.xmax, b.xmax) - max(txt_box.xmin, b.xmin))
                              * max(0, min(txt_box.ymax, b.ymax) - max(txt_box.ymin, b.ymin))
                              for b in occupied)
                if fits and not on_line and overlap == 0:
                    break
                if fits and not on_line and (best_overlap is None or overlap < best_overlap):
                    best_placement, best_overlap = (ha, va, x_off, y_off), overlap
            else:
                # No candidate was in-bounds, clear of the line, AND fully
                # clear of other labels -- redraw whichever in-bounds,
                # off-the-line candidate overlapped other labels least,
                # rather than leaving whatever the last-tried one was.
                if best_placement is not None:
                    txt.remove()
                    txt = place(*best_placement)
                    fig.canvas.draw()
            occupied.append(txt.get_window_extent(renderer))

        mark_extreme(low_idx, LOW_COLOR, "Low")
        mark_extreme(high_idx, HIGH_COLOR, "High")

    # ---------- axes styling ----------
    ax.set_ylabel(f"{label_a} − {label_b} Pressure (mb)", fontproperties=f_med, fontsize=12, color=INK)
    ax.set_xlabel("Time", fontproperties=f_med, fontsize=12, color=INK)
    # Explicit +/- sign on every tick except 0 itself -- the sign is the
    # point of this chart (unlike a plain pressure reading), but "+0"
    # reads oddly for the one tick that has no sign to show.
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: "0" if v == 0 else f"{v:+.0f}"))
    ax.set_axisbelow(False)
    ax.grid(axis="y", color=GRID_COLOR, alpha=0.25, linewidth=0.9, zorder=Z_GRID)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(AXIS_COLOR)
        ax.spines[spine].set_linewidth(1.0)

    # Every 12 hours (2 ticks/day) with a date+time label -- a 3-day (or
    # longer) window needs the date on every tick, unlike a single-day
    # chart's bare "%H:%M", since "00:00" alone no longer identifies which
    # day it falls on.
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=12, tz=tz))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%-m/%-d %Hh", tz=tz))
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
    # Derived from top_y (axpos.y1), same as tempest-pressure-chart's own
    # --no-current-conditions archive-day charts -- there's no stat-box
    # band below to reserve a fixed gap for, since this chart never draws
    # one.
    subtitle_y = top_y + 0.058
    title_y = subtitle_y + 0.035
    last_day_str = window_end - timedelta(days=1)
    date_range = f"{window_start.strftime('%B %-d')} – {last_day_str.strftime('%B %-d, %Y')}"
    title = f"Pressure Gradient — {label_a}–{label_b}"
    subtitle = f"{date_range} • {times[-1].strftime('%H:%M')} PT" if times else date_range
    fig.text(left_x, title_y, title, fontproperties=f_bold, fontsize=22, color=INK)
    fig.text(left_x, subtitle_y, subtitle, fontproperties=f_reg, fontsize=12, color=INK_SECONDARY)

    # ---------- attribution ----------
    fig.text(center_x, 0.02, "Ingalls Weather",
              fontproperties=f_reg, fontsize=9, color=INK_SECONDARY, ha="center")

    plt.savefig(output_path, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    print(f"saved {output_path}")


def main():
    args = parse_args()
    build_chart(args.data, args.output)


if __name__ == "__main__":
    main()

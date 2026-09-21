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

# ---------- current-conditions stat chip ----------
# Diverging around 0 mb (unlike tempest-pressure-chart's PRESSURE_COLOR_TABLE,
# which ramps across absolute station pressure) -- warm/orange for a
# negative (offshore, station B higher) gradient and blue for a positive
# (onshore, station A higher) one, since this is a signed difference, not
# an absolute reading. +-6 mb comfortably covers the range this gradient
# typically swings across; interp_color() clamps beyond it.
GRADIENT_COLOR_TABLE = [
    (-6, (140, 40, 8)),
    (-3, (214, 108, 39)),
    (-1, (240, 189, 150)),
    (0, (237, 236, 230)),
    (1, (177, 202, 228)),
    (3, (61, 116, 178)),
    (6, (20, 59, 110)),
]

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


def text_color_for_bg(rgb):
    """Black or white, whichever reads better against an (R, G, B) 0-255
    background -- ITU-R BT.601 perceptual luminance, the standard
    black/white text contrast heuristic."""
    r, g, b = rgb
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return "black" if luminance > 140 else "white"


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
    ap = argparse.ArgumentParser(description="Render a same-day pressure-gradient chart "
                                               "(station A minus station B sea-level pressure) "
                                               "for whichever day --data holds observations for.")
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


def build_chart(data_path, output_path):
    data = json.load(open(data_path))
    tz = ZoneInfo(data["timezone"])
    label_a, label_b = data["station_a"]["label"], data["station_b"]["label"]

    times = [datetime.fromisoformat(o["time"]) for o in data["observations"]]
    gradients = [o["gradient_mb"] for o in data["observations"]]

    day_start = datetime.fromisoformat(data["date"]).replace(tzinfo=tz)
    day_end = day_start + timedelta(days=1)

    # ---------- figure (same footprint as tempest-pressure-chart) ----------
    fig = plt.figure(figsize=(12, 8.3), dpi=200)
    fig.patch.set_facecolor(BG)
    ax_height = 0.56
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

        # Dotted marker at the last observation -- same reasoning as
        # tempest-pressure-chart's own "still live today" marker.
        ax.axvline(times[-1], color=AXIS_COLOR, linewidth=1.0, linestyle=":", zorder=Z_GRID)

        # Pad the day's raw (unsmoothed) range the same way tempest-
        # pressure-chart does, but also guarantee at least +-2.5 mb of
        # room around 0 either way -- the zero line and its onshore/
        # offshore labels need that space even on a day the gradient
        # never actually crosses sign.
        day_low, day_high = min(gradients), max(gradients)
        pad = 1.5
        min_half_range = 2.5
        y_low = min(day_low - pad, -min_half_range)
        y_high = max(day_high + pad, min_half_range)
        ax.set_ylim(y_low, y_high)
        ax.set_xlim(day_start, day_end)
    else:
        ax.text(0.5, 0.5, "No observations yet today", transform=ax.transAxes,
                 ha="center", va="center", fontproperties=f_med, fontsize=13, color=INK_SECONDARY)
        y_low, y_high = -2.5, 2.5
        ax.set_ylim(y_low, y_high)
        ax.set_xlim(day_start, day_end)

    # ---------- zero line + onshore/offshore labels ----------
    # A dotted reference line at 0 mb -- above it, station A (the west/
    # coastal side, PDX by default) is higher pressure than station B,
    # pushing air onshore through the gap between them; below it, station
    # B is higher, pushing air offshore. Pinned near the plot's left edge
    # (axes-fraction x, data-coordinate y) so the labels stay in the same
    # spot regardless of where the line itself happens to sit that day.
    ax.axhline(0, color=ZERO_LINE_COLOR, linewidth=1.3, linestyle=":", zorder=Z_ZERO)
    label_trans = blended_transform_factory(ax.transAxes, ax.transData)
    label_offset = 0.06 * (y_high - y_low)
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
    subtitle_y = 0.815
    title_y = subtitle_y + 0.035
    title = f"Today's Pressure Gradient — {label_a}–{label_b}"
    subtitle = f"{date_str} • Updated: {times[-1].strftime('%H:%M')} PT" if times else date_str
    fig.text(left_x, title_y, title, fontproperties=f_bold, fontsize=22, color=INK)
    fig.text(left_x, subtitle_y, subtitle, fontproperties=f_reg, fontsize=12, color=INK_SECONDARY)

    # ---------- current-conditions stat box ----------
    # Same single-stat, centered-chip layout as tempest-pressure-chart's
    # own current-conditions box, just fed from GRADIENT_COLOR_TABLE (a
    # diverging-around-0 table, not an absolute-pressure ramp) via the
    # same interp_color()/text_color_for_bg() mechanism.
    if times:
        current_gradient = gradients[-1]

        stat_center_y = 0.685 + 0.105 / 2
        label_fontsize = 14
        label_linespacing = 0.85
        fig_w_px = fig.get_size_inches()[0] * fig.get_dpi()
        label_number_gap_px = 0.012 * fig_w_px

        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()

        label_text = "Current\nGradient"
        value_text = f"{current_gradient:+.1f} mb"

        label_probe = fig.text(0, stat_center_y, label_text, fontproperties=f_reg,
                                 fontsize=label_fontsize, linespacing=label_linespacing)
        fig.canvas.draw()
        label_probe.remove()

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

        rgb = interp_color(current_gradient, GRADIENT_COLOR_TABLE)
        text_color = text_color_for_bg(rgb)
        chip_color = tuple(c / 255 for c in rgb)

        chip_pad = 0.35
        chip_kwargs = dict(fontproperties=f_bold, fontsize=number_fontsize, color=text_color,
                            va="center", bbox=dict(boxstyle=f"round,pad={chip_pad}",
                                                    facecolor=chip_color, edgecolor="none"))
        num_probe2 = fig.text(0, stat_center_y, value_text, ha="left", **chip_kwargs)
        fig.canvas.draw()
        text_width_px = num_probe2.get_window_extent(renderer).width
        num_probe2.remove()
        pad_px = chip_pad * number_fontsize * (fig.get_dpi() / 72)
        chip_width_px = text_width_px + 2 * pad_px

        chip_center_px = center_x * fig_w_px
        chip_left_visual_px = chip_center_px - chip_width_px / 2
        label_right_px = chip_left_visual_px - label_number_gap_px
        number_anchor_px = chip_left_visual_px + pad_px

        fig.text(label_right_px / fig_w_px, stat_center_y, label_text, fontproperties=f_reg,
                  fontsize=label_fontsize, color=INK, ha="right", va="center",
                  linespacing=label_linespacing, multialignment="right")
        fig.text(number_anchor_px / fig_w_px, stat_center_y, value_text, ha="left",
                  zorder=15, **chip_kwargs)

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

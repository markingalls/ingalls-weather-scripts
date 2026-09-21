import argparse
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
from matplotlib.transforms import blended_transform_factory

# Reuses fonts, palette, sizing constants, and the gap/smoothing helpers
# directly from build_chart.py -- this is the same chart family (same
# canvas, same zero-line/onshore-offshore/high-low mechanics), just with
# an observed+forecast split instead of observed-only, so duplicating all
# of that here would just be a maintenance hazard.
from build_chart import (
    AXIS_COLOR, BG, DEFAULT_Y_RANGE_MB, GRADIENT_COLOR, GRID_COLOR, HIGH_COLOR, INK,
    INK_SECONDARY, LOW_COLOR, MAX_GAP, SMOOTHING_WINDOW, Z_GRADIENT, Z_GRID,
    Z_MARKER, Z_ZERO, ZERO_LINE_COLOR, f_bold, f_med, f_reg, gradient_ylim, insert_gaps,
    place_logo, smooth,
)


def parse_args():
    ap = argparse.ArgumentParser(description="Render a pressure-gradient chart combining "
                                               "the past day's NWS-observed gradient (solid) "
                                               "with a WindBorne MetaMesh forecast (dashed).")
    ap.add_argument("--data", default="gradient_forecast.json")
    ap.add_argument("--output", default="gradient_forecast_chart.png")
    return ap.parse_args()


def build_forecast_chart(data_path, output_path):
    data = json.load(open(data_path))
    tz = ZoneInfo(data["timezone"])
    label_a, label_b = data["station_a"]["label"], data["station_b"]["label"]

    all_obs = data["observations"]
    times = [datetime.fromisoformat(o["time"]) for o in all_obs]
    gradients = [o["gradient_mb"] for o in all_obs]
    is_forecast = [o["is_forecast"] for o in all_obs]

    obs_times = [t for t, f in zip(times, is_forecast) if not f]
    obs_gradients = [g for g, f in zip(gradients, is_forecast) if not f]
    fc_times = [t for t, f in zip(times, is_forecast) if f]
    fc_gradients = [g for g, f in zip(gradients, is_forecast) if f]

    window_start = datetime.fromisoformat(data["window_start"])
    window_end = datetime.fromisoformat(data["window_end"])
    now = datetime.fromisoformat(data["now"])

    # ---------- figure (same footprint as build_chart.py) ----------
    fig = plt.figure(figsize=(12, 8.3), dpi=200)
    fig.patch.set_facecolor(BG)
    ax_height = 0.65
    ax = fig.add_axes([0.075, 0.10, 0.87, ax_height])
    ax.set_facecolor("white")

    axpos = ax.get_position()
    left_x, top_y = axpos.x0, axpos.y1
    center_x = (axpos.x0 + axpos.x1) / 2

    gradient_line = None
    fc_line = None
    line_paths = []
    if times:
        # Observed: smoothed the same way build_chart.py's single-series
        # chart is (NWS's ~5-minute cadence is noisy at this scale).
        # Forecast: left raw -- MetaMesh's hourly cadence is already
        # coarse enough that a 3-sample moving average would just blur
        # real hour-to-hour model detail rather than remove noise.
        if obs_times:
            smoothed_obs = smooth(obs_gradients, SMOOTHING_WINDOW)
            plot_obs_times, plot_obs_gradients = insert_gaps(obs_times, smoothed_obs, MAX_GAP)
            gradient_line = ax.plot(plot_obs_times, plot_obs_gradients, color=GRADIENT_COLOR,
                                     linewidth=2.6, zorder=Z_GRADIENT, label="Observed")[0]

        if fc_times:
            # Prepend the last observed point so the dashed segment
            # visually connects to the solid one with no gap at the
            # boundary, same idea as tri-cities-temp-chart's own
            # observed/forecast handoff.
            boundary_times = ([obs_times[-1]] + fc_times) if obs_times else fc_times
            boundary_gradients = ([obs_gradients[-1]] + fc_gradients) if obs_gradients else fc_gradients
            fc_line = ax.plot(boundary_times, boundary_gradients, color=GRADIENT_COLOR, linewidth=2.6,
                               linestyle="--", dashes=(5, 2.5), zorder=Z_GRADIENT, label="MetaMesh Forecast")[0]

        # Both lines' own drawn paths -- checked below by place_logo() and
        # mark_extreme() alike, so neither ever lands on top of either
        # line. An earlier version only ever checked `gradient_line`
        # (whichever of the two got assigned to it), silently never
        # checking the other.
        line_paths = [ln.get_transform().transform_path(ln.get_path())
                      for ln in (gradient_line, fc_line) if ln is not None]

        # Dotted marker at "now" -- the observed/forecast boundary. Unlike
        # build_chart.py's observed-only chart (where "now" is simply the
        # right edge of the plot), this chart keeps drawing past it into
        # the forecast, so the boundary still needs an explicit marker.
        ax.axvline(now, color=AXIS_COLOR, linewidth=1.0, linestyle=":", zorder=Z_GRID)

        y_low, y_high = gradient_ylim(gradients)
        ax.set_ylim(y_low, y_high)
        ax.set_xlim(window_start, window_end)
    else:
        ax.text(0.5, 0.5, "No observations or forecast in this window", transform=ax.transAxes,
                 ha="center", va="center", fontproperties=f_med, fontsize=13, color=INK_SECONDARY)
        y_low, y_high = -DEFAULT_Y_RANGE_MB, DEFAULT_Y_RANGE_MB
        ax.set_ylim(y_low, y_high)
        ax.set_xlim(window_start, window_end)

    # ---------- zero line + onshore/offshore labels ----------
    ax.axhline(0, color=ZERO_LINE_COLOR, linewidth=1.3, linestyle=":", zorder=Z_ZERO)
    label_trans = blended_transform_factory(ax.transAxes, ax.transData)
    label_offset = 0.2  # fixed mb offset -- see build_chart.py's own comment on this
    onshore_label = ax.text(0.014, label_offset, "Onshore Flow", transform=label_trans, ha="left", va="bottom",
                              fontproperties=f_med, fontsize=11, color=INK_SECONDARY, style="italic", zorder=Z_ZERO)
    offshore_label = ax.text(0.014, -label_offset, "Offshore Flow", transform=label_trans, ha="left", va="top",
                               fontproperties=f_med, fontsize=11, color=INK_SECONDARY, style="italic", zorder=Z_ZERO)

    # ---------- logo ----------
    # line_paths (both the observed and forecast lines' own drawn paths,
    # computed above) -- an earlier version of this only ever checked
    # `gradient_line` (whichever of the two happened to be assigned to
    # it), silently never checking the other.
    logo_ax, logo_bbox = place_logo(fig, axpos, line_paths)

    # ---------- high / low markers (across the full observed+forecast window) ----------
    if times:
        low_idx = min(range(len(gradients)), key=lambda i: gradients[i])
        high_idx = max(range(len(gradients)), key=lambda i: gradients[i])

        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        ax_box = ax.get_window_extent(renderer)
        occupied = [onshore_label.get_window_extent(renderer), offshore_label.get_window_extent(renderer)]
        if logo_bbox is not None:
            occupied.append(logo_bbox)
        # line_paths is also checked below -- an extreme is a point ON one
        # of the lines, so that line keeps running right past it in both
        # directions, and a label offset that clears every other label can
        # still land right on top of (or hugging right up against) the
        # line itself a little further along.

        def mark_extreme(idx, color, prefix):
            t_val, v_val = times[idx], gradients[idx]
            ax.scatter([t_val], [v_val], s=160, facecolors="none", edgecolors=color,
                       linewidths=2.2, zorder=Z_MARKER)
            label_text = f"{prefix}: {v_val:+.1f} mb at {t_val.strftime('%-m/%-d %H:%M')}"

            def place(ha, va, x_off, y_off):
                return ax.annotate(label_text, xy=(t_val, v_val), xytext=(x_off, y_off),
                                    textcoords="offset points", ha=ha, va=va,
                                    fontproperties=f_bold, fontsize=12, color=color, zorder=Z_MARKER,
                                    bbox=dict(facecolor="white", edgecolor="none", pad=2))

            # More, and larger-offset, fallbacks beyond build_chart.py's
            # own eight -- this chart's forecast segment often puts its
            # extreme right at the window's last point, in the
            # bottom-right corner the logo already claims, where none of
            # the tighter offsets clear both the logo and the line.
            candidates = [
                ("left", "bottom", 15, 12),
                ("right", "bottom", -15, 12),
                ("left", "top", 15, -12),
                ("right", "top", -15, -12),
                ("left", "bottom", 15, 30),
                ("right", "bottom", -15, 30),
                ("left", "top", 15, -30),
                ("right", "top", -15, -30),
                ("right", "bottom", -15, 50),
                ("right", "top", -15, -50),
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
                # No candidate was in-bounds, clear of both lines, AND
                # fully clear of other labels -- redraw whichever
                # in-bounds, off-the-line candidate overlapped other
                # labels least, rather than leaving whatever the
                # last-tried one was.
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
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: "0" if v == 0 else f"{v:+.0f}"))
    ax.set_axisbelow(False)
    ax.grid(axis="y", color=GRID_COLOR, alpha=0.25, linewidth=0.9, zorder=Z_GRID)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(AXIS_COLOR)
        ax.spines[spine].set_linewidth(1.0)

    ax.xaxis.set_major_locator(mdates.HourLocator(interval=12, tz=tz))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%-m/%-d %Hh", tz=tz))
    ax.tick_params(axis="both", colors=AXIS_COLOR, labelsize=10, length=4)
    for tick in ax.get_xticklabels():
        tick.set_fontproperties(f_reg)
        tick.set_color(INK_SECONDARY)
        tick.set_fontsize(9)
    for tick in ax.get_yticklabels():
        tick.set_fontproperties(f_reg)
        tick.set_color(INK_SECONDARY)
        tick.set_fontsize(10)

    # ---------- title / subtitle ----------
    subtitle_y = top_y + 0.058
    title_y = subtitle_y + 0.035
    title = f"Pressure Gradient — {label_a}–{label_b}"
    subtitle = f"Observed + MetaMesh Forecast • {now.strftime('%H:%M')} PT"
    fig.text(left_x, title_y, title, fontproperties=f_bold, fontsize=22, color=INK)
    fig.text(left_x, subtitle_y, subtitle, fontproperties=f_reg, fontsize=12, color=INK_SECONDARY)

    # ---------- legend (solid vs dashed needs a key, unlike the single-series chart) ----------
    if obs_times and fc_times:
        ax.legend(loc="lower right", bbox_to_anchor=(1.0, 1.01), ncol=2, frameon=False,
                   prop=f_reg, fontsize=10, labelcolor=INK_SECONDARY)

    # ---------- attribution ----------
    fig.text(center_x, 0.02, "Ingalls Weather",
              fontproperties=f_reg, fontsize=9, color=INK_SECONDARY, ha="center")

    plt.savefig(output_path, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    print(f"saved {output_path}")


def main():
    args = parse_args()
    build_forecast_chart(args.data, args.output)


if __name__ == "__main__":
    main()

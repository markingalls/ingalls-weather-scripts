"""
RRFS low-level wind cross section -- renderer
Ingalls Weather

Renders cross_section.json (see fetch_cross_section.py) into a styled
height-vs-distance cross section: wind speed shaded with the same color
table as the Tempest station wind chart (tempest-wind-chart/build_chart.py's
WIND_COLOR_TABLE), wind barbs for direction, and model terrain filled in
along the bottom. Only the layer from the ground up to the 700 mb surface is
shown. Vertical scale is heavily exaggerated (the section is ~70 mi long and
~2 mi tall) -- the exaggeration factor is printed in the footer.
"""

import argparse
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
from matplotlib.colors import BoundaryNorm, ListedColormap
import numpy as np

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
TERRAIN_FILL = "#4a3b2a"     # dark earth brown, reads against every wind color
TERRAIN_EDGE = "#1f1810"
BARB_COLOR = "#111111"
HALO = [pe.withStroke(linewidth=3, foreground="white")]

Z_SHADE = 1
Z_ISOBAR = 2
Z_BARBS = 3
Z_INVERSION = 4
Z_TERRAIN = 5
Z_LABEL = 6

PACIFIC = ZoneInfo("America/Los_Angeles")

M_TO_FT = 3.28084
KM_TO_MI = 0.621371
MS_TO_MPH = 2.23694
MS_TO_KT = 1.94384

# Same table as tempest-wind-chart/build_chart.py (the weather station wind
# chart's stat-box colors) -- (m/s, (R, G, B)) control points, linearly
# interpolated by interp_color(). Kept in the source table's own m/s units;
# converted to mph only for the shading bins and colorbar labels.
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

# Shading bins, mph. Low-level winds rarely exceed 100 mph, so the bins stop
# there (an "extend max" arrow covers anything higher) rather than spanning
# the whole table out to 300 mph and squashing the useful range.
SPEED_BINS_MPH = np.arange(0, 102.5, 2.5)

VERT_RES_FT = 25        # regridding resolution for the shaded field
BARB_SPACING_MI = 4.0
BARB_SPACING_FT = 1000
LABEL_STRIP_FT = 900     # below-sea-level ground strip holding town labels
TOWN_MIN_SEP_MI = 6.0
END_LABEL_WIDTH_MI = 6.0  # rough width of the Irrigon/Tollgate corner labels

INVERSION_COLOR = "#0b3d91"   # dark blue, same as hrrr-smoke-chart's second line
INVERSION_MIN_STRENGTH_C = 1.0  # warm layer must be this much warmer than 2 m
INVERSION_TOP_TOL_C = 0.5       # near-isothermal cap counts as part of the inversion
INVERSION_SMOOTH_PTS = 9        # ~4 km running mean along the section
INVERSION_MAX_MIXING_MPH = 30   # layer-mean wind at/above this mixes the inversion out


def interp_color(value, table):
    if value <= table[0][0]:
        return table[0][1]
    if value >= table[-1][0]:
        return table[-1][1]
    for (x0, c0), (x1, c1) in zip(table, table[1:]):
        if x0 <= value <= x1:
            frac = (value - x0) / (x1 - x0)
            return tuple(c0[i] + frac * (c1[i] - c0[i]) for i in range(3))
    return table[-1][1]


def wind_cmap():
    mids = (SPEED_BINS_MPH[:-1] + SPEED_BINS_MPH[1:]) / 2
    colors = [tuple(c / 255 for c in interp_color(m / MS_TO_MPH, WIND_COLOR_TABLE)) for m in mids]
    cmap = ListedColormap(colors)
    over = interp_color(SPEED_BINS_MPH[-1] / MS_TO_MPH, WIND_COLOR_TABLE)
    cmap.set_over(tuple(c / 255 for c in over))
    return cmap, BoundaryNorm(SPEED_BINS_MPH, cmap.N)


def parse_args():
    ap = argparse.ArgumentParser(description="Render an RRFS low-level wind cross section.")
    ap.add_argument("--data", default="cross_section.json")
    ap.add_argument("--output", default=None,
                     help="defaults to rrfs_wind_cross_section_<valid>.png")
    return ap.parse_args()


def regrid_columns(d, z_ft):
    """Interpolates u/v (separately -- interpolating speed would let a
    direction change through a layer read as a fake speed minimum) from each
    column's pressure levels onto a regular height grid. Each column's
    lowest point is the 10 m wind; pressure levels at or below the model
    ground (RRFS extrapolates them underground) are dropped. Returns
    (u, v) in m/s, shape (len(z_ft), n_columns), NaN below ground / above
    the column's 700 mb height."""
    sfc = np.array(d["surface_height_m"])
    hgt = np.array(d["height_m"])          # (level, col), 1000 mb first
    u = np.array(d["u_ms"])
    v = np.array(d["v_ms"])
    u10, v10 = np.array(d["u10_ms"]), np.array(d["v10_ms"])
    z_m = z_ft / M_TO_FT
    U = np.full((len(z_m), len(sfc)), np.nan)
    V = np.full_like(U, np.nan)
    for j in range(len(sfc)):
        above = hgt[:, j] > sfc[j] + 10
        zc = np.concatenate([[sfc[j] + 10], hgt[above, j]])
        uc = np.concatenate([[u10[j]], u[above, j]])
        vc = np.concatenate([[v10[j]], v[above, j]])
        ok = (z_m >= sfc[j]) & (z_m <= zc[-1])
        # Ground to 10 m: hold the 10 m wind (keeps the shading flush
        # against the terrain instead of leaving a 10 m sliver).
        U[ok, j] = np.interp(z_m[ok], zc, uc)
        V[ok, j] = np.interp(z_m[ok], zc, vc)
    return U, V


def inversion_top_ft(d):
    """Top of the low-level inversion in each column, ft MSL (NaN where
    there isn't one). Each column's profile is the 2 m temperature plus
    every pressure level above ground, interpolated to 10 m steps. The
    inversion is the warm layer above the ground: its warmest point must be
    at least INVERSION_MIN_STRENGTH_C warmer than 2 m, and its top is the
    highest height (below the next cooling-with-height layer) still within
    INVERSION_TOP_TOL_C of that warmest temperature -- so a near-isothermal
    cap on top of the warm nose counts toward the depth, as it would on a
    sounding. Only the lowest warm layer counts: the search stops at the
    first height where the profile has cooled 2 C below the warmest point."""
    sfc = np.array(d["surface_height_m"])
    hgt = np.array(d["height_m"])
    tmp = np.array(d["t_c"])
    t2 = np.array(d["t2m_c"])
    out = np.full(len(sfc), np.nan)
    for j in range(len(sfc)):
        above = hgt[:, j] > sfc[j] + 2
        zc = np.concatenate([[sfc[j] + 2], hgt[above, j]])
        tc = np.concatenate([[t2[j]], tmp[above, j]])
        z = np.arange(zc[0], zc[-1], 10.0)
        t = np.interp(z, zc, tc)
        run_max, i_max, i_end = -np.inf, 0, len(t)
        for i, ti in enumerate(t):
            if ti > run_max:
                run_max, i_max = ti, i
            elif run_max - ti > 2.0:
                i_end = i
                break
        if run_max - t2[j] < INVERSION_MIN_STRENGTH_C:
            continue
        seg = t[i_max:i_end]
        top = i_max + np.where(seg >= run_max - INVERSION_TOP_TOL_C)[0].max()
        out[j] = z[top] * M_TO_FT
    return out


def smooth_nan(y, n):
    """Centered running mean that leaves NaN gaps (no-inversion columns) as
    gaps instead of smearing them."""
    out = np.full_like(y, np.nan)
    h = n // 2
    for i in range(len(y)):
        if np.isfinite(y[i]):
            out[i] = np.nanmean(y[max(0, i - h):i + h + 1])
    return out


def main():
    args = parse_args()
    d = json.load(open(args.data))

    init_time = datetime.fromisoformat(d["initialization_time"].replace("Z", "+00:00"))
    valid_time = datetime.fromisoformat(d["valid_time"].replace("Z", "+00:00"))
    valid_local = valid_time.astimezone(PACIFIC)

    x_mi = np.array(d["distance_km"]) * KM_TO_MI
    sfc_ft = np.array(d["surface_height_m"]) * M_TO_FT
    hgt_ft = np.array(d["height_m"]) * M_TO_FT
    top_ft = hgt_ft[-1].min()   # lowest point of the 700 mb surface -- cap the chart there

    z_ft = np.arange(0, top_ft + VERT_RES_FT, VERT_RES_FT)
    U, V = regrid_columns(d, z_ft)
    speed_mph = np.hypot(U, V) * MS_TO_MPH

    # ---------- figure (same footprint as the other Ingalls Weather charts) ----------
    fig = plt.figure(figsize=(12, 8.3), dpi=200)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0.075, 0.14, 0.80, 0.65])
    ax.set_facecolor("white")

    cmap, norm = wind_cmap()
    mesh = ax.pcolormesh(x_mi, z_ft, np.ma.masked_invalid(speed_mph), cmap=cmap, norm=norm,
                         shading="nearest", zorder=Z_SHADE, rasterized=True)

    # ---------- inversion top ----------
    inv_raw = inversion_top_ft(d)
    # Mechanical mixing: drop columns where the layer-mean wind from the
    # ground up to the inversion top is strong enough that the model's
    # inversion likely wouldn't survive (e.g. the downslope jet on the Blues).
    for j in np.where(np.isfinite(inv_raw))[0]:
        layer = (z_ft >= sfc_ft[j]) & (z_ft <= inv_raw[j])
        if np.nanmean(speed_mph[layer, j]) >= INVERSION_MAX_MIXING_MPH:
            inv_raw[j] = np.nan
    inv_ft = smooth_nan(inv_raw, INVERSION_SMOOTH_PTS)
    inv_x = x_mi.copy()
    # Mountain end: the Basin cold pool's top is held level from its lowest
    # point (the dip near Adams on the default section) out to where that
    # height meets the slope, instead of following the model's jumpier
    # columns over the foothills. That's the layer that keeps the
    # downslope jet off the Basin floor, so it's what the line is for.
    ok = np.where(np.isfinite(inv_ft))[0]
    if len(ok):
        j0 = ok[np.argmin(inv_ft[ok])]
        cap = inv_ft[j0]
        hit = np.where((np.arange(len(sfc_ft)) > j0) & (sfc_ft >= cap))[0]
        j_hit = hit[0] if len(hit) else len(sfc_ft)
        inv_ft[j0 + 1:] = np.nan
        inv_ft[j0 + 1:j_hit] = cap
        if len(hit):
            # End exactly on the terrain line, not at the last sample before it.
            frac = (cap - sfc_ft[j_hit - 1]) / (sfc_ft[j_hit] - sfc_ft[j_hit - 1])
            inv_x[j_hit] = x_mi[j_hit - 1] + frac * (x_mi[j_hit] - x_mi[j_hit - 1])
            inv_ft[j_hit] = cap
    ax.plot(inv_x, inv_ft, color=INVERSION_COLOR, linewidth=2.0, linestyle=(0, (6, 3.5)),
            zorder=Z_INVERSION, path_effects=[pe.withStroke(linewidth=4.2, foreground="white")])
    ok = np.where(np.isfinite(inv_ft))[0]
    if len(ok):
        # Bold, white-haloed label above the line, a fifth of the way in,
        # over the Basin -- clear of the end labels and the barb columns.
        j = ok[len(ok) // 5]
        ax.text(x_mi[j], inv_ft[j] + 200, "Inversion top", ha="center", va="bottom",
                fontproperties=f_bold, fontsize=11, color=INVERSION_COLOR, zorder=Z_LABEL,
                path_effects=[pe.withStroke(linewidth=3.5, foreground="white")])

    # ---------- wind barbs (knots, meteorological convention) ----------
    bx = np.arange(BARB_SPACING_MI / 2, x_mi[-1], BARB_SPACING_MI)
    bz = np.arange(BARB_SPACING_FT / 2, top_ft - 200, BARB_SPACING_FT)
    BX, BZ, BU, BV = [], [], [], []
    for xb in bx:
        j = int(np.abs(x_mi - xb).argmin())
        for zb in bz:
            if zb < sfc_ft[j] + 250:
                continue
            i = int(np.abs(z_ft - zb).argmin())
            if np.isfinite(U[i, j]):
                BX.append(x_mi[j]); BZ.append(z_ft[i])
                BU.append(U[i, j] * MS_TO_KT); BV.append(V[i, j] * MS_TO_KT)
    ax.barbs(BX, BZ, BU, BV, length=5.6, linewidth=0.9, color=BARB_COLOR, zorder=Z_BARBS,
             path_effects=[pe.withStroke(linewidth=2.2, foreground="white")])

    # ---------- terrain ----------
    # The terrain fill runs below sea level into a solid "ground strip"
    # (LABEL_STRIP_FT) that holds the town labels, so low-elevation towns
    # (Irrigon/Hermiston sit only ~400-500 ft up) never get clipped.
    ax.fill_between(x_mi, -LABEL_STRIP_FT, sfc_ft, color=TERRAIN_FILL, zorder=Z_TERRAIN, linewidth=0)
    ax.plot(x_mi, sfc_ft, color=TERRAIN_EDGE, linewidth=1.4, zorder=Z_TERRAIN)
    ax.axhline(0, color="white", linewidth=0.6, alpha=0.35, zorder=Z_TERRAIN)

    ax.set_xlim(x_mi[0], x_mi[-1])
    ax.set_ylim(-LABEL_STRIP_FT, top_ft)

    # ---------- town labels in the ground strip ----------
    # End points at the corners; intermediate towns centered on their
    # along-section position. Towns arrive in priority order (see
    # fetch_cross_section.py's NEARBY_TOWNS) and each takes the first of the
    # two rows it fits in -- a lower-priority town that fits in neither (e.g.
    # Adams vs. Pendleton) is dropped rather than crowding a better label.
    row_y = [-0.30 * LABEL_STRIP_FT, -0.72 * LABEL_STRIP_FT]
    ax.text(x_mi[0] + 0.5, row_y[0], d["start"]["label"], ha="left", va="center",
            fontproperties=f_med, fontsize=10, color="white", zorder=Z_LABEL)
    ax.text(x_mi[-1] - 0.5, row_y[0], d["end"]["label"], ha="right", va="center",
            fontproperties=f_med, fontsize=10, color="white", zorder=Z_LABEL)
    end_room = END_LABEL_WIDTH_MI
    placed = [[x_mi[0] + end_room / 2 - TOWN_MIN_SEP_MI / 2, x_mi[-1] - end_room / 2 + TOWN_MIN_SEP_MI / 2],
              []]
    for t in d["towns"]:
        xt = t["distance_km"] * KM_TO_MI
        for row in (0, 1):
            clear = all(abs(xt - xp) >= TOWN_MIN_SEP_MI for xp in placed[row])
            # A row-1 label's leader line runs up through row 0 -- keep it
            # off any row-0 label's text.
            if row == 1:
                clear = clear and all(abs(xt - xp) >= TOWN_MIN_SEP_MI / 2.2 for xp in placed[0])
            if clear:
                break
        else:
            print(f"NOTE: dropping town label {t['label']} (no room)")
            continue
        placed[row].append(xt)
        j = int(np.abs(x_mi - xt).argmin())
        ax.plot([xt, xt], [row_y[row] + 0.13 * LABEL_STRIP_FT, sfc_ft[j]], color="white",
                linewidth=0.8, alpha=0.7, zorder=Z_LABEL)
        ax.text(xt, row_y[row], t["label"], ha="center", va="center", fontproperties=f_med,
                fontsize=9, color="white", zorder=Z_LABEL)

    # ---------- axes styling ----------
    ax.spines["left"].set_bounds(0, top_ft)
    ax.set_ylabel("Height (ft above sea level)", fontproperties=f_med, fontsize=12, color=INK)
    ax.yaxis.set_major_locator(matplotlib.ticker.MultipleLocator(1000))
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}" if v >= 0 else ""))
    ax.set_xticks([])
    ax.set_axisbelow(False)
    ax.grid(axis="y", color=GRID_COLOR, alpha=0.18, linewidth=0.8, zorder=Z_ISOBAR)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(AXIS_COLOR)
        ax.spines[spine].set_linewidth(1.0)
    ax.tick_params(axis="both", colors=AXIS_COLOR, labelsize=10, length=4)
    for tick in ax.get_xticklabels() + ax.get_yticklabels():
        tick.set_fontproperties(f_reg)
        tick.set_color(INK_SECONDARY)
        tick.set_fontsize(10)

    fig.canvas.draw()
    axpos = ax.get_position()
    left_x, right_x, top_y = axpos.x0, axpos.x1, axpos.y1
    center_x = (axpos.x0 + axpos.x1) / 2

    # ---------- colorbar (right of the plot) ----------
    cax = fig.add_axes([right_x + 0.022, axpos.y0, 0.018, axpos.height])
    cb = fig.colorbar(mesh, cax=cax, extend="max", ticks=np.arange(0, 101, 10))
    cb.outline.set_linewidth(0.6)
    cb.ax.tick_params(labelsize=9, colors=AXIS_COLOR, length=3)
    for tick in cb.ax.get_yticklabels():
        tick.set_fontproperties(f_reg)
        tick.set_color(INK_SECONDARY)
        tick.set_fontsize(9)
    cb.set_label("Wind Speed (mph)", fontproperties=f_med, fontsize=11, color=INK)

    # ---------- title / subtitle ----------
    subtitle_y = top_y + 0.058
    title_y = subtitle_y + 0.035
    fig.text(left_x, title_y, f"Low-Level Winds: {d['start']['label']} to {d['end']['label']}",
             fontproperties=f_bold, fontsize=22, color=INK)
    valid_str = valid_local.strftime("%a %-m/%-d %-I %p %Z")
    subtitle = (f"NOAA RRFS Init {init_time:%Y-%m-%d} {init_time:%H}z"
                f" • Valid {valid_str} ({valid_time:%H}z) • Surface to 700 mb")
    fig.text(left_x, subtitle_y, subtitle, fontproperties=f_reg, fontsize=12, color=INK_SECONDARY)
    fig.text(left_x, top_y + 0.018, "Shading: wind speed (mph) • Barbs: wind direction & speed (kt) • Dashed: inversion top",
             fontproperties=f_reg, fontsize=10.5, color=INK_SECONDARY)

    # ---------- logo ----------
    LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets",
                             "ingalls_weather_logo.png")
    if os.path.exists(LOGO_PATH):
        logo_img = plt.imread(LOGO_PATH)
        img_h, img_w = logo_img.shape[0], logo_img.shape[1]
        fig_w_in, fig_h_in = fig.get_size_inches()
        inset_y = 22 / (fig_h_in * fig.get_dpi())
        logo_top = title_y + 0.048
        logo_bottom = top_y + inset_y
        logo_height_fig = logo_top - logo_bottom
        logo_width_fig = logo_height_fig * fig_h_in * (img_w / img_h) / fig_w_in
        logo_ax = fig.add_axes([right_x - logo_width_fig, logo_bottom, logo_width_fig,
                                logo_height_fig], zorder=20)
        logo_ax.imshow(logo_img)
        logo_ax.axis("off")

    # ---------- attribution / exaggeration footnote ----------
    fig_w_in, fig_h_in = fig.get_size_inches()
    ax_w_in, ax_h_in = axpos.width * fig_w_in, axpos.height * fig_h_in
    exaggeration = ((top_ft + LABEL_STRIP_FT) / ax_h_in) ** -1 / ((x_mi[-1] * 5280) / ax_w_in) ** -1
    fig.text(center_x, axpos.y0 - 0.045,
             f"NOAA RRFS 3 km — Ingalls Weather  •  Vertical scale exaggerated ~{exaggeration:.0f}×"
             f"  •  Terrain is RRFS model terrain",
             fontproperties=f_reg, fontsize=9, color=INK_SECONDARY, ha="center")

    output = args.output or f"rrfs_wind_cross_section_{valid_time:%Y%m%d_%H}z.png"
    plt.savefig(output, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
    print(f"saved {output}")


if __name__ == "__main__":
    main()

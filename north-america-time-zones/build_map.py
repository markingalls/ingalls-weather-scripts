"""
North America Time Zone Map -- Winter 2026-27
Ingalls Weather

Styled map of North America's time zones as they stand after the
November 1, 2026 fall-back -- the first winter in which much of Western
and Central Canada stops changing clocks:

  - British Columbia: final spring-forward was March 8, 2026; stays on
    UTC-7 ("Pacific Time") year-round. The Peace region (Dawson Creek, Fort
    St. John, Fort Nelson) and Creston were already UTC-7 year-round.
  - East Kootenay (RDEK, incl. Cranbrook/Fernie/Invermere) and Golden:
    year-round Mountain Daylight Time, UTC-6 -- still matching Alberta.
  - Alberta (incl. Lloydminster): year-round "Alberta Time", UTC-6.
  - Northwest Territories: year-round UTC-6.
  - Manitoba and the Central-time part of northwestern Ontario (Kenora,
    Rainy River): year-round Central Daylight Time, UTC-5.
  - Saskatchewan (UTC-6) and Yukon (UTC-7): unchanged, already year-round.
  - Rest of Ontario, Quebec, Atlantic Canada, Nunavut: still fall back.

Fill color = clock offset from UTC this winter. Hatching = places that
don't change clocks at all. Hawaii is left out. City labels give each city's clock time at the
moment it's 12:00 in Seattle, which is the quickest way to read the new
oddities (Vancouver an hour ahead of Seattle; Winnipeg matching Toronto).

USAGE
-----
    python build_map.py
    python build_map.py --out output/custom.png

REQUIRES (checked into /maps at repo root; regenerate with
prepare_basemap.py):
    tz_boundaries_north_america.json, na_land_50m.json, na_lakes_50m.json,
    na_admin1_lines_50m.json, admin0_boundary_lines.json

Logo is read from /assets/ingalls_weather_logo.png at repo root.
"""

import argparse
import json
import warnings
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
from matplotlib.patches import Rectangle
from matplotlib.transforms import offset_copy
import numpy as np
import shapely
from PIL import Image
from shapely.geometry import Point, Polygon, shape
from shapely.ops import unary_union

import cartopy.crs as ccrs

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
MAPS_DIR = REPO_ROOT / "maps"
ASSETS_DIR = REPO_ROOT / "assets"
THIS_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = THIS_DIR / "output"

TZ_FILE = MAPS_DIR / "tz_boundaries_north_america.json"
LAND_FILE = MAPS_DIR / "na_land_50m.json"
LAKES_FILE = MAPS_DIR / "na_lakes_50m.json"
ADMIN1_LINES_FILE = MAPS_DIR / "na_admin1_lines_50m.json"
ADMIN0_LINES_FILE = MAPS_DIR / "admin0_boundary_lines.json"
LOGO_FILE = ASSETS_DIR / "ingalls_weather_logo.png"

POPPINS_REG_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf"
POPPINS_MED_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf"
POPPINS_BOLD_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf"

# ---------------------------------------------------------------------------
# Offsets. Everything outside Canada comes from the system tz database
# (checked at a winter and a summer instant). Canada's 2026 changes are
# pinned explicitly here so the map is right even on a machine with tzdata
# older than 2026e (which is where these changes landed) -- the script
# prints a note if the local tz database disagrees with this table.
#   tzid: (winter 2026-27 UTC offset, year-round?, stopped changing in 2026?)
# The tzid polygons cover more than their namesake city: America/Edmonton
# includes East Kootenay/Golden, Lloydminster, and most of NWT;
# America/Winnipeg includes Kenora/Rainy River in northwestern Ontario.
# ---------------------------------------------------------------------------
CANADA_2026 = {
    "America/Vancouver":     (-7.0, True,  True),
    "America/Edmonton":      (-6.0, True,  True),
    "America/Inuvik":        (-6.0, True,  True),
    "America/Winnipeg":      (-5.0, True,  True),
    "America/Whitehorse":    (-7.0, True,  False),
    "America/Dawson":        (-7.0, True,  False),
    "America/Dawson_Creek":  (-7.0, True,  False),
    "America/Fort_Nelson":   (-7.0, True,  False),
    "America/Creston":       (-7.0, True,  False),
    "America/Regina":        (-6.0, True,  False),
    "America/Swift_Current": (-6.0, True,  False),
    "America/Atikokan":      (-5.0, True,  False),
    "America/Toronto":       (-5.0, False, False),
    "America/Cambridge_Bay": (-7.0, False, False),
    "America/Rankin_Inlet":  (-6.0, False, False),
    "America/Resolute":      (-6.0, False, False),
    "America/Iqaluit":       (-5.0, False, False),
    "America/Blanc-Sablon":  (-4.0, True,  False),
    "America/Halifax":       (-4.0, False, False),
    "America/Glace_Bay":     (-4.0, False, False),
    "America/Moncton":       (-4.0, False, False),
    "America/Goose_Bay":     (-4.0, False, False),
    "America/St_Johns":      (-3.5, False, False),
}

WINTER_INSTANT = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)
SUMMER_INSTANT = datetime(2027, 7, 1, 12, tzinfo=timezone.utc)

# Reference moment for the city clock labels: noon in Seattle (PST) =
# 20:00 UTC.
REFERENCE_UTC_HOUR = 20.0
REFERENCE_LABEL = "12:00 in Seattle"
CITY_LABEL_FONTSIZE = 10

# Fill color per winter offset -- soft, adjacent offsets deliberately on
# different hues so neighbouring zones never blur together.
OFFSET_COLORS = {
    -10.0: "#c8b9dc",
    -9.0:  "#a9c6e4",
    -8.0:  "#f2c39a",
    -7.0:  "#b4d5a4",
    -6.0:  "#f1de8c",
    -5.0:  "#e9a8a2",
    -4.0:  "#9ccfca",
    -3.5:  "#d3b1d0",
    -3.0:  "#cfc59f",
    -2.0:  "#b8cce0",
    -1.0:  "#d8d3c6",
    0.0:   "#c9c4b8",
}
OCEAN_COLOR = "#e6edf0"
TZ_LINE_SNAP_DEG = 0.2

# ---------------------------------------------------------------------------
# Figure geometry / domain (Lambert Conformal, the standard NOAA/NWS
# continental projection). The frame is set in *projected* coordinates
# from the corner points below so it's a clean rectangle around North
# America (Aleutians to Newfoundland, Panama to the Arctic islands);
# FIG_WIDTH_IN is chosen so AXES_RECT's aspect matches that rectangle.
# ---------------------------------------------------------------------------
CENTER_LON = -100.0
PROJ = ccrs.LambertConformal(central_longitude=CENTER_LON, central_latitude=45.0,
                             standard_parallels=(33.0, 60.0))
FRAME_POINTS = [(-168.0, 54.0), (-52.0, 47.0), (-80.0, 7.5), (-120.0, 20.0),
                (-100.0, 76.0), (-60.0, 70.0), (-145.0, 70.0)]
# Not drawn (off-frame, and left out of the legend / city labels).
EXCLUDED_TZIDS = {"Pacific/Honolulu"}
FIG_DPI = 200
FIG_WIDTH_IN = 10.0
AXES_LEFT, AXES_WIDTH = 0.03, 0.94
# Title block above / legend below the map, in inches (not figure
# fractions) so they stay snug whatever height the frame works out to.
TOP_MARGIN_IN, BOTTOM_MARGIN_IN = 1.12, 1.6
MAP_FRAME_INSET_PX = 22

CITIES = [
    # (name, lon, lat, label side -- see LABEL_NAME_OFFSETS)
    ("Anchorage", -149.90, 61.22, "right"),
    ("Whitehorse", -135.06, 60.72, "right"),
    ("Yellowknife", -114.37, 62.45, "right"),
    ("Vancouver", -123.12, 49.28, "upper-left"),
    ("Seattle", -122.33, 47.61, "lower-left"),
    ("Calgary", -114.07, 51.04, "right"),
    ("Regina", -104.61, 50.45, "right"),
    ("Winnipeg", -97.14, 49.90, "right"),
    ("Toronto", -79.38, 43.65, "right"),
    ("Halifax", -63.57, 44.65, "right"),
    ("St. John's", -52.71, 47.56, "left"),
    ("Los Angeles", -118.24, 34.05, "left"),
    ("Phoenix", -112.07, 33.45, "right"),
    ("Denver", -104.99, 39.74, "right"),
    ("Chicago", -87.63, 41.88, "right"),
    ("New York", -74.01, 40.71, "right"),
    ("Mexico City", -99.13, 19.43, "right"),
    ("Dallas", -96.80, 32.78, "right"),
    ("Atlanta", -84.39, 33.75, "right"),
    ("Havana", -82.37, 23.11, "right"),
    ("Cancún", -86.85, 21.16, "left"),
    ("Cabo San Lucas", -109.92, 22.89, "left"),
    ("Iqaluit", -68.52, 63.75, "right"),
    ("Nuuk", -51.72, 64.18, "left"),
]


# City labels: name on the dot's line (vertically centered on the dot),
# bold time centered underneath the name. Only "upper-left"/"lower-left"
# (for city pairs too close together to share a line) move the name off
# the dot's line.
LABEL_NAME_OFFSETS = {
    "right": (5, 0, "left", "center"),
    "left": (-5, 0, "right", "center"),
    "upper-left": (-4, None, "right", "bottom"),  # None: computed so the time clears the dot
    "lower-left": (-4, -2, "right", "top"),
}
# Pulls the time line up toward the name (points); the name's bbox includes
# descender space and the time's includes ascender space, so a small
# positive nudge reads as tight-but-not-touching.
TIME_LINE_NUDGE_PT = 2.5


def draw_city_label(ax, base_transform, fig, lon, lat, name, time_str, side,
                    name_font, time_font, fontsize, stroke, zorder=101):
    dx, dy, ha, va = LABEL_NAME_OFFSETS[side]
    if dy is None:
        dy = 2 + fontsize * 1.05 - TIME_LINE_NUDGE_PT
    t = offset_copy(base_transform, fig=fig, x=dx, y=dy, units="points")
    name_txt = ax.text(lon, lat, name, color="white", ha=ha, va=va, zorder=zorder, transform=t)
    name_txt.set_fontproperties(name_font)
    name_txt.set_fontsize(fontsize)
    name_txt.set_path_effects(stroke)
    # Anchored to the name's own bounding box: centered under it.
    time_txt = ax.annotate(time_str, xy=(0.5, 0), xycoords=name_txt, xytext=(0, TIME_LINE_NUDGE_PT),
                           textcoords="offset points", ha="center", va="top", color="white",
                           zorder=zorder, annotation_clip=False)
    time_txt.set_fontproperties(time_font)
    time_txt.set_fontsize(fontsize)
    time_txt.set_path_effects(stroke)


# ---------------------------------------------------------------------------
# Offsets
# ---------------------------------------------------------------------------
def tz_offsets(tzid):
    """(winter offset hours, year_round, new_in_2026) for a tzid."""
    zi = ZoneInfo(tzid)
    w = WINTER_INSTANT.astimezone(zi).utcoffset().total_seconds() / 3600
    s = SUMMER_INSTANT.astimezone(zi).utcoffset().total_seconds() / 3600
    if tzid in CANADA_2026:
        pinned = CANADA_2026[tzid]
        if (w, w == s) != pinned[:2]:
            print(f"NOTE: local tz database disagrees for {tzid} (winter {w:+.1f}, "
                  f"year-round={w == s}); using the pinned 2026 value {pinned[0]:+.1f}.")
        return pinned
    return w, w == s, False


def fmt_offset(h):
    sign = "−" if h < 0 else "+"
    h = abs(h)
    return f"UTC{sign}{int(h)}" + (":30" if h % 1 else "")


def fmt_clock(offset):
    """24-hour local clock time at the reference moment, e.g. 13:00."""
    total = int(round(((REFERENCE_UTC_HOUR + offset) % 24) * 60))
    hh, mm = divmod(total, 60)
    return f"{hh:02d}:{mm:02d}"


# ---------------------------------------------------------------------------
# Basemap layers
# ---------------------------------------------------------------------------
def load_geoms(path):
    with open(path) as f:
        data = json.load(f)
    return [shape(feat["geometry"]) for feat in data["features"] if feat.get("geometry")]


def load_tz():
    with open(TZ_FILE) as f:
        data = json.load(f)
    return [(feat["properties"]["tzid"], shape(feat["geometry"])) for feat in data["features"]]


def frame_extent():
    xs, ys = [], []
    for lon, lat in FRAME_POINTS:
        x, y = PROJ.transform_point(lon, lat, ccrs.PlateCarree())
        xs.append(x)
        ys.append(y)
    return min(xs), max(xs), min(ys), max(ys)


def densify(geom, max_seg_deg=0.1):
    """Add vertices so long straight lon/lat segments (the 49th parallel
    is only a handful of vertices in the tz data) follow Lambert
    Conformal's curved parallels. Without this, two datasets' versions of
    the same border -- one sparse, one detailed -- project as visibly
    separate lines."""
    return shapely.segmentize(geom, max_seg_deg)


def frame_polygon_lonlat(x0, x1, y0, y1, n=200):
    """The projected frame rectangle as a lon/lat polygon (edges sampled
    densely, since they're curves in lon/lat)."""
    xs = np.concatenate([np.linspace(x0, x1, n), np.full(n, x1), np.linspace(x1, x0, n), np.full(n, x0)])
    ys = np.concatenate([np.full(n, y0), np.linspace(y0, y1, n), np.full(n, y1), np.linspace(y1, y0, n)])
    ll = ccrs.PlateCarree().transform_points(PROJ, xs, ys)
    return Polygon(ll[:, :2]).buffer(0)


def build_map(output_path):
    poppins_reg = fm.FontProperties(fname=POPPINS_REG_PATH)
    poppins_semibold = fm.FontProperties(fname=POPPINS_MED_PATH)
    poppins_bold = fm.FontProperties(fname=POPPINS_BOLD_PATH)
    pc = ccrs.PlateCarree()

    print("Loading basemap layers...")
    land = unary_union(load_geoms(LAND_FILE))
    lakes = unary_union(load_geoms(LAKES_FILE))
    land_minus_lakes = land.difference(lakes)
    admin1_lines = load_geoms(ADMIN1_LINES_FILE)
    admin0_lines = load_geoms(ADMIN0_LINES_FILE)

    print("Grouping time zones by winter 2026-27 offset...")
    by_offset, year_round = {}, []
    tz_info = {}
    for tzid, geom in load_tz():
        if tzid in EXCLUDED_TZIDS:
            continue
        off, yr, _ = tz_offsets(tzid)
        tz_info[tzid] = off
        by_offset.setdefault(off, []).append(geom)
        if yr:
            year_round.append(geom)
    by_offset = {off: densify(unary_union(g).intersection(land_minus_lakes)) for off, g in by_offset.items()}
    year_round_geom = densify(unary_union(year_round).intersection(land_minus_lakes))

    # Time zone lines = shared edges between offset groups (not coastlines).
    # These come from the same polygons as the fills, so they always sit
    # exactly on the color change. National/state border segments running
    # within TZ_LINE_SNAP_DEG of one are dropped -- otherwise Natural
    # Earth's version of e.g. the 49th parallel or the ID/OR line draws as
    # a second, slightly offset line beside the tz line.
    groups = list(by_offset.values())
    tz_lines = unary_union([groups[i].boundary.intersection(groups[j].boundary.buffer(0.02))
                            for i in range(len(groups)) for j in range(i + 1, len(groups))
                            if groups[i].buffer(0.02).intersects(groups[j])])
    tz_snap = tz_lines.buffer(TZ_LINE_SNAP_DEG)
    admin1_lines = [densify(g.difference(tz_snap)) for g in admin1_lines]
    admin0_lines = [densify(g.difference(tz_snap)) for g in admin0_lines]
    land_outline = densify(land_minus_lakes)

    x0, x1, y0, y1 = frame_extent()
    axes_h_in = FIG_WIDTH_IN * AXES_WIDTH * (y1 - y0) / (x1 - x0)
    fig_h_in = axes_h_in + TOP_MARGIN_IN + BOTTOM_MARGIN_IN
    axes_bottom = BOTTOM_MARGIN_IN / fig_h_in
    axes_rect = [AXES_LEFT, axes_bottom, AXES_WIDTH, axes_h_in / fig_h_in]

    fig = plt.figure(figsize=(FIG_WIDTH_IN, fig_h_in), dpi=FIG_DPI)
    fig.patch.set_facecolor("#f7f6f2")
    ax = fig.add_axes(axes_rect, projection=PROJ)
    ax.set_extent([x0, x1, y0, y1], crs=PROJ)
    ax.patch.set_facecolor(OCEAN_COLOR)

    offsets_present = sorted(by_offset)
    for off in offsets_present:
        ax.add_geometries([by_offset[off]], crs=pc, facecolor=OFFSET_COLORS.get(off, "#dddddd"),
                          edgecolor="none", zorder=1)

    # Year-round (no clock change) hatch. Hatch color comes from edgecolor;
    # linewidth=0 keeps the polygon edge itself invisible.
    plt.rcParams["hatch.linewidth"] = 0.45
    ax.add_geometries([year_round_geom], crs=pc, facecolor="none", edgecolor=(0.2, 0.17, 0.13, 0.38),
                      hatch="//////", linewidth=0, zorder=1.2)

    ax.add_geometries(admin1_lines, crs=pc, facecolor="none", edgecolor="#7d6e5c", linewidth=0.35,
                      alpha=0.8, zorder=1.4)
    ax.add_geometries([land_outline], crs=pc, facecolor="none", edgecolor="#4a6b7a", linewidth=0.5,
                      zorder=1.5)
    ax.add_geometries(admin0_lines, crs=pc, facecolor="none", edgecolor="#3a2f21", linewidth=0.8,
                      zorder=1.6)
    # Time zone boundaries, drawn darker than state/province lines.
    ax.add_geometries([tz_lines], crs=pc, facecolor="none", edgecolor="#2b2a26",
                      linewidth=0.9, zorder=1.8)

    # Cities, labelled with their clock time at the reference moment.
    tz_shapes = load_tz()
    geodetic_transform = pc._as_mpl_transform(ax)
    stroke = [pe.withStroke(linewidth=1.9, foreground=(0, 0, 0, 0.75))]
    for name, lon_c, lat_c, side in CITIES:
        pt = Point(lon_c, lat_c)
        tzid = next((t for t, g in tz_shapes if g.contains(pt)), None)
        if tzid is None:
            print(f"NOTE: no tz polygon for {name}, skipping.")
            continue
        clock = fmt_clock(tz_info[tzid])
        ax.plot(lon_c, lat_c, marker="o", markersize=4.2, color="white", zorder=100,
                mec="black", mew=0.7, transform=pc)
        draw_city_label(ax, geodetic_transform, fig, lon_c, lat_c, name, clock, side,
                        poppins_semibold, poppins_bold, CITY_LABEL_FONTSIZE, stroke)

    ax.spines["geo"].set_edgecolor("black")
    ax.spines["geo"].set_linewidth(1.6)

    # ---- Legend: one swatch per offset, with its clock time at the
    # reference moment (only offsets actually visible in the frame), plus
    # the hatch key ----
    lax = fig.add_axes([0.03, 0.15 / fig_h_in, 0.94, (BOTTOM_MARGIN_IN - 0.3) / fig_h_in])
    lax.set_xlim(0, 1)
    lax.set_ylim(0, 1)
    lax.axis("off")
    frame_ll = frame_polygon_lonlat(x0, x1, y0, y1)
    legend_offsets = [o for o in offsets_present if by_offset[o].intersection(frame_ll).area > 0.5]
    n = len(legend_offsets)
    sw_w = 0.94 / n
    for i, off in enumerate(legend_offsets):
        x = 0.03 + i * sw_w
        lax.add_patch(Rectangle((x + 0.004, 0.56), sw_w - 0.008, 0.22,
                                facecolor=OFFSET_COLORS.get(off, "#dddddd"), edgecolor="#8a887e",
                                linewidth=0.6))
        lax.text(x + sw_w / 2, 0.67, fmt_clock(off), ha="center", va="center", fontsize=8.6,
                 fontproperties=poppins_semibold, color="#2b2a26")
        lax.text(x + sw_w / 2, 0.47, fmt_offset(off), ha="center", va="center", fontsize=7.4,
                 fontproperties=poppins_reg, color="#5a584f")
    lax.text(0.5, 0.93, f"Clock time when it's {REFERENCE_LABEL}  ·  UTC offset this winter",
             ha="center", va="center", fontsize=9, fontproperties=poppins_reg, color="#2b2a26")

    # Hatch key
    lax.add_patch(Rectangle((0.335, 0.10), 0.045, 0.17, facecolor="#f1de8c", edgecolor="#8a887e",
                            linewidth=0.6))
    lax.add_patch(Rectangle((0.335, 0.10), 0.045, 0.17, facecolor="none",
                            edgecolor=(0.2, 0.17, 0.13, 0.38), hatch="//////", linewidth=0))
    lax.text(0.387, 0.185, "No clock changes (same time year-round)", ha="left", va="center",
             fontsize=8.6, fontproperties=poppins_reg, color="#2b2a26")

    # Title block
    top = 1 - 0.022 * 11.0 / fig_h_in
    fig.text(0.03, top, "North America Winter Time Zones", fontsize=21, fontproperties=poppins_reg,
             color="#2b2a26", ha="left", va="top")
    fig.text(0.03, top - 0.045 * 11.0 / fig_h_in,
             f"2026–27  •  Clock times when it's {REFERENCE_LABEL}",
             fontsize=11, fontproperties=poppins_reg, color="#5a584f", ha="left", va="top")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, facecolor=fig.get_facecolor(), dpi=FIG_DPI)
    plt.close(fig)
    print(f"Saved base map to {output_path}")

    # ---- Composite logo, bottom-left, snug inside the frame ----
    if LOGO_FILE.exists():
        base = Image.open(output_path).convert("RGB")
        bw, bh = base.size
        frame_left = int(axes_rect[0] * bw)
        frame_bottom = int((1 - axes_rect[1]) * bh)
        logo = Image.open(LOGO_FILE).convert("RGB")
        target_w = int(bw * 0.075)
        target_h = int(logo.height * target_w / logo.width)
        logo_resized = logo.resize((target_w, target_h), Image.LANCZOS)
        pos = (frame_left + MAP_FRAME_INSET_PX, frame_bottom - MAP_FRAME_INSET_PX - target_h)
        base.paste(logo_resized, pos)
        base.save(output_path)
        print(f"Composited logo at {pos}")
    else:
        print(f"NOTE: logo not found at {LOGO_FILE}, skipping (map saved without logo).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build an Ingalls Weather North America time zone map.")
    parser.add_argument("--out", type=Path, default=None,
                        help="Output PNG path (default: output/north_america_time_zones_2026.png).")
    args = parser.parse_args()
    build_map(args.out or (OUTPUT_DIR / "north_america_time_zones_2026.png"))

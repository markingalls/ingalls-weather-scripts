"""
Pacific Northwest Frost-Free Period Change Map -- builder
Ingalls Weather

Styled map covering the same BC/WA/OR/ID (+ slivers of NV/MT/WY) domain as
../pnw-frost-free-days-map/, ../pnw-first-freeze-change-map/, and
../dew-point-storm-map/: each station's change in average frost-free
period length (days between the last spring and first fall date the
daily low drops to <=32F / 0C) between 1961-1975 and 2006-2020 (see
fetch_climatology.py), plotted as a diverging-colored dot at that
station's location -- blue where the season is now shorter than it used
to be, red where it's now longer. No interpolation or shading between
stations, same reasoning as the sibling maps (see
../pnw-first-freeze-map/'s docstring/README): station coverage is uneven
and elevation-driven enough that a smoothed fill would visually claim
more precision than the data supports -- doubly so here, since this
map's station filter (a real record on both ends of a ~60-year span) is
stricter and the candidate pool smaller than the climatology sibling's.

USAGE
-----
    python build_map.py                          # reads ./climatology_change.json
    python build_map.py --climatology data.json
    python build_map.py --out output/custom_name.png

REQUIRES (already checked into /maps at repo root, shared across all
Ingalls Weather map projects):
    land_slim.json, states_lakes_slim.json, admin1_boundary_lines.json,
    admin0_boundary_lines.json

Logo is read from /assets/ingalls_weather_logo.png at repo root.
"""

import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
from matplotlib.colors import Normalize, LinearSegmentedColormap
from matplotlib.transforms import offset_copy
import numpy as np

import cartopy.crs as ccrs
from shapely.geometry import shape
from PIL import Image

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
MAPS_DIR = REPO_ROOT / "maps"
ASSETS_DIR = REPO_ROOT / "assets"
THIS_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = THIS_DIR / "output"

LAND_FILE = MAPS_DIR / "land_slim.json"
STATES_LAKES_FILE = MAPS_DIR / "states_lakes_slim.json"
ADMIN0_LINES_FILE = MAPS_DIR / "admin0_boundary_lines.json"
LOGO_FILE = ASSETS_DIR / "ingalls_weather_logo.png"

TARGET_COUNTRIES = {"United States of America", "Canada"}

POPPINS_REG_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf"
POPPINS_MED_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf"

# ---------------------------------------------------------------------------
# Figure geometry -- same as ../pnw-first-freeze-map/build_map.py.
# ---------------------------------------------------------------------------
FIG_WIDTH_IN, FIG_HEIGHT_IN = 8.4, 8.6
FIG_DPI = 200
AXES_RECT = [0.03, 0.135, 0.94, 0.73]  # [left, bottom, width, height], figure fraction
MAP_FRAME_INSET_PX = 22

# ---------------------------------------------------------------------------
# Map domain -- identical to the sibling maps' and ../dew-point-storm-map/'s
# BC/WA/OR/ID (+ slivers of NV/MT/WY) framing.
# ---------------------------------------------------------------------------
LON_MIN, LON_MAX = -128.2, -108.8
LAT_MIN, LAT_MAX = 39.7, 55.2
CENTER_LON, CENTER_LAT = -118.5, 47.45

CITIES = [
    ("Bella Coola", -126.7659, 52.3728, "right"),
    ("Wells", -121.5589, 53.1058, "right"),
    ("Vancouver", -123.1207, 49.2827, "left"),
    ("Victoria", -123.3656, 48.4284, "left"),
    ("Kelowna", -119.4960, 49.8880, "right"),
    ("Kamloops", -120.3273, 50.6745, "right"),
    ("Prince George", -122.7497, 53.9171, "right"),
    ("Cranbrook", -115.7697, 49.5097, "right"),
    ("Williams Lake", -122.1417, 52.1417, "left"),
    ("Seattle", -122.3321, 47.6062, "left"),
    ("Spokane", -117.4260, 47.6588, "left"),
    ("Tri-Cities", -119.2781, 46.2565, "right"),
    ("Portland", -122.6784, 45.5152, "left"),
    ("Bend", -121.3153, 44.0582, "left"),
    ("Eugene", -123.0868, 44.0521, "left"),
    ("Medford", -122.8756, 42.3265, "left"),
    ("Redding", -122.3917, 40.5865, "left"),
    ("Burns", -119.0541, 43.5866, "right"),
    ("Boise", -116.2023, 43.6150, "left"),
    ("Twin Falls", -114.4609, 42.5629, "left"),
    ("Idaho Falls", -112.0362, 43.4917, "right"),
    ("Winnemucca", -117.7357, 40.9730, "left"),
    ("Salt Lake City", -111.8910, 40.7608, "right"),
    ("Bozeman", -111.0429, 45.6770, "right"),
    ("Missoula", -113.9940, 46.8721, "left"),
    ("Great Falls", -111.3008, 47.5053, "right"),
    ("Calgary", -114.0719, 51.0447, "right"),
    ("Red Deer", -113.8112, 52.2681, "right"),
    ("Edmonton", -113.4938, 53.5461, "right"),
    ("Lethbridge", -112.8418, 49.6935, "right"),
]

# ---------------------------------------------------------------------------
# Change color table -- fixed control points keyed to the change in
# frost-free days (recent-period mean minus early-period mean), not
# rescaled per map, diverging around 0: blue where the season is now
# shorter than 1961-1975, white/gray near no change, red where it's now
# longer (the more commonly expected direction under a warming climate).
# Endpoints placeholder pending the actual fetched distribution -- see
# ../pnw-first-freeze-change-map/build_map.py's table for how these get
# tuned from real percentiles once fetch_climatology.py has run.
# ---------------------------------------------------------------------------
CHANGE_COLOR_TABLE_DAYS = [
    (-35, [33, 79, 140]),
    (-20, [104, 159, 201]),
    (-8,  [186, 212, 226]),
    (0,   [230, 227, 217]),
    (8,   [237, 199, 165]),
    (20,  [211, 129, 79]),
    (35,  [161, 60, 40]),
]
CHANGE_MIN = CHANGE_COLOR_TABLE_DAYS[0][0]
CHANGE_MAX = CHANGE_COLOR_TABLE_DAYS[-1][0]


def build_change_colormap():
    span = CHANGE_MAX - CHANGE_MIN
    stops = [((d - CHANGE_MIN) / span, [c / 255 for c in rgb]) for d, rgb in CHANGE_COLOR_TABLE_DAYS]
    return LinearSegmentedColormap.from_list("ingalls_frost_free_days_change", stops, N=256)


def change_label(days):
    return f"{days:+.0f}d"


# ---------------------------------------------------------------------------
# Basemap layers -- same loaders as ../pnw-first-freeze-map/build_map.py.
# ---------------------------------------------------------------------------
def load_land():
    with open(LAND_FILE) as f:
        data = json.load(f)
    return [shape(feat["geometry"]) for feat in data["features"] if feat.get("geometry")]


def load_states():
    """State/province polygons -- lake features in this dataset are
    dropped entirely (not just left unshaded) so they don't get drawn as
    if they were a state/province border."""
    with open(STATES_LAKES_FILE) as f:
        data = json.load(f)
    state_geoms = []
    for feat in data["features"]:
        props = feat["properties"]
        if "Lake" in props.get("featurecla", ""):
            continue
        if props.get("admin") in TARGET_COUNTRIES:
            state_geoms.append(shape(feat["geometry"]))
    return state_geoms


def load_boundary_lines(path):
    with open(path) as f:
        data = json.load(f)
    return [shape(feat["geometry"]) for feat in data["features"]]


def build_map(climatology, output_path):
    poppins_reg = fm.FontProperties(fname=POPPINS_REG_PATH)
    poppins_semibold = fm.FontProperties(fname=POPPINS_MED_PATH)

    stations = climatology["stations"]
    lons = np.array([s["lon"] for s in stations])
    lats = np.array([s["lat"] for s in stations])
    changes = np.array([s["change_days"] for s in stations])

    print("Loading basemap layers...")
    land_geoms = load_land()
    state_geoms = load_states()
    admin0_lines = load_boundary_lines(ADMIN0_LINES_FILE)

    # PlateCarree, not NearsidePerspective -- see ../dew-point-storm-map/
    # build_map.py's comment above the same choice; this is the same
    # domain, so the same reasoning (avoiding blank corners / duplicated
    # border lines at this bbox's shape) applies.
    pc = ccrs.PlateCarree()
    fig = plt.figure(figsize=(FIG_WIDTH_IN, FIG_HEIGHT_IN), dpi=FIG_DPI)
    fig.patch.set_facecolor("#f7f6f2")

    ax = fig.add_axes(AXES_RECT, projection=pc)
    ax.set_extent([LON_MIN, LON_MAX, LAT_MIN, LAT_MAX], crs=pc)
    ax.patch.set_facecolor("white")

    cmap = build_change_colormap()
    norm = Normalize(vmin=CHANGE_MIN, vmax=CHANGE_MAX)

    ax.add_geometries(land_geoms, crs=pc, facecolor="#eef1ea", edgecolor="#4a6b7a", linewidth=0.8, zorder=1)
    ax.add_geometries(state_geoms, crs=pc, facecolor="none", edgecolor="#5a4632", linewidth=0.8, zorder=2)
    ax.add_geometries(admin0_lines, crs=pc, facecolor="none", edgecolor="#3a2f21", linewidth=1.1, zorder=2.5)

    # Each station plotted at its own location, colored by its own change
    # in mean frost-free day count -- no interpolation/shading between
    # stations (see module docstring). A white halo underneath the
    # colored fill (drawn as a larger white-edge marker first, kept fully
    # opaque) keeps every dot legible against both the light land fill
    # and darker colors in the table; the colored fill itself gets
    # alpha=0.55, same as ../pnw-first-freeze-change-map/ (its diverging
    # table sits closer to a light neutral near 0 than the climatology
    # sibling maps' tables, so needs more saturation to stay legible), so
    # overlapping dots in dense clusters still show through each other.
    ax.scatter(lons, lats, s=95, facecolor="none", edgecolor="white", linewidth=2.2,
               transform=pc, zorder=3.9)
    ax.scatter(lons, lats, c=changes, cmap=cmap, norm=norm, s=70, edgecolor="black",
               linewidth=0.6, alpha=0.55, transform=pc, zorder=4)

    geodetic_transform = pc._as_mpl_transform(ax)
    stroke = [pe.withStroke(linewidth=2.0, foreground="white")]
    for name, lon_c, lat_c, pos in CITIES:
        if not (LON_MIN <= lon_c <= LON_MAX and LAT_MIN <= lat_c <= LAT_MAX):
            continue
        ax.plot(lon_c, lat_c, marker="o", markersize=4.6, color="white", zorder=100,
                mec="black", mew=0.7, transform=pc)
        dx_pt = 6 if pos == "right" else -6
        ha = "left" if pos == "right" else "right"
        name_transform = offset_copy(geodetic_transform, fig=fig, x=dx_pt, y=0, units="points")
        txt = ax.text(lon_c, lat_c, name, fontsize=9.25, fontproperties=poppins_semibold,
                       color="black", ha=ha, va="center", zorder=101, transform=name_transform)
        txt.set_path_effects(stroke)

    ax.spines['geo'].set_edgecolor('black')
    ax.spines['geo'].set_linewidth(1.6)

    # Colorbar -- below the map, centered on the rendered map frame, ticks
    # labeled as signed day counts. alpha=0.55 matches the station dots
    # above, so the swatch shows the same color a single dot actually
    # renders at, not a stronger one.
    fig.canvas.draw()
    frame_px = ax.get_window_extent()
    frame_left = frame_px.x0 / (FIG_WIDTH_IN * FIG_DPI)
    frame_right = frame_px.x1 / (FIG_WIDTH_IN * FIG_DPI)
    cbar_width, cbar_height = (frame_right - frame_left) * 0.7, 0.017
    cbar_left = (frame_left + frame_right) / 2 - cbar_width / 2
    cbar_bottom = 0.083

    gradient = np.linspace(CHANGE_MIN, CHANGE_MAX, 256).reshape(1, -1)
    cax = fig.add_axes([cbar_left, cbar_bottom, cbar_width, cbar_height])
    cax.set_facecolor("white")
    cax.imshow(gradient, aspect="auto", cmap=cmap, norm=norm, alpha=0.55,
               extent=[CHANGE_MIN, CHANGE_MAX, 0, 1])
    cax.set_yticks([])
    for spine in cax.spines.values():
        spine.set_edgecolor("#8a887e")
        spine.set_linewidth(0.6)

    tick_days = [-30, -20, -10, 0, 10, 20, 30]
    cax.set_xticks(tick_days)
    cax.set_xticklabels([change_label(d) for d in tick_days])
    cax.tick_params(labelsize=8.5, color="#8a887e", labelcolor="#2b2a26")
    for label in cax.get_xticklabels():
        label.set_fontproperties(poppins_reg)

    # Title & subtitle above the map
    fig.text(0.03, 0.977, "Pacific Northwest Change in Frost-Free Period", fontsize=16.5,
              fontproperties=poppins_reg, color="#2b2a26", ha="left", va="top")
    fig.text(0.03, 0.940, f"{climatology['period_early']} to {climatology['period_recent']} "
                          f"• Change in Days Between Freezes ≤32°F (0°C)",
              fontsize=12, fontproperties=poppins_semibold, color="#3a3835", ha="left", va="top")
    fig.text(0.03, 0.909, f"NOAA GHCN-Daily • {len(stations)} stations",
              fontsize=10.5, fontproperties=poppins_reg, color="#5a584f", ha="left", va="top")

    fig.text(0.5, 0.014, "NOAA GHCN-Daily — Ingalls Weather", fontsize=8.5,
              fontproperties=poppins_reg, color="#8a887e", ha="center", va="bottom")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, facecolor=fig.get_facecolor(), dpi=200)
    plt.close(fig)
    print(f"Saved base map to {output_path}")

    # ---- Composite logo, bottom-left, snug inside the frame ----
    if LOGO_FILE.exists():
        base = Image.open(output_path).convert("RGB")
        bw, bh = base.size
        arr = np.array(base)
        y = bh // 2
        black_cols = [x for x in range(bw) if arr[y, x][0] < 40 and arr[y, x][1] < 40 and arr[y, x][2] < 40]
        x = bw // 2
        black_rows = [yy for yy in range(bh) if arr[yy, x][0] < 40 and arr[yy, x][1] < 40 and arr[yy, x][2] < 40]
        frame_left = min(black_cols) if black_cols else 20
        frame_bottom = max(black_rows) if black_rows else bh - 20

        logo = Image.open(LOGO_FILE).convert("RGB")
        target_w = int(bw * 0.08)
        scale = target_w / logo.width
        target_h = int(logo.height * scale)
        logo_resized = logo.resize((target_w, target_h), Image.LANCZOS)

        pos = (frame_left + MAP_FRAME_INSET_PX, frame_bottom - MAP_FRAME_INSET_PX - target_h)
        base.paste(logo_resized, pos)
        base.save(output_path)
        print(f"Composited logo at {pos}")
    else:
        print(f"NOTE: logo not found at {LOGO_FILE}, skipping (map saved without logo).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build an Ingalls Weather PNW/BC frost-free period change map.")
    parser.add_argument("--climatology", type=Path, default=THIS_DIR / "climatology_change.json",
                         help="Path to climatology_change.json from fetch_climatology.py.")
    parser.add_argument("--out", type=Path, default=None,
                         help="Output PNG path (default: output/pnw_frost_free_days_change_map.png).")
    args = parser.parse_args()

    if not args.climatology.exists():
        sys.exit(f"{args.climatology} not found -- run fetch_climatology.py first.")

    with open(args.climatology) as f:
        climatology = json.load(f)
    if not climatology["stations"]:
        sys.exit(f"{args.climatology} has no qualifying stations.")

    out_path = args.out or (OUTPUT_DIR / "pnw_frost_free_days_change_map.png")
    build_map(climatology, out_path)

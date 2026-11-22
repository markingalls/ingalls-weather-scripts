"""
Pacific Northwest Thanksgiving Snow Climatology Map -- builder
Ingalls Weather

Styled map of Washington, Oregon, and Idaho: one dot per ACIS station,
colored by the percent of Thanksgivings in that station's period of record
that had snow. Two metrics (--metric):
  - snowfall (default): measurable snow *fell* on Thanksgiving Day
    (daily snowfall >= SNOWFALL_THRESHOLD_IN, 0.1" -- trace doesn't count).
  - depth: a "white Thanksgiving" -- snow *on the ground* Thanksgiving
    morning (snow depth >= DEPTH_THRESHOLD_IN, 1").

Each station's percentage only counts Thanksgivings it actually has a
valid reading for (missing years are excluded from both numerator and
denominator, not counted as no-snow), and stations with fewer than
--min-years valid Thanksgivings (default 20) are dropped as too thin a
sample to call a climatology.

A handful of major cities get labeled with their own station's value
(CITY_STATIONS below -- mostly first-order airport sites, with long-
running COOP sites where the airport's record is short).

Reads output/thanksgiving_snow.json, written by fetch_climatology.py --
run that first (once; it only needs re-running after a new Thanksgiving).

USAGE
-----
    python fetch_climatology.py                # once
    python build_map.py                        # measurable snowfall
    python build_map.py --metric depth         # snow on the ground
    python build_map.py --min-years 30

REQUIRES (already checked into /maps at repo root, shared across all
Ingalls Weather map projects):
    land_slim.json, states_lakes_slim.json, admin0_boundary_lines.json

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
from matplotlib.colors import BoundaryNorm, ListedColormap
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
DATA_FILE = OUTPUT_DIR / "thanksgiving_snow.json"

LAND_FILE = MAPS_DIR / "land_slim.json"
STATES_LAKES_FILE = MAPS_DIR / "states_lakes_slim.json"
ADMIN0_LINES_FILE = MAPS_DIR / "admin0_boundary_lines.json"
LOGO_FILE = ASSETS_DIR / "ingalls_weather_logo.png"

TARGET_COUNTRIES = {"United States of America", "Canada", "Mexico"}
# States the data covers -- everything else gets a muted fill so it reads
# as "no data here" rather than "0%".
DATA_STATES = {"Washington", "Oregon", "Idaho"}

POPPINS_REG_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf"
POPPINS_MED_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf"

# ---------------------------------------------------------------------------
# Figure geometry
# ---------------------------------------------------------------------------
FIG_WIDTH_IN, FIG_HEIGHT_IN = 10.0, 9.0
FIG_DPI = 200
AXES_RECT = [0.03, 0.135, 0.94, 0.735]  # [left, bottom, width, height], figure fraction
MAP_FRAME_INSET_PX = 22

# ---------------------------------------------------------------------------
# Map domain -- WA/OR/ID with a little padding on every side.
# ---------------------------------------------------------------------------
LON_MIN, LON_MAX = -125.0, -110.7
LAT_MIN, LAT_MAX = 41.45, 49.25
CENTER_LON, CENTER_LAT = -117.85, 45.5

# ---------------------------------------------------------------------------
# Metric definitions
# ---------------------------------------------------------------------------
SNOWFALL_THRESHOLD_IN = 0.1
DEPTH_THRESHOLD_IN = 1.0
DEFAULT_MIN_YEARS = 20

METRICS = {
    "snowfall": {
        "key": "snow", "threshold": SNOWFALL_THRESHOLD_IN,
        "subtitle": f"% of Thanksgivings with Measurable Snowfall (≥{SNOWFALL_THRESHOLD_IN:.1f}\")",
    },
    "depth": {
        "key": "snwd", "threshold": DEPTH_THRESHOLD_IN,
        "subtitle": f"% of Thanksgivings with Snow on the Ground (≥{DEPTH_THRESHOLD_IN:.0f}\" depth)",
    },
}

# ---------------------------------------------------------------------------
# Color table -- fixed bins (not rescaled per map, so a given shade always
# means the same percentage across runs/metrics). Exactly-0% stations get
# their own muted tan so "never on record" stands apart from "rarely".
# Above that, pale ice blue through deep blue and violet to magenta.
# ---------------------------------------------------------------------------
PCT_BINS = [0, 0.001, 5, 10, 15, 20, 30, 40, 50, 75, 100.001]
PCT_COLORS = [
    "#d9cfbf",  # 0%
    "#cfe6f2",  # <5
    "#9fcbe6",  # 5-10
    "#6aaad6",  # 10-15
    "#3f86c2",  # 15-20
    "#2a5fa8",  # 20-30
    "#3d3f99",  # 30-40
    "#6a3399",  # 40-50
    "#a1309b",  # 50-75
    "#d8418f",  # 75-100
]
PCT_TICK_LABELS = ["0", "5", "10", "15", "20", "30", "40", "50", "75", "100"]

# ---------------------------------------------------------------------------
# Labeled cities -- (label, ACIS sid matched against each station's sids,
# text side). Mostly first-order airports; COOP sites where the airport's
# own record is short (Tri-Cities: KPSC only has ~14 Thanksgivings, so
# Kennewick's 1890s-present COOP record is used instead; Bend's long
# record is the COOP site).
# ---------------------------------------------------------------------------
CITY_STATIONS = [
    ("Seattle", "KSEA 5", "left"),
    ("Bellingham", "KBLI 5", "right"),
    ("Portland", "KPDX 5", "left"),
    ("Eugene", "KEUG 5", "left"),
    ("Medford", "KMFR 5", "right"),
    ("Bend", "350694 2", "right"),
    ("Klamath Falls", "KLMT 5", "right"),
    ("Yakima", "KYKM 5", "left"),
    ("Wenatchee", "KEAT 5", "right"),
    ("Tri-Cities", "454154 2", "left"),
    ("Walla Walla", "KALW 5", "right"),
    ("Pendleton", "KPDT 5", "left"),
    ("Spokane", "KGEG 5", "right"),
    ("Lewiston", "KLWS 5", "right"),
    ("Baker City", "KBKE 5", "left"),
    ("Boise", "KBOI 5", "left"),
    ("McCall", "105708 2", "right"),
    ("Idaho Falls", "KIDA 5", "left"),
    ("Pocatello", "KPIH 5", "left"),
]


# ---------------------------------------------------------------------------
# Climatology
# ---------------------------------------------------------------------------
def compute_station_pcts(stations, key, threshold, min_years):
    """Per-station % of valid Thanksgivings meeting the threshold. Returns
    a list of dicts (lon, lat, pct, n, sids, ...) for stations with at
    least min_years valid Thanksgivings, plus the overall year span."""
    out = []
    span_lo, span_hi = 9999, 0
    for uid, s in stations.items():
        valid = {int(y): v[key] for y, v in s["years"].items() if v[key] is not None}
        if len(valid) < min_years:
            continue
        hits = sum(1 for v in valid.values() if v >= threshold)
        span_lo, span_hi = min(span_lo, min(valid)), max(span_hi, max(valid))
        out.append({"uid": uid, "name": s["name"], "state": s["state"], "lon": s["lon"], "lat": s["lat"],
                    "elev_ft": s["elev_ft"], "sids": s["sids"], "n": len(valid), "hits": hits,
                    "pct": 100.0 * hits / len(valid), "first": min(valid), "last": max(valid)})
    return out, span_lo, span_hi


# ---------------------------------------------------------------------------
# Basemap layers
# ---------------------------------------------------------------------------
def load_land():
    with open(LAND_FILE) as f:
        data = json.load(f)
    return [shape(feat["geometry"]) for feat in data["features"] if feat.get("geometry")]


def load_states():
    """(data_state_geoms, other_state_geoms, lake_geoms) -- lakes split out
    so they can be filled as water rather than drawn as state borders."""
    with open(STATES_LAKES_FILE) as f:
        data = json.load(f)
    data_states, other_states, lakes = [], [], []
    for feat in data["features"]:
        props = feat["properties"]
        geom = shape(feat["geometry"])
        if "Lake" in props.get("featurecla", ""):
            lakes.append(geom)
        elif props.get("admin") in TARGET_COUNTRIES:
            (data_states if props.get("name") in DATA_STATES else other_states).append(geom)
    return data_states, other_states, lakes


def load_boundary_lines(path):
    with open(path) as f:
        data = json.load(f)
    return [shape(feat["geometry"]) for feat in data["features"]]


def build_map(metric, min_years, output_path):
    poppins_reg = fm.FontProperties(fname=POPPINS_REG_PATH)
    poppins_semibold = fm.FontProperties(fname=POPPINS_MED_PATH)

    if not DATA_FILE.exists():
        sys.exit(f"{DATA_FILE} not found -- run fetch_climatology.py first.")
    with open(DATA_FILE) as f:
        data = json.load(f)

    cfg = METRICS[metric]
    stns, span_lo, span_hi = compute_station_pcts(data["stations"], cfg["key"], cfg["threshold"], min_years)
    stns = [s for s in stns if LON_MIN <= s["lon"] <= LON_MAX and LAT_MIN <= s["lat"] <= LAT_MAX]
    if not stns:
        sys.exit("No stations met the minimum-years requirement.")
    pcts = np.array([s["pct"] for s in stns])
    print(f"{len(stns)} stations with >= {min_years} valid Thanksgivings ({span_lo}-{span_hi}); "
          f"median {np.median(pcts):.0f}%, max {pcts.max():.0f}%")
    for s in sorted(stns, key=lambda s: -s["pct"])[:8]:
        print(f"  {s['pct']:5.1f}%  {s['hits']:>3}/{s['n']:<3}  {s['name']}, {s['state']} ({s['elev_ft']:.0f} ft)")

    print("Loading basemap layers...")
    land_geoms = load_land()
    data_states, other_states, lake_geoms = load_states()
    admin0_lines = load_boundary_lines(ADMIN0_LINES_FILE)

    pc = ccrs.PlateCarree()
    proj = ccrs.NearsidePerspective(central_longitude=CENTER_LON, central_latitude=CENTER_LAT,
                                    satellite_height=4_000_000)

    fig = plt.figure(figsize=(FIG_WIDTH_IN, FIG_HEIGHT_IN), dpi=FIG_DPI)
    fig.patch.set_facecolor("#f7f6f2")

    ax = fig.add_axes(AXES_RECT, projection=proj)
    ax.set_extent([LON_MIN, LON_MAX, LAT_MIN, LAT_MAX], crs=pc)
    ax.patch.set_facecolor("#dfe8ec")  # water

    ax.add_geometries(land_geoms, crs=pc, facecolor="#e3e1da", edgecolor="none", zorder=1)
    ax.add_geometries(data_states, crs=pc, facecolor="#fbfaf7", edgecolor="none", zorder=1.1)
    ax.add_geometries(lake_geoms, crs=pc, facecolor="#dfe8ec", edgecolor="none", zorder=1.2)
    ax.add_geometries(land_geoms, crs=pc, facecolor="none", edgecolor="#4a6b7a", linewidth=0.8, zorder=1.5)
    ax.add_geometries(other_states, crs=pc, facecolor="none", edgecolor="#8a8172", linewidth=0.7, zorder=2)
    ax.add_geometries(data_states, crs=pc, facecolor="none", edgecolor="#5a4632", linewidth=0.9, zorder=2.1)
    ax.add_geometries(admin0_lines, crs=pc, facecolor="none", edgecolor="#3a2f21", linewidth=1.1, zorder=2.5)

    # Station dots -- drawn lowest-% first so the snowiest (usually
    # mountain) stations sit on top where they cluster with valley sites.
    cmap = ListedColormap(PCT_COLORS)
    norm = BoundaryNorm(PCT_BINS, cmap.N)
    order = np.argsort(pcts, kind="stable")
    lons = np.array([stns[i]["lon"] for i in order])
    lats = np.array([stns[i]["lat"] for i in order])
    ax.scatter(lons, lats, c=pcts[order], cmap=cmap, norm=norm, s=30, marker="o",
               edgecolors="#2b2a26", linewidths=0.45, transform=pc, zorder=10)

    # City labels -- each city's own station dot gets re-drawn larger with
    # a white ring so it's clear which dot the number belongs to.
    by_sid = {}
    for s in stns:
        for sid in s["sids"]:
            by_sid.setdefault(sid, s)
    geodetic_transform = pc._as_mpl_transform(ax)
    stroke = [pe.withStroke(linewidth=2.2, foreground=(0, 0, 0, 0.8))]
    print("City stations:")
    for label, sid, side in CITY_STATIONS:
        s = by_sid.get(sid)
        if s is None:
            print(f"  {label}: {sid} not in the map's station set (too few years?) -- skipped")
            continue
        print(f"  {label}: {s['pct']:.0f}% ({s['hits']}/{s['n']}, {s['first']}-{s['last']}) -- {s['name']}")
        ax.scatter([s["lon"]], [s["lat"]], c=[s["pct"]], cmap=cmap, norm=norm, s=62, marker="o",
                   edgecolors="white", linewidths=1.6, transform=pc, zorder=20)
        dx_pt = 7 if side == "right" else -7
        ha = "left" if side == "right" else "right"
        name_transform = offset_copy(geodetic_transform, fig=fig, x=dx_pt, y=0, units="points")
        txt = ax.text(s["lon"], s["lat"], f"{label} {s['pct']:.0f}%", fontsize=9.25,
                      fontproperties=poppins_semibold, color="white", ha=ha, va="center",
                      zorder=21, transform=name_transform)
        txt.set_path_effects(stroke)

    ax.spines["geo"].set_edgecolor("black")
    ax.spines["geo"].set_linewidth(1.6)

    # Colorbar -- below the map, centered on the rendered map frame, one
    # evenly-sized block per bin (the bins aren't evenly spaced in %, so a
    # proportional bar would squash the low end where most stations live).
    fig.canvas.draw()
    frame_px = ax.get_window_extent()
    frame_left = frame_px.x0 / (FIG_WIDTH_IN * FIG_DPI)
    frame_right = frame_px.x1 / (FIG_WIDTH_IN * FIG_DPI)
    cbar_width, cbar_height = (frame_right - frame_left) * 0.62, 0.018
    cbar_left = (frame_left + frame_right) / 2 - cbar_width / 2
    cbar_bottom = 0.072

    cax = fig.add_axes([cbar_left, cbar_bottom, cbar_width, cbar_height])
    n_bins = len(PCT_COLORS)
    cax.imshow(np.arange(n_bins).reshape(1, -1), aspect="auto", cmap=cmap,
               norm=BoundaryNorm(np.arange(n_bins + 1) - 0.5, n_bins), extent=[0, n_bins, 0, 1])
    for x in range(1, n_bins):
        cax.axvline(x, color="#f7f6f2", linewidth=0.8)
    cax.set_yticks([])
    for spine in cax.spines.values():
        spine.set_edgecolor("#8a887e")
        spine.set_linewidth(0.6)
    # First block is "exactly 0%": its label sits centered under it; the
    # rest are bin edges, labeled at the boundaries (the 0%/<5% boundary
    # itself is left unlabeled).
    tick_pos = [0.5] + list(range(2, n_bins + 1))
    cax.set_xticks(tick_pos)
    cax.set_xticklabels([f"{t}%" for t in PCT_TICK_LABELS])
    cax.tick_params(labelsize=8.5, color="#8a887e", labelcolor="#2b2a26")
    for label in cax.get_xticklabels():
        label.set_fontproperties(poppins_reg)

    # Title & subtitle above the map
    fig.text(0.03, 0.978, "Pacific Northwest Thanksgiving Snow Climatology", fontsize=19,
             fontproperties=poppins_reg, color="#2b2a26", ha="left", va="top")
    fig.text(0.03, 0.938, cfg["subtitle"], fontsize=12.5, fontproperties=poppins_semibold,
             color="#3a3835", ha="left", va="top")
    fig.text(0.03, 0.905,
             f"{len(stns)} WA/OR/ID stations with ≥{min_years} Thanksgivings on record • "
             f"Each station's full period of record, {span_lo}–{span_hi}",
             fontsize=10.5, fontproperties=poppins_reg, color="#5a584f", ha="left", va="top")

    fig.text(0.5, 0.012, "NOAA NCEI / RCC-ACIS daily station data — Ingalls Weather", fontsize=9,
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
        description="Build an Ingalls Weather WA/OR/ID Thanksgiving snow climatology map.")
    parser.add_argument("--metric", choices=sorted(METRICS), default="snowfall",
                        help="snowfall = measurable snow fell (default); depth = snow on the ground.")
    parser.add_argument("--min-years", type=int, default=DEFAULT_MIN_YEARS,
                        help=f"Minimum valid Thanksgivings for a station to plot (default {DEFAULT_MIN_YEARS}).")
    parser.add_argument("--out", type=Path, default=None,
                        help="Output PNG path (default: output/thanksgiving_snow_<metric>.png).")
    args = parser.parse_args()

    out_path = args.out or (OUTPUT_DIR / f"thanksgiving_snow_{args.metric}.png")
    build_map(args.metric, args.min_years, out_path)

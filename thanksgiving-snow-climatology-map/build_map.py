"""
Pacific Northwest Thanksgiving Snow Climatology Map -- builder
Ingalls Weather

Gridded map of the Pacific Northwest (WA/OR/ID plus the visible parts of
BC, AB, MT, WY, UT, NV, and CA) shaded by the percent of Thanksgivings that
had snow, built from every ACIS station's own period of record and spread
onto a ~3 km terrain grid (see grid_climatology()). Land farther than
MAX_STATION_DIST_KM from any qualifying station is left unshaded rather
than extrapolated. Two
metrics (--metric):
  - snowfall (default): measurable snow *fell* on Thanksgiving Day
    (daily snowfall >= SNOWFALL_THRESHOLD_IN, 0.1" -- trace doesn't count).
  - depth: a "white Thanksgiving" -- snow *on the ground* Thanksgiving
    morning (snow depth >= DEPTH_THRESHOLD_IN, 1").

Each station's percentage only counts Thanksgivings it actually has a
valid reading for (missing years are excluded from both numerator and
denominator, not counted as no-snow), and stations with fewer than
--min-years valid Thanksgivings (default 20) are dropped as too thin a
sample to call a climatology.

Gridding (PRISM-style, much simplified): Thanksgiving snow odds are
mostly a function of elevation, which changes far faster than station
spacing in the Cascades, Blues, and central Idaho, so plain distance
interpolation would smear valley and pass stations together. Instead, at
every grid cell, a distance-weighted linear regression of station % on
station elevation is fit to the nearest stations, then evaluated at the
cell's own terrain elevation (ETOPO 2022, ~3 km). Each station's leftover
residual from that fit is then spread back out with short-range weights,
so the grid honors the stations where they are and falls back on the
local elevation relationship between them.

Labels follow the repo's default value-at-location convention (no dot,
name on a 50% black box centered on the point, bold value above it), with
values sampled from the nearest grid cell. Unlike the convention's default,
0% is shown as "0%" rather than name-only -- on this map a 0% is the
point (e.g. Portland), not a missing value.

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
    land_slim.json, states_lakes_slim.json, admin0_boundary_lines.json,
    admin1_boundary_lines.json, pnw_terrain_3km.npz (re-fetched from NCEI
    automatically if missing)

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
import requests
from scipy.ndimage import gaussian_filter, zoom
from scipy.spatial import cKDTree

import cartopy.crs as ccrs
import shapely
from shapely.geometry import shape
from shapely.ops import unary_union
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
ADMIN1_LINES_FILE = MAPS_DIR / "admin1_boundary_lines.json"
ADMIN0_LINES_FILE = MAPS_DIR / "admin0_boundary_lines.json"
TERRAIN_FILE = MAPS_DIR / "pnw_terrain_3km.npz"
LOGO_FILE = ASSETS_DIR / "ingalls_weather_logo.png"

TARGET_COUNTRIES = {"United States of America", "Canada", "Mexico"}

POPPINS_REG_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf"
POPPINS_MED_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf"
POPPINS_SEMIBOLD_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-SemiBold.ttf"
POPPINS_BOLD_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf"

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

# Grid bounds -- padded past the frame so the shading reaches the frame
# edge under the perspective projection's curved corners.
GRID_PAD_DEG = 1.0

# ---------------------------------------------------------------------------
# Borders -- same line-based approach as ../western-us-noaa-outlooks/
# build_map.py (see the long comment above GEOM_SIMPLIFY_TOLERANCE_DEG
# there): state/country borders come from the dedicated admin-1/admin-0
# *line* datasets rather than outlining state polygons, state lines that
# duplicate the US/Canada border are trimmed out (otherwise two diverging
# lines show along the WA/BC border through the San Juans), and each
# coastal state's offshore 3 nm state-waters line is dropped (otherwise a
# phantom line runs parallel to the WA/OR coast and through the Strait of
# Juan de Fuca).
# ---------------------------------------------------------------------------
GEOM_SIMPLIFY_TOLERANCE_DEG = 0.02
BORDER_DENSIFY_SEGMENT_DEG = 0.5
COORD_SNAP_GRID_DEG = 0.001
STATE_COUNTRY_DEDUP_BUFFER_DEG = 0.08
OFFSHORE_LINE_DISTANCE_DEG = 0.02

# ---------------------------------------------------------------------------
# Terrain -- ETOPO 2022 60 arc-second surface elevation from NOAA NCEI,
# block-averaged to 2 arc-minutes (~3 km). Same file/fetch as
# pnw-mslp-precip-map; cached in /maps.
# ---------------------------------------------------------------------------
TERRAIN_LON_MIN, TERRAIN_LON_MAX = -131.0, -106.0
TERRAIN_LAT_MIN, TERRAIN_LAT_MAX = 37.0, 58.0
ETOPO_OPENDAP_URL = ("https://www.ngdc.noaa.gov/thredds/dodsC/global/ETOPO2022/60s/"
                     "60s_surface_elev_netcdf/ETOPO_2022_v1_60s_N90W180_surface.nc")
ETOPO_CELLS_PER_DEG = 60
TERRAIN_BLOCK = 2

# ---------------------------------------------------------------------------
# Gridding parameters (see grid_climatology()).
# ---------------------------------------------------------------------------
GWR_NEIGHBORS = 30            # stations used in each cell's elevation regression
GWR_MIN_BANDWIDTH_KM = 40.0   # Gaussian distance weight's minimum length scale
GWR_BANDWIDTH_NEIGHBOR = 12   # ...or the distance to this many-th neighbor, if larger
GWR_MAX_SLOPE_PCT_PER_M = 0.08  # caps the %-per-meter slope (a 1,000 m climb adds at most 80 pts)
GWR_EXTRAP_ABOVE_M = 400.0    # don't extrapolate further than this above the highest neighbor
GWR_EXTRAP_BELOW_M = 300.0    # ...or below the lowest
RESID_NEIGHBORS = 8
RESID_LENGTH_KM = 20.0        # residual-correction Gaussian length scale
RESID_NUGGET = 0.25           # pulls the residual back toward 0 away from stations
# Land cells farther than this from every qualifying station stay unshaded
# (plain muted land) instead of being extrapolated -- mostly matters in BC
# and AB, where ACIS's GHCN-fed Canadian coverage is thin.
MAX_STATION_DIST_KM = 60.0
FINAL_SMOOTH_SIGMA = 0.8      # grid cells; just takes the edge off single-cell speckle
# Display-only bilinear upsampling of the ~3 km grid, so bin boundaries
# render as smooth curves instead of stair-stepped ~3 km cells. Labels
# still sample the un-upsampled grid.
DISPLAY_UPSAMPLE = 4

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
# means the same percentage across runs/metrics). Under 1% gets its own
# muted tan so "essentially never" stands apart from "rarely." Above that,
# pale ice blue through deep blue and violet to magenta.
# ---------------------------------------------------------------------------
PCT_BINS = [0, 1, 5, 10, 15, 20, 30, 40, 50, 75, 100.001]
PCT_COLORS = [
    "#e2d8c6",  # <1
    "#cfe6f2",  # 1-5
    "#9fcbe6",  # 5-10
    "#6aaad6",  # 10-15
    "#3f86c2",  # 15-20
    "#2a5fa8",  # 20-30
    "#3d3f99",  # 30-40
    "#6a3399",  # 40-50
    "#a1309b",  # 50-75
    "#d8418f",  # 75-100
]
PCT_TICK_LABELS = ["0", "1", "5", "10", "15", "20", "30", "40", "50", "75", "100"]

# ---------------------------------------------------------------------------
# Labels -- the repo's default value-at-location convention (see CLAUDE.md /
# blue-mountains-downslope-map): no dot, name centered on the point on a
# 50% black box, bold value centered just above it. Kept to a short list of
# well-separated places so the larger labels don't collide.
#
# (name, label lon, label lat, sample points). The value shown is the mean
# of the nearest grid cell to each sample point; None means sample at the
# label point itself. "Tri-Cities" is one label at the centroid of
# Kennewick, Pasco and Richland, averaging all three.
# ---------------------------------------------------------------------------
LABELS = [
    ("Bellingham", -122.4787, 48.7519, None),
    ("Astoria", -123.8313, 46.1879, None),
    ("Seattle", -122.3321, 47.6062, None),
    ("Portland", -122.6784, 45.5152, None),
    ("Eugene", -123.0868, 44.0521, None),
    ("Medford", -122.8756, 42.3265, None),
    ("Bend", -121.3153, 44.0582, None),
    ("Wenatchee", -120.3103, 47.4235, None),
    ("Yakima", -120.5059, 46.6021, None),
    ("Tri-Cities", -119.1741, 46.2455, [(-119.1372, 46.2112),    # Kennewick
                                        (-119.1006, 46.2396),    # Pasco
                                        (-119.2845, 46.2856)]),  # Richland
    ("Omak", -119.5273, 48.4110, None),
    ("Spokane", -117.4260, 47.6588, None),
    ("Lewiston", -117.0177, 46.4165, None),
    ("Baker City", -117.8344, 44.7749, None),
    ("Burns", -119.0541, 43.5866, None),
    ("McCall", -116.0987, 44.9110, None),
    ("Boise", -116.2023, 43.6150, None),
    ("Salmon", -113.9213, 45.1758, None),
    ("Twin Falls", -114.4609, 42.5629, None),
    ("Idaho Falls", -112.0362, 43.4917, None),
]
NAME_FONTSIZE = 12.5
VALUE_FONTSIZE = 20
VALUE_GAP_PT = 7.0  # name's half-height + a small gap, in points


# ---------------------------------------------------------------------------
# Station climatology
# ---------------------------------------------------------------------------
def compute_station_pcts(stations, key, threshold, min_years):
    """Per-station % of valid Thanksgivings meeting the threshold. Returns
    a list of dicts for stations with at least min_years valid
    Thanksgivings, plus the overall year span."""
    out = []
    span_lo, span_hi = 9999, 0
    for uid, s in stations.items():
        valid = {int(y): v[key] for y, v in s["years"].items() if v[key] is not None}
        if len(valid) < min_years:
            continue
        hits = sum(1 for v in valid.values() if v >= threshold)
        span_lo, span_hi = min(span_lo, min(valid)), max(span_hi, max(valid))
        out.append({"uid": uid, "name": s["name"], "state": s["state"], "lon": s["lon"], "lat": s["lat"],
                    "elev_ft": s["elev_ft"], "n": len(valid), "hits": hits,
                    "pct": 100.0 * hits / len(valid)})
    return out, span_lo, span_hi


# ---------------------------------------------------------------------------
# Terrain
# ---------------------------------------------------------------------------
def fetch_terrain():
    """Pull ETOPO 2022 60 arc-second surface elevation from NCEI's OPeNDAP
    server (ASCII response -- no netCDF4 dependency), block-average to
    TERRAIN_BLOCK arc-minutes, and cache to TERRAIN_FILE. Same as
    pnw-mslp-precip-map's fetch_terrain()."""
    i0 = round((TERRAIN_LAT_MIN + 90) * ETOPO_CELLS_PER_DEG)
    i1 = round((TERRAIN_LAT_MAX + 90) * ETOPO_CELLS_PER_DEG) - 1
    j0 = round((TERRAIN_LON_MIN + 180) * ETOPO_CELLS_PER_DEG)
    j1 = round((TERRAIN_LON_MAX + 180) * ETOPO_CELLS_PER_DEG) - 1
    url = f"{ETOPO_OPENDAP_URL}.ascii?z%5B{i0}:1:{i1}%5D%5B{j0}:1:{j1}%5D"
    print(f"Fetching ETOPO 2022 terrain ({i1 - i0 + 1}x{j1 - j0 + 1} cells) from NCEI ...")
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    _, body = resp.text.split("-" * 20, 1)
    rows = [line.split(",", 1)[1] for line in body.splitlines() if line.startswith("[")]
    elev = np.array([np.fromstring(r, sep=",") for r in rows], dtype=np.float32)
    lat = (np.arange(i0, i1 + 1) + 0.5) / ETOPO_CELLS_PER_DEG - 90
    lon = (np.arange(j0, j1 + 1) + 0.5) / ETOPO_CELLS_PER_DEG - 180
    b = TERRAIN_BLOCK
    ny, nx = (elev.shape[0] // b) * b, (elev.shape[1] // b) * b
    elev = elev[:ny, :nx].reshape(ny // b, b, nx // b, b).mean(axis=(1, 3))
    lat = lat[:ny].reshape(-1, b).mean(axis=1)
    lon = lon[:nx].reshape(-1, b).mean(axis=1)
    np.savez_compressed(TERRAIN_FILE, lat=lat, lon=lon, elev_m=np.round(elev).astype(np.int16))
    print(f"Cached terrain to {TERRAIN_FILE}")
    return lat, lon, elev


def load_terrain():
    if not TERRAIN_FILE.exists():
        return fetch_terrain()
    npz = np.load(TERRAIN_FILE)
    return npz["lat"], npz["lon"], npz["elev_m"].astype(np.float32)


# ---------------------------------------------------------------------------
# Gridding
# ---------------------------------------------------------------------------
def to_km(lon, lat):
    """Simple equirectangular km coordinates -- plenty accurate for
    neighbor distances at this domain's size."""
    return np.column_stack([np.asarray(lon) * 111.32 * np.cos(np.radians(CENTER_LAT)),
                            np.asarray(lat) * 110.57])


def local_elevation_fit(tree, st_xy, st_z, st_p, q_xy, q_z):
    """Evaluate, at each query point, a Gaussian-distance-weighted linear
    regression of station % on station elevation over its GWR_NEIGHBORS
    nearest stations. The slope is clamped to [0, GWR_MAX_SLOPE_PCT_PER_M]
    (snow odds don't go *down* with elevation; a handful of stations can
    otherwise fit a wild slope), and the query elevation is clamped to
    within GWR_EXTRAP_BELOW_M / GWR_EXTRAP_ABOVE_M of the neighbors'
    elevation range, so a high peak far above every nearby station doesn't
    get an unbounded extrapolation."""
    dist, idx = tree.query(q_xy, k=GWR_NEIGHBORS)
    bw = np.maximum(dist[:, GWR_BANDWIDTH_NEIGHBOR - 1], GWR_MIN_BANDWIDTH_KM)[:, None]
    w = np.exp(-(dist / bw) ** 2)
    z, p = st_z[idx], st_p[idx]
    wsum = w.sum(axis=1)
    zbar = (w * z).sum(axis=1) / wsum
    pbar = (w * p).sum(axis=1) / wsum
    dz = z - zbar[:, None]
    var = (w * dz * dz).sum(axis=1) / wsum
    cov = (w * dz * (p - pbar[:, None])).sum(axis=1) / wsum
    slope = np.where(var > 50.0 ** 2, cov / np.maximum(var, 1e-6), 0.0)
    slope = np.clip(slope, 0.0, GWR_MAX_SLOPE_PCT_PER_M)
    qz = np.clip(q_z, z.min(axis=1) - GWR_EXTRAP_BELOW_M, z.max(axis=1) + GWR_EXTRAP_ABOVE_M)
    return pbar + slope * (qz - zbar)


def grid_climatology(stns, glon, glat, gelev):
    """Station percentages -> grid. Elevation regression (trend) plus a
    short-range residual correction (see module docstring). Returns the
    grid (same shape as gelev), clipped to 0-100."""
    st_xy = to_km([s["lon"] for s in stns], [s["lat"] for s in stns])
    st_z = np.array([s["elev_m"] for s in stns])
    st_p = np.array([s["pct"] for s in stns])
    tree = cKDTree(st_xy)

    q_xy = to_km(glon.ravel(), glat.ravel())
    trend = local_elevation_fit(tree, st_xy, st_z, st_p, q_xy, gelev.ravel())

    # Residuals at the stations themselves, then spread with short-range
    # Gaussian weights; the nugget term pulls the correction toward zero
    # once a cell is well away from every station.
    st_trend = local_elevation_fit(tree, st_xy, st_z, st_p, st_xy, st_z)
    resid = st_p - st_trend
    dist, idx = tree.query(q_xy, k=RESID_NEIGHBORS)
    w = np.exp(-(dist / RESID_LENGTH_KM) ** 2)
    corr = (w * resid[idx]).sum(axis=1) / (w.sum(axis=1) + RESID_NUGGET)

    grid = (trend + corr).reshape(gelev.shape)
    grid = gaussian_filter(grid, sigma=FINAL_SMOOTH_SIGMA)
    return np.clip(grid, 0.0, 100.0)


# ---------------------------------------------------------------------------
# Basemap layers (see the Borders comment block above)
# ---------------------------------------------------------------------------
def load_land():
    with open(LAND_FILE) as f:
        data = json.load(f)
    return [shapely.set_precision(shape(feat["geometry"]), grid_size=COORD_SNAP_GRID_DEG)
            .simplify(GEOM_SIMPLIFY_TOLERANCE_DEG, preserve_topology=True)
            .segmentize(BORDER_DENSIFY_SEGMENT_DEG)
            for feat in data["features"] if feat.get("geometry")]


def load_lakes():
    with open(STATES_LAKES_FILE) as f:
        data = json.load(f)
    return [shapely.set_precision(shape(feat["geometry"]), grid_size=COORD_SNAP_GRID_DEG)
            .segmentize(BORDER_DENSIFY_SEGMENT_DEG)
            for feat in data["features"] if "Lake" in feat["properties"].get("featurecla", "")]


def load_boundary_lines(path, country_filter):
    with open(path) as f:
        data = json.load(f)
    return [shape(feat["geometry"]).segmentize(BORDER_DENSIFY_SEGMENT_DEG)
            for feat in data["features"] if country_filter(feat["properties"])]


def load_country_lines():
    return load_boundary_lines(
        ADMIN0_LINES_FILE,
        lambda props: props.get("adm0_left") in TARGET_COUNTRIES and props.get("adm0_right") in TARGET_COUNTRIES)


def load_state_lines(country_lines):
    """State/province lines with the stretch duplicating the US/Canada
    border trimmed out and offshore state-waters lines dropped -- same as
    ../western-us-noaa-outlooks/build_map.py's load_state_lines()."""
    lines = load_boundary_lines(ADMIN1_LINES_FILE, lambda props: props.get("adm0_name") in TARGET_COUNTRIES)
    country_buffer = unary_union(country_lines).buffer(STATE_COUNTRY_DEDUP_BUFFER_DEG)
    trimmed = [g for g in (line.difference(country_buffer) for line in lines) if not g.is_empty]
    with open(LAND_FILE) as f:
        land_data = json.load(f)
    land_union = unary_union([shape(feat["geometry"]) for feat in land_data["features"] if feat.get("geometry")])
    return [g for g in trimmed if g.distance(land_union) <= OFFSHORE_LINE_DISTANCE_DEG]


def build_map(metric, min_years, output_path):
    poppins_reg = fm.FontProperties(fname=POPPINS_REG_PATH)
    poppins_med = fm.FontProperties(fname=POPPINS_MED_PATH)
    poppins_semibold = fm.FontProperties(fname=POPPINS_SEMIBOLD_PATH)
    poppins_bold = fm.FontProperties(fname=POPPINS_BOLD_PATH)

    if not DATA_FILE.exists():
        sys.exit(f"{DATA_FILE} not found -- run fetch_climatology.py first.")
    with open(DATA_FILE) as f:
        data = json.load(f)

    cfg = METRICS[metric]
    stns, span_lo, span_hi = compute_station_pcts(data["stations"], cfg["key"], cfg["threshold"], min_years)
    if not stns:
        sys.exit("No stations met the minimum-years requirement.")
    pcts = np.array([s["pct"] for s in stns])
    print(f"{len(stns)} stations with >= {min_years} valid Thanksgivings ({span_lo}-{span_hi}); "
          f"median {np.median(pcts):.0f}%, max {pcts.max():.0f}%")

    # ---- Terrain grid over the (padded) domain ----
    tlat, tlon, telev = load_terrain()
    lat_sel = (tlat >= LAT_MIN - GRID_PAD_DEG) & (tlat <= LAT_MAX + GRID_PAD_DEG)
    lon_sel = (tlon >= LON_MIN - GRID_PAD_DEG) & (tlon <= LON_MAX + GRID_PAD_DEG)
    glat_1d, glon_1d = tlat[lat_sel], tlon[lon_sel]
    gelev = np.maximum(telev[np.ix_(lat_sel, lon_sel)], 0.0)
    glon, glat = np.meshgrid(glon_1d, glat_1d)

    # Station elevation: ACIS metadata (ft) where present, else terrain.
    for s in stns:
        if s["elev_ft"] is not None:
            s["elev_m"] = s["elev_ft"] * 0.3048
        else:
            j, i = np.abs(glon_1d - s["lon"]).argmin(), np.abs(glat_1d - s["lat"]).argmin()
            s["elev_m"] = float(gelev[i, j])

    print(f"Gridding onto {glon.shape[1]}x{glon.shape[0]} terrain cells ...")
    grid = grid_climatology(stns, glon, glat, gelev)

    print("Loading basemap layers...")
    land_geoms = load_land()
    lake_geoms = load_lakes()
    land_union = unary_union(land_geoms)
    country_lines = load_country_lines()
    state_lines = load_state_lines(country_lines)

    # Shade land within MAX_STATION_DIST_KM of a qualifying station.
    st_tree = cKDTree(to_km([s["lon"] for s in stns], [s["lat"] for s in stns]))

    def shade_mask(lon2d, lat2d):
        near = st_tree.query(to_km(lon2d.ravel(), lat2d.ravel()))[0].reshape(lon2d.shape) <= MAX_STATION_DIST_KM
        return near & shapely.contains_xy(land_union, lon2d, lat2d)

    inside = shade_mask(glon, glat)
    # Display grid: bilinear upsample, then mask at the finer resolution so
    # the shading meets the coastline cleanly.
    dlon_1d = np.linspace(glon_1d[0], glon_1d[-1], len(glon_1d) * DISPLAY_UPSAMPLE)
    dlat_1d = np.linspace(glat_1d[0], glat_1d[-1], len(glat_1d) * DISPLAY_UPSAMPLE)
    dgrid = zoom(grid, (len(dlat_1d) / grid.shape[0], len(dlon_1d) / grid.shape[1]), order=1)
    dlon, dlat = np.meshgrid(dlon_1d, dlat_1d)
    grid_masked = np.ma.masked_where(~shade_mask(dlon, dlat), dgrid)
    vis = grid[inside & (glon >= LON_MIN) & (glon <= LON_MAX) & (glat >= LAT_MIN) & (glat <= LAT_MAX)]
    print(f"Shaded grid range in frame: {vis.min():.0f}% - {vis.max():.0f}%")

    # ---- Label values: nearest grid cell, averaged over sample points ----
    def sample(lon, lat):
        return float(grid[np.abs(glat_1d - lat).argmin(), np.abs(glon_1d - lon).argmin()])
    label_vals = {}
    print("Label readout (nearest grid cell, averaged where a label covers several):")
    for name, lon_c, lat_c, samples in LABELS:
        pts = samples or [(lon_c, lat_c)]
        label_vals[name] = float(np.mean([sample(lo, la) for lo, la in pts]))
        print(f"  {name}: {label_vals[name]:.1f}%")

    pc = ccrs.PlateCarree()
    proj = ccrs.NearsidePerspective(central_longitude=CENTER_LON, central_latitude=CENTER_LAT,
                                    satellite_height=4_000_000)

    fig = plt.figure(figsize=(FIG_WIDTH_IN, FIG_HEIGHT_IN), dpi=FIG_DPI)
    fig.patch.set_facecolor("#f7f6f2")

    ax = fig.add_axes(AXES_RECT, projection=proj)
    ax.set_extent([LON_MIN, LON_MAX, LAT_MIN, LAT_MAX], crs=pc)
    ax.patch.set_facecolor("white")

    ax.add_geometries(land_geoms, crs=pc, facecolor="#e3e1da", edgecolor="none", linewidth=0, zorder=1)

    # Shaded grid -- pcolormesh (forward-projects each cell, so no gaps at
    # the frame's curved corners; see dew-point-storm-map's note), with
    # the fixed bins as a BoundaryNorm.
    cmap = ListedColormap(PCT_COLORS)
    norm = BoundaryNorm(PCT_BINS, cmap.N)
    ax.pcolormesh(dlon_1d, dlat_1d, grid_masked, transform=pc, cmap=cmap, norm=norm,
                  shading="nearest", zorder=1.2, rasterized=True)

    ax.add_geometries(lake_geoms, crs=pc, facecolor="white", edgecolor="#4a6b7a", linewidth=0.5, zorder=1.8)
    ax.add_geometries(land_geoms, crs=pc, facecolor="none", edgecolor="#4a6b7a", linewidth=0.8, zorder=1.9)
    ax.add_geometries(state_lines, crs=pc, facecolor="none", edgecolor="#5a4632", linewidth=0.9, zorder=2)
    ax.add_geometries(country_lines, crs=pc, facecolor="none", edgecolor="#3a2f21", linewidth=1.1, zorder=2.5)

    # Labels -- name centered on the point on a 50% black box, value (bold,
    # larger, no box) centered just above it. Repo default convention; see
    # blue-mountains-downslope-map. 0% is shown as a value here, not
    # name-only (see module docstring).
    geodetic_transform = pc._as_mpl_transform(ax)
    name_stroke = [pe.withStroke(linewidth=0.9, foreground=(0, 0, 0, 0.85))]
    value_stroke = [pe.withStroke(linewidth=2.2, foreground=(0, 0, 0, 0.9))]
    for name, lon_c, lat_c, _ in LABELS:
        t = ax.text(lon_c, lat_c, f" {name} ", fontsize=NAME_FONTSIZE, fontproperties=poppins_semibold,
                    color="white", ha="center", va="center", zorder=101, transform=geodetic_transform,
                    # Box pad is uniform, so keep it tiny (short box) and get the side
                    # padding from the space on each end of the name instead.
                    bbox=dict(boxstyle="round,pad=0.04,rounding_size=0.25", facecolor="black",
                              alpha=0.50, edgecolor="none"))
        t.set_path_effects(name_stroke)
        val_tr = offset_copy(geodetic_transform, fig=fig, x=0, y=VALUE_GAP_PT, units="points")
        v = ax.text(lon_c, lat_c, f"{label_vals[name]:.0f}%", fontsize=VALUE_FONTSIZE, fontproperties=poppins_bold,
                    color="white", ha="center", va="bottom", zorder=102, transform=val_tr)
        v.set_path_effects(value_stroke)

    ax.spines["geo"].set_edgecolor("black")
    ax.spines["geo"].set_linewidth(1.6)

    # Colorbar -- below the map, centered on the rendered map frame, one
    # evenly-sized block per bin (the bins aren't evenly spaced in %, so a
    # proportional bar would squash the low end where most of the map is).
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
    cax.set_xticks(range(n_bins + 1))
    cax.set_xticklabels([f"{t}%" for t in PCT_TICK_LABELS])
    cax.tick_params(labelsize=8.5, color="#8a887e", labelcolor="#2b2a26")
    for label in cax.get_xticklabels():
        label.set_fontproperties(poppins_reg)

    # Title & subtitle above the map
    fig.text(0.03, 0.978, "Pacific Northwest Thanksgiving Snow Climatology", fontsize=19,
             fontproperties=poppins_reg, color="#2b2a26", ha="left", va="top")
    fig.text(0.03, 0.938, cfg["subtitle"], fontsize=12.5, fontproperties=poppins_med,
             color="#3a3835", ha="left", va="top")
    fig.text(0.03, 0.905,
             f"Gridded from {len(stns)} stations with ≥{min_years} Thanksgivings on record "
             f"({span_lo}–{span_hi}) + terrain",
             fontsize=10.5, fontproperties=poppins_reg, color="#5a584f", ha="left", va="top")

    fig.text(0.5, 0.012, "NOAA NCEI / RCC-ACIS daily station data, ETOPO 2022 terrain — Ingalls Weather",
             fontsize=9, fontproperties=poppins_reg, color="#8a887e", ha="center", va="bottom")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, facecolor=fig.get_facecolor(), dpi=FIG_DPI)
    plt.close(fig)
    print(f"Saved base map to {output_path}")

    # ---- Composite logo, top-right, snug inside the frame ----
    if LOGO_FILE.exists():
        base = Image.open(output_path).convert("RGB")
        bw, bh = base.size
        arr = np.array(base)
        y = bh // 2
        black_cols = [x for x in range(bw) if (arr[y, x] < 40).all()]
        x = bw // 2
        black_rows = [yy for yy in range(bh) if (arr[yy, x] < 40).all()]
        frame_right = max(black_cols) if black_cols else bw - 20
        frame_top = min(black_rows) if black_rows else 20

        logo = Image.open(LOGO_FILE).convert("RGB")
        target_w = int(bw * 0.08)
        target_h = int(logo.height * target_w / logo.width)
        logo_resized = logo.resize((target_w, target_h), Image.LANCZOS)

        pos = (frame_right - MAP_FRAME_INSET_PX - target_w, frame_top + MAP_FRAME_INSET_PX)
        base.paste(logo_resized, pos)
        base.save(output_path)
        print(f"Composited logo at {pos}")
    else:
        print(f"NOTE: logo not found at {LOGO_FILE}, skipping (map saved without logo).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build an Ingalls Weather Pacific Northwest Thanksgiving snow climatology map.")
    parser.add_argument("--metric", choices=sorted(METRICS), default="snowfall",
                        help="snowfall = measurable snow fell (default); depth = snow on the ground.")
    parser.add_argument("--min-years", type=int, default=DEFAULT_MIN_YEARS,
                        help=f"Minimum valid Thanksgivings for a station to count (default {DEFAULT_MIN_YEARS}).")
    parser.add_argument("--out", type=Path, default=None,
                        help="Output PNG path (default: output/thanksgiving_snow_<metric>.png).")
    args = parser.parse_args()

    out_path = args.out or (OUTPUT_DIR / f"thanksgiving_snow_{args.metric}.png")
    build_map(args.metric, args.min_years, out_path)

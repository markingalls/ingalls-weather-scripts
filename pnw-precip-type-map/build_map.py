"""
Pacific Northwest Precipitation Type + Highs Map -- map builder
Ingalls Weather

Styled map of WA, OR, ID (plus slivers of southern BC, western MT, and
northern CA/NV) for one local (Pacific) day -- tomorrow by default:
  - Shading: where precipitation falls that day, colored by type (rain /
    mix / snow) and shaded light/moderate/heavy by the day's total liquid
    equivalent -- the same idea as a TV "forecast highs and weather" map.
  - Labels: the day's forecast high at a set of select cities.

Everything comes from a single source, ECMWF's free Open Data IFS
distribution (0.25 deg, 3-hourly steps), fetched live via Herbie -- no API
key needed:
  tp      total precipitation (accumulated since init, m of water)
  sf      snowfall (accumulated since init, m of water equivalent)
  ptype   instantaneous precipitation type (WMO code table 4.201)
  mx2t3   max 2m temperature over the preceding 3 hours

Precip type is decided per grid cell from how the day's precipitation
splits between rain, snow, and "mix" (see classify_precip()):
  - snow   = sf increments
  - mix    = tp increments in any 3-hour step whose ptype at the end of the
             step is freezing rain, freezing drizzle, ice pellets, or a
             rain/snow mix
  - rain   = everything else
A cell is "snow" if snow makes up >= SNOW_FRAC_SNOW of the day's total,
"rain" if snow is <= SNOW_FRAC_RAIN and mix is under MIX_FRAC_MIX, and
"mix" otherwise -- so a cell that rains in the morning and changes to snow
in the afternoon reads as mix, the same way a daily TV map would show it.

USAGE
-----
    python build_map.py                        # tomorrow
    python build_map.py --date 2026-11-27
    python build_map.py --file output/snapshot_2026-11-26.npz  # re-render, no fetch

REQUIRES (already checked into /maps at repo root, shared across all
Ingalls Weather map projects):
    land_slim.json, states_lakes_slim.json, admin0_boundary_lines.json

Logo is read from /assets/ingalls_weather_logo.png at repo root.
"""

import argparse
import json
import sys
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# cfgrib's xr.merge (used when Herbie loads a GRIB2 subset) warns about a
# future xarray default that doesn't affect a single-variable subset.
warnings.filterwarnings("ignore", message="In a future version of xarray.*compat", category=FutureWarning)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.patches import Rectangle
from matplotlib.transforms import offset_copy
import numpy as np
from scipy.interpolate import griddata
from scipy.ndimage import gaussian_filter
from herbie import Herbie

import cartopy.crs as ccrs
from shapely import segmentize
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
ADMIN1_LINES_FILE = MAPS_DIR / "admin1_boundary_lines.json"
ADMIN0_LINES_FILE = MAPS_DIR / "admin0_boundary_lines.json"
LOGO_FILE = ASSETS_DIR / "ingalls_weather_logo.png"

POPPINS_REG_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf"
POPPINS_MED_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf"
POPPINS_SEMIBOLD_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-SemiBold.ttf"
POPPINS_BOLD_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf"

LOCAL_TZ = ZoneInfo("America/Los_Angeles")

# ---------------------------------------------------------------------------
# Figure geometry -- fixed output size (2000 x 1568 px at FIG_DPI): a
# 9.4 x 5.39 in map frame with room for titles above and the legend below.
# The map's zoom is fit to this frame (see MAP_EXTENT), not the other way
# around.
# ---------------------------------------------------------------------------
FIG_WIDTH_IN = 10.0
FIG_DPI = 200
AXES_LEFT, AXES_WIDTH_FRAC = 0.03, 0.94
AXES_BOTTOM_IN, AXES_TOP_GAP_IN = 1.45, 1.00   # room for legend below / titles above
_axes_h_in = 5.3893
FIG_HEIGHT_IN = AXES_BOTTOM_IN + _axes_h_in + AXES_TOP_GAP_IN
AXES_RECT = [AXES_LEFT, AXES_BOTTOM_IN / FIG_HEIGHT_IN, AXES_WIDTH_FRAC, _axes_h_in / FIG_HEIGHT_IN]
MAP_FRAME_INSET_PX = 22

# ---------------------------------------------------------------------------
# Map domain / projection -- Lambert Conformal Conic centered on WA/OR/ID,
# standard parallels bracketing the region (shapes and east-west scale stay
# true, unlike PlateCarree's ~40% horizontal stretch at 45N). The frame
# spans LAT_MIN..LAT_MAX along the central meridian -- enough to fit
# Bellingham's value label at the top and Medford at the bottom -- and its
# width follows from the frame's fixed aspect ratio, which takes in the
# coast to the west and Great Falls to the east.
# ---------------------------------------------------------------------------
CENTER_LON = -117.6
LAT_MIN, LAT_MAX = 41.95, 49.45
PROJ = ccrs.LambertConformal(central_longitude=CENTER_LON,
                             central_latitude=(LAT_MIN + LAT_MAX) / 2,
                             standard_parallels=(43.0, 48.0))


def projected_extent():
    """[x0, x1, y0, y1] in PROJ coordinates: LAT_MIN..LAT_MAX tall along the
    central meridian, as wide as the frame's aspect ratio allows."""
    pts = PROJ.transform_points(ccrs.PlateCarree(), np.array([CENTER_LON, CENTER_LON]),
                                np.array([LAT_MIN, LAT_MAX]))
    y0, y1 = pts[0, 1], pts[1, 1]
    half_w = (y1 - y0) * (FIG_WIDTH_IN * AXES_WIDTH_FRAC / _axes_h_in) / 2
    return [-half_w, half_w, y0, y1]


MAP_EXTENT = projected_extent()


def extent_lonlat_bounds():
    """Lon/lat bounding box of the projected frame (for cropping fetches)."""
    x0, x1, y0, y1 = MAP_EXTENT
    xs = np.concatenate([np.linspace(x0, x1, 50), np.full(50, x1), np.linspace(x1, x0, 50), np.full(50, x0)])
    ys = np.concatenate([np.full(50, y0), np.linspace(y0, y1, 50), np.full(50, y1), np.linspace(y1, y0, 50)])
    ll = ccrs.PlateCarree().transform_points(PROJ, xs, ys)
    return ll[:, 0].min(), ll[:, 0].max(), ll[:, 1].min(), ll[:, 1].max()


LON_MIN, LON_MAX, _LAT_LO, _LAT_HI = extent_lonlat_bounds()

FETCH_PAD_DEG = 1.5

# Precip is resampled straight onto a regular grid in PROJ's own (x, y)
# meters, one cell per output pixel of the map frame, and drawn with
# imshow. Resampling on a lon/lat grid instead and letting cartopy project
# it rotates that grid's cells under LCC, so categorical edges come out as
# visible stair-steps; a pixel-aligned projected grid has none.
GRID_NX = int(round(FIG_WIDTH_IN * AXES_WIDTH_FRAC * FIG_DPI))
GRID_NY = int(round(_axes_h_in * FIG_DPI))
# Gaussian smoothing applied to the precip fields before classifying, so
# 0.25 deg (~25 km) cell edges round off into natural curves. ~11 km --
# under the native grid spacing, so it doesn't smear real features.
SMOOTH_KM = 11.0
# Boundary geometries are densified to this vertex spacing (deg) before
# drawing: Natural Earth stores straight-in-lon/lat borders like the 49th
# parallel with very few vertices, which LCC would otherwise draw as
# straight chords instead of following the parallel's curve.
DENSIFY_DEG = 0.05

# ---------------------------------------------------------------------------
# ECMWF IFS (Open Data, via Herbie) -- 0.25 deg, 3-hourly steps.
# ---------------------------------------------------------------------------
STEP_HOURS = 3
# Local-hour window the high is taken over: mx2t3 at each step is the max
# over the 3 hours *ending* at that step, so steps ending 10am..7pm cover
# roughly 7am-7pm -- the window that reliably contains the daily peak.
HIGH_WINDOW_LOCAL = (8, 20)

# WMO code table 4.201 values ECMWF's ptype uses that count as "mix":
# 3 freezing rain, 7 mixed rain/snow, 8 ice pellets, 12 freezing drizzle.
PTYPE_MIX_CODES = (3, 7, 8, 12)

# ---------------------------------------------------------------------------
# Precip classification -- daily totals in inches of liquid equivalent.
# ---------------------------------------------------------------------------
MM_PER_IN = 25.4
INTENSITY_THRESHOLDS_IN = (0.01, 0.10, 0.50)   # light / moderate / heavy floors
INTENSITY_LABELS = ("Light", "Moderate", "Heavy")
SNOW_FRAC_SNOW = 0.65   # >= this share of the day's total as snow -> snow
SNOW_FRAC_RAIN = 0.35   # <= this share as snow (and little mix) -> rain
MIX_FRAC_MIX = 0.30     # >= this share falling as ptype-mix -> mix

PRECIP_TYPES = ("Rain", "Mix", "Snow")
# Three shades per type, light -> heavy. Same hue families as the TV maps
# (green rain, purple mix, blue snow) but toned to sit with this repo's
# muted basemap palette rather than broadcast-neon.
PRECIP_COLORS = {
    "Rain": ["#a6dba0", "#5aae61", "#1b7837"],
    "Mix":  ["#d4b9da", "#b07cc6", "#7b3f9e"],
    "Snow": ["#b9e0f7", "#6baed6", "#2b6cb0"],
}
PRECIP_ALPHA = 0.88

# Same label set as ../thanksgiving-snow-climatology-map/ (the repo's
# standard PNW city list for this domain).
CITIES = [
    # (name, lon, lat[, (dx_pt, dy_pt)]) -- the optional offset nudges the
    # whole label (box + value) off the point to keep it from crowding a
    # neighbor; the high is still sampled at the city's actual lon/lat.
    ("Bellingham", -122.4787, 48.7519),
    ("Astoria", -123.8313, 46.1879),
    ("Seattle", -122.3321, 47.6062),
    ("Portland", -122.6784, 45.5152, (10, -6)),      # off Astoria
    ("Eugene", -123.0868, 44.0521),
    ("Medford", -122.8756, 42.3265),
    ("Bend", -121.3153, 44.0582),
    ("Wenatchee", -120.3103, 47.4235),
    ("Yakima", -120.5059, 46.6021),
    ("Tri-Cities", -119.1741, 46.2455, (8, -14)),    # off Yakima
    ("Omak", -119.5273, 48.4110),
    ("Spokane", -117.4260, 47.6588),
    ("Lewiston", -117.0177, 46.4165),
    ("Baker City", -117.8344, 44.7749),
    ("Burns", -119.0541, 43.5866),
    ("McCall", -116.0987, 44.9110),
    ("Boise", -116.2023, 43.6150),
    ("Salmon", -113.9213, 45.1758),
    ("Ketchum", -114.3637, 43.6807),
    ("Kalispell", -114.3129, 48.1958),
    ("Missoula", -113.9940, 46.8721),
    ("Butte", -112.5348, 46.0038),
    ("Great Falls", -111.3008, 47.5053),
    ("Havre", -109.6841, 48.5500),
    ("Twin Falls", -114.4609, 42.5629),
    ("Idaho Falls", -112.0362, 43.4917),
    ("Bozeman", -111.0429, 45.6770),
    ("La Push", -124.6365, 47.9087),
    ("Coos Bay", -124.2179, 43.3665),
    ("Old Faithful", -110.8281, 44.4605),
    ("Afton", -110.9318, 42.7247, (8, -14)),         # off Idaho Falls
]
# Label style -- the repo default (see ../thanksgiving-snow-climatology-map/
# and blue-mountains-downslope-map): name centered on the point in a 50%
# black rounded box, value in bold just above it. Sizes scaled down a touch
# from that map's 12.5/20 pt for this shorter frame.
NAME_FONTSIZE = 11.5
VALUE_FONTSIZE = 18
VALUE_GAP_PT = 6.5  # name's half-height + a small gap, in points


# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------
def k_to_f(k):
    return (k - 273.15) * 9 / 5 + 32


# ---------------------------------------------------------------------------
# ECMWF IFS run selection / step snapping (same approach as
# ../dew-point-storm-map/build_map.py and ../columbia-basin-temps/).
# ---------------------------------------------------------------------------
def local_day_bounds_utc(date):
    start = datetime(date.year, date.month, date.day, 0, tzinfo=LOCAL_TZ)
    end = start + timedelta(days=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def select_ecmwf_run(last_valid_time):
    """Latest IFS run whose files already reach last_valid_time (checked by
    probing the last step actually needed, since Open Data posts a run's
    steps progressively)."""
    now = datetime.now(timezone.utc)
    latest_cycle = now.replace(hour=(now.hour // 6) * 6, minute=0, second=0, microsecond=0)
    for lookback_cycles in range(12):
        candidate = latest_cycle - timedelta(hours=6 * lookback_cycles)
        last_fxx = int(np.ceil((last_valid_time - candidate).total_seconds() / 3600 / STEP_HOURS) * STEP_HOURS)
        # 06z/18z runs only go out to 90h in Open Data, 00z/12z to 144h+ at 3-hourly.
        max_fxx = 90 if candidate.hour in (6, 18) else 144
        if last_fxx > max_fxx:
            continue
        if Herbie(candidate.replace(tzinfo=None), model="ifs", product="oper", fxx=last_fxx,
                  verbose=False).grib is not None:
            return candidate
    sys.exit("Could not find an ECMWF IFS run covering the requested date.")


def day_step_list(date, run_init):
    """3-hourly fxx steps bracketing the local day: the step at/just before
    local midnight through the step at/just after the next local midnight.
    Accumulated-field differences across consecutive steps then cover the
    whole day (plus at most a couple hours' slop either side, since 3-hourly
    steps don't land exactly on Pacific midnight)."""
    start_utc, end_utc = local_day_bounds_utc(date)
    f0 = (start_utc - run_init).total_seconds() / 3600
    f1 = (end_utc - run_init).total_seconds() / 3600
    first = max(int(np.floor(f0 / STEP_HOURS)) * STEP_HOURS, 0)
    last = int(np.ceil(f1 / STEP_HOURS)) * STEP_HOURS
    # Pick the bracketing that's closest to the true day boundaries.
    if f0 - first > STEP_HOURS / 2:
        first += STEP_HOURS
    if last - f1 > STEP_HOURS / 2:
        last -= STEP_HOURS
    return list(range(first, last + 1, STEP_HOURS))


def high_step_list(date, run_init):
    h0, h1 = HIGH_WINDOW_LOCAL
    steps = []
    for fxx in day_step_list(date, run_init):
        local = (run_init + timedelta(hours=fxx)).astimezone(LOCAL_TZ)
        if local.date() == date and h0 + STEP_HOURS - 1 <= local.hour <= h1:
            steps.append(fxx)
    return steps


def fetch_day(date):
    """Fetch ECMWF IFS tp/sf/ptype/mx2t3 across the local day, cropped to
    the map bbox. Returns a dict of 2D arrays plus run_init."""
    start_utc, end_utc = local_day_bounds_utc(date)
    run_init = select_ecmwf_run(end_utc)
    fxxs = day_step_list(date, run_init)
    high_fxxs = set(high_step_list(date, run_init))

    lat = lon = lat_idx = lon_idx = None
    prev_tp = prev_sf = None
    total_tp = snow = mix = high_k = None

    def crop(ds, var):
        return ds[var].values[np.ix_(lat_idx, lon_idx)].astype(np.float32)

    for i, fxx in enumerate(fxxs):
        params = ["tp", "sf", "ptype"] + (["mx2t3"] if fxx in high_fxxs else [])
        print(f"Fetching ECMWF IFS {run_init:%Y-%m-%d %H}z F{fxx:03d} ({', '.join(params)}) ...")
        H = Herbie(run_init.replace(tzinfo=None), model="ifs", product="oper", fxx=fxx, verbose=False)
        # Anchored on colons -- Herbie's plain-substring search would
        # otherwise also match e.g. "tprate" against "tp".
        ds_tp = H.xarray(":tp:")

        if lat is None:
            lat_1d, lon_1d = ds_tp.latitude.values, ds_tp.longitude.values
            lon_1d = np.where(lon_1d > 180, lon_1d - 360, lon_1d)
            lat_idx = np.where((lat_1d >= _LAT_LO - FETCH_PAD_DEG) & (lat_1d <= _LAT_HI + FETCH_PAD_DEG))[0]
            lon_idx = np.where((lon_1d >= LON_MIN - FETCH_PAD_DEG) & (lon_1d <= LON_MAX + FETCH_PAD_DEG))[0]
            lon, lat = np.meshgrid(lon_1d[lon_idx], lat_1d[lat_idx])
            total_tp = np.zeros(lat.shape, dtype=np.float32)
            snow = np.zeros(lat.shape, dtype=np.float32)
            mix = np.zeros(lat.shape, dtype=np.float32)
            high_k = np.full(lat.shape, -np.inf, dtype=np.float32)

        tp = crop(ds_tp, "tp")
        sf = crop(H.xarray(":sf:"), "sf")
        ptype = crop(H.xarray(":ptype:"), "ptype")
        if fxx in high_fxxs:
            high_k = np.maximum(high_k, crop(H.xarray(":mx2t3:"), "mx2t3"))

        if i > 0:
            d_tp = np.clip(tp - prev_tp, 0, None)
            d_sf = np.clip(np.minimum(sf - prev_sf, d_tp), 0, None)
            is_mix = np.isin(np.rint(ptype), PTYPE_MIX_CODES)
            total_tp += d_tp
            snow += d_sf
            mix += np.where(is_mix, d_tp - d_sf, 0)
        prev_tp, prev_sf = tp, sf

    return dict(lat=lat, lon=lon, total_tp_m=total_tp, snow_m=snow, mix_m=mix, high_k=high_k,
                run_init=run_init.isoformat())


# ---------------------------------------------------------------------------
# Resampling / classification
# ---------------------------------------------------------------------------
def projected_grid_axes():
    """Cell-center x/y (PROJ meters) of the pixel-aligned map grid."""
    x0, x1, y0, y1 = MAP_EXTENT
    dx, dy = (x1 - x0) / GRID_NX, (y1 - y0) / GRID_NY
    return (np.linspace(x0 + dx / 2, x1 - dx / 2, GRID_NX),
            np.linspace(y0 + dy / 2, y1 - dy / 2, GRID_NY))


def resample_to_projected_grid(lat, lon, values_list):
    """Linearly interpolate one or more fields on the source lon/lat grid
    onto the pixel-aligned PROJ grid. The Delaunay triangulation is shared
    across fields."""
    from scipy.interpolate import LinearNDInterpolator
    from scipy.spatial import Delaunay
    src = PROJ.transform_points(ccrs.PlateCarree(), np.ravel(lon), np.ravel(lat))[:, :2]
    tri = Delaunay(src)
    gx, gy = np.meshgrid(*projected_grid_axes())
    out = []
    for values in values_list:
        out.append(LinearNDInterpolator(tri, np.ravel(values))(gx, gy))
    return out


def sample_points(lat, lon, values, lon_pts, lat_pts):
    """Linear interpolation of a source-grid field at arbitrary points."""
    return griddata(np.column_stack([np.ravel(lon), np.ravel(lat)]), np.ravel(values),
                    (np.asarray(lon_pts), np.asarray(lat_pts)), method="linear")


def classify_precip(total_in, snow_in, mix_in):
    """Return an int grid: 0 = none, else 1 + type_index * 3 + intensity_index
    (type order PRECIP_TYPES, intensity order light/moderate/heavy)."""
    with np.errstate(invalid="ignore", divide="ignore"):
        snow_frac = np.where(total_in > 0, snow_in / total_in, 0)
        mix_frac = np.where(total_in > 0, mix_in / total_in, 0)

    type_idx = np.full(total_in.shape, 1)  # default mix
    type_idx[(snow_frac <= SNOW_FRAC_RAIN) & (mix_frac < MIX_FRAC_MIX)] = 0
    type_idx[(snow_frac >= SNOW_FRAC_SNOW) & (mix_frac < MIX_FRAC_MIX)] = 2

    intensity = np.digitize(total_in, INTENSITY_THRESHOLDS_IN) - 1  # -1 = below light floor
    cat = np.where(intensity >= 0, 1 + type_idx * 3 + np.clip(intensity, 0, 2), 0)
    return cat


# ---------------------------------------------------------------------------
# Basemap layers
# ---------------------------------------------------------------------------
def load_land():
    with open(LAND_FILE) as f:
        data = json.load(f)
    return [segmentize(shape(feat["geometry"]), DENSIFY_DEG) for feat in data["features"] if feat.get("geometry")]


def load_boundary_lines(path):
    """Border *lines* (each border stored once, so neighbors share vertices
    -- same reasoning as ../columbia-basin-temps/), densified so they
    follow parallels' curves under LCC (see DENSIFY_DEG)."""
    with open(path) as f:
        data = json.load(f)
    return [segmentize(shape(feat["geometry"]), DENSIFY_DEG) for feat in data["features"]]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def build_map(date, output_path, override_path=None, high_overrides=None):
    poppins_reg = fm.FontProperties(fname=POPPINS_REG_PATH)
    poppins_semibold = fm.FontProperties(fname=POPPINS_MED_PATH)

    if override_path:
        print(f"Using local snapshot: {override_path}")
        snap = dict(np.load(override_path))
    else:
        snap = fetch_day(date)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        np.savez(OUTPUT_DIR / f"snapshot_{date.isoformat()}.npz", **snap)
    run_init = datetime.fromisoformat(str(snap["run_init"]))
    lat, lon = snap["lat"], snap["lon"]

    print("Resampling onto the projected map grid...")
    m_to_in = 1000 / MM_PER_IN
    gx, gy = projected_grid_axes()
    sigma = SMOOTH_KM * 1000 / (gx[1] - gx[0])
    total_in, snow_in, mix_in = (gaussian_filter(np.nan_to_num(g), sigma) for g in resample_to_projected_grid(
        lat, lon, [snap["total_tp_m"] * m_to_in, snap["snow_m"] * m_to_in, snap["mix_m"] * m_to_in]))

    cat = classify_precip(total_in, snow_in, mix_in)
    for t_i, t in enumerate(PRECIP_TYPES):
        n = ((cat >= 1 + t_i * 3) & (cat <= 3 + t_i * 3)).sum()
        print(f"  {t}: {100 * n / cat.size:.1f}% of map")
    print(f"Max daily precip: {total_in.max():.2f} in")

    city_highs_f = k_to_f(sample_points(lat, lon, snap["high_k"],
                                        [c[1] for c in CITIES], [c[2] for c in CITIES]))

    print("Loading basemap layers...")
    land_geoms = load_land()
    admin1_lines = load_boundary_lines(ADMIN1_LINES_FILE)
    admin0_lines = load_boundary_lines(ADMIN0_LINES_FILE)

    # Lambert Conformal (see PROJ above).
    pc = ccrs.PlateCarree()
    fig = plt.figure(figsize=(FIG_WIDTH_IN, FIG_HEIGHT_IN), dpi=FIG_DPI)
    fig.patch.set_facecolor("#f7f6f2")

    ax = fig.add_axes(AXES_RECT, projection=PROJ)
    ax.set_extent(MAP_EXTENT, crs=PROJ)
    ax.patch.set_facecolor("#bfe1ef")  # pastel ocean, same as ../wildcad-fires-map/

    ax.add_geometries(land_geoms, crs=pc, facecolor="#d7dcd0", edgecolor="none", zorder=1)

    # Precip shading -- categorical, drawn pixel-for-pixel from the projected
    # grid with nearest interpolation, so neighboring categories never blend
    # into colors that aren't on the legend.
    colors = [c for t in PRECIP_TYPES for c in PRECIP_COLORS[t]]
    cmap = ListedColormap(colors)
    norm = BoundaryNorm(np.arange(0.5, len(colors) + 1.5), cmap.N)
    ax.imshow(np.ma.masked_equal(cat, 0), origin="lower", extent=MAP_EXTENT, transform=PROJ,
              cmap=cmap, norm=norm, interpolation="nearest", alpha=PRECIP_ALPHA, zorder=1.2)

    ax.add_geometries(land_geoms, crs=pc, facecolor="none", edgecolor="#4a6b7a", linewidth=0.8, zorder=1.5)
    ax.add_geometries(admin1_lines, crs=pc, facecolor="none", edgecolor="#5a4632", linewidth=0.8, zorder=2)
    ax.add_geometries(admin0_lines, crs=pc, facecolor="none", edgecolor="#3a2f21", linewidth=1.1, zorder=2.5)

    # City labels -- repo default style (see NAME_FONTSIZE above).
    poppins_bold = fm.FontProperties(fname=POPPINS_BOLD_PATH)
    poppins_sb = fm.FontProperties(fname=POPPINS_SEMIBOLD_PATH)
    geodetic_transform = pc._as_mpl_transform(ax)
    name_stroke = [pe.withStroke(linewidth=0.9, foreground=(0, 0, 0, 0.85))]
    value_stroke = [pe.withStroke(linewidth=2.2, foreground=(0, 0, 0, 0.9))]
    x0, x1, y0, y1 = MAP_EXTENT
    high_overrides = high_overrides or {}
    unknown = set(high_overrides) - {c[0] for c in CITIES}
    if unknown:
        sys.exit(f"--set-high: unknown city {sorted(unknown)}")
    for (name, lon_c, lat_c, *opt), city_f in zip(CITIES, city_highs_f):
        if name in high_overrides:
            print(f"  {name}: high set to {high_overrides[name]} (model {city_f:.0f})")
            city_f = high_overrides[name]
        dx_pt, dy_pt = opt[0] if opt else (0, 0)
        name_tr = offset_copy(geodetic_transform, fig=fig, x=dx_pt, y=dy_pt, units="points")
        px, py = PROJ.transform_point(lon_c, lat_c, pc)
        if not (x0 <= px <= x1 and y0 <= py <= y1):
            continue
        t = ax.text(lon_c, lat_c, f" {name} ", fontsize=NAME_FONTSIZE, fontproperties=poppins_sb,
                    color="white", ha="center", va="center", zorder=101, transform=name_tr,
                    bbox=dict(boxstyle="round,pad=0.04,rounding_size=0.25", facecolor="black",
                              alpha=0.50, edgecolor="none"))
        t.set_path_effects(name_stroke)
        val_tr = offset_copy(geodetic_transform, fig=fig, x=dx_pt, y=dy_pt + VALUE_GAP_PT, units="points")
        v = ax.text(lon_c, lat_c, f"{city_f:.0f}°", fontsize=VALUE_FONTSIZE, fontproperties=poppins_bold,
                    color="white", ha="center", va="bottom", zorder=102, transform=val_tr)
        v.set_path_effects(value_stroke)

    ax.spines['geo'].set_edgecolor('black')
    ax.spines['geo'].set_linewidth(1.6)

    # Legend -- a segmented bar below the map: three shades per type, type
    # name above each group, light/heavy and the liquid-equivalent
    # thresholds below. Centered on the rendered map frame.
    fig.canvas.draw()
    frame_px = ax.get_window_extent()
    fig_w_px = FIG_WIDTH_IN * FIG_DPI
    frame_left, frame_right = frame_px.x0 / fig_w_px, frame_px.x1 / fig_w_px
    leg_w = (frame_right - frame_left) * 0.62
    leg_h_in = 0.17
    leg_bottom = 0.74 / FIG_HEIGHT_IN
    leg_left = (frame_left + frame_right) / 2 - leg_w / 2
    lax = fig.add_axes([leg_left, leg_bottom, leg_w, leg_h_in / FIG_HEIGHT_IN])
    lax.set_xlim(0, 1)
    lax.set_ylim(0, 1)
    lax.axis("off")
    group_gap = 0.03
    group_w = (1 - group_gap * (len(PRECIP_TYPES) - 1)) / len(PRECIP_TYPES)
    for t_i, t in enumerate(PRECIP_TYPES):
        x0 = t_i * (group_w + group_gap)
        sw = group_w / 3
        for s_i, c in enumerate(PRECIP_COLORS[t]):
            lax.add_patch(Rectangle((x0 + s_i * sw, 0), sw, 1, facecolor=c, alpha=PRECIP_ALPHA,
                                    edgecolor="none"))
        lax.add_patch(Rectangle((x0, 0), group_w, 1, facecolor="none", edgecolor="#8a887e", linewidth=0.6))
        lax.text(x0 + group_w / 2, 1.35, t.upper(), fontproperties=poppins_semibold, fontsize=10,
                 color="#2b2a26", ha="center", va="bottom")
        lax.text(x0 + 0.005, -0.25, "Light", fontproperties=poppins_reg, fontsize=8,
                 color="#5a584f", ha="left", va="top")
        lax.text(x0 + group_w - 0.005, -0.25, "Heavy", fontproperties=poppins_reg, fontsize=8,
                 color="#5a584f", ha="right", va="top")

    thresh_txt = ", ".join(f"{lbl} ≥ {v:.2f} in".replace(" 0.", " .", 1)
                           for lbl, v in zip(INTENSITY_LABELS, INTENSITY_THRESHOLDS_IN))
    fig.text(0.5, 0.28 / FIG_HEIGHT_IN,
             f"Day's total liquid equivalent: {thresh_txt}  •  City values: forecast high (°F)",
             fontsize=8, fontproperties=poppins_reg, color="#5a584f", ha="center", va="bottom")

    # Title & subtitle above the map
    top = 1 - 0.18 / FIG_HEIGHT_IN
    fig.text(0.03, top, f"{date.strftime('%A')} Forecast Highs & Precipitation", fontsize=21,
             fontproperties=poppins_reg, color="#2b2a26", ha="left", va="top")
    fig.text(0.03, top - 0.48 / FIG_HEIGHT_IN, f"{date.strftime('%B')} {date.day}, {date.year}  •  "
             f"ECMWF IFS 0.25°  •  Init {run_init.strftime('%Y-%m-%d %H')}z",
             fontsize=11, fontproperties=poppins_reg, color="#5a584f", ha="left", va="top")

    fig.text(0.5, 0.04 / FIG_HEIGHT_IN, "ECMWF IFS — Ingalls Weather", fontsize=9,
             fontproperties=poppins_reg, color="#8a887e", ha="center", va="bottom")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, facecolor=fig.get_facecolor(), dpi=FIG_DPI)
    plt.close(fig)
    print(f"Saved base map to {output_path}")

    # ---- Composite logo, bottom-left, snug inside the frame ----
    if LOGO_FILE.exists():
        base = Image.open(output_path).convert("RGB")
        bw, bh = base.size
        logo = Image.open(LOGO_FILE).convert("RGB")
        target_w = int(bw * 0.075)
        target_h = int(logo.height * target_w / logo.width)
        logo_resized = logo.resize((target_w, target_h), Image.LANCZOS)
        # Frame position straight from the axes' rendered extent (y flipped:
        # matplotlib's origin is bottom-left, PIL's top-left).
        pos = (int(frame_px.x0) + MAP_FRAME_INSET_PX, bh - int(frame_px.y0) - MAP_FRAME_INSET_PX - target_h)
        base.paste(logo_resized, pos)
        base.save(output_path)
        print(f"Composited logo at {pos}")
    else:
        print(f"NOTE: logo not found at {LOGO_FILE}, skipping (map saved without logo).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build an Ingalls Weather Pacific Northwest precip-type + highs map.")
    parser.add_argument("--date", type=str, default=None,
                        help="Target date, YYYY-MM-DD, local (Pacific) time (default: tomorrow).")
    parser.add_argument("--file", type=Path, default=None,
                        help="Render from a local saved snapshot (.npz) instead of fetching live.")
    parser.add_argument("--set-high", action="append", default=[], metavar="CITY=F",
                        help="Hand-set a city's displayed high (°F), e.g. --set-high Tri-Cities=57. "
                             "Repeatable. Applies to this run only.")
    parser.add_argument("--out", type=Path, default=None,
                        help="Output PNG path (default: output/pnw_precip_type_map_<date>.png).")
    args = parser.parse_args()

    if args.file and not args.file.exists():
        sys.exit(f"--file {args.file} not found.")

    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        target_date = datetime.now(LOCAL_TZ).date() + timedelta(days=1)

    out_path = args.out or (OUTPUT_DIR / f"pnw_precip_type_map_{target_date.isoformat()}.png")
    overrides = {}
    for item in args.set_high:
        city, _, val = item.rpartition("=")
        if not city:
            sys.exit(f"--set-high expects CITY=F, got {item!r}")
        overrides[city] = int(val)
    build_map(target_date, out_path, override_path=args.file, high_overrides=overrides)

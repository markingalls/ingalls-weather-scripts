"""
Pacific Northwest MSLP + 3-Hour Precipitation Map -- one-off builder
Ingalls Weather

Styled map over the same Pacific Northwest domain as
../dew-point-storm-map/ (Prince George BC (N), Bella Coola BC (W),
Winnemucca NV (S), Yellowstone WY (E)):
  - Shading: WindBorne WeatherMesh-6 (global, 0.25 deg) deterministic (or,
    with --product mean, ensemble-mean) 3-hour total precipitation ending at the valid time, drawn on a ~3 km
    terrain grid. Where that terrain sits at or above the model's freezing
    level, precip is shaded with a snow color table instead of the rain one.
  - Contours: MSLP isobars, every 4 hPa, for the same valid
    time, with "L"/"H" pressure-center markers.
  - Basemap: hillshaded terrain (the same ~3 km grid), so the rain/snow
    split reads against the actual mountains it's following.

The freezing level is derived here, not fetched: WM-6 has no freezing-
level field, so it's interpolated per grid column from the same product's
temperature/geopotential profile on pressure levels -- the *highest*
0 C crossing, matching how GFS's "HGT:0C isotherm" is defined (see
compute_freezing_level()). It's then bilinearly interpolated onto the
terrain grid and compared against terrain height directly. This is the
freezing level, not a snow level -- snow typically reaches ~1,000 ft
below it -- so the snow shading is, if anything, conservative.

USAGE
-----
    python build_map.py                              # tomorrow, 12z
    python build_map.py --valid 2026-10-25T06
    python build_map.py --valid 2026-10-25T06 --product mean  # ensemble mean
    python build_map.py --file output/snapshot_det_2026-10-25T06.npz  # re-render without re-fetching

Requires WB_API_KEY in the environment (see
https://app.windbornesystems.com/api_tokens).

REQUIRES (already checked into /maps at repo root, shared across all
Ingalls Weather map projects):
    land_slim.json, states_lakes_slim.json, admin0_boundary_lines.json,
    pnw_terrain_3km.npz
  pnw_terrain_3km.npz is NOAA NCEI's ETOPO 2022 (60 arc-second surface
  elevation) block-averaged 2x2 to 2 arc-minutes (~3.7 km N-S, ~2.5 km E-W
  at this latitude). If it's missing, fetch_terrain() regenerates it from
  NCEI's THREDDS OPeNDAP server (~20 MB transfer) and caches it there.

Logo is read from /assets/ingalls_weather_logo.png at repo root.
"""

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
from matplotlib.colors import LightSource, LinearSegmentedColormap, Normalize
from matplotlib.transforms import offset_copy
import numpy as np
import requests
import zarr
from remotezip import RemoteZip
from scipy.interpolate import RegularGridInterpolator
from scipy.ndimage import label, maximum_filter, minimum_filter, uniform_filter

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
TERRAIN_FILE = MAPS_DIR / "pnw_terrain_3km.npz"
LOGO_FILE = ASSETS_DIR / "ingalls_weather_logo.png"

TARGET_COUNTRIES = {"United States of America", "Canada"}

# Same pastel land/ocean pair as ../tpw-wm6-ensemble-map/build_map.py.
# Land gets hillshaded (see build_map()); ocean is left flat.
LAND_COLOR = "#F5E7B3"
OCEAN_COLOR = "#D2E8F3"

POPPINS_REG_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf"
POPPINS_MED_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf"
# L/H markers -- see ../tpw-wm6-ensemble-map/build_map.py's BALOO_BOLD_PATH.
BALOO_BOLD_PATH = ASSETS_DIR / "fonts" / "Baloo2-Bold.ttf"

LOCAL_TZ = ZoneInfo("America/Los_Angeles")

# ---------------------------------------------------------------------------
# WindBorne API
# ---------------------------------------------------------------------------
WB_BASE = "https://api.windbornesystems.com/forecasts/v1/wm-6"
PRECIP_VARIABLE = "total_precipitation_3h"
# Which WM-6 product to map. Deterministic is the default: averaging the
# ensemble's differently-placed bands smears 3-hour precip into a broad,
# light field (the 2026-10-25 06z test case peaked at 0.14" in the mean
# vs. 1.9" deterministic), which washes out the terrain-driven rain/snow
# split this map is built to show. The ensemble mean (what
# ../tpw-wm6-ensemble-map/ uses) is still available via --product mean,
# and is the better central estimate at long leads.
PRODUCT_GROUPS = {"mean": "ensemble_mean", "det": "deterministic"}
PRODUCT_LABELS = {"mean": "Ensemble Mean", "det": "Deterministic"}
MSLP_VARIABLE = "pressure_msl"

# Pressure levels used to find the freezing level. 300 hPa (~9 km) is well
# above any realistic freezing level; anything higher is wasted fetch.
FREEZING_LEVEL_LEVELS_HPA = [1000, 975, 950, 925, 900, 850, 800, 750, 700, 650,
                             600, 550, 500, 450, 400, 350, 300]
FREEZING_K = 273.15
GRAVITY = 9.80665  # geopotential (m^2/s^2) -> geopotential height (m)

MSLP_CONTOUR_INTERVAL_HPA = 4

# Smaller than the TPW map's 6 deg -- this domain is roughly a third the
# width, so two genuinely distinct centers can sit closer together here.
PRESSURE_EXTREMA_MIN_SEPARATION_DEG = 4.0

# ---------------------------------------------------------------------------
# Figure geometry -- same as ../dew-point-storm-map/build_map.py (same
# domain, same PlateCarree aspect-ratio match).
# ---------------------------------------------------------------------------
FIG_WIDTH_IN, FIG_HEIGHT_IN = 8.4, 9.0
FIG_DPI = 200
AXES_RECT = [0.03, 0.17, 0.94, 0.70]  # [left, bottom, width, height], figure fraction
MAP_FRAME_INSET_PX = 22

# ---------------------------------------------------------------------------
# Map domain -- same as ../dew-point-storm-map/build_map.py.
# ---------------------------------------------------------------------------
LON_MIN, LON_MAX = -128.2, -108.8
LAT_MIN, LAT_MAX = 39.7, 55.2

# The WM-6 crop is padded much wider than the terrain grid needs, so
# find_pressure_extrema()'s wide background-mean window (3x the separation
# window) has real data to average over near the frame edges.
FETCH_PAD_DEG = 8.0

# Terrain grid bounds (also the render raster's bounds). Padded past the
# plotted extent so imshow's inverse lookup never runs off the raster's
# edge at the frame corners -- see ../columbia-basin-temps/build_map.py's
# RESAMPLE_PAD_DEG comment.
TERRAIN_LON_MIN, TERRAIN_LON_MAX = -131.0, -106.0
TERRAIN_LAT_MIN, TERRAIN_LAT_MAX = 37.0, 58.0

# ETOPO 2022 60 arc-second surface elevation (land topography + ocean
# bathymetry), from NOAA NCEI. Cell-centered global grid starting at
# -89.99167 lat / -179.99167 lon, 1/60 deg spacing -- see fetch_terrain()
# for the index math. Averaged TERRAIN_BLOCK x TERRAIN_BLOCK down to the
# "~3 km" grid this map uses: 2 arc-minutes is ~3.7 km N-S and ~2.5 km E-W
# at 47 N.
ETOPO_OPENDAP_URL = ("https://www.ngdc.noaa.gov/thredds/dodsC/global/ETOPO2022/60s/"
                     "60s_surface_elev_netcdf/ETOPO_2022_v1_60s_N90W180_surface.nc")
ETOPO_CELLS_PER_DEG = 60
TERRAIN_BLOCK = 2

CITIES = [
    ("Bella Coola", -126.7659, 52.3728, "right"),
    ("Vancouver", -123.1207, 49.2827, "left"),
    ("Victoria", -123.3656, 48.4284, "left"),
    ("Kelowna", -119.4960, 49.8880, "right"),
    ("Kamloops", -120.3273, 50.6745, "right"),
    ("Prince George", -122.7497, 53.9171, "right"),
    ("Cranbrook", -115.7697, 49.5097, "right"),
    ("Seattle", -122.3321, 47.6062, "left"),
    ("Spokane", -117.4260, 47.6588, "left"),
    ("Tri-Cities", -119.2781, 46.2565, "right"),
    ("Portland", -122.6784, 45.5152, "left"),
    ("Bend", -121.3153, 44.0582, "left"),
    ("Eugene", -123.0868, 44.0521, "left"),
    ("Medford", -122.8756, 42.3265, "left"),
    ("Redding", -122.3917, 40.5865, "left"),
    ("Boise", -116.2023, 43.6150, "left"),
    ("Twin Falls", -114.4609, 42.5629, "left"),
    ("Idaho Falls", -112.0362, 43.4917, "right"),
    ("Winnemucca", -117.7357, 40.9730, "left"),
    ("Salt Lake City", -111.8910, 40.7608, "right"),
    ("Missoula", -113.9940, 46.8721, "left"),
    ("Great Falls", -111.3008, 47.5053, "right"),
    ("Calgary", -114.0719, 51.0447, "right"),
    ("Edmonton", -113.4938, 53.5461, "right"),
]

# ---------------------------------------------------------------------------
# 3-hour precipitation color tables -- fixed inch-to-RGB control points (not
# rescaled per map), one for rain and one for snow (liquid equivalent, on
# the same inch stops so the two colorbars line up value-for-value). Colors
# are spaced *evenly* across the colorbar by stop index rather than by
# value (see precip_to_index()), so the light end -- where most 3-hour
# totals actually fall -- isn't squeezed into a sliver of the bar.
# ---------------------------------------------------------------------------
PRECIP_STOPS_IN = [0.01, 0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0]
RAIN_RGB_COLORS = [
    [196, 234, 178],
    [126, 204, 112],
    [52, 160, 72],
    [22, 112, 52],
    [244, 222, 64],
    [246, 152, 40],
    [218, 52, 40],
    [156, 22, 92],
]
# Snow: pale ice blue through royal blue to violet/magenta -- reads as
# "cold" at a glance, and distinct from every rain color at every stop.
SNOW_RGB_COLORS = [
    [222, 236, 252],
    [168, 202, 242],
    [108, 156, 228],
    [56, 100, 204],
    [40, 52, 160],
    [104, 42, 172],
    [164, 64, 192],
    [222, 126, 226],
]

# Like the TPW map's floor fade: fully transparent below the first stop,
# ramping to PRECIP_ALPHA_FADE_END by PRECIP_ALPHA_FADE_END_IN, so the
# hillshaded basemap shows through very light totals instead of the data
# switching on abruptly at 0.01". Starting the ramp at fully transparent
# (not partway up) matters at 0.25 deg: anything higher draws the 0.01"
# contour as a hard, blocky-looking edge across broad light-precip areas.
PRECIP_ALPHA_FADE_END_IN = 0.05
PRECIP_ALPHA_FADE_START = 0.0
PRECIP_ALPHA_FADE_END = 0.92

# Hillshade strength: final RGB is multiplied by (1 - k + k * hillshade),
# with k stronger on bare land than under precip shading, so the terrain
# texture still shows through the data without muddying its colors.
HILLSHADE_STRENGTH_LAND = 0.55
HILLSHADE_STRENGTH_PRECIP = 0.30
HILLSHADE_VERT_EXAG = 3.0


def build_precip_colormap(name, rgb_colors):
    n = len(rgb_colors)
    stops = [(i / (n - 1), [c / 255 for c in rgb]) for i, rgb in enumerate(rgb_colors)]
    return LinearSegmentedColormap.from_list(name, stops, N=256)


def precip_to_index(precip_in):
    """Map inches onto colorbar position 0..1, linear between stops (see
    the color tables' comment)."""
    n = len(PRECIP_STOPS_IN)
    return np.interp(precip_in, PRECIP_STOPS_IN, np.linspace(0, 1, n))


def mm_to_in(mm):
    return mm / 25.4


# ---------------------------------------------------------------------------
# Terrain
# ---------------------------------------------------------------------------
def fetch_terrain():
    """Pull ETOPO 2022 60 arc-second surface elevation over the terrain
    grid's bounds from NCEI's OPeNDAP server (ASCII response -- no netCDF4
    dependency needed), block-average to TERRAIN_BLOCK arc-minutes, and
    cache to TERRAIN_FILE. Returns (lat_1d, lon_1d, elev_m_2d)."""
    i0 = round((TERRAIN_LAT_MIN + 90) * ETOPO_CELLS_PER_DEG)
    i1 = round((TERRAIN_LAT_MAX + 90) * ETOPO_CELLS_PER_DEG) - 1
    j0 = round((TERRAIN_LON_MIN + 180) * ETOPO_CELLS_PER_DEG)
    j1 = round((TERRAIN_LON_MAX + 180) * ETOPO_CELLS_PER_DEG) - 1
    url = f"{ETOPO_OPENDAP_URL}.ascii?z%5B{i0}:1:{i1}%5D%5B{j0}:1:{j1}%5D"
    print(f"Fetching ETOPO 2022 terrain ({i1 - i0 + 1}x{j1 - j0 + 1} cells) from NCEI ...")
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()

    # The ASCII body is a header, then one "[row], v, v, v, ..." line per
    # latitude row, then the lat/lon map vectors.
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
# WindBorne WM-6 fetch
# ---------------------------------------------------------------------------
def wb_get(path, api_key, **params):
    headers = {"Authorization": f"Bearer {api_key}"}
    resp = requests.get(f"{WB_BASE}/{path}", headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_zarr_array(remote_zip, names, tmp_dir, array_path):
    """Same as ../tpw-wm6-ensemble-map/build_map.py's -- copy one array's
    metadata + chunk file(s) out of the remote zip and open it with zarr."""
    entries = [n for n in names if n == f"{array_path}/zarr.json" or n.startswith(f"{array_path}/c")]
    for name in entries:
        dest = tmp_dir / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(remote_zip.read(name))
    return zarr.open_array(store=str(tmp_dir), path=array_path, mode="r")[:]


def fetch_wm6_fields(valid_time_utc, api_key, product):
    """Fetch WM-6 3-hour precip, MSLP, and the temperature/
    geopotential profile (for the freezing level) from `product` (see
    PRODUCT_GROUPS) valid at valid_time_utc, cropped to the padded map bbox.

    Uses the same full-file presigned URL + remotezip range-request
    approach as ../tpw-wm6-ensemble-map/build_map.py's fetch_wm6_fields()
    -- see its docstring. That works whether or not the run has been
    archived yet, and pulls the ~36 arrays this map needs out of the
    ~2 GB file in one session.

    Returns (lat_1d, lon_1d, precip_mm_2d, mslp_hpa_2d, freezing_level_m_2d,
    meta dict with initialization_time/valid_time/forecast_hour)."""
    url_info = wb_get("gridded", api_key, variable="all",
                       time=valid_time_utc.strftime("%Y-%m-%dT%H:%M:%SZ"), as_url="true")
    print("Opening WM-6 run via presigned URL (range-request fetch, not a full download)...")

    with RemoteZip(url_info["url"]) as rz:
        names = rz.namelist()
        root_meta = json.loads(rz.read("zarr.json"))["attributes"]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            lat = fetch_zarr_array(rz, names, tmp_dir, "latitude")
            lon = fetch_zarr_array(rz, names, tmp_dir, "longitude")
            lon = ((lon + 180) % 360) - 180
            lat_idx = np.where((lat >= LAT_MIN - FETCH_PAD_DEG) & (lat <= LAT_MAX + FETCH_PAD_DEG))[0]
            lon_idx = np.where((lon >= LON_MIN - FETCH_PAD_DEG) & (lon <= LON_MAX + FETCH_PAD_DEG))[0]
            lon_idx = lon_idx[np.argsort(lon[lon_idx])]

            def crop(array_path):
                return fetch_zarr_array(rz, names, tmp_dir, f"{PRODUCT_GROUPS[product]}/{array_path}")[np.ix_(lat_idx, lon_idx)]

            precip = crop(PRECIP_VARIABLE)
            mslp_pa = crop(MSLP_VARIABLE)
            temps, geopots = [], []
            for level in FREEZING_LEVEL_LEVELS_HPA:
                print(f"  temperature/geopotential {level} hPa ...")
                temps.append(crop(f"temperature_{level}"))
                geopots.append(crop(f"geopotential_{level}"))

    lat_crop, lon_crop = lat[lat_idx], lon[lon_idx]
    freezing_level_m = compute_freezing_level(np.stack(temps), np.stack(geopots) / GRAVITY)

    # WM-6's total_precipitation_3h is already mm (per the array's zarr
    # "units" attribute) -- not meters, as ERA5/IFS store it.
    precip_mm = precip
    mslp_hpa = mslp_pa / 100.0

    if lat_crop[0] > lat_crop[-1]:
        lat_crop = lat_crop[::-1]
        precip_mm, mslp_hpa, freezing_level_m = (a[::-1, :] for a in (precip_mm, mslp_hpa, freezing_level_m))

    meta = {
        "initialization_time": root_meta["initialization_time"],
        "valid_time": root_meta["valid_time"],
        "forecast_hour": root_meta["forecast_hour"],
    }
    return lat_crop, lon_crop, precip_mm, mslp_hpa, freezing_level_m, meta


def compute_freezing_level(temp_k, height_m):
    """Per-column height (m MSL) of the *highest* 0 C crossing in a
    (level, y, x) profile ordered bottom-up (FREEZING_LEVEL_LEVELS_HPA's
    order), linearly interpolated between the two levels that bracket it.
    Highest rather than lowest so a shallow surface-based cold pool under a
    warm layer aloft doesn't drag the freezing level down to the valley
    floor -- the same definition as GFS's "HGT:0C isotherm".

    Levels below the ground (e.g. 1000 hPa under the Rockies) carry the
    model's extrapolated values; that only matters if the crossing itself
    lands underground, where terrain is above it either way.

    Columns with no crossing at all are cold top to bottom -- set to -inf
    so every terrain cell under them counts as above the freezing level."""
    warm = temp_k >= FREEZING_K
    crossing = warm[:-1] & ~warm[1:]  # level k warm, level k+1 above it cold
    n_pairs = crossing.shape[0]
    # Highest crossing index per column (argmax over the flipped stack).
    highest = n_pairs - 1 - np.argmax(crossing[::-1], axis=0)
    has_crossing = crossing.any(axis=0)

    k = highest[None]
    t0, t1 = np.take_along_axis(temp_k, k, 0)[0], np.take_along_axis(temp_k, k + 1, 0)[0]
    z0, z1 = np.take_along_axis(height_m, k, 0)[0], np.take_along_axis(height_m, k + 1, 0)[0]
    frac = (FREEZING_K - t0) / np.where(t1 == t0, -1e-6, t1 - t0)
    level = z0 + frac * (z1 - z0)
    return np.where(has_crossing, level, -np.inf).astype(np.float32)


def interp_to_terrain(lat, lon, values, t_lat, t_lon):
    """Bilinearly interpolate a regular 0.25 deg (lat, lon) field onto the
    terrain grid."""
    interp = RegularGridInterpolator((lat, lon), values, method="linear",
                                     bounds_error=False, fill_value=None)
    t_lon_grid, t_lat_grid = np.meshgrid(t_lon, t_lat)
    return interp((t_lat_grid, t_lon_grid))


def find_pressure_extrema(lat, lon, mslp_hpa):
    """Same approach as ../tpw-wm6-ensemble-map/build_map.py's
    find_pressure_extrema() -- sliding min/max filter, plateau collapse via
    connected-component labeling, then a prominence check against a 3x-
    wider background mean so terrain-reduction ripples don't get marked.
    Returns a list of (lon, lat, value_hpa, "L" or "H") tuples inside the
    visible map box."""
    lat_res = abs(lat[1] - lat[0])
    lon_res = abs(lon[1] - lon[0])
    size_lat = max(3, int(round(PRESSURE_EXTREMA_MIN_SEPARATION_DEG / lat_res)))
    size_lon = max(3, int(round(PRESSURE_EXTREMA_MIN_SEPARATION_DEG / lon_res)))

    local_min = mslp_hpa == minimum_filter(mslp_hpa, size=(size_lat, size_lon), mode="nearest")
    local_max = mslp_hpa == maximum_filter(mslp_hpa, size=(size_lat, size_lon), mode="nearest")
    background = uniform_filter(mslp_hpa, size=(size_lat * 3, size_lon * 3), mode="nearest")

    extrema = []
    for mask, kind, sign in [(local_min, "L", -1), (local_max, "H", 1)]:
        labeled, n_features = label(mask)
        for i in range(1, n_features + 1):
            ys, xs = np.where(labeled == i)
            cy, cx = int(round(ys.mean())), int(round(xs.mean()))
            ex_lon, ex_lat = lon[cx], lat[cy]
            if not (LON_MIN <= ex_lon <= LON_MAX and LAT_MIN <= ex_lat <= LAT_MAX):
                continue
            value = mslp_hpa[cy, cx]
            prominence = sign * (value - background[cy, cx])
            if prominence >= MSLP_CONTOUR_INTERVAL_HPA:
                extrema.append((ex_lon, ex_lat, value, kind))
    return extrema


# ---------------------------------------------------------------------------
# Basemap layers
# ---------------------------------------------------------------------------
def load_land():
    with open(LAND_FILE) as f:
        data = json.load(f)
    return [shape(feat["geometry"]) for feat in data["features"] if feat.get("geometry")]


def load_states():
    """State/province polygons -- lake features dropped so they don't draw
    as if they were a state/province border."""
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


def build_surface_rgb(t_lat, elev_m, precip_in, is_snow):
    """Composite the hillshaded land/ocean basemap and the rain/snow precip
    shading into one RGB raster on the terrain grid. Done as a single
    numpy composite (rather than stacked imshow layers) so the hillshade
    can be multiplied through the precip colors too -- see
    HILLSHADE_STRENGTH_PRECIP."""
    is_land = elev_m > 0
    land_rgb = np.array(matplotlib.colors.to_rgb(LAND_COLOR))
    ocean_rgb = np.array(matplotlib.colors.to_rgb(OCEAN_COLOR))
    rgb = np.where(is_land[..., None], land_rgb, ocean_rgb)

    idx = precip_to_index(precip_in)
    rain_rgb = build_precip_colormap("ingalls_rain_3h", RAIN_RGB_COLORS)(idx)[..., :3]
    snow_rgb = build_precip_colormap("ingalls_snow_3h", SNOW_RGB_COLORS)(idx)[..., :3]
    precip_rgb = np.where(is_snow[..., None], snow_rgb, rain_rgb)

    floor_in = PRECIP_STOPS_IN[0]
    fade = np.clip((precip_in - floor_in) / (PRECIP_ALPHA_FADE_END_IN - floor_in), 0, 1)
    alpha = PRECIP_ALPHA_FADE_START + (PRECIP_ALPHA_FADE_END - PRECIP_ALPHA_FADE_START) * fade
    alpha = np.where(precip_in < floor_in, 0.0, alpha)[..., None]
    rgb = rgb * (1 - alpha) + precip_rgb * alpha

    # Hillshade with real ground spacing -- E-W cell width shrinks with
    # cos(lat), so dx varies by row; LightSource only takes a scalar, so
    # use the domain-center value (the error is small over 21 deg of lat).
    cell_deg = abs(t_lat[1] - t_lat[0])
    dy = cell_deg * 111_320
    dx = dy * np.cos(np.radians(np.mean(t_lat)))
    hs = LightSource(azdeg=315, altdeg=45).hillshade(np.where(is_land, elev_m, 0),
                                                      vert_exag=HILLSHADE_VERT_EXAG, dx=dx, dy=dy)
    # Strength eases from the land value to the precip value along with the
    # precip alpha fade -- switching it hard at the 0.01" floor drew that
    # contour as a visible brightness step across flat terrain.
    precip_weight = alpha[..., 0] / PRECIP_ALPHA_FADE_END
    k = HILLSHADE_STRENGTH_LAND + (HILLSHADE_STRENGTH_PRECIP - HILLSHADE_STRENGTH_LAND) * precip_weight
    shade = np.where(is_land, 1 - k + k * hs, 1.0)[..., None]
    return np.clip(rgb * shade, 0, 1)


def draw_precip_colorbar(fig, rect, rgb_colors, label_text, poppins_reg):
    cmap = build_precip_colormap("cbar", rgb_colors)
    cax = fig.add_axes(rect)
    cax.imshow(np.linspace(0, 1, 256).reshape(1, -1), aspect="auto", cmap=cmap,
               norm=Normalize(0, 1), extent=[0, 1, 0, 1])
    cax.set_yticks([])
    for spine in cax.spines.values():
        spine.set_edgecolor("#8a887e")
        spine.set_linewidth(0.6)
    ticks = precip_to_index(PRECIP_STOPS_IN)
    cax.set_xticks(ticks)
    cax.set_xticklabels([f"{v:g}" for v in PRECIP_STOPS_IN])
    cax.tick_params(labelsize=7.5, color="#8a887e", labelcolor="#2b2a26")
    for lbl in cax.get_xticklabels():
        lbl.set_fontproperties(poppins_reg)
    cax.set_xlabel(label_text, fontsize=8.5, fontproperties=poppins_reg, color="#5a584f")
    return cax


def build_map(valid_time_utc, product, output_path, override_path=None):
    poppins_reg = fm.FontProperties(fname=POPPINS_REG_PATH)
    poppins_semibold = fm.FontProperties(fname=POPPINS_MED_PATH)
    baloo_bold = fm.FontProperties(fname=BALOO_BOLD_PATH)

    if override_path:
        print(f"Using local snapshot: {override_path}")
        npz = np.load(override_path, allow_pickle=True)
        lat, lon = npz["lat"], npz["lon"]
        precip_mm, mslp_hpa, freezing_level_m = npz["precip_mm"], npz["mslp_hpa"], npz["freezing_level_m"]
        meta = npz["meta"].item()
    else:
        api_key = os.environ.get("WB_API_KEY")
        if not api_key:
            sys.exit("WB_API_KEY not set -- get a token at "
                      "https://app.windbornesystems.com/api_tokens, or pass --file "
                      "to render from a saved snapshot instead.")
        lat, lon, precip_mm, mslp_hpa, freezing_level_m, meta = fetch_wm6_fields(valid_time_utc, api_key, product)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        np.savez(OUTPUT_DIR / f"snapshot_{product}_{valid_time_utc:%Y-%m-%dT%H}.npz", lat=lat, lon=lon,
                 precip_mm=precip_mm, mslp_hpa=mslp_hpa, freezing_level_m=freezing_level_m, meta=meta)

    t_lat, t_lon, elev_m = load_terrain()

    finite_fl = freezing_level_m[np.isfinite(freezing_level_m)]
    print(f"3-hr precip max in fetched crop: {mm_to_in(precip_mm.max()):.2f} in")
    print(f"MSLP range in fetched crop: {mslp_hpa.min():.0f} - {mslp_hpa.max():.0f} hPa")
    print(f"Freezing level range: {finite_fl.min():.0f} - {finite_fl.max():.0f} m "
          f"({(~np.isfinite(freezing_level_m)).sum()} fully-subfreezing columns)")
    pressure_extrema = find_pressure_extrema(lat, lon, mslp_hpa)
    print(f"Pressure centers found: {', '.join(f'{k}{v:.0f}' for _, _, v, k in pressure_extrema) or 'none'}")

    # -inf (cold top to bottom) doesn't survive linear interpolation, so
    # swap in a value well below sea level first -- still below every
    # terrain cell, which is all the comparison needs.
    fl_for_interp = np.where(np.isfinite(freezing_level_m), freezing_level_m, -1000.0)
    fl_t = interp_to_terrain(lat, lon, fl_for_interp, t_lat, t_lon)
    precip_in_t = np.clip(mm_to_in(interp_to_terrain(lat, lon, precip_mm, t_lat, t_lon)), 0, None)
    # Ocean cells compare at sea level, not their bathymetric depth.
    is_snow = np.maximum(elev_m, 0) >= fl_t
    surface_rgb = build_surface_rgb(t_lat, elev_m, precip_in_t, is_snow)

    print("Loading basemap layers...")
    land_geoms = load_land()
    state_geoms = load_states()
    admin0_lines = load_boundary_lines(ADMIN0_LINES_FILE)

    # PlateCarree, for the same reason as ../dew-point-storm-map/build_map.py
    # (same domain) -- no blank-corner slack at this domain's shape.
    pc = ccrs.PlateCarree()
    proj = pc

    fig = plt.figure(figsize=(FIG_WIDTH_IN, FIG_HEIGHT_IN), dpi=FIG_DPI)
    fig.patch.set_facecolor("#f7f6f2")

    ax = fig.add_axes(AXES_RECT, projection=proj)
    ax.set_extent([LON_MIN, LON_MAX, LAT_MIN, LAT_MAX], crs=pc)
    ax.patch.set_facecolor(OCEAN_COLOR)

    # Bilinear display interpolation: at this zoom each ~3 km terrain cell
    # spans ~3 screen pixels, which reads as blocky with nearest-neighbor.
    half = abs(t_lat[1] - t_lat[0]) / 2
    ax.imshow(surface_rgb, origin="lower", transform=pc, interpolation="bilinear",
              extent=[t_lon[0] - half, t_lon[-1] + half, t_lat[0] - half, t_lat[-1] + half], zorder=1)

    ax.add_geometries(land_geoms, crs=pc, facecolor="none", edgecolor="#4a6b7a", linewidth=0.8, zorder=1.5)
    ax.add_geometries(state_geoms, crs=pc, facecolor="none", edgecolor="#5a4632", linewidth=0.8, zorder=2)
    ax.add_geometries(admin0_lines, crs=pc, facecolor="none", edgecolor="#3a2f21", linewidth=1.1, zorder=2.5)

    # MSLP isobars -- levels computed from the data's actual range at the
    # standard 4 hPa interval, same as the TPW map. Drawn above the basemap
    # lines so they stay legible over both rain and snow shading.
    level_start = np.floor(mslp_hpa.min() / MSLP_CONTOUR_INTERVAL_HPA) * MSLP_CONTOUR_INTERVAL_HPA
    level_end = np.ceil(mslp_hpa.max() / MSLP_CONTOUR_INTERVAL_HPA) * MSLP_CONTOUR_INTERVAL_HPA
    mslp_levels = np.arange(level_start, level_end + MSLP_CONTOUR_INTERVAL_HPA, MSLP_CONTOUR_INTERVAL_HPA)
    isobars = ax.contour(lon, lat, mslp_hpa, levels=mslp_levels, transform=pc,
                          colors="#3a3a3a", linewidths=1.0, zorder=3)
    labels = ax.clabel(isobars, inline=True, fontsize=7.5, fmt="%d", colors="#3a3a3a")
    for lbl in labels:
        lbl.set_path_effects([pe.withStroke(linewidth=2.0, foreground="white")])

    for ex_lon, ex_lat, _, kind in pressure_extrema:
        color = "#c0392b" if kind == "L" else "#1f5fa8"
        ax.text(ex_lon, ex_lat, kind, ha="center", va="center", fontsize=24, transform=pc,
                 color=color, zorder=4, fontproperties=baloo_bold,
                 path_effects=[pe.withStroke(linewidth=1.8, foreground="white")])

    geodetic_transform = pc._as_mpl_transform(ax)
    stroke = [pe.withStroke(linewidth=1.5, foreground=(0, 0, 0, 0.75))]
    for name, lon_c, lat_c, pos in CITIES:
        if not (LON_MIN <= lon_c <= LON_MAX and LAT_MIN <= lat_c <= LAT_MAX):
            continue
        ax.plot(lon_c, lat_c, marker="o", markersize=4.6, color="white", zorder=100,
                mec="black", mew=0.7, transform=pc)
        dx_pt = 6 if pos == "right" else -6
        ha = "left" if pos == "right" else "right"
        name_transform = offset_copy(geodetic_transform, fig=fig, x=dx_pt, y=0, units="points")
        txt = ax.text(lon_c, lat_c, name, fontsize=9.25, fontproperties=poppins_semibold,
                       color="white", ha=ha, va="center", zorder=101, transform=name_transform)
        txt.set_path_effects(stroke)

    ax.spines['geo'].set_edgecolor('black')
    ax.spines['geo'].set_linewidth(1.6)

    # Two colorbars side by side below the map -- rain (left) and snow
    # (right), on the same inch stops so they line up value-for-value.
    fig.canvas.draw()
    frame_px = ax.get_window_extent()
    frame_left = frame_px.x0 / (FIG_WIDTH_IN * FIG_DPI)
    frame_right = frame_px.x1 / (FIG_WIDTH_IN * FIG_DPI)
    frame_w = frame_right - frame_left
    cbar_width, cbar_height, gap = frame_w * 0.40, 0.016, frame_w * 0.06
    cbar_bottom = 0.10
    left_x = (frame_left + frame_right) / 2 - gap / 2 - cbar_width
    right_x = (frame_left + frame_right) / 2 + gap / 2
    draw_precip_colorbar(fig, [left_x, cbar_bottom, cbar_width, cbar_height], RAIN_RGB_COLORS,
                          "Rain (in)", poppins_reg)
    draw_precip_colorbar(fig, [right_x, cbar_bottom, cbar_width, cbar_height], SNOW_RGB_COLORS,
                          "Snow, liquid equiv. (in)", poppins_reg)

    init_dt = datetime.fromisoformat(meta["initialization_time"].replace("Z", "+00:00"))
    valid_dt_utc = datetime.fromisoformat(meta["valid_time"].replace("Z", "+00:00"))
    valid_dt_local = valid_dt_utc.astimezone(LOCAL_TZ)
    h12 = valid_dt_local.hour % 12 or 12
    ampm = "AM" if valid_dt_local.hour < 12 else "PM"
    tz_abbr = valid_dt_local.strftime("%Z")

    fig.text(0.03, 0.978, f"{valid_dt_local.strftime('%A')} {h12}:00 {ampm} {tz_abbr[0]}T Pressure + Precip",
              fontsize=19, fontproperties=poppins_reg, color="#2b2a26", ha="left", va="top")
    fig.text(0.03, 0.943, "MSLP + 3-Hour Precipitation, Rain/Snow by Terrain vs. Freezing Level",
              fontsize=12.5, fontproperties=poppins_semibold, color="#3a3835", ha="left", va="top")
    fig.text(0.03, 0.914,
              f"WindBorne WM-6 {PRODUCT_LABELS[product]} • Init {init_dt:%Y-%m-%d %H}z • "
              f"Valid {valid_dt_utc:%Y-%m-%d %H}z (F{meta['forecast_hour']:03d})",
              fontsize=10.5, fontproperties=poppins_reg, color="#5a584f", ha="left", va="top")

    fig.text(0.5, 0.012, "WindBorne WM-6 • Terrain: NOAA ETOPO 2022 — Ingalls Weather", fontsize=9,
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
        description="Build an Ingalls Weather Pacific Northwest MSLP + 3-hour precip map.")
    parser.add_argument("--valid", type=str, default=None,
                         help="Valid time, YYYY-MM-DDTHH, UTC (default: tomorrow 12z). "
                              "WM-6 publishes 3-hourly steps, so use a multiple of 3.")
    parser.add_argument("--file", type=Path, default=None,
                         help="Render from a local saved snapshot (.npz) instead of fetching live.")
    parser.add_argument("--product", choices=sorted(PRODUCT_GROUPS), default="det",
                         help="WM-6 deterministic run or ensemble mean (default: det).")
    parser.add_argument("--out", type=Path, default=None,
                         help="Output PNG path (default: output/pnw_mslp_precip_<valid>.png).")
    args = parser.parse_args()

    if args.file and not args.file.exists():
        sys.exit(f"--file {args.file} not found.")

    if args.valid:
        valid_time = datetime.strptime(args.valid, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)
    else:
        tomorrow = datetime.now(timezone.utc).date() + timedelta(days=1)
        valid_time = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 12, tzinfo=timezone.utc)
    if valid_time.hour % 3:
        parser.error("--valid hour must be a multiple of 3 (WM-6 publishes 3-hourly steps).")

    out_path = args.out or (OUTPUT_DIR / f"pnw_mslp_precip_{args.product}_{valid_time:%Y-%m-%dT%H}z.png")
    build_map(valid_time, args.product, out_path, override_path=args.file)

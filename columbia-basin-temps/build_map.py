"""
Columbia Basin Temperature Map -- canonical map builder
Ingalls Weather

Styled map of 2m temperatures over the Columbia Basin (same domain as
../columbia-basin-alerts-map/build_map.py: North Bend, WA down to the
Baker City, OR corridor), supporting four forecast sources and three
temperature metrics:

  --source wm6-3km    WindBorne WeatherMesh-6, 3 km, fetched directly from
                       the WindBorne API (requires WB_API_KEY).
  --source hrrr        NOAA HRRR CONUS, 3 km          \\
  --source ecmwf-ifs    ECMWF IFS, 0.25 deg             } via Open-Meteo
  --source ecmwf-aifs   ECMWF AIFS, 0.25 deg           /  (no key needed)

  --metric high   max hourly 2m temp, 8am-8pm local time (the daytime
                  window that reliably contains the daily peak)
  --metric low    min hourly 2m temp, 2am-9am local time (the pre-dawn
                  window that reliably contains the daily trough)
  --metric time   2m temp at one specific local hour, via --hour H (0-23)

USAGE
-----
    python build_map.py                                    # WM-6 3km high, coming Sunday
    python build_map.py --source hrrr --metric low --date 2026-07-12
    python build_map.py --source ecmwf-ifs --metric time --hour 17 --date 2026-07-12
    python build_map.py --source ecmwf-aifs --date 2026-07-12

wm6-3km requires WB_API_KEY (see https://app.windbornesystems.com/api_tokens)
in the environment. The Open-Meteo-backed sources (hrrr, ecmwf-ifs,
ecmwf-aifs) need no API key, but query a coarse grid of points across the
domain (Open-Meteo serves point forecasts, not gridded downloads) and
interpolate -- see fetch_open_meteo() and OPEN_METEO_GRID_DEG.

To render from a previously-saved grid instead of fetching live (useful for
testing, or to avoid re-fetching), pass --file path/to/snapshot.npz -- see
fetch_wm6_3km() / fetch_open_meteo() for the npz layout.

REQUIRES (already checked into /maps at repo root, shared across all
Ingalls Weather map projects):
    admin1_boundary_lines.json, admin0_boundary_lines.json
  Sourced from raw.githubusercontent.com/martynafford/natural-earth-geojson
  (10m), clipped down to US/Canada/Mexico. These are Natural Earth's
  dedicated line datasets (not polygon outlines) because adjacent
  state/province polygons are simplified independently -- drawing their
  outlines directly produces two slightly different paths for the same
  real-world border. The line datasets store each border once, so
  neighboring regions share identical vertices.

    land_slim.json -- drawn outline-only (no fill) on top of the
  temperature raster so the Puget Sound coastline reads clearly without
  hiding the temperature color over water.

    washington_roads.geojson, oregon_roads.geojson, idaho_roads_north.geojson
  -- motorway + trunk highways, same source/styling as
  ../columbia-basin-alerts-map/build_map.py.

Logo is read from /assets/ingalls_weather_logo.png at repo root.
"""

import argparse
import io
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
from matplotlib.colors import Normalize, LinearSegmentedColormap
from matplotlib.transforms import offset_copy
import numpy as np
import requests
import jwt
import zarr
from scipy.interpolate import griddata

import cartopy.crs as ccrs
from shapely.geometry import shape
from PIL import Image

# ---------------------------------------------------------------------------
# Paths (relative to this script's location: columbia-basin-temps/)
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
MAPS_DIR = REPO_ROOT / "maps"
ASSETS_DIR = REPO_ROOT / "assets"
THIS_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = THIS_DIR / "output"

ADMIN1_LINES_FILE = MAPS_DIR / "admin1_boundary_lines.json"
ADMIN0_LINES_FILE = MAPS_DIR / "admin0_boundary_lines.json"
LAND_FILE = MAPS_DIR / "land_slim.json"
ROAD_FILES = ["washington_roads.geojson", "oregon_roads.geojson", "idaho_roads_north.geojson"]
LOGO_FILE = ASSETS_DIR / "ingalls_weather_logo.png"

MOTORWAY_TYPES = {"motorway", "motorway_link"}
TRUNK_TYPES = {"trunk", "trunk_link"}
MOTORWAY_COLOR = "#8FB8E0"  # pastel blue
TRUNK_COLOR = "#F2B880"     # pastel orange

POPPINS_REG_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf"
POPPINS_MED_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf"

# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------
WB_BASE = "https://api.windbornesystems.com/forecasts/v1/wm-6-3km"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_MODELS = {
    "hrrr": "ncep_hrrr_conus",
    "ecmwf-ifs": "ecmwf_ifs025",
    "ecmwf-aifs": "ecmwf_aifs025_single",
}
SOURCE_LABELS = {
    "wm6-3km": "WeatherMesh-6 3 km",
    "hrrr": "NOAA HRRR 3 km",
    "ecmwf-ifs": "ECMWF IFS 0.25°",
    "ecmwf-aifs": "ECMWF AIFS 0.25°",
}
SOURCES = ["wm6-3km", "hrrr", "ecmwf-ifs", "ecmwf-aifs"]
METRICS = ["high", "low", "time"]

LOCAL_TZ = ZoneInfo("America/Los_Angeles")
# Local-hour windows used to reduce a day's hourly temps to a single high or
# low without needing every one of the 24 hourly grids (wm6-3km's hourly
# fetches are ~90 MB each). "high" reliably contains the daily peak; "low"
# reliably contains the pre-dawn trough. A true overnight low spanning
# midnight isn't captured -- see the README.
HIGH_WINDOW = (8, 20)
LOW_WINDOW = (2, 9)

# Open-Meteo serves point forecasts, not gridded downloads, so the
# Open-Meteo-backed sources (hrrr, ecmwf-ifs, ecmwf-aifs) are sampled on a
# regular query grid at this spacing (degrees) across the padded domain,
# then interpolated the same way wm6-3km's native curvilinear grid is.
# 0.15 deg (~15-17 km here) balances map fidelity against request count --
# HRRR's native 3 km grid and IFS/AIFS's native 0.25 deg grid both have
# real detail below/near this, but a report map doesn't need per-pixel
# accuracy, and a finer query grid means proportionally more requests.
OPEN_METEO_GRID_DEG = 0.15
OPEN_METEO_BATCH = 200

# ---------------------------------------------------------------------------
# Figure geometry. AXES_RECT leaves extra room below the map (compared to a
# full-bleed map area) for the off-map colorbar + attribution.
# MAP_FRAME_INSET_PX positions the logo snug inside the map frame's
# lower-right corner.
# ---------------------------------------------------------------------------
FIG_WIDTH_IN, FIG_HEIGHT_IN = 10, 8.9
FIG_DPI = 200
AXES_RECT = [0.035, 0.15, 0.93, 0.75]  # [left, bottom, width, height], figure fraction
MAP_FRAME_INSET_PX = 22

# ---------------------------------------------------------------------------
# Map domain -- same extent as ../columbia-basin-alerts-map/build_map.py
# (North Bend, WA down to the Baker City, OR corridor).
# ---------------------------------------------------------------------------
LON_MIN, LON_MAX = -123.3, -116.2
LAT_MIN, LAT_MAX = 44.4, 48.0
CENTER_LON, CENTER_LAT = -119.75, 46.2

# Degrees beyond the plotted extent to keep when cropping wm6-3km's fetched
# (curvilinear) grid, so the regular (and itself padded, see
# RESAMPLE_PAD_DEG below) grid has real data to interpolate from all the
# way to its own edges.
FETCH_PAD_DEG = 2.0

# The source grid is curvilinear (the model's native projection warped into
# lat/lon), which leaves rendering gaps at the corners of a NearsidePerspective
# frame -- both for pcolormesh (a reprojected QuadMesh) and, it turns out,
# imshow too, unless the resampled raster itself extends past the plotted
# extent. cartopy warps imshow's raster into the map projection by inverse-
# projecting each screen pixel back to lon/lat and sampling the source array;
# right at the requested extent's edge that inverse lookup can land a hair
# outside the source array's bounds and get masked out. Resampling onto a
# regular grid that's padded beyond LON_MIN/MAX/LAT_MIN/MAX (then still
# cropping the *view* to the unpadded extent via ax.set_extent) gives that
# lookup a margin to sample from, so no corner goes unfilled.
RESAMPLE_NX, RESAMPLE_NY = 500, 400
RESAMPLE_PAD_DEG = 1.5

# Same city list (and left/right sides) as ../columbia-basin-alerts-map/build_map.py,
# extended with additional cities across the widened domain.
CITIES = [
    ("Spokane", -117.4260, 47.6588, "right"),
    ("Seattle", -122.3321, 47.6062, "right"),
    ("Wenatchee", -120.3103, 47.4235, "right"),
    ("Tacoma", -122.4443, 47.2529, "right"),
    ("Moses Lake", -119.2781, 47.1301, "left"),
    ("Ritzville", -118.3766, 47.1289, "right"),
    ("Ellensburg", -120.5478, 46.9965, "left"),
    ("Othello", -119.1717, 46.8273, "left"),
    ("Pullman", -117.1817, 46.7298, "left"),
    ("Yakima", -120.5059, 46.6021, "right"),
    ("Packwood", -121.6733, 46.6088, "right"),
    ("Dayton", -117.9762, 46.3212, "right"),
    ("Prosser", -119.7686, 46.2532, "left"),
    ("Kennewick", -119.1372, 46.2112, "right"),
    ("Walla Walla", -118.3430, 46.0646, "right"),
    ("Goldendale", -120.8215, 45.8210, "left"),
    ("Boardman", -119.7006, 45.8393, "left"),
    ("Hermiston", -119.2895, 45.8404, "right"),
    ("Pendleton", -118.7879, 45.6721, "right"),
    ("The Dalles", -121.1787, 45.5946, "left"),
    ("La Grande", -118.0877, 45.3246, "right"),
    ("Condon", -120.1837, 45.2373, "left"),
    ("Portland", -122.6784, 45.5152, "left"),
    ("Salem", -123.0351, 44.9429, "right"),
    ("Longview", -122.9382, 46.1382, "right"),
    ("Olympia", -122.9007, 47.0379, "right"),
    ("Maupin", -121.0793, 45.1748, "left"),
    ("Centralia", -122.9542, 46.7162, "right"),
    ("Davenport", -118.1489, 47.6543, "left"),
    ("Heppner", -119.5528, 45.3554, "right"),
    ("Lewiston", -117.0177, 46.4165, "right"),
    ("Baker City", -117.8344, 44.7749, "right"),
    ("Madras", -121.1290, 44.6338, "right"),
    ("Enterprise", -117.2782, 45.4271, "right"),
]

# ---------------------------------------------------------------------------
# Temperature color table -- a fixed Kelvin-to-RGB enhancement curve (not
# rescaled per map) so the same color always means the same absolute
# temperature across every map this script renders. (K, [R, G, B]) control
# points; the source table's alpha channel is constant (fully opaque) and
# is dropped here.
# ---------------------------------------------------------------------------
TEMP_COLOR_TABLE = [
    (205.53962824635747, [20, 1, 11]),
    (220.54105933801642, [72, 2, 42]),
    (223.30970412365585, [114, 5, 69]),
    (226.07834890929527, [156, 7, 95]),
    (228.8469936949347, [190, 31, 133]),
    (231.61563848057412, [216, 33, 184]),
    (234.38428326621354, [224, 94, 226]),
    (237.15292805185297, [208, 143, 208]),
    (239.9215728374924, [198, 174, 206]),
    (242.71111221757047, [177, 149, 200]),
    (245.48274194527255, [153, 122, 186]),
    (248.25437167297463, [120, 90, 160]),
    (251.02600140067673, [95, 67, 136]),
    (253.7976311283788, [75, 44, 128]),
    (256.5692608560809, [52, 34, 130]),
    (259.2740222360249, [44, 54, 150]),
    (262.11252031148507, [62, 73, 174]),
    (264.88415003918715, [79, 90, 198]),
    (267.13811875987665, [90, 128, 206]),
    (269.1251668409579, [100, 165, 214]),
    (271.1122149220392, [94, 194, 212]),
    (273.0992630031204, [40, 142, 160]),
    (275.0863110842017, [24, 105, 120]),
    (279.0604072463642, [28, 108, 79]),
    (283.03450340852675, [39, 132, 85]),
    (286.97216346781227, [60, 150, 83]),
    (289.741977590991, [112, 172, 91]),
    (292.5117917141697, [159, 190, 91]),
    (295.2816058373485, [208, 200, 84]),
    (298.0514199605272, [204, 172, 70]),
    (300.8212340837059, [212, 146, 61]),
    (303.5910482068847, [218, 121, 35]),
    (306.3608623300634, [208, 90, 31]),
    (309.13067645324213, [216, 59, 32]),
    (311.9004905764209, [182, 32, 7]),
    (314.6703046995996, [142, 36, 19]),
    (317.44011882277835, [102, 23, 10]),
    (320.20993294595706, [142, 15, 54]),
    (322.9797470691358, [194, 50, 94]),
    (325.74956119231456, [216, 120, 149]),
    (332.71070543555834, [204, 16, 171]),
]
TEMP_KMIN = TEMP_COLOR_TABLE[0][0]
TEMP_KMAX = TEMP_COLOR_TABLE[-1][0]


def build_temp_colormap():
    span = TEMP_KMAX - TEMP_KMIN
    stops = [((k - TEMP_KMIN) / span, [c / 255 for c in rgb]) for k, rgb in TEMP_COLOR_TABLE]
    return LinearSegmentedColormap.from_list("ingalls_temp", stops, N=256)


def f_to_k(f):
    return (f - 32) * 5 / 9 + 273.15


def k_to_f(k):
    return (k - 273.15) * 9 / 5 + 32


def c_to_k(c):
    return c + 273.15


def f_to_c(f):
    return (f - 32) * 5 / 9


def c_to_f(c):
    return c * 9 / 5 + 32


RESAMPLE_LON_MIN, RESAMPLE_LON_MAX = LON_MIN - RESAMPLE_PAD_DEG, LON_MAX + RESAMPLE_PAD_DEG
RESAMPLE_LAT_MIN, RESAMPLE_LAT_MAX = LAT_MIN - RESAMPLE_PAD_DEG, LAT_MAX + RESAMPLE_PAD_DEG


def resample_to_regular_grid(lat, lon, values):
    """Interpolate a curvilinear or scattered-point (lat, lon, values) grid
    onto a plain regular lat/lon grid padded past the map's plotted extent
    (see RESAMPLE_PAD_DEG). Works equally for wm6-3km's curvilinear native
    grid and the Open-Meteo sources' scattered query-point grid, since both
    just get raveled into flat point lists. Returns values_2d, indexed
    [lat, lon] ascending."""
    reg_lon = np.linspace(RESAMPLE_LON_MIN, RESAMPLE_LON_MAX, RESAMPLE_NX)
    reg_lat = np.linspace(RESAMPLE_LAT_MIN, RESAMPLE_LAT_MAX, RESAMPLE_NY)
    reg_lon_grid, reg_lat_grid = np.meshgrid(reg_lon, reg_lat)
    points = np.column_stack([np.ravel(lon), np.ravel(lat)])
    regridded = griddata(points, np.ravel(values), (reg_lon_grid, reg_lat_grid), method="linear")
    nan_mask = np.isnan(regridded)
    if nan_mask.any():
        regridded[nan_mask] = griddata(points, np.ravel(values),
                                        (reg_lon_grid[nan_mask], reg_lat_grid[nan_mask]), method="nearest")
    return regridded


def sample_grid_value(value_grid, lon_pt, lat_pt):
    """Nearest value in the regular RESAMPLE_NX x RESAMPLE_NY grid to a point."""
    col = round((lon_pt - RESAMPLE_LON_MIN) / (RESAMPLE_LON_MAX - RESAMPLE_LON_MIN) * (RESAMPLE_NX - 1))
    row = round((lat_pt - RESAMPLE_LAT_MIN) / (RESAMPLE_LAT_MAX - RESAMPLE_LAT_MIN) * (RESAMPLE_NY - 1))
    col = min(max(col, 0), RESAMPLE_NX - 1)
    row = min(max(row, 0), RESAMPLE_NY - 1)
    return value_grid[row, col]


def metric_local_hour_window(metric, hour):
    """Local-hour (start, end) inclusive window to reduce over for a given
    metric. For "time", start == end (a single hour)."""
    if metric == "high":
        return HIGH_WINDOW
    if metric == "low":
        return LOW_WINDOW
    return hour, hour


def reduce_temps(metric, temps):
    """Reduce a sequence of temperatures (same units in and out) to the
    single value the metric asks for."""
    return min(temps) if metric == "low" else max(temps)


# ---------------------------------------------------------------------------
# wm6-3km (WindBorne API)
# ---------------------------------------------------------------------------
def sign_jwt(api_key):
    return jwt.encode({"iat": int(time.time())}, api_key, algorithm="HS256")


def wb_get(path, api_key, **params):
    token = sign_jwt(api_key)
    resp = requests.get(f"{WB_BASE}/{path}", headers={"Authorization": f"Bearer {token}"},
                         params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def local_window_valid_times(date, start_hour, end_hour):
    """UTC valid times for each local hour in [start_hour, end_hour] on `date`."""
    times = []
    for h in range(start_hour, end_hour + 1):
        local_dt = datetime(date.year, date.month, date.day, h, tzinfo=LOCAL_TZ)
        times.append(local_dt.astimezone(ZoneInfo("UTC")))
    return times


def fetch_wm6_3km(date, metric, hour, api_key):
    """Fetch hourly temperature_2m grids spanning the local-hour window the
    requested metric needs, crop to the map bbox, and reduce. Returns
    (lat_2d, lon_2d, temp_k_2d, {"kind": "init", "value": init_time})."""
    start_hour, end_hour = metric_local_hour_window(metric, hour)

    run_info = wb_get("run_information", api_key)
    forecast_zero = datetime.fromisoformat(run_info["forecast_zero"].replace("Z", "+00:00"))
    init_time = run_info["initialization_time"]
    available_hours = {a["forecast_hour"] for a in run_info["available"]}

    valid_times = local_window_valid_times(date, start_hour, end_hour)
    lat = lon = None
    reduced_temp_k = None
    r0 = r1 = c0 = c1 = None

    for valid_time in valid_times:
        forecast_hour = round((valid_time - forecast_zero).total_seconds() / 3600)
        if forecast_hour not in available_hours:
            sys.exit(f"Forecast hour {forecast_hour} (valid {valid_time.isoformat()}) "
                      f"is not yet available from run {init_time}. wm-6-3km's horizon "
                      f"may not reach the requested date yet -- try again closer to it.")
        url_info = wb_get("gridded", api_key, variable="all", domain="conus", format="zarr",
                           as_url="true", initialization_time=init_time,
                           forecast_hour=forecast_hour, time=valid_time.strftime("%Y-%m-%dT%H:%M:%SZ"))
        print(f"Fetching forecast hour {forecast_hour} (valid {valid_time.isoformat()}) ...")
        resp = requests.get(url_info["url"], timeout=60)
        resp.raise_for_status()
        store = zarr.storage.ZipStore(io.BytesIO(resp.content), mode="r")
        g = zarr.open(store, mode="r")
        if lat is None:
            lat = g["latitude"][:]
            lon = g["longitude"][:]
            mask = ((lon >= LON_MIN - FETCH_PAD_DEG) & (lon <= LON_MAX + FETCH_PAD_DEG) &
                    (lat >= LAT_MIN - FETCH_PAD_DEG) & (lat <= LAT_MAX + FETCH_PAD_DEG))
            rows = np.where(mask.any(axis=1))[0]
            cols = np.where(mask.any(axis=0))[0]
            r0, r1 = rows.min(), rows.max() + 1
            c0, c1 = cols.min(), cols.max() + 1
            lat, lon = lat[r0:r1, c0:c1], lon[r0:r1, c0:c1]
            fill = np.inf if metric == "low" else -np.inf
            reduced_temp_k = np.full(lat.shape, fill, dtype=np.float32)
        hour_temp_k = g["temperature_2m"][r0:r1, c0:c1]
        reduced_temp_k = (np.minimum if metric == "low" else np.maximum)(reduced_temp_k, hour_temp_k)
        store.close()

    return lat, lon, reduced_temp_k, {"kind": "init", "value": init_time}


# ---------------------------------------------------------------------------
# Open-Meteo (hrrr, ecmwf-ifs, ecmwf-aifs)
# ---------------------------------------------------------------------------
def open_meteo_query_points():
    """Regular query grid across the padded domain -- see OPEN_METEO_GRID_DEG."""
    lons = np.arange(RESAMPLE_LON_MIN, RESAMPLE_LON_MAX + 1e-9, OPEN_METEO_GRID_DEG)
    lats = np.arange(RESAMPLE_LAT_MIN, RESAMPLE_LAT_MAX + 1e-9, OPEN_METEO_GRID_DEG)
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    return lat_grid.ravel(), lon_grid.ravel()


def fetch_open_meteo(source, date, metric, hour):
    """Query a grid of points across the domain from Open-Meteo, reduce each
    point's local hourly series to the metric's single value, and return
    (lat_flat, lon_flat, temp_k_flat, {"kind": "retrieved", "value": iso_utc}).
    Open-Meteo serves point forecasts (not gridded downloads), so this
    samples OPEN_METEO_GRID_DEG-spaced points rather than fetching a native
    grid -- resample_to_regular_grid() interpolates the rest same as it
    does for wm6-3km's curvilinear grid."""
    model = OPEN_METEO_MODELS[source]
    start_hour, end_hour = metric_local_hour_window(metric, hour)
    date_str = date.isoformat()

    query_lats, query_lons = open_meteo_query_points()
    n = len(query_lats)

    out_lat, out_lon, out_temp_k = [], [], []
    missing = 0
    for i in range(0, n, OPEN_METEO_BATCH):
        batch_lat = query_lats[i:i + OPEN_METEO_BATCH]
        batch_lon = query_lons[i:i + OPEN_METEO_BATCH]
        print(f"Fetching {source} points {i + 1}-{min(i + OPEN_METEO_BATCH, n)} of {n} ...")
        resp = requests.get(OPEN_METEO_URL, params={
            "latitude": ",".join(f"{v:.4f}" for v in batch_lat),
            "longitude": ",".join(f"{v:.4f}" for v in batch_lon),
            "hourly": "temperature_2m",
            "models": model,
            "start_date": date_str,
            "end_date": date_str,
            "timezone": "America/Los_Angeles",
        }, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        locations = data if isinstance(data, list) else [data]

        for loc in locations:
            hourly_by_local_hour = {
                t[11:13]: v for t, v in zip(loc["hourly"]["time"], loc["hourly"]["temperature_2m"])
                if t[:10] == date_str
            }
            wanted_c = [hourly_by_local_hour.get(f"{h:02d}") for h in range(start_hour, end_hour + 1)]
            if any(v is None for v in wanted_c):
                missing += 1
                continue
            out_lat.append(loc["latitude"])
            out_lon.append(loc["longitude"])
            out_temp_k.append(c_to_k(reduce_temps(metric, wanted_c)))

    if missing > n * 0.5:
        sys.exit(f"{source} returned no data for {missing}/{n} query points on {date_str} -- "
                  f"the date is likely outside this model's forecast horizon on Open-Meteo.")

    retrieved = datetime.now(timezone.utc).strftime("%Y-%m-%d %H") + "z"
    return (np.array(out_lat), np.array(out_lon), np.array(out_temp_k),
            {"kind": "retrieved", "value": retrieved})


def fetch_grid(source, date, metric, hour, api_key=None):
    if source == "wm6-3km":
        if not api_key:
            sys.exit("WB_API_KEY not set -- get a token at "
                      "https://app.windbornesystems.com/api_tokens, or pass --file "
                      "to render from a saved snapshot instead.")
        return fetch_wm6_3km(date, metric, hour, api_key)
    return fetch_open_meteo(source, date, metric, hour)


# ---------------------------------------------------------------------------
# Basemap layers
# ---------------------------------------------------------------------------
def load_boundary_lines(path):
    """Natural Earth's dedicated boundary-*line* datasets (as opposed to
    polygon outlines) -- each border is stored once, so adjacent
    states/provinces/countries share identical vertices and draw as a
    single clean line instead of two independently-simplified, slightly
    misaligned ones."""
    with open(path) as f:
        data = json.load(f)
    return [shape(feat["geometry"]) for feat in data["features"]]


def load_land():
    with open(LAND_FILE) as f:
        data = json.load(f)
    return [shape(feat["geometry"]) for feat in data["features"] if feat.get("geometry")]


def load_roads():
    """Motorway + trunk highways (WA/OR/ID), same source/styling as
    ../columbia-basin-alerts-map/build_map.py."""
    motorway_geoms, trunk_geoms = [], []
    for region_file in ROAD_FILES:
        with open(MAPS_DIR / region_file) as f:
            data = json.load(f)
        for feat in data["features"]:
            hwy = feat["properties"].get("highway")
            geom = shape(feat["geometry"])
            if hwy in MOTORWAY_TYPES:
                motorway_geoms.append(geom)
            elif hwy in TRUNK_TYPES:
                trunk_geoms.append(geom)
    return motorway_geoms, trunk_geoms


def metric_title(metric, hour):
    if metric == "high":
        return "High Temperatures"
    if metric == "low":
        return "Low Temperatures"
    h12 = hour % 12 or 12
    ampm = "am" if hour < 12 else "pm"
    return f"{h12}{ampm} Temperatures"


def metric_tag(metric, hour):
    return metric if metric != "time" else f"time{hour:02d}"


def build_map(source, metric, hour, date, output_path, override_path=None):
    poppins_reg = fm.FontProperties(fname=POPPINS_REG_PATH)
    poppins_semibold = fm.FontProperties(fname=POPPINS_MED_PATH)

    if override_path:
        print(f"Using local snapshot: {override_path}")
        npz = np.load(override_path)
        lat, lon, temp_k = npz["lat"], npz["lon"], npz["temp_k"]
        meta = {"kind": str(npz["meta_kind"]), "value": str(npz["meta_value"])} if "meta_kind" in npz else None
    else:
        api_key = os.environ.get("WB_API_KEY")
        lat, lon, temp_k, meta = fetch_grid(source, date, metric, hour, api_key)

    print("Resampling onto a regular grid...")
    temp_k = resample_to_regular_grid(lat, lon, temp_k)

    temp_f = k_to_f(temp_k)
    # Slice off the resample padding (real data, but outside the visible
    # frame) before reporting the range actually shown on the map.
    lon_frac0 = (LON_MIN - RESAMPLE_LON_MIN) / (RESAMPLE_LON_MAX - RESAMPLE_LON_MIN)
    lon_frac1 = (LON_MAX - RESAMPLE_LON_MIN) / (RESAMPLE_LON_MAX - RESAMPLE_LON_MIN)
    lat_frac0 = (LAT_MIN - RESAMPLE_LAT_MIN) / (RESAMPLE_LAT_MAX - RESAMPLE_LAT_MIN)
    lat_frac1 = (LAT_MAX - RESAMPLE_LAT_MIN) / (RESAMPLE_LAT_MAX - RESAMPLE_LAT_MIN)
    visible = temp_f[round(lat_frac0 * RESAMPLE_NY):round(lat_frac1 * RESAMPLE_NY),
                      round(lon_frac0 * RESAMPLE_NX):round(lon_frac1 * RESAMPLE_NX)]
    print(f"{metric.capitalize()} range: {visible.min():.0f}F - {visible.max():.0f}F")

    print("Loading basemap layers...")
    admin1_lines = load_boundary_lines(ADMIN1_LINES_FILE)
    admin0_lines = load_boundary_lines(ADMIN0_LINES_FILE)
    land_geoms = load_land()
    motorway_geoms, trunk_geoms = load_roads()

    proj = ccrs.NearsidePerspective(central_longitude=CENTER_LON, central_latitude=CENTER_LAT,
                                     satellite_height=4_000_000)
    pc = ccrs.PlateCarree()

    fig = plt.figure(figsize=(FIG_WIDTH_IN, FIG_HEIGHT_IN), dpi=FIG_DPI)
    fig.patch.set_facecolor("#f7f6f2")

    ax = fig.add_axes(AXES_RECT, projection=proj)
    ax.set_extent([LON_MIN, LON_MAX, LAT_MIN, LAT_MAX], crs=pc)
    ax.patch.set_facecolor("white")

    # Temperature field -- a fixed Kelvin-to-color enhancement curve (not
    # rescaled to this map's data range), so color reads consistently
    # across every map this script renders. Rendered with imshow (not
    # pcolormesh): cartopy warps the raster directly into the map
    # projection, which -- unlike a reprojected QuadMesh -- doesn't leave
    # rendering gaps at the corners of a NearsidePerspective frame.
    temp_cmap = build_temp_colormap()
    temp_norm = Normalize(vmin=TEMP_KMIN, vmax=TEMP_KMAX)
    ax.imshow(temp_k, transform=pc, cmap=temp_cmap, norm=temp_norm, origin="lower",
              extent=[RESAMPLE_LON_MIN, RESAMPLE_LON_MAX, RESAMPLE_LAT_MIN, RESAMPLE_LAT_MAX], zorder=1)

    # Coastline -- outline only (no fill) so the temperature color still
    # shows over water; this is what traces the Puget Sound's shape.
    ax.add_geometries(land_geoms, crs=pc, facecolor="none", edgecolor="#4a6b7a", linewidth=0.8, zorder=1.5)

    ax.add_geometries(admin1_lines, crs=pc, facecolor="none", edgecolor="#5a4632", linewidth=0.8, zorder=2)
    ax.add_geometries(admin0_lines, crs=pc, facecolor="none", edgecolor="#3a2f21", linewidth=1.1, zorder=2.5)

    ax.add_geometries(trunk_geoms, crs=pc, facecolor="none", edgecolor=TRUNK_COLOR, linewidth=1.1, zorder=2.6)
    ax.add_geometries(motorway_geoms, crs=pc, facecolor="none", edgecolor=MOTORWAY_COLOR, linewidth=1.3, zorder=2.7)

    # City labels -- name plus that spot's forecast value, sampled from the
    # resampled regular grid. Text always sits left or right of its dot;
    # the name (top line) is vertically centered on the dot, with the
    # temperature tucked in tight just below it. Both the dot-to-label gap
    # and the name-to-temperature gap are offsets in *points* (via
    # offset_copy), not degrees, so they stay a constant, tight distance
    # regardless of map scale rather than growing or shrinking with it.
    geodetic_transform = pc._as_mpl_transform(ax)
    stroke = [pe.withStroke(linewidth=1.5, foreground=(0, 0, 0, 0.8))]
    for name, lon_c, lat_c, pos in CITIES:
        ax.plot(lon_c, lat_c, marker="o", markersize=5.0, color="white", zorder=100,
                mec="black", mew=0.8, transform=pc)
        city_f = sample_grid_value(temp_f, lon_c, lat_c)
        dx_pt = 6 if pos == "right" else -6
        ha = "left" if pos == "right" else "right"

        name_transform = offset_copy(geodetic_transform, fig=fig, x=dx_pt, y=0, units="points")
        name_txt = ax.text(lon_c, lat_c, name, fontsize=9.75, fontproperties=poppins_semibold,
                            color="white", ha=ha, va="center", zorder=101, transform=name_transform)
        name_txt.set_path_effects(stroke)

        temp_transform = offset_copy(geodetic_transform, fig=fig, x=dx_pt, y=-4, units="points")
        temp_txt = ax.text(lon_c, lat_c, f"{city_f:.0f}°F", fontsize=9.75,
                            fontproperties=poppins_semibold, color="white", ha=ha, va="top",
                            zorder=101, transform=temp_transform)
        temp_txt.set_path_effects(stroke)

    ax.spines['geo'].set_edgecolor('black')
    ax.spines['geo'].set_linewidth(1.6)

    # Colorbar -- below the map, horizontally centered on the rendered map
    # frame (cartopy shrinks the axes box to preserve the projection's
    # aspect ratio, so the frame doesn't necessarily span AXES_RECT's full
    # width -- ask the canvas where it actually landed).
    fig.canvas.draw()
    frame_px = ax.get_window_extent()
    frame_left = frame_px.x0 / (FIG_WIDTH_IN * FIG_DPI)
    frame_right = frame_px.x1 / (FIG_WIDTH_IN * FIG_DPI)
    cbar_width, cbar_height = (frame_right - frame_left) * 0.55, 0.022
    cbar_left = (frame_left + frame_right) / 2 - cbar_width / 2
    cbar_bottom = 0.085

    # Only draw the slice of the color table that's actually visible on the
    # map today -- but sample it with the exact same cmap + Kelvin norm used
    # to color the map, so a given shade still means the same temperature it
    # always does. Rounded outward to the nearest 5F so the bar's ends land
    # on clean numbers.
    vmin_disp = 5 * np.floor(visible.min() / 5)
    vmax_disp = 5 * np.ceil(visible.max() / 5)
    gradient_k = f_to_k(np.linspace(vmin_disp, vmax_disp, 256)).reshape(1, -1)

    cax = fig.add_axes([cbar_left, cbar_bottom, cbar_width, cbar_height])
    cax.imshow(gradient_k, aspect="auto", cmap=temp_cmap, norm=temp_norm,
               extent=[vmin_disp, vmax_disp, 0, 1])
    cax.set_yticks([])
    for spine in cax.spines.values():
        spine.set_edgecolor("#8a887e")
        spine.set_linewidth(0.6)

    # Primary axis (bottom): Fahrenheit, ticked every 10F across the
    # visible range.
    f_ticks = [f for f in range(-100, 151, 10) if vmin_disp <= f <= vmax_disp]
    cax.set_xticks(f_ticks)
    cax.set_xticklabels([f"{f}°F" for f in f_ticks])
    cax.tick_params(labelsize=8.5, color="#8a887e", labelcolor="#2b2a26")
    for label in cax.get_xticklabels():
        label.set_fontproperties(poppins_reg)

    # Secondary axis (top): the same range in Celsius.
    cax_c = cax.secondary_xaxis("top", functions=(f_to_c, c_to_f))
    cax_c.xaxis.set_major_formatter(lambda c, _: f"{c:.0f}°C")
    cax_c.tick_params(labelsize=8.5, color="#8a887e", labelcolor="#2b2a26")
    for label in cax_c.get_xticklabels():
        label.set_fontproperties(poppins_reg)

    # Title & subtitle above the map
    if meta and meta["kind"] == "init":
        init_dt = datetime.fromisoformat(meta["value"].replace("Z", "+00:00"))
        run_str = f"Init {init_dt.strftime('%Y-%m-%d %H')}z"
    elif meta:
        run_str = f"Retrieved {meta['value']}"
    else:
        run_str = "unknown"
    fig.text(0.03, 0.975, f"{date.strftime('%A')} {metric_title(metric, hour)}", fontsize=22,
              fontproperties=poppins_reg, color="#2b2a26", ha="left", va="top")
    fig.text(0.03, 0.935, f"{SOURCE_LABELS[source]} • {run_str}",
              fontsize=12, fontproperties=poppins_reg, color="#5a584f", ha="left", va="top")

    # Attribution
    fig.text(0.5, 0.012, f"{SOURCE_LABELS[source]} — Ingalls Weather", fontsize=9,
              fontproperties=poppins_reg, color="#8a887e", ha="center", va="bottom")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, facecolor=fig.get_facecolor(), dpi=200)
    plt.close(fig)
    print(f"Saved base map to {output_path}")

    # ---- Composite logo, bottom-right, snug inside the frame ----
    if LOGO_FILE.exists():
        base = Image.open(output_path).convert("RGB")
        bw, bh = base.size
        arr = np.array(base)
        y = bh // 2
        black_cols = [x for x in range(bw) if arr[y, x][0] < 40 and arr[y, x][1] < 40 and arr[y, x][2] < 40]
        x = bw // 2
        black_rows = [yy for yy in range(bh) if arr[yy, x][0] < 40 and arr[yy, x][1] < 40 and arr[yy, x][2] < 40]
        frame_right = max(black_cols) if black_cols else bw - 20
        frame_bottom = max(black_rows) if black_rows else bh - 20

        logo = Image.open(LOGO_FILE).convert("RGB")
        target_w = int(bw * 0.08)
        scale = target_w / logo.width
        target_h = int(logo.height * scale)
        logo_resized = logo.resize((target_w, target_h), Image.LANCZOS)

        pos = (frame_right - MAP_FRAME_INSET_PX - target_w, frame_bottom - MAP_FRAME_INSET_PX - target_h)
        base.paste(logo_resized, pos)
        base.save(output_path)
        print(f"Composited logo at {pos}")
    else:
        print(f"NOTE: logo not found at {LOGO_FILE}, skipping (map saved without logo).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build an Ingalls Weather Columbia Basin temperature map.")
    parser.add_argument("--source", choices=SOURCES, default="wm6-3km",
                         help="Forecast source (default: wm6-3km).")
    parser.add_argument("--metric", choices=METRICS, default="high",
                         help="Temperature metric: high, low, or time (default: high).")
    parser.add_argument("--hour", type=int, default=None,
                         help="Local hour (0-23), required when --metric time.")
    parser.add_argument("--date", type=str, default=None,
                         help="Target date, YYYY-MM-DD (default: the coming Sunday).")
    parser.add_argument("--file", type=Path, default=None,
                         help="Render from a local saved grid (.npz with lat/lon/temp_k) "
                              "instead of fetching live.")
    parser.add_argument("--out", type=Path, default=None,
                         help="Output PNG path (default: output/columbia_basin_<source>_<metric>_<date>.png).")
    args = parser.parse_args()

    if args.metric == "time" and args.hour is None:
        parser.error("--metric time requires --hour H (0-23).")
    if args.hour is not None and not (0 <= args.hour <= 23):
        parser.error("--hour must be between 0 and 23.")

    if args.file and not args.file.exists():
        sys.exit(f"--file {args.file} not found.")

    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        today = datetime.now(LOCAL_TZ).date()
        days_ahead = (6 - today.weekday()) % 7 or 7  # next Sunday, weekday(): Mon=0..Sun=6
        target_date = today + timedelta(days=days_ahead)

    out_path = args.out or (OUTPUT_DIR / f"columbia_basin_{args.source}_"
                             f"{metric_tag(args.metric, args.hour)}_{target_date.isoformat()}.png")
    build_map(args.source, args.metric, args.hour, target_date, out_path, override_path=args.file)

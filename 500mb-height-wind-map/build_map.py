"""
WM-6 Ensemble Mean 500 mb Heights & Wind Map -- one-off builder
Ingalls Weather

Styled map centered on Portland, OR, wide enough to reach north into SE
Alaska -- the Northeast Pacific, US West Coast, and Western Canada in one
frame:
  - Contours: ensemble-mean 500 mb geopotential height isolines, every 6 dam
    (60 m -- the user-requested interval; note this is finer than the
    standard 6 dam... see MSLP sibling script's 4 hPa note for the general
    pattern of "pick the standard synoptic interval" -- 6 dam *is* the
    standard 500 mb analysis interval), labeled with the conventional
    3-digit truncated dam value (e.g. "564" for 5640 m).
  - Shading: ensemble-mean 500 mb wind speed, varied purple, starting at 30
    kt (below that is left unshaded).

USAGE
-----
    python build_map.py --date 2026-08-22 --hour 0    # 2026-08-22 00Z
    python build_map.py --file snapshot.npz            # render from a saved fetch

Requires WB_API_KEY in the environment (see
https://app.windbornesystems.com/api_tokens).

WM-6's gridded endpoint only serves per-variable/per-level subsets for
forecast hours still in "hot" storage; every run the sibling TPW map was
tested against had already moved to archived storage by fetch time, at
which point the API only serves the complete per-hour archive (all
variables/levels/products, ~2 GB compressed) via a presigned URL
(`as_url=true`) -- see fetch_wm6_fields()'s docstring for how this script
avoids downloading the whole thing, same approach as
../tpw-wm6-ensemble-map/build_map.py.

WindBorne's public docs (api.windbornesystems.com) document the
*hot-storage* API's `variable`/`level` query parameters for pressure-level
fields (`geopotential`, `wind_u`, `wind_v`, 25 levels 10-1000 hPa) but don't
document the *archived* Zarr file's internal array layout for a
multi-level variable -- unlike ../tpw-wm6-ensemble-map/build_map.py's
single-level surface fields (TCWV, MSLP), which are flat (lat, lon)
arrays under `ensemble_mean/<variable>`, a pressure-level variable could
plausibly be archived either as one array per level (e.g.
`ensemble_mean/geopotential_500`) or as a single 3D (level, lat, lon)
array alongside a level coordinate array. fetch_pressure_level_field()
below tries the level-specific-array layout first, falls back to the
single-3D-array-plus-coordinate layout, and fails with a diagnostic
listing everything actually found under `ensemble_mean/` if neither
guess matches -- this was written without the ability to test against a
real archived file (no WB_API_KEY in this environment), so treat the
first real run as the thing that validates this assumption.

REQUIRES (already checked into /maps at repo root, shared across all
Ingalls Weather map projects):
    countries_slim.json, states_lakes_slim.json, admin0_boundary_lines.json
  countries_slim.json (full country polygons, not just the coastline-only
  land_slim.json, which is clipped to the Pacific Northwest and doesn't
  reach SE Alaska) draws both the coastline and doubles as the land layer.
  Sourced from raw.githubusercontent.com/martynafford/natural-earth-geojson.

Logo is read from /assets/ingalls_weather_logo.png at repo root.
"""

import argparse
import json
import re
import sys
import tempfile
import os
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.colors import Normalize, LinearSegmentedColormap
import numpy as np
import requests
import zarr
from remotezip import RemoteZip
from scipy.interpolate import RegularGridInterpolator

import cartopy.crs as ccrs
import shapely
from shapely.geometry import shape, box
from PIL import Image

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
MAPS_DIR = REPO_ROOT / "maps"
ASSETS_DIR = REPO_ROOT / "assets"
THIS_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = THIS_DIR / "output"

COUNTRIES_FILE = MAPS_DIR / "countries_slim.json"
STATES_LAKES_FILE = MAPS_DIR / "states_lakes_slim.json"
ADMIN0_LINES_FILE = MAPS_DIR / "admin0_boundary_lines.json"
LOGO_FILE = ASSETS_DIR / "ingalls_weather_logo.png"

TARGET_COUNTRIES = {"United States of America", "Canada", "Mexico"}

LAND_COLOR = "#EBEBE8"  # neutral light grey -- toned down further on request so it stays
# quiet under the purple wind shading (was #F5E7B3, then #EDE5C1).
OCEAN_COLOR = "#D2E8F3"

# "Major" lakes only -- states_lakes_slim.json's Natural Earth `scalerank`
# field ranks lake prominence (0 = most prominent, e.g. Lake Superior/
# Great Slave Lake/Lake Winnipeg, up through small reservoirs at 5-6);
# checked against every lake feature that actually falls within this map's
# domain (see load_lakes()) and 0-2 is the cutoff that keeps genuinely
# major lakes (Great Salt Lake, Great Slave Lake, Lake Winnipeg, Lake
# Athabasca, Lake of the Woods, ...) without pulling in minor reservoirs.
MAJOR_LAKE_MAX_SCALERANK = 2

POPPINS_REG_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf"
POPPINS_MED_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf"

# ---------------------------------------------------------------------------
# Figure geometry -- tuned by eye against this map's (wider than tall)
# domain, same LambertConformal caveat as the TPW sibling map: the visible
# curved area doesn't fill the rectangular axes box, so a mismatched
# FIG_WIDTH_IN/FIG_HEIGHT_IN just means more/less unfilled margin, not a
# hard visual bug.
# ---------------------------------------------------------------------------
FIG_WIDTH_IN, FIG_HEIGHT_IN = 10.2, 8.6
FIG_DPI = 200
AXES_RECT = [0.03, 0.15, 0.94, 0.72]  # [left, bottom, width, height], figure fraction
MAP_FRAME_INSET_PX = 22

# ---------------------------------------------------------------------------
# Map domain -- centered on Portland, OR (45.52N/122.68W), wide enough
# north to reach SE Alaska (Ketchikan 55.3N / Sitka 57.1N / Juneau 58.3N
# all comfortably inside LAT_MAX) and far enough south/wide enough in
# longitude to show real synoptic-scale context around a 500 mb wave
# rather than just the immediate Pacific Northwest.
# ---------------------------------------------------------------------------
LON_MIN, LON_MAX = -152.0, -95.0
LAT_MIN, LAT_MAX = 30.0, 61.0
CENTER_LON, CENTER_LAT = (LON_MIN + LON_MAX) / 2, (LAT_MIN + LAT_MAX) / 2

# See ../tpw-wm6-ensemble-map/build_map.py's FETCH_PAD_LON_DEG/
# FETCH_PAD_LAT_DEG comment for why a conic projection needs generous,
# asymmetric padding beyond a plain rectangular lon/lat crop. Re-derived
# for this map's own domain/figure geometry (not copied from the TPW
# map's, which has a different aspect ratio) by inverse-transforming the
# rendered axes' actual corner pixels back to lon/lat: the top corners
# need ~18.3 deg of extra longitude beyond LON_MIN/LON_MAX, and the
# bottom edge dips ~4.1 deg south of LAT_MIN at its corners -- both
# comfortably inside the padding below.
FETCH_PAD_LON_DEG = 30.0
FETCH_PAD_LAT_DEG = 5.0

MAP_CLIP_BOX = box(LON_MIN - FETCH_PAD_LON_DEG, LAT_MIN - FETCH_PAD_LAT_DEG,
                    LON_MAX + FETCH_PAD_LON_DEG, LAT_MAX + FETCH_PAD_LAT_DEG)

# WM-6's native 0.25 deg spacing upsampled for a smooth curved warp -- see
# ../tpw-wm6-ensemble-map/build_map.py's RESAMPLE_FACTOR comment.
RESAMPLE_FACTOR = 6

# ---------------------------------------------------------------------------
# 500 mb height contours -- 6 dam (60 m) interval, the standard synoptic
# 500 mb analysis interval and the user-requested one. Labeled with the
# conventional truncated 3-digit dam value (e.g. "564" for 5640 m).
# ---------------------------------------------------------------------------
HEIGHT_CONTOUR_INTERVAL_DAM = 6
STANDARD_GRAVITY = 9.80665  # m/s^2 -- geopotential (m^2/s^2) -> geopotential height (m)

# ---------------------------------------------------------------------------
# 500 mb wind speed shading -- varied purple, starting at 30 kt (per the
# user's spec) through a strong 500 mb jet core. Not power-law spaced like
# the TPW sibling map's color table (no established compressed convention
# for wind speed the way TPW has for moisture) -- plain linear steps.
# ---------------------------------------------------------------------------
WIND_RGB_COLORS = [
    [241, 230, 249],   # 30 kt -- pale lavender
    [214, 179, 234],   # 50 kt
    [178, 102, 217],   # 70 kt
    [122, 31, 162],    # 90 kt
    [59, 7, 100],       # 110 kt -- deep violet / near-black purple (jet core)
]
WIND_KT_MIN = 30.0
WIND_KT_MAX = 110.0
WIND_KT_STOPS = np.linspace(WIND_KT_MIN, WIND_KT_MAX, len(WIND_RGB_COLORS))

# Fades in by alpha (not a hard on/off switch) between WIND_KT_MIN and
# WIND_ALPHA_FADE_END_KT -- same rationale as the TPW map's
# TPW_ALPHA_FADE_END_IN: the basemap shows through faintly right at the 30
# kt floor rather than the shading switching on abruptly.
WIND_ALPHA_FADE_END_KT = 40.0
WIND_ALPHA_FADE_START = 0.35
WIND_ALPHA_FADE_END = 1.0

MS_TO_KT = 1.943844


def build_wind_colormap():
    span = WIND_KT_MAX - WIND_KT_MIN
    stops = [((kt - WIND_KT_MIN) / span, [c / 255 for c in rgb])
             for kt, rgb in zip(WIND_KT_STOPS, WIND_RGB_COLORS)]
    return LinearSegmentedColormap.from_list("ingalls_500mb_wind", stops, N=256)


# ---------------------------------------------------------------------------
# WindBorne API
# ---------------------------------------------------------------------------
WB_BASE = "https://api.windbornesystems.com/forecasts/v1/wm-6"
LEVEL_HPA = 500
GEOPOTENTIAL_VARIABLE = "geopotential"
WIND_U_VARIABLE = "wind_u"
WIND_V_VARIABLE = "wind_v"

# Candidate names for a pressure-level coordinate array inside the archived
# Zarr file, in case the geopotential/wind_u/wind_v arrays are archived as
# a single 3D (level, lat, lon) array rather than one array per level --
# see this file's module docstring for why both layouts are handled.
LEVEL_COORD_CANDIDATES = ["level", "levels", "pressure_level", "pressure_levels", "isobaricInhPa", "plev"]


def wb_get(path, api_key, **params):
    headers = {"Authorization": f"Bearer {api_key}"}
    resp = requests.get(f"{WB_BASE}/{path}", headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_zarr_array(remote_zip, names, tmp_dir, array_path):
    """Copy just one array's metadata + chunk file(s) out of the remote
    zip into a local directory tree, then open it with zarr -- lets zarr's
    codec pipeline handle decoding without pulling in the rest of the
    archive. Same helper as ../tpw-wm6-ensemble-map/build_map.py."""
    entries = [n for n in names if n == f"{array_path}/zarr.json" or n.startswith(f"{array_path}/c")]
    for name in entries:
        dest = tmp_dir / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(remote_zip.read(name))
    return zarr.open_array(store=str(tmp_dir), path=array_path, mode="r")[:]


def fetch_pressure_level_field(remote_zip, names, tmp_dir, variable, level_hpa, lat_len, lon_len):
    """Fetch a single-level 2D (lat, lon) slice of an ensemble-mean
    pressure-level variable, regardless of which of two plausible archive
    layouts WM-6 actually uses (see module docstring):

    1. A level-specific array, e.g. `ensemble_mean/geopotential_500` --
       tried first by scanning for any top-level array path containing
       both `variable` and `level_hpa`.
    2. A single 3D array `ensemble_mean/<variable>` (level, lat, lon in
       some order) plus a 1D level-coordinate array (see
       LEVEL_COORD_CANDIDATES) -- the level axis is located by matching
       shape entries against the coordinate array's length rather than
       assumed positionally, since the axis order isn't documented.

    Raises SystemExit with the actual archive contents under
    `ensemble_mean/` if neither layout matches, rather than guessing
    silently wrong.
    """
    # Every array's root group path -- the prefix before "/zarr.json" --
    # at whatever depth it actually lives, not just the first path
    # segment (a nested array like "ensemble_mean/geopotential/zarr.json"
    # would otherwise only ever surface as "ensemble_mean", which can
    # never match a variable-specific lookup).
    array_group_paths = sorted({n[: -len("/zarr.json")] for n in names if n.endswith("/zarr.json")})
    level_str = str(level_hpa)
    direct_matches = [p for p in array_group_paths
                       if p.startswith(f"ensemble_mean/{variable}") and level_str in p]
    if len(direct_matches) == 1:
        print(f"  {variable}: found level-specific array '{direct_matches[0]}'")
        return fetch_zarr_array(remote_zip, names, tmp_dir, direct_matches[0])

    array_path = f"ensemble_mean/{variable}"
    if array_path not in array_group_paths:
        ensemble_mean_entries = [p for p in array_group_paths if p.startswith("ensemble_mean/")]
        raise SystemExit(
            f"Could not find '{array_path}' (or a level-specific variant) in the archive. "
            f"Entries found under ensemble_mean/: {ensemble_mean_entries}"
        )

    shape_meta = json.loads(remote_zip.read(f"{array_path}/zarr.json"))
    arr_shape = tuple(shape_meta["shape"])
    if len(arr_shape) == 2:
        print(f"  {variable}: array is already 2D ({arr_shape}) -- no level axis to slice")
        return fetch_zarr_array(remote_zip, names, tmp_dir, array_path)

    for cand in LEVEL_COORD_CANDIDATES:
        if cand in array_group_paths:
            level_values = np.asarray(fetch_zarr_array(remote_zip, names, tmp_dir, cand))
            level_axis_candidates = [i for i, n in enumerate(arr_shape) if n == len(level_values)]
            if len(level_axis_candidates) != 1:
                continue
            level_idx = int(np.argmin(np.abs(level_values - level_hpa)))
            print(f"  {variable}: 3D array {arr_shape}, level coord '{cand}', "
                  f"axis {level_axis_candidates[0]}, index {level_idx} "
                  f"({level_values[level_idx]:g} -- requested {level_hpa} hPa)")
            full = fetch_zarr_array(remote_zip, names, tmp_dir, array_path)
            return np.take(full, level_idx, axis=level_axis_candidates[0])

    raise SystemExit(
        f"'{array_path}' is a {len(arr_shape)}D array {arr_shape} but no pressure-level coordinate "
        f"array was found among {LEVEL_COORD_CANDIDATES}. Top-level arrays present: {top_names}"
    )


def fetch_wm6_fields(valid_time_utc, api_key):
    """Fetch the WM-6 ensemble-mean 500 mb geopotential, wind_u, and
    wind_v grids valid nearest to valid_time_utc, cropped to the map bbox,
    in a single remote-zip session. Same archived-run / presigned-URL /
    remotezip range-request approach as
    ../tpw-wm6-ensemble-map/build_map.py's fetch_wm6_fields() -- see that
    file's docstring for the full explanation of why (WM-6 archives a run
    shortly after it finishes, at which point per-variable filtering is
    rejected and only the complete ~2 GB per-forecast-hour file is
    servable, so this avoids downloading the whole thing).

    Returns (lat_1d, lon_1d, height_dam_2d, wind_kt_2d, meta dict with
    initialization_time/valid_time/forecast_hour)."""
    url_info = wb_get("gridded", api_key, variable="all",
                       time=valid_time_utc.strftime("%Y-%m-%dT%H:%M:%SZ"), as_url="true")
    print("Opening archived WM-6 run via presigned URL (range-request fetch, not a full download)...")

    with RemoteZip(url_info["url"]) as rz:
        names = rz.namelist()
        root_meta = json.loads(rz.read("zarr.json"))["attributes"]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            lat = fetch_zarr_array(rz, names, tmp_dir, "latitude")
            lon = fetch_zarr_array(rz, names, tmp_dir, "longitude")

            print(f"Fetching 500 mb fields (lat {len(lat)} x lon {len(lon)} native grid)...")
            geopotential = fetch_pressure_level_field(rz, names, tmp_dir, GEOPOTENTIAL_VARIABLE,
                                                       LEVEL_HPA, len(lat), len(lon))
            wind_u = fetch_pressure_level_field(rz, names, tmp_dir, WIND_U_VARIABLE,
                                                 LEVEL_HPA, len(lat), len(lon))
            wind_v = fetch_pressure_level_field(rz, names, tmp_dir, WIND_V_VARIABLE,
                                                 LEVEL_HPA, len(lat), len(lon))

    height_m = geopotential / STANDARD_GRAVITY
    height_dam = height_m / 10.0
    wind_kt = np.hypot(wind_u, wind_v) * MS_TO_KT

    # Longitude unwrapped around CENTER_LON before cropping -- see
    # ../tpw-wm6-ensemble-map/build_map.py's fetch_wm6_fields() comment on
    # FETCH_PAD_LON_DEG for why (lets the antimeridian-crossing padding
    # crop correctly instead of splitting into two disjoint pieces).
    lon_unwrapped = ((lon - CENTER_LON + 180) % 360) - 180 + CENTER_LON
    lat_idx = np.where((lat >= LAT_MIN - FETCH_PAD_LAT_DEG) & (lat <= LAT_MAX + FETCH_PAD_LAT_DEG))[0]
    lon_mask = (lon_unwrapped >= LON_MIN - FETCH_PAD_LON_DEG) & (lon_unwrapped <= LON_MAX + FETCH_PAD_LON_DEG)
    lon_idx = np.where(lon_mask)[0]
    lon_idx = lon_idx[np.argsort(lon_unwrapped[lon_idx])]
    lat_crop = lat[lat_idx]
    lon_crop = lon_unwrapped[lon_idx]
    height_crop = height_dam[np.ix_(lat_idx, lon_idx)]
    wind_crop = wind_kt[np.ix_(lat_idx, lon_idx)]

    # WM-6's latitude axis runs north-to-south; flip to ascending -- see
    # ../tpw-wm6-ensemble-map/build_map.py's fetch_wm6_fields() for why.
    if lat_crop[0] > lat_crop[-1]:
        lat_crop = lat_crop[::-1]
        height_crop = height_crop[::-1, :]
        wind_crop = wind_crop[::-1, :]

    meta = {
        "initialization_time": root_meta["initialization_time"],
        "valid_time": root_meta["valid_time"],
        "forecast_hour": root_meta["forecast_hour"],
    }
    return lat_crop, lon_crop, height_crop, wind_crop, meta


def resample_to_finer_grid(lat, lon, values, factor=RESAMPLE_FACTOR):
    interp = RegularGridInterpolator((lat, lon), values, method="linear")
    fine_lat = np.linspace(lat[0], lat[-1], len(lat) * factor)
    fine_lon = np.linspace(lon[0], lon[-1], len(lon) * factor)
    fine_lon_grid, fine_lat_grid = np.meshgrid(fine_lon, fine_lat)
    fine_values = interp((fine_lat_grid, fine_lon_grid))
    return fine_lat, fine_lon, fine_values


def imshow_antimeridian_safe(ax, data, lon, lat, transform, **imshow_kwargs):
    """Same helper as ../tpw-wm6-ensemble-map/build_map.py -- see its
    docstring for why a single imshow call can't be used for a lon array
    that extends past standard -180..180."""
    boundary_overlap_deg = 0.1
    lon_std = ((lon + 180) % 360) - 180
    wrap_idx = np.where(np.diff(lon_std) < 0)[0]
    bounds = [0, *(i + 1 for i in wrap_idx), len(lon_std)]
    n_pieces = len(bounds) - 1
    for i, (start, end) in enumerate(zip(bounds[:-1], bounds[1:])):
        left = lon_std[start] if i == 0 else -180.0 - boundary_overlap_deg
        right = lon_std[end - 1] if i == n_pieces - 1 else 180.0 + boundary_overlap_deg
        ax.imshow(data[:, start:end], transform=transform, origin="lower",
                  extent=[left, right, lat[0], lat[-1]], **imshow_kwargs)


# ---------------------------------------------------------------------------
# Basemap layers -- same loaders as ../tpw-wm6-ensemble-map/build_map.py
# ---------------------------------------------------------------------------
def clip_to_map(geom):
    clipped = shapely.segmentize(geom, max_segment_length=0.5).intersection(MAP_CLIP_BOX)
    return None if clipped.is_empty else clipped


def clip_outline_to_map(geom):
    return clip_to_map(geom.boundary)


def _load_country_geoms():
    with open(COUNTRIES_FILE) as f:
        data = json.load(f)
    return [shape(feat["geometry"]) for feat in data["features"]
            if feat["properties"].get("NAME") in TARGET_COUNTRIES]


def load_countries():
    return [g for g in (clip_outline_to_map(g) for g in _load_country_geoms()) if g is not None]


def load_countries_filled():
    return [g for g in (clip_to_map(g) for g in _load_country_geoms()) if g is not None]


def load_states():
    with open(STATES_LAKES_FILE) as f:
        data = json.load(f)
    state_geoms = []
    for feat in data["features"]:
        props = feat["properties"]
        if "Lake" in props.get("featurecla", ""):
            continue
        if props.get("admin") in TARGET_COUNTRIES:
            clipped = clip_outline_to_map(shape(feat["geometry"]))
            if clipped is not None:
                state_geoms.append(clipped)
    return state_geoms


def load_lakes():
    """Major lake polygons -- see MAJOR_LAKE_MAX_SCALERANK. Clipped as
    filled area (like load_countries_filled()), not outline-only, since
    lakes are drawn as their own filled water layer rather than just a
    boundary line."""
    with open(STATES_LAKES_FILE) as f:
        data = json.load(f)
    lake_geoms = []
    for feat in data["features"]:
        props = feat["properties"]
        if "Lake" not in props.get("featurecla", ""):
            continue
        if (props.get("scalerank") or 0) > MAJOR_LAKE_MAX_SCALERANK:
            continue
        clipped = clip_to_map(shape(feat["geometry"]))
        if clipped is not None:
            lake_geoms.append(clipped)
    return lake_geoms


def load_boundary_lines(path):
    with open(path) as f:
        data = json.load(f)
    geoms = [shape(feat["geometry"]) for feat in data["features"]]
    return [g for g in (clip_to_map(g) for g in geoms) if g is not None]


def height_contour_label(dam_value):
    """Conventional truncated 3-digit synoptic label, e.g. 5640 m -> 564
    dam -> "564"."""
    return f"{int(round(dam_value)) % 1000:03d}"


def build_map(valid_time_utc, output_path, override_path=None):
    poppins_reg = fm.FontProperties(fname=POPPINS_REG_PATH)
    poppins_semibold = fm.FontProperties(fname=POPPINS_MED_PATH)

    if override_path:
        print(f"Using local snapshot: {override_path}")
        npz = np.load(override_path, allow_pickle=True)
        lat, lon, height_dam, wind_kt = npz["lat"], npz["lon"], npz["height_dam"], npz["wind_kt"]
        meta = npz["meta"].item()
    else:
        api_key = os.environ.get("WB_API_KEY")
        if not api_key:
            sys.exit("WB_API_KEY not set -- get a token at "
                      "https://app.windbornesystems.com/api_tokens, or pass --file "
                      "to render from a saved snapshot instead.")
        lat, lon, height_dam, wind_kt, meta = fetch_wm6_fields(valid_time_utc, api_key)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        snapshot_name = f"snapshot_{valid_time_utc.strftime('%Y-%m-%d_%H')}z.npz"
        np.savez(OUTPUT_DIR / snapshot_name,
                  lat=lat, lon=lon, height_dam=height_dam, wind_kt=wind_kt, meta=meta)

    print(f"500 mb height range in fetched crop: {height_dam.min():.0f} - {height_dam.max():.0f} dam")
    print(f"500 mb wind range in fetched crop: {wind_kt.min():.0f} - {wind_kt.max():.0f} kt")
    print(f"Resampling from {lat.size}x{lon.size} native grid...")
    lat_r, lon_r, height_dam = resample_to_finer_grid(lat, lon, height_dam)
    _, _, wind_kt = resample_to_finer_grid(lat, lon, wind_kt)
    lat, lon = lat_r, lon_r

    print("Loading basemap layers...")
    country_geoms = load_countries()
    country_fill_geoms = load_countries_filled()
    state_geoms = load_states()
    lake_geoms = load_lakes()
    admin0_lines = load_boundary_lines(ADMIN0_LINES_FILE)

    pc = ccrs.PlateCarree()
    proj = ccrs.LambertConformal(central_longitude=CENTER_LON, central_latitude=CENTER_LAT,
                                  standard_parallels=(LAT_MIN, LAT_MAX))

    fig = plt.figure(figsize=(FIG_WIDTH_IN, FIG_HEIGHT_IN), dpi=FIG_DPI)
    fig.patch.set_facecolor("#f7f6f2")

    ax = fig.add_axes(AXES_RECT, projection=proj)
    ax.set_extent([LON_MIN, LON_MAX, LAT_MIN, LAT_MAX], crs=pc)
    ax.patch.set_facecolor(OCEAN_COLOR)

    ax.add_geometries(country_fill_geoms, crs=pc, facecolor=LAND_COLOR, edgecolor="none", zorder=0.5)

    # Wind speed shading -- fixed kt-to-color enhancement curve, faded in
    # via per-pixel alpha between WIND_KT_MIN and WIND_ALPHA_FADE_END_KT --
    # see ../tpw-wm6-ensemble-map/build_map.py's TPW field comment for why
    # (basemap shows through faintly near the floor instead of switching
    # on abruptly).
    wind_cmap = build_wind_colormap()
    wind_norm = Normalize(vmin=WIND_KT_MIN, vmax=WIND_KT_MAX)
    wind_rgba = wind_cmap(wind_norm(wind_kt))

    fade_ratio = np.clip((wind_kt - WIND_KT_MIN) / (WIND_ALPHA_FADE_END_KT - WIND_KT_MIN), 0, 1)
    alpha = WIND_ALPHA_FADE_START + (WIND_ALPHA_FADE_END - WIND_ALPHA_FADE_START) * fade_ratio
    wind_rgba[..., 3] = np.where(wind_kt < WIND_KT_MIN, 0.0, alpha)

    imshow_antimeridian_safe(ax, wind_rgba, lon, lat, pc, zorder=1)

    # Major lakes -- drawn over the wind shading (so a lake reads as plain
    # water, not tinted purple) but under the height contours, the same
    # way a real analysis chart shows contours running across a lake
    # surface rather than stopping at its shoreline.
    ax.add_geometries(lake_geoms, crs=pc, facecolor=OCEAN_COLOR, edgecolor="#4a6b7a", linewidth=0.6, zorder=1.2)

    ax.add_geometries(country_geoms, crs=pc, facecolor="none", edgecolor="#4a6b7a", linewidth=0.8, zorder=1.5)
    ax.add_geometries(state_geoms, crs=pc, facecolor="none", edgecolor="#5a4632", linewidth=0.8, zorder=2)
    ax.add_geometries(admin0_lines, crs=pc, facecolor="none", edgecolor="#3a2f21", linewidth=1.1, zorder=2.5)

    # 500 mb height contours -- 6 dam interval, drawn above everything else
    # so they stay legible over the wind shading and basemap alike.
    level_start = np.floor(height_dam.min() / HEIGHT_CONTOUR_INTERVAL_DAM) * HEIGHT_CONTOUR_INTERVAL_DAM
    level_end = np.ceil(height_dam.max() / HEIGHT_CONTOUR_INTERVAL_DAM) * HEIGHT_CONTOUR_INTERVAL_DAM
    height_levels = np.arange(level_start, level_end + HEIGHT_CONTOUR_INTERVAL_DAM, HEIGHT_CONTOUR_INTERVAL_DAM)
    contours = ax.contour(lon, lat, height_dam, levels=height_levels, transform=pc,
                          colors="#1a1a1a", linewidths=1.1, zorder=3)
    ax.clabel(contours, inline=True, fontsize=7.5,
              fmt=lambda v: height_contour_label(v), colors="#1a1a1a")

    ax.spines['geo'].set_edgecolor('black')
    ax.spines['geo'].set_linewidth(1.6)

    # Colorbar -- below the map, centered on the rendered map frame.
    fig.canvas.draw()
    frame_px = ax.get_window_extent()
    frame_left = frame_px.x0 / (FIG_WIDTH_IN * FIG_DPI)
    frame_right = frame_px.x1 / (FIG_WIDTH_IN * FIG_DPI)
    cbar_width, cbar_height = (frame_right - frame_left) * 0.55, 0.016
    cbar_left = (frame_left + frame_right) / 2 - cbar_width / 2
    cbar_bottom = 0.095

    gradient_kt = np.linspace(WIND_KT_MIN, WIND_KT_MAX, 256).reshape(1, -1)
    cax = fig.add_axes([cbar_left, cbar_bottom, cbar_width, cbar_height])
    cax.imshow(gradient_kt, aspect="auto", cmap=wind_cmap, norm=wind_norm,
               extent=[WIND_KT_MIN, WIND_KT_MAX, 0, 1])
    cax.set_yticks([])
    for spine in cax.spines.values():
        spine.set_edgecolor("#8a887e")
        spine.set_linewidth(0.6)

    kt_ticks = np.arange(WIND_KT_MIN, WIND_KT_MAX + 1, 20)
    cax.set_xticks(kt_ticks)
    cax.set_xticklabels([f"{kt:g}" for kt in kt_ticks])
    cax.tick_params(labelsize=8.5, color="#8a887e", labelcolor="#2b2a26")
    for label in cax.get_xticklabels():
        label.set_fontproperties(poppins_reg)
    cax.set_xlabel("500 mb Wind Speed (kt)", fontsize=8.5, fontproperties=poppins_reg, color="#5a584f")

    # Title & subtitle above the map -- titled off the actual valid time
    # (WM-6's 3-hourly steps mean it's not always exactly the requested
    # hour) rather than the requested one.
    init_dt = datetime.fromisoformat(meta["initialization_time"].replace("Z", "+00:00"))
    valid_dt = datetime.fromisoformat(meta["valid_time"].replace("Z", "+00:00"))

    fig.text(0.03, 0.978, f"{valid_dt.strftime('%a %Y-%m-%d')} {valid_dt.hour:02d}Z 500 mb Heights & Wind",
              fontsize=19, fontproperties=poppins_reg, color="#2b2a26", ha="left", va="top")
    fig.text(0.03, 0.943, "WindBorne WM-6 Ensemble Mean", fontsize=12.5,
              fontproperties=poppins_semibold, color="#3a3835", ha="left", va="top")
    fig.text(0.03, 0.914, f"Init {init_dt.strftime('%Y-%m-%d %H')}Z -- Heights every 6 dam",
              fontsize=10.5, fontproperties=poppins_reg, color="#5a584f", ha="left", va="top")

    fig.text(0.5, 0.012, "WindBorne WM-6 — Ingalls Weather", fontsize=9,
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
        description="Build an Ingalls Weather WM-6 ensemble mean 500 mb heights & wind map.")
    parser.add_argument("--date", type=str, default=None,
                         help="Target date, YYYY-MM-DD, UTC (required unless --file is given).")
    parser.add_argument("--hour", type=int, default=0,
                         help="Target UTC hour, 0-23 (default: 0, i.e. 00Z).")
    parser.add_argument("--file", type=Path, default=None,
                         help="Render from a local saved snapshot (.npz) instead of fetching live.")
    parser.add_argument("--out", type=Path, default=None,
                         help="Output PNG path (default: output/500mb_wm6_ensemble_<date>_<hour>z.png).")
    args = parser.parse_args()

    if not (0 <= args.hour <= 23):
        parser.error("--hour must be between 0 and 23.")

    if args.file and not args.file.exists():
        sys.exit(f"--file {args.file} not found.")

    if not args.file and not args.date:
        parser.error("--date is required (YYYY-MM-DD, UTC) unless --file is given.")

    valid_time_utc = None
    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        valid_time_utc = datetime(target_date.year, target_date.month, target_date.day,
                                   args.hour, tzinfo=timezone.utc)
        date_str = target_date.isoformat()
    else:
        date_str = "snapshot"

    out_path = args.out or (OUTPUT_DIR / f"500mb_wm6_ensemble_{date_str}_{args.hour:02d}z.png")
    build_map(valid_time_utc, out_path, override_path=args.file)

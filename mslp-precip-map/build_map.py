"""
WM-6 Ensemble Mean MSLP & 3-Hour Precipitation Map -- one-off builder
Ingalls Weather

Same domain as ../500mb-height-wind-map/ by default (centered on
Portland, OR, wide enough north to reach SE Alaska), showing a different
pair of fields -- and overridable per-render via
--lon-min/--lon-max/--lat-min/--lat-max for a one-off zoomed view:
  - Contours: ensemble-mean mean sea level pressure isobars, every 4 hPa
    (the standard surface-analysis interval) -- same field/interval as
    ../tpw-wm6-ensemble-map/build_map.py's MSLP contours. The single
    deepest low in view is marked with a red "L" (find_major_low()).
  - Shading: ensemble-mean 3-hour accumulated precipitation (WM-6's
    `total_precipitation_3h`, already the accumulation ending at the
    requested valid time -- see fetch_wm6_fields()'s docstring), discrete
    (bucketed, not a gradient) light-blue -> purple -> red -> white bands
    spanning 0.01-1.5 in, labeled in inches -- see precip_mm_to_rgba().

USAGE
-----
    python build_map.py --date 2026-09-02 --hour 0    # 2026-09-02 00Z
    python build_map.py --file snapshot.npz            # render from a saved fetch

Requires WB_API_KEY in the environment (see
https://app.windbornesystems.com/api_tokens).

Both fields fetched here (`pressure_msl`, `total_precipitation_3h`) are
flat (lat, lon) arrays under `ensemble_mean/` in the archived Zarr file --
confirmed directly against a real archive while building this (unlike
../500mb-height-wind-map/'s pressure-level fields, there's no per-level
array-layout guesswork needed here). Same archived-run / presigned-URL /
remotezip range-request fetch approach as
../tpw-wm6-ensemble-map/build_map.py -- see that file's docstring for the
full explanation of why.

REQUIRES (already checked into /maps at repo root, shared across all
Ingalls Weather map projects):
    countries_slim.json, states_lakes_slim.json, admin0_boundary_lines.json

Logo is read from /assets/ingalls_weather_logo.png at repo root.
"""

import argparse
import json
import sys
import tempfile
import os
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
from matplotlib.colors import LinearSegmentedColormap
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

# Same styling as ../500mb-height-wind-map/build_map.py, kept consistent
# across both products that share this domain.
LAND_COLOR = "#EBEBE8"
OCEAN_COLOR = "#D2E8F3"
MAJOR_LAKE_MAX_SCALERANK = 2  # see ../500mb-height-wind-map/build_map.py's comment

POPPINS_REG_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf"
POPPINS_MED_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf"
# Bold + genuinely rounded, used only for L/H pressure-center markers --
# same font/rationale as ../tpw-wm6-ensemble-map/build_map.py's
# BALOO_BOLD_PATH (checked into /assets since it's variable-only upstream).
BALOO_BOLD_PATH = ASSETS_DIR / "fonts" / "Baloo2-Bold.ttf"

# ---------------------------------------------------------------------------
# Figure geometry -- identical to ../500mb-height-wind-map/build_map.py's
# (same domain, so the same frame/padding math applies verbatim).
# ---------------------------------------------------------------------------
FIG_WIDTH_IN, FIG_HEIGHT_IN = 10.2, 8.6
FIG_DPI = 200
AXES_RECT = [0.03, 0.15, 0.94, 0.72]  # [left, bottom, width, height], figure fraction
MAP_FRAME_INSET_PX = 22

# ---------------------------------------------------------------------------
# Map domain -- identical to ../500mb-height-wind-map/build_map.py's: see
# that file's comment for how this was chosen (centered on Portland, OR,
# reaching SE Alaska) and how FETCH_PAD_LON_DEG/FETCH_PAD_LAT_DEG were
# verified against this exact figure geometry.
# ---------------------------------------------------------------------------
LON_MIN, LON_MAX = -152.0, -95.0
LAT_MIN, LAT_MAX = 30.0, 61.0
CENTER_LON, CENTER_LAT = (LON_MIN + LON_MAX) / 2, (LAT_MIN + LAT_MAX) / 2

FETCH_PAD_LON_DEG = 30.0
FETCH_PAD_LAT_DEG = 5.0

MAP_CLIP_BOX = box(LON_MIN - FETCH_PAD_LON_DEG, LAT_MIN - FETCH_PAD_LAT_DEG,
                    LON_MAX + FETCH_PAD_LON_DEG, LAT_MAX + FETCH_PAD_LAT_DEG)

RESAMPLE_FACTOR = 6

# ---------------------------------------------------------------------------
# MSLP isobars -- 4 hPa interval, the standard surface-analysis interval
# (same as ../tpw-wm6-ensemble-map/build_map.py's).
# ---------------------------------------------------------------------------
MSLP_CONTOUR_INTERVAL_HPA = 4

# ---------------------------------------------------------------------------
# 3-hour precipitation shading -- discrete (bucketed, not a smooth
# gradient) light-blue -> purple -> red -> white bands spanning 0.01-1.5
# in, quantized into PRECIP_N_BUCKETS steps rather than just the 4 anchor
# colors themselves -- 4 solid bands read as a blocky staircase with most
# of a typical (sub-0.5 in) event stuck in a single band, while 25 finer
# steps still reads as clearly bucketed/categorical (not a blend) but
# keeps enough gradation to show spatial structure in the light-to-
# moderate range. PRECIP_RGB_COLORS/PRECIP_IN_STOPS are the same 4 anchor
# colors as before -- build_precip_colormap() interpolates between them,
# then precip_mm_to_rgba() samples that continuous ramp at each bucket's
# center and snaps every pixel to its bucket's single color (no blending
# within a bucket). Defined natively in inches (the unit the legend
# displays); WM-6's data comes back in mm, so PRECIP_MM_STOPS is derived
# from these. Below the floor (0.01 in) is left unshaded.
# ---------------------------------------------------------------------------
PRECIP_RGB_COLORS = [
    [173, 216, 245],    # 0.01 in -- light blue
    [142, 45, 172],     # 0.51 in -- purple
    [214, 39, 40],       # 1.01 in -- red
    [255, 255, 255],     # 1.5 in -- white (open-ended)
]
PRECIP_IN_STOPS = [0.01, 0.51, 1.01, 1.5]
PRECIP_MM_STOPS = [round(v * 25.4, 3) for v in PRECIP_IN_STOPS]
PRECIP_IN_MIN, PRECIP_IN_MAX = PRECIP_IN_STOPS[0], PRECIP_IN_STOPS[-1]
PRECIP_MM_MIN, PRECIP_MM_MAX = PRECIP_MM_STOPS[0], PRECIP_MM_STOPS[-1]
PRECIP_N_BUCKETS = 25


def build_precip_colormap():
    span = PRECIP_MM_MAX - PRECIP_MM_MIN
    stops = [((mm - PRECIP_MM_MIN) / span, [c / 255 for c in rgb])
             for mm, rgb in zip(PRECIP_MM_STOPS, PRECIP_RGB_COLORS)]
    return LinearSegmentedColormap.from_list("ingalls_precip_3h", stops, N=256)


def precip_bucket_colors():
    """The PRECIP_N_BUCKETS solid colors -- build_precip_colormap()
    sampled at each bucket's midpoint -- shared by precip_mm_to_rgba() and
    the colorbar so both use exactly the same swatches."""
    cmap = build_precip_colormap()
    centers = (np.arange(PRECIP_N_BUCKETS) + 0.5) / PRECIP_N_BUCKETS
    return cmap(centers)[:, :3]


def precip_mm_to_rgba(precip_mm):
    """Quantize a precip_mm array into PRECIP_N_BUCKETS equal-width
    buckets between PRECIP_MM_MIN and PRECIP_MM_MAX, each pixel snapped to
    its bucket's single solid color (see precip_bucket_colors()) -- fully
    transparent below the floor, fully opaque at and above it (no alpha
    blending, since this is still a categorical/bucketed fill, just with
    finer steps than the 4 anchor colors alone)."""
    colors = precip_bucket_colors()
    idx = np.clip(((precip_mm - PRECIP_MM_MIN) / (PRECIP_MM_MAX - PRECIP_MM_MIN) * PRECIP_N_BUCKETS).astype(int),
                   0, PRECIP_N_BUCKETS - 1)
    rgba = np.concatenate([colors[idx], np.ones(idx.shape + (1,))], axis=-1)
    rgba[..., 3] = np.where(precip_mm < PRECIP_MM_MIN, 0.0, 1.0)
    return rgba


def find_major_low(lat, lon, mslp_hpa, lon_min, lon_max, lat_min, lat_max):
    """Locate the single deepest low (lowest MSLP grid cell) within the
    visible bbox -- the map's one "major low" marker, not a general
    multi-center L/H detector (a prominence-filtered local-minima scan,
    like ../tpw-wm6-ensemble-map/build_map.py's find_pressure_extrema(),
    was tried first here but also flagged weak, sub-isobar-interval
    minima over flat interior terrain that aren't a real synoptic
    feature -- a plain global minimum is what "that major low" actually
    means for this map). Run before resample_to_finer_grid() so the
    result is a native grid cell, not a smoothed/upsampled one.

    Returns (lon, lat, value_hpa) or None if no cell falls in the bbox."""
    lat_idx = np.where((lat >= lat_min) & (lat <= lat_max))[0]
    lon_idx = np.where((lon >= lon_min) & (lon <= lon_max))[0]
    if lat_idx.size == 0 or lon_idx.size == 0:
        return None
    sub = mslp_hpa[np.ix_(lat_idx, lon_idx)]
    cy, cx = np.unravel_index(np.argmin(sub), sub.shape)
    return lon[lon_idx[cx]], lat[lat_idx[cy]], sub[cy, cx]


# ---------------------------------------------------------------------------
# WindBorne API
# ---------------------------------------------------------------------------
WB_BASE = "https://api.windbornesystems.com/forecasts/v1/wm-6"
MSLP_VARIABLE = "pressure_msl"
PRECIP_VARIABLE = "total_precipitation_3h"


def wb_get(path, api_key, **params):
    headers = {"Authorization": f"Bearer {api_key}"}
    resp = requests.get(f"{WB_BASE}/{path}", headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_zarr_array(remote_zip, names, tmp_dir, array_path):
    """Copy just one array's metadata + chunk file(s) out of the remote
    zip into a local directory tree, then open it with zarr. Same helper
    as ../tpw-wm6-ensemble-map/build_map.py and
    ../500mb-height-wind-map/build_map.py."""
    entries = [n for n in names if n == f"{array_path}/zarr.json" or n.startswith(f"{array_path}/c")]
    for name in entries:
        dest = tmp_dir / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(remote_zip.read(name))
    return zarr.open_array(store=str(tmp_dir), path=array_path, mode="r")[:]


def fetch_wm6_fields(valid_time_utc, api_key):
    """Fetch the WM-6 ensemble-mean MSLP and 3-hour precipitation grids
    valid nearest to valid_time_utc, cropped to the map bbox, in a single
    remote-zip session. Same archived-run / presigned-URL / remotezip
    range-request approach as ../tpw-wm6-ensemble-map/build_map.py's
    fetch_wm6_fields() -- see that file's docstring for the full
    explanation of why.

    Returns (lat_1d, lon_1d, mslp_hpa_2d, precip_mm_2d, meta dict with
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
            mslp_pa = fetch_zarr_array(rz, names, tmp_dir, f"ensemble_mean/{MSLP_VARIABLE}")
            precip_mm = fetch_zarr_array(rz, names, tmp_dir, f"ensemble_mean/{PRECIP_VARIABLE}")

    mslp_hpa = mslp_pa / 100.0

    lon_unwrapped = ((lon - CENTER_LON + 180) % 360) - 180 + CENTER_LON
    lat_idx = np.where((lat >= LAT_MIN - FETCH_PAD_LAT_DEG) & (lat <= LAT_MAX + FETCH_PAD_LAT_DEG))[0]
    lon_mask = (lon_unwrapped >= LON_MIN - FETCH_PAD_LON_DEG) & (lon_unwrapped <= LON_MAX + FETCH_PAD_LON_DEG)
    lon_idx = np.where(lon_mask)[0]
    lon_idx = lon_idx[np.argsort(lon_unwrapped[lon_idx])]
    lat_crop = lat[lat_idx]
    lon_crop = lon_unwrapped[lon_idx]
    mslp_crop = mslp_hpa[np.ix_(lat_idx, lon_idx)]
    precip_crop = precip_mm[np.ix_(lat_idx, lon_idx)]

    if lat_crop[0] > lat_crop[-1]:
        lat_crop = lat_crop[::-1]
        mslp_crop = mslp_crop[::-1, :]
        precip_crop = precip_crop[::-1, :]

    meta = {
        "initialization_time": root_meta["initialization_time"],
        "valid_time": root_meta["valid_time"],
        "forecast_hour": root_meta["forecast_hour"],
    }
    return lat_crop, lon_crop, mslp_crop, precip_crop, meta


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
# Basemap layers -- same loaders as ../500mb-height-wind-map/build_map.py
# (including the major-lakes layer added there).
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
    filled area, not outline-only."""
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


def build_map(valid_time_utc, output_path, override_path=None):
    poppins_reg = fm.FontProperties(fname=POPPINS_REG_PATH)
    poppins_semibold = fm.FontProperties(fname=POPPINS_MED_PATH)
    baloo_bold = fm.FontProperties(fname=BALOO_BOLD_PATH)

    if override_path:
        print(f"Using local snapshot: {override_path}")
        npz = np.load(override_path, allow_pickle=True)
        lat, lon, mslp_hpa, precip_mm = npz["lat"], npz["lon"], npz["mslp_hpa"], npz["precip_mm"]
        meta = npz["meta"].item()
    else:
        api_key = os.environ.get("WB_API_KEY")
        if not api_key:
            sys.exit("WB_API_KEY not set -- get a token at "
                      "https://app.windbornesystems.com/api_tokens, or pass --file "
                      "to render from a saved snapshot instead.")
        lat, lon, mslp_hpa, precip_mm, meta = fetch_wm6_fields(valid_time_utc, api_key)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        snapshot_name = f"snapshot_{valid_time_utc.strftime('%Y-%m-%d_%H')}z.npz"
        np.savez(OUTPUT_DIR / snapshot_name,
                  lat=lat, lon=lon, mslp_hpa=mslp_hpa, precip_mm=precip_mm, meta=meta)

    print(f"MSLP range in fetched crop: {mslp_hpa.min():.0f} - {mslp_hpa.max():.0f} hPa")
    print(f"3-hr precip range in fetched crop: {precip_mm.min():.1f} - {precip_mm.max():.1f} mm")
    major_low = find_major_low(lat, lon, mslp_hpa, LON_MIN, LON_MAX, LAT_MIN, LAT_MAX)
    if major_low:
        print(f"Major low: {major_low[2]:.0f} hPa at {major_low[1]:.2f}N, {major_low[0]:.2f}E")
    print(f"Resampling from {lat.size}x{lon.size} native grid...")
    lat_r, lon_r, mslp_hpa = resample_to_finer_grid(lat, lon, mslp_hpa)
    _, _, precip_mm = resample_to_finer_grid(lat, lon, precip_mm)
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

    # 3-hour precip shading -- discrete QPF buckets (see precip_mm_to_rgba()),
    # not a smooth gradient.
    precip_rgba = precip_mm_to_rgba(precip_mm)

    imshow_antimeridian_safe(ax, precip_rgba, lon, lat, pc, zorder=1)

    # Major lakes -- drawn over the precip shading but under the MSLP
    # isobars, same layering as ../500mb-height-wind-map/build_map.py.
    ax.add_geometries(lake_geoms, crs=pc, facecolor=OCEAN_COLOR, edgecolor="#4a6b7a", linewidth=0.6, zorder=1.2)

    ax.add_geometries(country_geoms, crs=pc, facecolor="none", edgecolor="#4a6b7a", linewidth=0.8, zorder=1.5)
    ax.add_geometries(state_geoms, crs=pc, facecolor="none", edgecolor="#5a4632", linewidth=0.8, zorder=2)
    ax.add_geometries(admin0_lines, crs=pc, facecolor="none", edgecolor="#3a2f21", linewidth=1.1, zorder=2.5)

    # MSLP isobars -- 4 hPa interval, drawn above everything else so they
    # stay legible over the precip shading and basemap alike. Levels
    # computed from this map's actual MSLP range (not a fixed set), same
    # as ../tpw-wm6-ensemble-map/build_map.py's.
    level_start = np.floor(mslp_hpa.min() / MSLP_CONTOUR_INTERVAL_HPA) * MSLP_CONTOUR_INTERVAL_HPA
    level_end = np.ceil(mslp_hpa.max() / MSLP_CONTOUR_INTERVAL_HPA) * MSLP_CONTOUR_INTERVAL_HPA
    mslp_levels = np.arange(level_start, level_end + MSLP_CONTOUR_INTERVAL_HPA, MSLP_CONTOUR_INTERVAL_HPA)
    isobars = ax.contour(lon, lat, mslp_hpa, levels=mslp_levels, transform=pc,
                          colors="#1a1a1a", linewidths=1.0, zorder=3)
    isobars.set_path_effects([pe.withStroke(linewidth=2.6, foreground="white")])
    isobar_labels = ax.clabel(isobars, inline=True, fontsize=7.5, fmt="%d", colors="#1a1a1a")
    for txt in isobar_labels:
        txt.set_path_effects([pe.withStroke(linewidth=2.0, foreground="white")])

    # The major low's "L" marker -- same styling as
    # ../tpw-wm6-ensemble-map/build_map.py's pressure-center markers (red,
    # Baloo 2 Bold, white halo), projected to axes data coordinates once
    # via proj.transform_point().
    if major_low:
        low_lon, low_lat, _ = major_low
        px, py = proj.transform_point(low_lon, low_lat, pc)
        ax.text(px, py, "L", ha="center", va="center", fontsize=22,
                 color="#c0392b", zorder=4, fontproperties=baloo_bold,
                 path_effects=[pe.withStroke(linewidth=1.8, foreground="white")])

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

    # Discrete swatches (equal-width, one per bucket, PRECIP_N_BUCKETS of
    # them) rather than a gradient -- matches the bucketed shading above.
    # With this many buckets, ticking every swatch edge would be
    # unreadable, so ticks go at clean round inch values instead (same
    # approach as a continuous colorbar), positioned at that value's
    # fractional position along the PRECIP_MM_MIN-PRECIP_MM_MAX span.
    swatch_colors = precip_bucket_colors().reshape(1, PRECIP_N_BUCKETS, 3)
    cax = fig.add_axes([cbar_left, cbar_bottom, cbar_width, cbar_height])
    cax.imshow(swatch_colors, aspect="auto", interpolation="nearest",
               extent=[0, PRECIP_N_BUCKETS, 0, 1])
    cax.set_yticks([])
    for spine in cax.spines.values():
        spine.set_edgecolor("#8a887e")
        spine.set_linewidth(0.6)

    in_ticks = np.arange(0.0, PRECIP_IN_MAX + 0.01, 0.25)
    in_ticks[0] = PRECIP_IN_MIN
    tick_positions = (in_ticks - PRECIP_IN_MIN) / (PRECIP_IN_MAX - PRECIP_IN_MIN) * PRECIP_N_BUCKETS
    cax.set_xticks(tick_positions)
    cax.set_xticklabels([f'{v:g}"' for v in in_ticks])
    cax.tick_params(labelsize=8.5, color="#8a887e", labelcolor="#2b2a26")
    for label in cax.get_xticklabels():
        label.set_fontproperties(poppins_reg)
    cax.set_xlabel("3-Hour Precipitation (in)", fontsize=8.5, fontproperties=poppins_reg, color="#5a584f")

    # Title & subtitle above the map.
    init_dt = datetime.fromisoformat(meta["initialization_time"].replace("Z", "+00:00"))
    valid_dt = datetime.fromisoformat(meta["valid_time"].replace("Z", "+00:00"))

    fig.text(0.03, 0.978, f"{valid_dt.strftime('%a %Y-%m-%d')} {valid_dt.hour:02d}Z MSLP & 3-Hour Precip",
              fontsize=19, fontproperties=poppins_reg, color="#2b2a26", ha="left", va="top")
    fig.text(0.03, 0.943, "WindBorne WM-6 Ensemble Mean", fontsize=12.5,
              fontproperties=poppins_semibold, color="#3a3835", ha="left", va="top")
    fig.text(0.03, 0.914, f"Init {init_dt.strftime('%Y-%m-%d %H')}Z",
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
        description="Build an Ingalls Weather WM-6 ensemble mean MSLP & 3-hour precipitation map.")
    parser.add_argument("--date", type=str, default=None,
                         help="Target date, YYYY-MM-DD, UTC (required unless --file is given).")
    parser.add_argument("--hour", type=int, default=0,
                         help="Target UTC hour, 0-23 (default: 0, i.e. 00Z).")
    parser.add_argument("--file", type=Path, default=None,
                         help="Render from a local saved snapshot (.npz) instead of fetching live.")
    parser.add_argument("--out", type=Path, default=None,
                         help="Output PNG path (default: output/mslp_precip_wm6_ensemble_<date>_<hour>z.png).")
    parser.add_argument("--lon-min", type=float, default=None,
                         help="Override the default domain -- all four of --lon-min/--lon-max/"
                              "--lat-min/--lat-max must be given together. Intended for one-off "
                              "zoomed views (e.g. onto a specific storm); the module-level "
                              "LON_MIN/LON_MAX/LAT_MIN/LAT_MAX stay the project's standing default.")
    parser.add_argument("--lon-max", type=float, default=None)
    parser.add_argument("--lat-min", type=float, default=None)
    parser.add_argument("--lat-max", type=float, default=None)
    args = parser.parse_args()

    if not (0 <= args.hour <= 23):
        parser.error("--hour must be between 0 and 23.")

    if args.file and not args.file.exists():
        sys.exit(f"--file {args.file} not found.")

    if not args.file and not args.date:
        parser.error("--date is required (YYYY-MM-DD, UTC) unless --file is given.")

    domain_overrides = (args.lon_min, args.lon_max, args.lat_min, args.lat_max)
    if any(v is not None for v in domain_overrides):
        if any(v is None for v in domain_overrides):
            parser.error("--lon-min/--lon-max/--lat-min/--lat-max must all be given together.")
        # Reassign the module-level domain globals -- every function above
        # (fetch_wm6_fields, clip_to_map, build_map, ...) reads these as
        # free variables resolved at call time, so overriding them here
        # before build_map() runs is enough; no need to thread a domain
        # argument through every function. FETCH_PAD_LON_DEG/
        # FETCH_PAD_LAT_DEG are left as-is: they were sized for the
        # default (wider, higher-latitude) domain, so they over-cover any
        # smaller/lower-latitude zoom -- more padding just fetches a bit
        # more data, it doesn't produce a wrong result.
        LON_MIN, LON_MAX, LAT_MIN, LAT_MAX = args.lon_min, args.lon_max, args.lat_min, args.lat_max
        CENTER_LON, CENTER_LAT = (LON_MIN + LON_MAX) / 2, (LAT_MIN + LAT_MAX) / 2
        MAP_CLIP_BOX = box(LON_MIN - FETCH_PAD_LON_DEG, LAT_MIN - FETCH_PAD_LAT_DEG,
                            LON_MAX + FETCH_PAD_LON_DEG, LAT_MAX + FETCH_PAD_LAT_DEG)
        print(f"Domain override: lon [{LON_MIN}, {LON_MAX}], lat [{LAT_MIN}, {LAT_MAX}]")

    valid_time_utc = None
    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        valid_time_utc = datetime(target_date.year, target_date.month, target_date.day,
                                   args.hour, tzinfo=timezone.utc)
        date_str = target_date.isoformat()
    else:
        date_str = "snapshot"

    out_path = args.out or (OUTPUT_DIR / f"mslp_precip_wm6_ensemble_{date_str}_{args.hour:02d}z.png")
    build_map(valid_time_utc, out_path, override_path=args.file)

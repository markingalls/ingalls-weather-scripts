"""
Tropical Storm Elida Moisture Surge -> Pacific Northwest Map (one-off)
Ingalls Weather

Tracks the moisture plume moving north out of (post-)Tropical Storm Elida,
currently churning in the open eastern Pacific ~985 mi west of southern
Baja California, toward the Pacific Northwest: for every WM-6 (WindBorne
WeatherMesh-6) forecast step over the next 10 days, reads the ensemble
mean total column water vapor (TPW / precipitable water) at each grid
point, then takes the max across all of those steps -- so the map shows,
per pixel, the single highest TPW value forecast to pass over that spot
at any point in the window, in inches, regardless of which day it
happens. Elida itself is forecast to weaken to a remnant low and dissipate
within a few days (NHC, 200 AM PDT Jul 19 2026 advisory); this map tracks
where its moisture ends up, not the storm's own track.

This plots the actual forecast quantity (peak ensemble-mean TPW) rather
than a derived exceedance probability -- an earlier version of this script
computed "chance of TPW > 1 inch" via a Gaussian estimate from WM-6's
mean/std (that variable has no raw-member or threshold-probability output
via the API), but a statistical estimate on top of a forecast read as less
trustworthy than just showing the forecast value itself.

USAGE
-----
    export WB_API_KEY=...              # https://app.windbornesystems.com/api_tokens
    python build_map.py                          # latest WM-6 run, 10-day peak TPW, daily steps
    python build_map.py --max-hour 168 --step-hours 12  # 7-day window, twice-daily sampling

WM-6's gridded endpoint refuses to filter to a single variable for this
run ("Variable filtering is not available for archived forecasts") and
requires variable=all instead, which downloads the full global,
all-163-variable file (~1.9 GB) for every sampled forecast hour rather
than a small single-variable slice -- ~20-25s per fetch at good bandwidth.
Default is one fetch per day (11 requests for the full 10-day window);
--step-hours 12 or 6 samples more finely at ~2x/4x the download time. To
re-render without re-fetching, pass --file path/to/snapshot.npz (see
save/load format in fetch_all() / build_map()).

REQUIRES (already checked into /maps at repo root, shared across all
Ingalls Weather map projects):
    admin1_boundary_lines.json, admin0_boundary_lines.json, land_slim.json
Logo is read from /assets/ingalls_weather_logo.png at repo root.
"""

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
from matplotlib.colors import Normalize, LinearSegmentedColormap
from matplotlib.transforms import offset_copy
import numpy as np
import requests
import zarr
from scipy.interpolate import griddata

import cartopy.crs as ccrs
from shapely.geometry import shape
from PIL import Image

# ---------------------------------------------------------------------------
# Paths (relative to this script's location: elida-moisture-pnw-map/)
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
MAPS_DIR = REPO_ROOT / "maps"
ASSETS_DIR = REPO_ROOT / "assets"
THIS_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = THIS_DIR / "output"

ADMIN1_LINES_FILE = MAPS_DIR / "admin1_boundary_lines.json"
ADMIN0_LINES_FILE = MAPS_DIR / "admin0_boundary_lines.json"
LAND_FILE = MAPS_DIR / "land_slim.json"
LOGO_FILE = ASSETS_DIR / "ingalls_weather_logo.png"

POPPINS_REG_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf"
POPPINS_MED_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf"

# ---------------------------------------------------------------------------
# Data source -- WM-6 global ensemble, gridded (not wm6-3km: that's a
# CONUS-only deterministic 3km product). Runs 3-hourly out to 360h (15
# days). The gridded endpoint's "domain" param (default "conus") is
# documented as a regional crop for the regional-native products (wm6-3km,
# hrrr); it's left unset here rather than assumed to also apply usefully to
# wm-6's own global grid -- Elida's current position (21.4N 125.2W) sits
# well south and west of a strict CONUS bounding box, so this deliberately
# fetches whatever extent the API actually returns un-cropped and lets
# crop_to_bbox() below pull out the map's bbox from that, instead of risking
# a server-side "conus" crop silently cutting off the storm itself.
# ---------------------------------------------------------------------------
WB_BASE = "https://api.windbornesystems.com/forecasts/v1/wm-6"
VARIABLE = "total_column_water_vapour"  # TPW / precipitable water, kg/m^2 (== mm liquid equivalent)
KGM2_PER_INCH = 25.4

# ---------------------------------------------------------------------------
# Figure geometry -- same canvas/colorbar layout as columbia-basin-temps
# and the rest of this repo's maps.
# ---------------------------------------------------------------------------
FIG_WIDTH_IN, FIG_HEIGHT_IN = 10, 8.9
FIG_DPI = 200
AXES_RECT = [0.035, 0.15, 0.93, 0.75]  # [left, bottom, width, height], figure fraction
MAP_FRAME_INSET_PX = 22

# ---------------------------------------------------------------------------
# Map domain -- zoomed out enough to show Elida's current position in the
# open eastern Pacific with real context (not just a tight corridor) up
# through the CA/NV/OR coastal and Great Basin corridor into the Pacific
# Northwest. Wider than this repo's other (more regionally-compact) maps
# since this domain is inherently more north-south elongated -- the extra
# longitude span is what keeps it filling the same 10x8.9in canvas as
# everything else here without heavy letterboxing.
# ---------------------------------------------------------------------------
LON_MIN, LON_MAX = -132.0, -99.0
LAT_MIN, LAT_MAX = 19.0, 50.5
CENTER_LON, CENTER_LAT = -115.5, 34.75

# Elida's center per NHC's 200 AM PDT Sun Jul 19 2026 advisory (0900 UTC):
# 21.4N 125.2W, ~985 mi west of southern Baja California, moving NNW ~13
# mph. A snapshot of where the storm was at advisory time, not a fixed
# geographic point -- update ELIDA_LON/LAT/LABEL if re-running later with a
# newer advisory.
ELIDA_LON, ELIDA_LAT = -125.2, 21.4
ELIDA_LABEL = "TS Elida (09Z Jul 19 position)"

# Degrees beyond the plotted extent to keep when cropping the fetched
# grid, so the padded resample grid below has real data to interpolate
# from all the way to its own edges.
FETCH_PAD_DEG = 1.5

# Resampled onto a common regular lat/lon grid before rendering, padded past
# the plotted extent -- see columbia-basin-temps/build_map.py's
# resample_to_regular_grid() docstring for why the padding matters (cartopy
# imshow gaps at the frame's corners otherwise).
RESAMPLE_NX, RESAMPLE_NY = 600, 500
RESAMPLE_PAD_DEG = 1.5
RESAMPLE_LON_MIN, RESAMPLE_LON_MAX = LON_MIN - RESAMPLE_PAD_DEG, LON_MAX + RESAMPLE_PAD_DEG
RESAMPLE_LAT_MIN, RESAMPLE_LAT_MAX = LAT_MIN - RESAMPLE_PAD_DEG, LAT_MAX + RESAMPLE_PAD_DEG

# ---------------------------------------------------------------------------
# City labels along Elida's likely path -- the Baja/California coast up
# through the Great Basin into the Pacific Northwest.
# ---------------------------------------------------------------------------
CITIES = [
    ("Cabo San Lucas", -109.9124, 22.8905, "left"),
    ("San Diego", -117.1611, 32.7157, "left"),
    ("Los Angeles", -118.2437, 34.0522, "left"),
    ("Las Vegas", -115.1398, 36.1699, "right"),
    ("San Francisco", -122.4194, 37.7749, "left"),
    ("Reno", -119.8138, 39.5296, "right"),
    ("Sacramento", -121.4944, 38.5816, "right"),
    ("Eureka", -124.1637, 40.8021, "left"),
    ("Boise", -116.2023, 43.6150, "right"),
    ("Medford", -122.8756, 42.3265, "left"),
    ("Bend", -121.3153, 44.0582, "right"),
    ("Pendleton", -118.7879, 45.6721, "right"),
    ("Portland", -122.6784, 45.5152, "left"),
    ("Yakima", -120.5059, 46.6021, "right"),
    ("Spokane", -117.4260, 47.6588, "right"),
    ("Seattle", -122.3321, 47.6062, "left"),
]

# ---------------------------------------------------------------------------
# TPW color ramp -- tan (dry) -> green (moistening) -> blue (saturated), a
# fixed absolute inches-of-TPW scale (not rescaled per map, same spirit as
# TEMP_COLOR_TABLE in columbia-basin-temps/build_map.py) so a given shade
# always means the same TPW value across every run of this script.
# ---------------------------------------------------------------------------
TPW_COLOR_STOPS = [
    (0.00, "#efe3bd"),
    (0.20, "#e1d89c"),
    (0.40, "#b7cf7c"),
    (0.60, "#6fae6f"),
    (0.80, "#4a93a0"),
    (1.00, "#215ea8"),
]
TPW_VMIN_IN, TPW_VMAX_IN = 0.0, 3.0  # inches; the eastern Pacific tropical airmass near
                                       # Elida itself can push TPW toward 2.5-3in.


def build_tpw_colormap():
    return LinearSegmentedColormap.from_list("ingalls_tpw", TPW_COLOR_STOPS, N=256)


def resample_to_regular_grid(lat, lon, values):
    """Interpolate a (lat, lon, values) grid -- regular but arbitrarily
    ordered/ranged -- onto a single common regular lat/lon grid padded past
    the map's plotted extent. Returns values_2d, indexed [lat, lon]
    ascending. Mirrors columbia-basin-temps/build_map.py."""
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


# ---------------------------------------------------------------------------
# WindBorne API (WM-6 global ensemble, gridded)
# ---------------------------------------------------------------------------
def wb_get(path, api_key, **params):
    resp = requests.get(f"{WB_BASE}/{path}", headers={"Authorization": f"Bearer {api_key}"},
                         params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _is_array(node):
    """Zarr Arrays have .shape/.dtype; Groups don't -- version-agnostic way
    to tell a leaf array from a subgroup while walking the store."""
    return hasattr(node, "shape") and hasattr(node, "dtype")


def _iter_children(group):
    """(name, child) pairs for a zarr Group -- via .keys()/__getitem__ rather
    than .items(), since zarr's Group API dropped .items() in v3 while still
    supporting the former in both v2 and v3."""
    for name in group.keys():
        yield name, group[name]


def describe_zarr_tree(group, prefix=""):
    lines = []
    for name, child in _iter_children(group):
        path = f"{prefix}/{name}" if prefix else name
        if _is_array(child):
            lines.append(f"  {path}  shape={child.shape} dtype={child.dtype}")
        else:
            lines.append(f"  {path}/")
            lines.extend(describe_zarr_tree(child, path))
    return lines


def find_arrays_by_keyword(group, keyword, prefix=""):
    hits = []
    for name, child in _iter_children(group):
        path = f"{prefix}/{name}" if prefix else name
        if _is_array(child):
            if keyword in name.lower():
                hits.append((path, child))
        else:
            hits.extend(find_arrays_by_keyword(child, keyword, path))
    return hits


def fetch_deterministic_field(g):
    """WM-6's plain (non-distribution) gridded response nests each variable
    under a top-level "deterministic" group -- per WindBorne's own
    documented code example (g["deterministic"]["temperature_2m"]). Falls
    back to searching the whole tree by variable name, and prints the full
    structure if neither finds it, rather than silently mis-reading."""
    try:
        return np.asarray(g["deterministic"][VARIABLE][:])
    except KeyError:
        pass
    hits = find_arrays_by_keyword(g, VARIABLE.lower())
    if len(hits) == 1:
        return np.asarray(hits[0][1][:])
    tree = "\n".join(describe_zarr_tree(g))
    sys.exit(
        f"Couldn't find {VARIABLE} under 'deterministic' or by name in the gridded "
        f"response ({len(hits)} name matches). Full zarr structure returned:\n{tree}\n"
        f"Update fetch_deterministic_field() to match."
    )


def crop_to_bbox(lat, lon, pad=FETCH_PAD_DEG):
    """Crop 1D or 2D lat/lon coordinate arrays to the map bbox (+pad).
    Returns (r0, r1, c0, c1, lat_2d, lon_2d) -- the row/col slice bounds
    apply the same way to any data array shaped like the original grid."""
    lon = np.where(lon > 180, lon - 360, lon)
    if lat.ndim == 1:
        lat2d, lon2d = np.meshgrid(lat, lon, indexing="ij")
    else:
        lat2d, lon2d = lat, lon
    mask = ((lon2d >= LON_MIN - pad) & (lon2d <= LON_MAX + pad) &
            (lat2d >= LAT_MIN - pad) & (lat2d <= LAT_MAX + pad))
    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    if rows.size == 0 or cols.size == 0:
        sys.exit("Fetched grid doesn't overlap the map domain at all -- check LON_MIN/LAT_MIN etc.")
    r0, r1 = int(rows.min()), int(rows.max()) + 1
    c0, c1 = int(cols.min()), int(cols.max()) + 1
    return r0, r1, c0, c1, lat2d[r0:r1, c0:c1], lon2d[r0:r1, c0:c1]


def fetch_all(max_hour, step_hours, api_key):
    """Fetch WM-6's ensemble-mean TPW at every step_hours-spaced forecast
    hour out to max_hour and take the elementwise max across all steps.
    Returns (lat_2d, lon_2d, peak_tpw_in_2d, init_time, hours_used)."""
    run_info = wb_get("run_information", api_key)
    init_time = run_info["initialization_time"]
    available = {a["forecast_hour"] for a in run_info["available"]}
    hours = [h for h in range(0, max_hour + 1, step_hours) if h in available]
    if not hours:
        sys.exit(f"No forecast hours available yet for run {init_time} within 0-{max_hour}h. "
                  f"Try again shortly, or lower --max-hour.")
    if max(hours) < max_hour:
        print(f"NOTE: run {init_time} currently only has data out to F{max(hours):03d} "
              f"(requested out to F{max_hour:03d}); using what's available so far.")

    lat = lon = peak_kgm2 = None
    r0 = r1 = c0 = c1 = None
    for i, fh in enumerate(hours):
        # variable filtering (variable=VARIABLE) 400s on every forecast hour
        # of the current run with "Variable filtering is not available for
        # archived forecasts. Use variable=all ..." -- WM-6's gridded
        # endpoint apparently treats a run's whole storage tier as archived
        # well before every forecast hour has passed, not just genuinely
        # past-valid-time hours. variable=all downloads the full global,
        # all-163-variable file (~1.9 GB) per forecast hour instead of a
        # small single-variable slice -- see README for the size/time
        # tradeoff this forces.
        t0 = time.time()
        print(f"Fetching F{fh:03d} ({i + 1}/{len(hours)}) ...", end=" ", flush=True)
        url_info = wb_get("gridded", api_key, variable="all", format="zarr",
                           as_url="true", initialization_time=init_time, forecast_hour=fh)
        resp = requests.get(url_info["url"], timeout=180)
        resp.raise_for_status()
        print(f"{len(resp.content) / 1e6:.0f} MB in {time.time() - t0:.0f}s")
        # zarr's ZipStore wants a real file path (not an in-memory buffer --
        # this differs between zarr major versions, so write to a temp file
        # rather than assume either constructor signature).
        with tempfile.NamedTemporaryFile(suffix=".zarr.zip") as tmp:
            tmp.write(resp.content)
            tmp.flush()
            store = zarr.storage.ZipStore(tmp.name, mode="r")
            g = zarr.open(store, mode="r")

            if lat is None:
                lat_raw = np.asarray(g["latitude"][:])
                lon_raw = np.asarray(g["longitude"][:])
                print(f"  API returned lat {lat_raw.min():.1f}..{lat_raw.max():.1f}, "
                      f"lon {lon_raw.min():.1f}..{lon_raw.max():.1f}")
                if lat_raw.min() > LAT_MIN or lon_raw.min() > LON_MIN:
                    print(f"  NOTE: returned grid doesn't reach the map's SW corner "
                          f"({LAT_MIN}N, {LON_MIN}E) -- that corner (near Elida's current "
                          f"position) will be nearest-neighbor extrapolated, not real model data.")
                r0, r1, c0, c1, lat, lon = crop_to_bbox(lat_raw, lon_raw)

            field_kgm2 = fetch_deterministic_field(g)[r0:r1, c0:c1]
            store.close()

        peak_kgm2 = field_kgm2 if peak_kgm2 is None else np.maximum(peak_kgm2, field_kgm2)

    return lat, lon, peak_kgm2 / KGM2_PER_INCH, init_time, hours


# ---------------------------------------------------------------------------
# Basemap layers
# ---------------------------------------------------------------------------
def load_boundary_lines(path):
    with open(path) as f:
        data = json.load(f)
    return [shape(feat["geometry"]) for feat in data["features"]]


def load_land():
    with open(LAND_FILE) as f:
        data = json.load(f)
    return [shape(feat["geometry"]) for feat in data["features"] if feat.get("geometry")]


def build_map(max_hour, step_hours, output_path, override_path=None):
    poppins_reg = fm.FontProperties(fname=POPPINS_REG_PATH)
    poppins_semibold = fm.FontProperties(fname=POPPINS_MED_PATH)

    if override_path:
        print(f"Using local snapshot: {override_path}")
        npz = np.load(override_path)
        lat, lon, peak_tpw_in = npz["lat"], npz["lon"], npz["peak_tpw_in"]
        init_time = str(npz["init_time"])
        hours = npz["hours"].tolist()
    else:
        api_key = os.environ.get("WB_API_KEY")
        if not api_key:
            raise SystemExit("Set WB_API_KEY in your environment before running this script.")
        lat, lon, peak_tpw_in, init_time, hours = fetch_all(max_hour, step_hours, api_key)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        snapshot_path = OUTPUT_DIR / f"elida_moisture_snapshot_{init_time.replace(':', '')}.npz"
        np.savez(snapshot_path, lat=lat, lon=lon, peak_tpw_in=peak_tpw_in, init_time=init_time,
                 hours=np.array(hours))
        print(f"Saved raw grid to {snapshot_path} (re-render with --file).")

    print("Resampling onto a regular grid...")
    tpw_grid = resample_to_regular_grid(lat, lon, peak_tpw_in)

    # Slice off the resample padding (real data, but outside the visible
    # frame) before reporting/scaling to the range actually shown.
    lon_frac0 = (LON_MIN - RESAMPLE_LON_MIN) / (RESAMPLE_LON_MAX - RESAMPLE_LON_MIN)
    lon_frac1 = (LON_MAX - RESAMPLE_LON_MIN) / (RESAMPLE_LON_MAX - RESAMPLE_LON_MIN)
    lat_frac0 = (LAT_MIN - RESAMPLE_LAT_MIN) / (RESAMPLE_LAT_MAX - RESAMPLE_LAT_MIN)
    lat_frac1 = (LAT_MAX - RESAMPLE_LAT_MIN) / (RESAMPLE_LAT_MAX - RESAMPLE_LAT_MIN)
    visible = tpw_grid[round(lat_frac0 * RESAMPLE_NY):round(lat_frac1 * RESAMPLE_NY),
                        round(lon_frac0 * RESAMPLE_NX):round(lon_frac1 * RESAMPLE_NX)]
    print(f"Peak TPW over the window (visible frame): {np.nanmin(visible):.2f}in - {np.nanmax(visible):.2f}in")

    print("Loading basemap layers...")
    admin1_lines = load_boundary_lines(ADMIN1_LINES_FILE)
    admin0_lines = load_boundary_lines(ADMIN0_LINES_FILE)
    land_geoms = load_land()

    proj = ccrs.NearsidePerspective(central_longitude=CENTER_LON, central_latitude=CENTER_LAT,
                                     satellite_height=4_000_000)
    pc = ccrs.PlateCarree()

    fig = plt.figure(figsize=(FIG_WIDTH_IN, FIG_HEIGHT_IN), dpi=FIG_DPI)
    fig.patch.set_facecolor("#f7f6f2")

    ax = fig.add_axes(AXES_RECT, projection=proj)
    ax.set_extent([LON_MIN, LON_MAX, LAT_MIN, LAT_MAX], crs=pc)
    ax.patch.set_facecolor("#f7f6f2")

    tpw_cmap = build_tpw_colormap()
    tpw_norm = Normalize(vmin=TPW_VMIN_IN, vmax=TPW_VMAX_IN)
    ax.imshow(tpw_grid, transform=pc, cmap=tpw_cmap, norm=tpw_norm, origin="lower",
              extent=[RESAMPLE_LON_MIN, RESAMPLE_LON_MAX, RESAMPLE_LAT_MIN, RESAMPLE_LAT_MAX], zorder=1)

    ax.add_geometries(land_geoms, crs=pc, facecolor="none", edgecolor="#4a6b7a", linewidth=0.8, zorder=1.5)
    ax.add_geometries(admin1_lines, crs=pc, facecolor="none", edgecolor="#5a4632", linewidth=0.8, zorder=2)
    ax.add_geometries(admin0_lines, crs=pc, facecolor="none", edgecolor="#3a2f21", linewidth=1.1, zorder=2.5)

    # Tropical Storm Elida's position at advisory time -- marked distinctly
    # (tropical-cyclone-style filled circle) from the regular city dots.
    ax.plot(ELIDA_LON, ELIDA_LAT, marker="o", markersize=13, color="#e8722c", zorder=102,
            mec="black", mew=1.3, transform=pc)
    elida_txt = ax.text(ELIDA_LON + 0.5, ELIDA_LAT, ELIDA_LABEL, fontsize=11,
                         fontproperties=poppins_semibold, color="white", ha="left", va="center",
                         zorder=103, transform=pc)
    elida_txt.set_path_effects([pe.withStroke(linewidth=1.8, foreground=(0, 0, 0, 0.85))])

    # City labels -- name plus that spot's peak TPW over the window,
    # sampled from the resampled grid.
    geodetic_transform = pc._as_mpl_transform(ax)
    stroke = [pe.withStroke(linewidth=1.5, foreground=(0, 0, 0, 0.8))]
    for name, lon_c, lat_c, pos in CITIES:
        ax.plot(lon_c, lat_c, marker="o", markersize=5.0, color="white", zorder=100,
                mec="black", mew=0.8, transform=pc)
        city_val = sample_grid_value(tpw_grid, lon_c, lat_c)
        dx_pt = 6 if pos == "right" else -6
        ha = "left" if pos == "right" else "right"

        name_transform = offset_copy(geodetic_transform, fig=fig, x=dx_pt, y=0, units="points")
        name_txt = ax.text(lon_c, lat_c, name, fontsize=9.75, fontproperties=poppins_semibold,
                            color="white", ha=ha, va="center", zorder=101, transform=name_transform)
        name_txt.set_path_effects(stroke)

        val_transform = offset_copy(geodetic_transform, fig=fig, x=dx_pt, y=-4, units="points")
        val_txt = ax.text(lon_c, lat_c, f"{city_val:.1f}\"", fontsize=9.75,
                           fontproperties=poppins_semibold, color="white", ha=ha, va="top",
                           zorder=101, transform=val_transform)
        val_txt.set_path_effects(stroke)

    ax.spines['geo'].set_edgecolor('black')
    ax.spines['geo'].set_linewidth(1.6)

    # Colorbar -- below the map, horizontally centered on the rendered map
    # frame (cartopy shrinks the axes box to preserve the projection's
    # aspect ratio, so ask the canvas where the frame actually landed).
    fig.canvas.draw()
    frame_px = ax.get_window_extent()
    frame_left = frame_px.x0 / (FIG_WIDTH_IN * FIG_DPI)
    frame_right = frame_px.x1 / (FIG_WIDTH_IN * FIG_DPI)
    cbar_width, cbar_height = (frame_right - frame_left) * 0.55, 0.022
    cbar_left = (frame_left + frame_right) / 2 - cbar_width / 2
    cbar_bottom = 0.085

    # Only draw the slice of the color table actually visible on the map
    # today (rounded outward to a clean 0.25in step), same spirit as
    # columbia-basin-temps' temperature colorbar -- but always sampled from
    # the same fixed cmap+norm, so a given shade means the same TPW value
    # across every run.
    vmin_disp = max(TPW_VMIN_IN, 0.25 * np.floor(np.nanmin(visible) / 0.25))
    vmax_disp = min(TPW_VMAX_IN, 0.25 * np.ceil(np.nanmax(visible) / 0.25))
    gradient = np.linspace(vmin_disp, vmax_disp, 256).reshape(1, -1)

    cax = fig.add_axes([cbar_left, cbar_bottom, cbar_width, cbar_height])
    cax.imshow(gradient, aspect="auto", cmap=tpw_cmap, norm=tpw_norm, extent=[vmin_disp, vmax_disp, 0, 1])
    cax.set_yticks([])
    for spine in cax.spines.values():
        spine.set_edgecolor("#8a887e")
        spine.set_linewidth(0.6)
    ticks = np.arange(np.ceil(vmin_disp / 0.5) * 0.5, vmax_disp + 1e-9, 0.5)
    cax.set_xticks(ticks)
    cax.set_xticklabels([f'{t:g}"' for t in ticks])
    cax.tick_params(labelsize=8.5, color="#8a887e", labelcolor="#2b2a26")
    for label in cax.get_xticklabels():
        label.set_fontproperties(poppins_reg)

    # Title & subtitle above the map
    init_dt = datetime.fromisoformat(init_time.replace("Z", "+00:00"))
    fig.text(0.03, 0.975, "Moisture Surge: TS Elida → Pacific Northwest", fontsize=20,
              fontproperties=poppins_reg, color="#2b2a26", ha="left", va="top")
    fig.text(0.03, 0.935, f"Peak TPW over 10 days • WindBorne WeatherMesh-6 Ensemble • "
                          f"Init {init_dt.strftime('%Y-%m-%d %H')}z • F000–F{max(hours):03d}",
              fontsize=12, fontproperties=poppins_reg, color="#5a584f", ha="left", va="top")

    # Attribution
    fig.text(0.5, 0.012, "WindBorne WeatherMesh-6 — Ingalls Weather", fontsize=9,
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
        description="Build the Tropical Storm Elida -> Pacific Northwest peak TPW map.")
    parser.add_argument("--max-hour", type=int, default=240,
                         help="Forecast window in hours (default: 240 = 10 days).")
    parser.add_argument("--step-hours", type=int, default=24,
                         help="Sampling interval in hours across the window (default: 24 = "
                              "daily). Every fetch pulls WM-6's full global, all-variable "
                              "gridded file (~1.9 GB -- see README) since variable filtering "
                              "isn't available for this run, so halving this doubles both the "
                              "fetch count and the download time.")
    parser.add_argument("--file", type=Path, default=None,
                         help="Render from a previously saved snapshot (.npz) instead of fetching live.")
    parser.add_argument("--out", type=Path, default=None,
                         help="Output PNG path (default: output/elida_moisture_pnw.png).")
    args = parser.parse_args()

    if args.file and not args.file.exists():
        sys.exit(f"--file {args.file} not found.")

    out_path = args.out or (OUTPUT_DIR / "elida_moisture_pnw.png")
    build_map(args.max_hour, args.step_hours, out_path, override_path=args.file)

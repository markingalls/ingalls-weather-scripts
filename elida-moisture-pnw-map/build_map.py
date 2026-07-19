"""
Elida Moisture Surge -> Pacific Northwest Map (one-off)
Ingalls Weather

Tracks the moisture plume moving north out of the Elida, NM area toward the
Pacific Northwest: for every WM-6 (WindBorne WeatherMesh-6) forecast step
over the next 10 days, computes the ensemble's chance of total column water
vapor (TPW / precipitable water) exceeding 1 inch at each grid point, then
takes the max across all of those steps -- so the map shows, per pixel, the
best chance of a moist plume passing over that spot at any point in the
window, regardless of which day it happens.

WHY A GAUSSIAN ESTIMATE, NOT A RAW MEMBER COUNT
-------------------------------------------------
WM-6's gridded API exposes true per-grid-point ensemble stats (128 raw
members, or a member count exceeding a fixed threshold) for several
variables -- but total_column_water_vapour is not one of them; it only
carries calibrated mean + standard deviation (confirmed via the API's
`variables` endpoint, which lists each surface variable's available
distribution stats). So "chance of TPW > 1 inch" here is computed
analytically from that mean/std, assuming a normal distribution:

    P(TPW > threshold) = 1 - CDF_normal(threshold; mean, std)

via scipy.stats.norm.sf(). This is a real ensemble-derived estimate (mean
and std are both calibrated from the full 128-member ensemble), just not a
literal "N of 128 members exceeded it" count -- that count isn't available
for this variable through the API. If WindBorne ever adds member-level or
threshold-probability output for total_column_water_vapour, swap this for
a direct count.

USAGE
-----
    export WB_API_KEY=...              # https://app.windbornesystems.com/api_tokens
    python build_map.py                              # latest WM-6 run, 10-day max, 1in threshold
    python build_map.py --max-hour 168 --step-hours 3  # 7-day window, finer time sampling
    python build_map.py --threshold-in 0.75            # different TPW threshold

Each grid point is fetched once per sampled forecast hour (default every 6h
out to 240h/10 days -- 41 requests), each a small single-variable,
CONUS-cropped zarr file. To re-render without re-fetching, pass
--file path/to/snapshot.npz (see save/load format in fetch_all() /
build_map()).

REQUIRES (already checked into /maps at repo root, shared across all
Ingalls Weather map projects):
    admin1_boundary_lines.json, admin0_boundary_lines.json, land_slim.json
Logo is read from /assets/ingalls_weather_logo.png at repo root.

NOTE ON API SHAPE: WindBorne's docs describe include_distribution=true as
adding "mean, std, ... where applicable" but don't publish the exact zarr
key layout for those stats. extract_stat() below searches the returned
zarr store's full tree for arrays named like "mean"/"std" rather than
assuming a fixed path, and prints the whole tree if it can't find exactly
one of each -- so if WindBorne's actual layout differs from that guess,
the first run will fail with the real structure printed instead of a
silent wrong answer.
"""

import argparse
import json
import os
import sys
import tempfile
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
from scipy.stats import norm

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
# Data source -- WM-6 global ensemble, gridded + cropped to the CONUS domain
# (not wm6-3km: that's a CONUS-only deterministic 3km product with no
# distribution stats at all). Runs 3-hourly out to 360h (15 days).
# ---------------------------------------------------------------------------
WB_BASE = "https://api.windbornesystems.com/forecasts/v1/wm-6"
VARIABLE = "total_column_water_vapour"  # TPW / precipitable water, kg/m^2 (== mm liquid equivalent)
KGM2_PER_INCH = 25.4
MIN_STD_KGM2 = 0.1  # guards norm.sf() against a zero-std divide if WM-6 ever reports one

# ---------------------------------------------------------------------------
# Figure geometry -- same canvas/colorbar layout as columbia-basin-temps.
# ---------------------------------------------------------------------------
FIG_WIDTH_IN, FIG_HEIGHT_IN = 10, 8.9
FIG_DPI = 200
AXES_RECT = [0.035, 0.15, 0.93, 0.75]  # [left, bottom, width, height], figure fraction
MAP_FRAME_INSET_PX = 22

# ---------------------------------------------------------------------------
# Map domain -- eastern NM (Elida, with a comfortable margin south/east)
# up through the Interior West into the Pacific Northwest.
# ---------------------------------------------------------------------------
LON_MIN, LON_MAX = -125.0, -100.0
LAT_MIN, LAT_MAX = 29.0, 49.5
CENTER_LON, CENTER_LAT = -113.0, 40.0

ELIDA_LON, ELIDA_LAT = -103.6355, 35.0503

# Degrees beyond the plotted extent to keep when cropping the fetched
# (regional) grid, so the padded resample grid below has real data to
# interpolate from all the way to its own edges.
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
# City labels along the plume's path, Elida NM up to the PNW.
# ---------------------------------------------------------------------------
CITIES = [
    ("Albuquerque", -106.6504, 35.0844, "left"),
    ("Farmington", -108.2187, 36.7281, "left"),
    ("Denver", -104.9903, 39.7392, "right"),
    ("Grand Junction", -108.5506, 39.0639, "left"),
    ("Salt Lake City", -111.8910, 40.7608, "right"),
    ("Twin Falls", -114.4609, 42.5629, "left"),
    ("Boise", -116.2023, 43.6150, "right"),
    ("Pendleton", -118.7879, 45.6721, "right"),
    ("Yakima", -120.5059, 46.6021, "left"),
    ("Spokane", -117.4260, 47.6588, "right"),
    ("Portland", -122.6784, 45.5152, "left"),
    ("Seattle", -122.3321, 47.6062, "right"),
]

# ---------------------------------------------------------------------------
# Probability color ramp -- teal -> blue -> purple, distinct from the
# rainbow temperature table used elsewhere in this repo, transparent at 0%
# so the basemap shows through where there's no chance at all.
# ---------------------------------------------------------------------------
PROB_COLOR_STOPS = [
    (0.00, "#f7f6f2"),
    (0.08, "#dcefec"),
    (0.25, "#9fd6cd"),
    (0.45, "#57b3ad"),
    (0.65, "#3d84b8"),
    (0.82, "#5c4fa8"),
    (1.00, "#9b2fae"),
]


def build_prob_colormap():
    return LinearSegmentedColormap.from_list("ingalls_prob", PROB_COLOR_STOPS, N=256)


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
# WindBorne API (WM-6 global ensemble, gridded, CONUS domain)
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


def extract_stat(g, keyword):
    """Find the single array in the zarr store whose name contains
    `keyword` (e.g. "mean", "std") -- see the module docstring's note on
    why this searches by name instead of assuming a fixed path."""
    hits = find_arrays_by_keyword(g, keyword)
    if len(hits) != 1:
        tree = "\n".join(describe_zarr_tree(g))
        sys.exit(
            f"Expected exactly one array containing '{keyword}' for {VARIABLE} in the "
            f"include_distribution response, found {len(hits)}: {[h[0] for h in hits]}\n"
            f"Full zarr structure returned:\n{tree}\n"
            f"WindBorne's response layout differs from what extract_stat() assumes -- "
            f"update the keyword/path lookup above to match."
        )
    return np.asarray(hits[0][1][:])


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


def fetch_all(max_hour, step_hours, threshold_kgm2, api_key):
    """Fetch WM-6's TPW mean/std at every step_hours-spaced forecast hour
    out to max_hour, convert each to a Gaussian exceedance probability, and
    take the elementwise max across all steps. Returns
    (lat_2d, lon_2d, prob_max_2d[0-1], init_time, hours_used)."""
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

    lat = lon = prob_max = None
    r0 = r1 = c0 = c1 = None
    for i, fh in enumerate(hours):
        print(f"Fetching F{fh:03d} ({i + 1}/{len(hours)}) ...")
        url_info = wb_get("gridded", api_key, variable=VARIABLE, domain="conus", format="zarr",
                           as_url="true", include_distribution="true",
                           initialization_time=init_time, forecast_hour=fh)
        resp = requests.get(url_info["url"], timeout=60)
        resp.raise_for_status()
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
                r0, r1, c0, c1, lat, lon = crop_to_bbox(lat_raw, lon_raw)

            mean_kgm2 = extract_stat(g, "mean")[r0:r1, c0:c1]
            std_kgm2 = extract_stat(g, "std")[r0:r1, c0:c1]
            store.close()

        prob = norm.sf(threshold_kgm2, loc=mean_kgm2, scale=np.maximum(std_kgm2, MIN_STD_KGM2))
        prob_max = prob if prob_max is None else np.maximum(prob_max, prob)

    return lat, lon, prob_max, init_time, hours


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


def build_map(max_hour, step_hours, threshold_in, output_path, override_path=None):
    poppins_reg = fm.FontProperties(fname=POPPINS_REG_PATH)
    poppins_semibold = fm.FontProperties(fname=POPPINS_MED_PATH)
    threshold_kgm2 = threshold_in * KGM2_PER_INCH

    if override_path:
        print(f"Using local snapshot: {override_path}")
        npz = np.load(override_path)
        lat, lon, prob = npz["lat"], npz["lon"], npz["prob"]
        init_time = str(npz["init_time"])
        hours = npz["hours"].tolist()
        threshold_in = float(npz["threshold_in"])
    else:
        api_key = os.environ.get("WB_API_KEY")
        if not api_key:
            raise SystemExit("Set WB_API_KEY in your environment before running this script.")
        lat, lon, prob, init_time, hours = fetch_all(max_hour, step_hours, threshold_kgm2, api_key)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        snapshot_path = OUTPUT_DIR / f"elida_moisture_snapshot_{init_time.replace(':', '')}.npz"
        np.savez(snapshot_path, lat=lat, lon=lon, prob=prob, init_time=init_time,
                 hours=np.array(hours), threshold_in=threshold_in)
        print(f"Saved raw grid to {snapshot_path} (re-render with --file).")

    print("Resampling onto a regular grid...")
    prob_grid = resample_to_regular_grid(lat, lon, prob)
    prob_pct = np.clip(prob_grid, 0.0, 1.0) * 100

    print(f"Max chance of TPW > {threshold_in:g}in over the window: {np.nanmax(prob_pct):.0f}%")

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

    prob_cmap = build_prob_colormap()
    prob_norm = Normalize(vmin=0, vmax=100)
    ax.imshow(prob_pct, transform=pc, cmap=prob_cmap, norm=prob_norm, origin="lower",
              extent=[RESAMPLE_LON_MIN, RESAMPLE_LON_MAX, RESAMPLE_LAT_MIN, RESAMPLE_LAT_MAX], zorder=1)

    ax.add_geometries(land_geoms, crs=pc, facecolor="none", edgecolor="#4a6b7a", linewidth=0.8, zorder=1.5)
    ax.add_geometries(admin1_lines, crs=pc, facecolor="none", edgecolor="#5a4632", linewidth=0.8, zorder=2)
    ax.add_geometries(admin0_lines, crs=pc, facecolor="none", edgecolor="#3a2f21", linewidth=1.1, zorder=2.5)

    # Elida, NM -- the plume's point of origin, marked distinctly from the
    # regular city dots.
    ax.plot(ELIDA_LON, ELIDA_LAT, marker="*", markersize=16, color="#f2b807", zorder=102,
            mec="black", mew=1.0, transform=pc)
    elida_txt = ax.text(ELIDA_LON + 0.35, ELIDA_LAT, "Elida, NM", fontsize=11,
                         fontproperties=poppins_semibold, color="white", ha="left", va="center",
                         zorder=103, transform=pc)
    elida_txt.set_path_effects([pe.withStroke(linewidth=1.8, foreground=(0, 0, 0, 0.85))])

    # City labels -- name plus that spot's max chance over the window,
    # sampled from the resampled grid.
    geodetic_transform = pc._as_mpl_transform(ax)
    stroke = [pe.withStroke(linewidth=1.5, foreground=(0, 0, 0, 0.8))]
    for name, lon_c, lat_c, pos in CITIES:
        ax.plot(lon_c, lat_c, marker="o", markersize=5.0, color="white", zorder=100,
                mec="black", mew=0.8, transform=pc)
        city_pct = sample_grid_value(prob_pct, lon_c, lat_c)
        dx_pt = 6 if pos == "right" else -6
        ha = "left" if pos == "right" else "right"

        name_transform = offset_copy(geodetic_transform, fig=fig, x=dx_pt, y=0, units="points")
        name_txt = ax.text(lon_c, lat_c, name, fontsize=9.75, fontproperties=poppins_semibold,
                            color="white", ha=ha, va="center", zorder=101, transform=name_transform)
        name_txt.set_path_effects(stroke)

        pct_transform = offset_copy(geodetic_transform, fig=fig, x=dx_pt, y=-4, units="points")
        pct_txt = ax.text(lon_c, lat_c, f"{city_pct:.0f}%", fontsize=9.75,
                           fontproperties=poppins_semibold, color="white", ha=ha, va="top",
                           zorder=101, transform=pct_transform)
        pct_txt.set_path_effects(stroke)

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

    gradient = np.linspace(0, 100, 256).reshape(1, -1)
    cax = fig.add_axes([cbar_left, cbar_bottom, cbar_width, cbar_height])
    cax.imshow(gradient, aspect="auto", cmap=prob_cmap, norm=prob_norm, extent=[0, 100, 0, 1])
    cax.set_yticks([])
    for spine in cax.spines.values():
        spine.set_edgecolor("#8a887e")
        spine.set_linewidth(0.6)
    cax.set_xticks(range(0, 101, 20))
    cax.set_xticklabels([f"{p}%" for p in range(0, 101, 20)])
    cax.tick_params(labelsize=8.5, color="#8a887e", labelcolor="#2b2a26")
    for label in cax.get_xticklabels():
        label.set_fontproperties(poppins_reg)

    # Title & subtitle above the map
    init_dt = datetime.fromisoformat(init_time.replace("Z", "+00:00"))
    fig.text(0.03, 0.975, "Moisture Surge: Elida, NM → Pacific Northwest", fontsize=20,
              fontproperties=poppins_reg, color="#2b2a26", ha="left", va="top")
    fig.text(0.03, 0.935, f"Chance of TPW > {threshold_in:g}\" • WindBorne WeatherMesh-6 Ensemble • "
                          f"Init {init_dt.strftime('%Y-%m-%d %H')}z • max over 10 days (F000–F{max(hours):03d})",
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
        description="Build the Elida, NM -> Pacific Northwest moisture surge map.")
    parser.add_argument("--max-hour", type=int, default=240,
                         help="Forecast window in hours (default: 240 = 10 days).")
    parser.add_argument("--step-hours", type=int, default=6,
                         help="Sampling interval in hours across the window (default: 6). "
                              "WM-6 natively steps every 3h; halving this doubles the fetch count.")
    parser.add_argument("--threshold-in", type=float, default=1.0,
                         help="TPW exceedance threshold in inches (default: 1.0).")
    parser.add_argument("--file", type=Path, default=None,
                         help="Render from a previously saved snapshot (.npz) instead of fetching live.")
    parser.add_argument("--out", type=Path, default=None,
                         help="Output PNG path (default: output/elida_moisture_pnw.png).")
    args = parser.parse_args()

    if args.file and not args.file.exists():
        sys.exit(f"--file {args.file} not found.")

    out_path = args.out or (OUTPUT_DIR / "elida_moisture_pnw.png")
    build_map(args.max_hour, args.step_hours, args.threshold_in, out_path, override_path=args.file)

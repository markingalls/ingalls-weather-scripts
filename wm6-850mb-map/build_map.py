"""
WM-6 Ensemble Mean 850 mb Height & Temperature Map -- one-off builder
Ingalls Weather

Styled map of the Pacific Northwest (Washington, Oregon, Idaho, southern
British Columbia, plus enough of the NE Pacific/northern California/
western Montana for synoptic context):
  - Shading: WindBorne WeatherMesh-6 (global, 0.25 deg) ensemble-mean 850 mb
    temperature, for a single valid time, using Ingalls Weather's standard
    temperature color table (same fixed Kelvin-to-RGB curve as
    ../columbia-basin-temps/).
  - Contours: ensemble-mean 850 mb geopotential height, every 30 m (3 dam,
    the standard 850 mb analysis interval), labeled in dam.
  - "L" markers at closed 850 mb height minima.

USAGE
-----
    python build_map.py                        # tomorrow, 12:00 PM Pacific
    python build_map.py --date 2026-10-30 --hour 5
    python build_map.py --file snapshot.npz     # render from a saved fetch

Requires WB_API_KEY in the environment (see
https://app.windbornesystems.com/api_tokens).

Fetch works the same way as ../tpw-wm6-ensemble-map/build_map.py: archived
WM-6 runs only serve the complete per-hour zarr zip via a presigned URL, so
fetch_wm6_fields() range-requests just the arrays this map needs out of it
(see that function's docstring).

REQUIRES (already checked into /maps at repo root, shared across all
Ingalls Weather map projects):
    states_lakes_slim.json, admin0_boundary_lines.json, countries_slim.json

Logo is read from /assets/ingalls_weather_logo.png at repo root.
"""

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
from matplotlib.colors import Normalize, LinearSegmentedColormap
import numpy as np
import requests
import zarr
from remotezip import RemoteZip
from scipy.interpolate import RegularGridInterpolator
from scipy.ndimage import label, minimum_filter, uniform_filter

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

POPPINS_REG_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf"
POPPINS_MED_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf"
# Same L-marker font as ../tpw-wm6-ensemble-map/ -- see BALOO_BOLD_PATH's
# comment there for why Baloo 2 (checked into /assets) rather than Poppins.
BALOO_BOLD_PATH = ASSETS_DIR / "fonts" / "Baloo2-Bold.ttf"

LOCAL_TZ = ZoneInfo("America/Los_Angeles")

# ---------------------------------------------------------------------------
# WindBorne API
# ---------------------------------------------------------------------------
WB_BASE = "https://api.windbornesystems.com/forecasts/v1/wm-6"
LEVEL_HPA = 850
TEMP_VARIABLE = f"temperature_{LEVEL_HPA}"
HEIGHT_VARIABLE = f"geopotential_{LEVEL_HPA}"
GRAVITY = 9.80665  # m/s^2 -- geopotential (m^2/s^2) -> geopotential height (m)

# Height contours every 30 m (3 dam) -- the standard 850 mb analysis
# interval -- at whatever levels the map's actual height range crosses.
HEIGHT_CONTOUR_INTERVAL_M = 30

# Minimum separation, in degrees, between two "L" markers -- see
# find_height_lows(). Smaller than the TPW map's 6 deg since this domain is
# roughly half the size, but still wide enough that one broad trough isn't
# tagged twice off adjacent near-tied grid cells.
LOW_MIN_SEPARATION_DEG = 4.0

# ---------------------------------------------------------------------------
# Figure geometry -- tuned by eye against the domain below (same approach
# as ../tpw-wm6-ensemble-map/: cartopy fits the projection's true aspect
# within AXES_RECT, so a mismatch only changes the unfilled margin).
# ---------------------------------------------------------------------------
FIG_WIDTH_IN, FIG_HEIGHT_IN = 8.66, 9.0
FIG_DPI = 200
AXES_RECT = [0.03, 0.17, 0.94, 0.70]  # [left, bottom, width, height], figure fraction
MAP_FRAME_INSET_PX = 22

# ---------------------------------------------------------------------------
# Map domain -- Pacific Northwest, a bit wider than
# ../dew-point-storm-map/'s BC/WA/OR/ID frame so offshore troughs and the
# Great Basin/northern Rockies side of the height pattern stay in view.
# ---------------------------------------------------------------------------
LON_MIN, LON_MAX = -134.0, -106.0
LAT_MIN, LAT_MAX = 39.0, 55.5
CENTER_LON, CENTER_LAT = (LON_MIN + LON_MAX) / 2, (LAT_MIN + LAT_MAX) / 2

# Fetch/basemap-clip padding past the declared box -- needed for the same
# conic-projection reason ../tpw-wm6-ensemble-map/'s FETCH_PAD_LON_DEG
# comment lays out (converging meridians mean the frame's top corners sit
# west/east of LON_MIN/LON_MAX, and its bottom corners dip south of
# LAT_MIN), just much smaller here since this domain is far narrower and
# doesn't come near the antimeridian.
FETCH_PAD_LON_DEG = 8.0
FETCH_PAD_LAT_DEG = 3.0

MAP_CLIP_BOX = box(LON_MIN - FETCH_PAD_LON_DEG, LAT_MIN - FETCH_PAD_LAT_DEG,
                    LON_MAX + FETCH_PAD_LON_DEG, LAT_MAX + FETCH_PAD_LAT_DEG)

# WM-6's native 0.25 deg (~28 km) grid looks blocky at this zoom level once
# warped into LambertConformal -- see resample_to_finer_grid().
RESAMPLE_FACTOR = 8

# ---------------------------------------------------------------------------
# Temperature color table -- Ingalls Weather's standard fixed Kelvin-to-RGB
# enhancement curve, copied verbatim from ../columbia-basin-temps/ so the
# same color means the same absolute temperature here as on every other
# Ingalls temperature map. (K, [R, G, B]) control points; the source
# table's alpha channel is constant (fully opaque) and is dropped here.
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


def c_to_k(c):
    return c + 273.15


def c_to_f(c):
    return c * 9 / 5 + 32


def f_to_c(f):
    return (f - 32) * 5 / 9


# ---------------------------------------------------------------------------
# WindBorne WM-6 fetch
# ---------------------------------------------------------------------------
def wb_get(path, api_key, **params):
    headers = {"Authorization": f"Bearer {api_key}"}
    resp = requests.get(f"{WB_BASE}/{path}", headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_zarr_array(remote_zip, names, tmp_dir, array_path):
    """Copy just one array's metadata + chunk file(s) out of the remote
    zip into a local directory tree, then open it with zarr (which handles
    WM-6's zstd/blosc + zarr v3 sharding codecs itself)."""
    entries = [n for n in names if n == f"{array_path}/zarr.json" or n.startswith(f"{array_path}/c")]
    for name in entries:
        dest = tmp_dir / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(remote_zip.read(name))
    return zarr.open_array(store=str(tmp_dir), path=array_path, mode="r")[:]


def fetch_wm6_fields(valid_time_utc, api_key):
    """Fetch the WM-6 ensemble-mean 850 mb temperature and geopotential
    grids valid nearest to valid_time_utc, cropped to the map bbox.

    Archived WM-6 runs reject `variable=` filtering, so this requests the
    full per-forecast-hour archive's presigned URL (`variable=all`,
    `as_url=true`, ~2 GB) and uses `remotezip` HTTP range requests to pull
    only the lat/lon coordinate arrays and the two 850 mb ensemble-mean
    fields -- a few MB -- exactly as ../tpw-wm6-ensemble-map/ does.

    Returns (lat_1d, lon_1d, temp_k_2d, height_m_2d, meta dict with
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
            temp_k = fetch_zarr_array(rz, names, tmp_dir, f"ensemble_mean/{TEMP_VARIABLE}")
            geopot = fetch_zarr_array(rz, names, tmp_dir, f"ensemble_mean/{HEIGHT_VARIABLE}")

    # This domain never nears the antimeridian, so a plain -180..180 range
    # check is enough here (unlike the TPW map's unwrapped crop).
    lat_idx = np.where((lat >= LAT_MIN - FETCH_PAD_LAT_DEG) & (lat <= LAT_MAX + FETCH_PAD_LAT_DEG))[0]
    lon_idx = np.where((lon >= LON_MIN - FETCH_PAD_LON_DEG) & (lon <= LON_MAX + FETCH_PAD_LON_DEG))[0]
    lat_crop = lat[lat_idx]
    lon_crop = lon[lon_idx]
    temp_crop = temp_k[np.ix_(lat_idx, lon_idx)].astype(np.float64)
    height_crop = geopot[np.ix_(lat_idx, lon_idx)].astype(np.float64) / GRAVITY

    # WM-6's latitude axis runs north-to-south; flip to ascending so
    # imshow(..., origin="lower") behaves like every other map builder here.
    if lat_crop[0] > lat_crop[-1]:
        lat_crop = lat_crop[::-1]
        temp_crop = temp_crop[::-1, :]
        height_crop = height_crop[::-1, :]

    meta = {
        "initialization_time": root_meta["initialization_time"],
        "valid_time": root_meta["valid_time"],
        "forecast_hour": root_meta["forecast_hour"],
    }
    return lat_crop, lon_crop, temp_crop, height_crop, meta


def resample_to_finer_grid(lat, lon, values, factor=RESAMPLE_FACTOR):
    """Upsample a regular (lat, lon, values) grid by `factor` via linear
    interpolation -- see RESAMPLE_FACTOR's comment for why."""
    interp = RegularGridInterpolator((lat, lon), values, method="linear")
    fine_lat = np.linspace(lat[0], lat[-1], len(lat) * factor)
    fine_lon = np.linspace(lon[0], lon[-1], len(lon) * factor)
    fine_lon_grid, fine_lat_grid = np.meshgrid(fine_lon, fine_lat)
    fine_values = interp((fine_lat_grid, fine_lon_grid))
    return fine_lat, fine_lon, fine_values


def find_height_lows(lat, lon, height_m):
    """Find closed 850 mb height minima ("L" centers) in the native-
    resolution height grid -- the same sliding-minimum + plateau-collapse +
    prominence approach as ../tpw-wm6-ensemble-map/'s
    find_pressure_extrema() (see its docstring), applied to geopotential
    height instead of MSLP. A candidate is kept only if it sits at least
    one HEIGHT_CONTOUR_INTERVAL_M below the mean over a 3x-wider window, so
    a drawn contour could plausibly close around it -- which keeps a weak
    terrain-induced dimple from being labeled like a real low. Searches the
    full padded grid but only returns lows inside the visible box.

    Returns a list of (lon, lat, height_m) tuples."""
    lat_res = abs(lat[1] - lat[0])
    lon_res = abs(lon[1] - lon[0])
    size_lat = max(3, int(round(LOW_MIN_SEPARATION_DEG / lat_res)))
    size_lon = max(3, int(round(LOW_MIN_SEPARATION_DEG / lon_res)))

    local_min = height_m == minimum_filter(height_m, size=(size_lat, size_lon), mode="nearest")
    background = uniform_filter(height_m, size=(size_lat * 3, size_lon * 3), mode="nearest")

    candidates = []
    labeled, n_features = label(local_min)
    for i in range(1, n_features + 1):
        ys, xs = np.where(labeled == i)
        cy, cx = int(round(ys.mean())), int(round(xs.mean()))
        ex_lon, ex_lat = lon[cx], lat[cy]
        if not (LON_MIN <= ex_lon <= LON_MAX and LAT_MIN <= ex_lat <= LAT_MAX):
            continue
        value = height_m[cy, cx]
        if background[cy, cx] - value >= HEIGHT_CONTOUR_INTERVAL_M:
            candidates.append((ex_lon, ex_lat, value))

    # WM-6's quantized output can leave several *separate* (non-touching)
    # cells tied at a low's exact minimum, which the plateau labeling above
    # can't merge -- seen in practice as three stacked "L"s on one low. Keep
    # the deepest candidate and drop any other within
    # LOW_MIN_SEPARATION_DEG of one already kept.
    lows = []
    for ex_lon, ex_lat, value in sorted(candidates, key=lambda c: c[2]):
        if all(np.hypot(ex_lon - k_lon, ex_lat - k_lat) >= LOW_MIN_SEPARATION_DEG
               for k_lon, k_lat, _ in lows):
            lows.append((ex_lon, ex_lat, value))
    return lows


# ---------------------------------------------------------------------------
# Basemap layers
# ---------------------------------------------------------------------------
def clip_to_map(geom):
    # segmentize first so long, nearly-straight lon/lat runs (the 49th
    # parallel border) bend correctly once reprojected into LambertConformal.
    clipped = shapely.segmentize(geom, max_segment_length=0.5).intersection(MAP_CLIP_BOX)
    return None if clipped.is_empty else clipped


def clip_outline_to_map(geom):
    """Clip a polygon's boundary (not the polygon) so MAP_CLIP_BOX's own
    straight edge isn't drawn as a fake coastline/border segment."""
    return clip_to_map(geom.boundary)


def load_countries():
    """Country outlines -- doubles as the coastline, drawn outline-only so
    the temperature shading over water stays visible."""
    with open(COUNTRIES_FILE) as f:
        data = json.load(f)
    geoms = [shape(feat["geometry"]) for feat in data["features"]
             if feat["properties"].get("NAME") in TARGET_COUNTRIES]
    return [g for g in (clip_outline_to_map(g) for g in geoms) if g is not None]


def load_states():
    """State/province outlines -- lake features dropped so they don't draw
    as if they were a state/province border."""
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


def load_boundary_lines(path):
    with open(path) as f:
        data = json.load(f)
    geoms = [shape(feat["geometry"]) for feat in data["features"]]
    return [g for g in (clip_to_map(g) for g in geoms) if g is not None]


def build_map(date, hour, output_path, override_path=None):
    poppins_reg = fm.FontProperties(fname=POPPINS_REG_PATH)
    poppins_semibold = fm.FontProperties(fname=POPPINS_MED_PATH)
    baloo_bold = fm.FontProperties(fname=BALOO_BOLD_PATH)

    local_dt = datetime(date.year, date.month, date.day, hour, tzinfo=LOCAL_TZ)
    valid_time_utc = local_dt.astimezone(ZoneInfo("UTC"))

    if override_path:
        print(f"Using local snapshot: {override_path}")
        npz = np.load(override_path, allow_pickle=True)
        lat, lon, temp_k, height_m = npz["lat"], npz["lon"], npz["temp_k"], npz["height_m"]
        meta = npz["meta"].item()
    else:
        api_key = os.environ.get("WB_API_KEY")
        if not api_key:
            sys.exit("WB_API_KEY not set -- get a token at "
                      "https://app.windbornesystems.com/api_tokens, or pass --file "
                      "to render from a saved snapshot instead.")
        lat, lon, temp_k, height_m, meta = fetch_wm6_fields(valid_time_utc, api_key)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        np.savez(OUTPUT_DIR / f"snapshot_{date.isoformat()}_{hour:02d}.npz",
                  lat=lat, lon=lon, temp_k=temp_k, height_m=height_m, meta=meta)

    print(f"{LEVEL_HPA} mb temp range in fetched crop: {temp_k.min() - 273.15:.1f} - {temp_k.max() - 273.15:.1f} C")
    print(f"{LEVEL_HPA} mb height range in fetched crop: {height_m.min():.0f} - {height_m.max():.0f} m")
    lows = find_height_lows(lat, lon, height_m)
    print(f"Lows found: {', '.join(f'{v / 10:.0f} dam @ {y:.1f}N {-x:.1f}W' for x, y, v in lows) or 'none'}")
    print(f"Resampling from {lat.size}x{lon.size} native grid...")
    lat_r, lon_r, temp_k = resample_to_finer_grid(lat, lon, temp_k)
    _, _, height_m = resample_to_finer_grid(lat, lon, height_m)
    lat, lon = lat_r, lon_r

    print("Loading basemap layers...")
    country_geoms = load_countries()
    state_geoms = load_states()
    admin0_lines = load_boundary_lines(ADMIN0_LINES_FILE)

    # LambertConformal, the standard NOAA/NWS regional projection -- same
    # choice and reasoning as ../tpw-wm6-ensemble-map/build_map().
    pc = ccrs.PlateCarree()
    proj = ccrs.LambertConformal(central_longitude=CENTER_LON, central_latitude=CENTER_LAT,
                                  standard_parallels=(LAT_MIN, LAT_MAX))

    fig = plt.figure(figsize=(FIG_WIDTH_IN, FIG_HEIGHT_IN), dpi=FIG_DPI)
    fig.patch.set_facecolor("#f7f6f2")

    ax = fig.add_axes(AXES_RECT, projection=proj)
    ax.set_extent([LON_MIN, LON_MAX, LAT_MIN, LAT_MAX], crs=pc)
    ax.patch.set_facecolor("white")

    # Temperature field -- the fixed Kelvin-to-color curve (not rescaled
    # to this map's range), so color reads consistently with every other
    # Ingalls temperature map. 850 mb is above the terrain almost
    # everywhere in this domain, so unlike a 2m field there's no masking
    # to do -- it's a continuous field edge to edge (WM-6 extrapolates
    # below-ground values over the highest terrain, as all models do).
    temp_cmap = build_temp_colormap()
    temp_norm = Normalize(vmin=TEMP_KMIN, vmax=TEMP_KMAX)
    ax.imshow(temp_k, transform=pc, cmap=temp_cmap, norm=temp_norm, origin="lower",
              extent=[lon[0], lon[-1], lat[0], lat[-1]], zorder=1)

    ax.add_geometries(country_geoms, crs=pc, facecolor="none", edgecolor="#4a6b7a", linewidth=0.8, zorder=1.5)
    ax.add_geometries(state_geoms, crs=pc, facecolor="none", edgecolor="#5a4632", linewidth=0.8, zorder=2)
    ax.add_geometries(admin0_lines, crs=pc, facecolor="none", edgecolor="#3a2f21", linewidth=1.1, zorder=2.5)

    # Height contours -- drawn above every other layer so they stay
    # legible over the shading and basemap. Black rather than the TPW
    # map's mid-gray isobars, since this color table runs dark in places
    # (navy/purple cold air) where gray would wash out. Labeled in dam (the
    # conventional upper-air unit: 150 = 1500 m).
    level_start = np.floor(height_m.min() / HEIGHT_CONTOUR_INTERVAL_M) * HEIGHT_CONTOUR_INTERVAL_M
    level_end = np.ceil(height_m.max() / HEIGHT_CONTOUR_INTERVAL_M) * HEIGHT_CONTOUR_INTERVAL_M
    height_levels = np.arange(level_start, level_end + HEIGHT_CONTOUR_INTERVAL_M, HEIGHT_CONTOUR_INTERVAL_M)
    ax.contour(lon, lat, height_m, levels=height_levels, transform=pc,
               colors="#1a1a1a", linewidths=1.0, zorder=3)

    # Labels come from a second, invisible contour pass over just the
    # visible box (inset a little so labels don't sit on the frame edge):
    # clabel() on the full padded grid above happily places a contour's
    # one label out in the off-screen padding, leaving it unlabeled on the
    # map. The thick white halo blanks the visible line underneath each
    # label, standing in for clabel's inline line-break.
    label_inset_deg = 1.0
    lat_in = (lat >= LAT_MIN + label_inset_deg) & (lat <= LAT_MAX - label_inset_deg)
    lon_in = (lon >= LON_MIN + label_inset_deg) & (lon <= LON_MAX - label_inset_deg)
    label_contours = ax.contour(lon[lon_in], lat[lat_in], height_m[np.ix_(lat_in, lon_in)],
                                levels=height_levels, transform=pc, colors="none", zorder=3)
    contour_labels = ax.clabel(label_contours, inline=False, fontsize=7.5, colors="#1a1a1a",
                               fmt=lambda m: f"{m / 10:.0f}", inline_spacing=0)
    for txt in contour_labels:
        txt.set_fontproperties(poppins_semibold)
        txt.set_fontsize(7.5)
        txt.set_path_effects([pe.withStroke(linewidth=3.5, foreground="white")])

    # "L" markers at closed height minima -- red, Baloo 2 Bold, white halo,
    # matching ../tpw-wm6-ensemble-map/'s pressure-center markers, with the
    # center's height (dam) tucked underneath.
    for ex_lon, ex_lat, value in lows:
        px, py = proj.transform_point(ex_lon, ex_lat, pc)
        ax.text(px, py, "L", ha="center", va="center", fontsize=24,
                 color="#c0392b", zorder=4, fontproperties=baloo_bold,
                 path_effects=[pe.withStroke(linewidth=2.0, foreground="white")])
        ax.annotate(f"{value / 10:.0f}", (px, py), xytext=(0, -15), textcoords="offset points",
                    ha="center", va="top", fontsize=8.5, color="#c0392b", zorder=4,
                    fontproperties=poppins_semibold,
                    path_effects=[pe.withStroke(linewidth=1.8, foreground="white")])

    ax.spines['geo'].set_edgecolor('black')
    ax.spines['geo'].set_linewidth(1.6)

    # Colorbar -- below the map, centered on the rendered map frame. Like
    # ../columbia-basin-temps/, only the slice of the color table visible
    # on the map is drawn (sampled through the same cmap + Kelvin norm so a
    # shade still means its usual temperature), rounded outward to clean
    # numbers. Primary axis is Celsius here (the upper-air convention),
    # with Fahrenheit mirrored on top.
    fig.canvas.draw()
    frame_px = ax.get_window_extent()
    frame_left = frame_px.x0 / (FIG_WIDTH_IN * FIG_DPI)
    frame_right = frame_px.x1 / (FIG_WIDTH_IN * FIG_DPI)
    cbar_width, cbar_height = (frame_right - frame_left) * 0.55, 0.022
    cbar_left = (frame_left + frame_right) / 2 - cbar_width / 2
    cbar_bottom = 0.085

    in_box = ((lat >= LAT_MIN) & (lat <= LAT_MAX))[:, None] & ((lon >= LON_MIN) & (lon <= LON_MAX))[None, :]
    visible_c = temp_k[in_box] - 273.15
    vmin_disp = 5 * np.floor(visible_c.min() / 5)
    vmax_disp = 5 * np.ceil(visible_c.max() / 5)
    gradient_k = c_to_k(np.linspace(vmin_disp, vmax_disp, 256)).reshape(1, -1)

    cax = fig.add_axes([cbar_left, cbar_bottom, cbar_width, cbar_height])
    cax.imshow(gradient_k, aspect="auto", cmap=temp_cmap, norm=temp_norm,
               extent=[vmin_disp, vmax_disp, 0, 1])
    cax.set_yticks([])
    for spine in cax.spines.values():
        spine.set_edgecolor("#8a887e")
        spine.set_linewidth(0.6)

    c_ticks = np.arange(vmin_disp, vmax_disp + 0.01, 5)
    cax.set_xticks(c_ticks)
    cax.set_xticklabels([f"{c:.0f}°C" for c in c_ticks])
    cax.tick_params(labelsize=8.5, color="#8a887e", labelcolor="#2b2a26")
    for lbl in cax.get_xticklabels():
        lbl.set_fontproperties(poppins_reg)
    cax.set_xlabel(f"{LEVEL_HPA} mb Temperature", fontsize=8.5, fontproperties=poppins_reg, color="#5a584f")

    cax_f = cax.secondary_xaxis("top", functions=(c_to_f, f_to_c))
    cax_f.xaxis.set_major_formatter(lambda f, _: f"{f:.0f}°F")
    cax_f.tick_params(labelsize=8.5, color="#8a887e", labelcolor="#2b2a26")
    for lbl in cax_f.get_xticklabels():
        lbl.set_fontproperties(poppins_reg)

    # Title & subtitle -- titled off the actual valid time (WM-6's 3-hourly
    # steps mean it's not always exactly the requested hour).
    init_dt = datetime.fromisoformat(meta["initialization_time"].replace("Z", "+00:00"))
    valid_dt_utc = datetime.fromisoformat(meta["valid_time"].replace("Z", "+00:00"))
    valid_dt_local = valid_dt_utc.astimezone(LOCAL_TZ)

    h12 = valid_dt_local.hour % 12 or 12
    ampm = "AM" if valid_dt_local.hour < 12 else "PM"
    fig.text(0.03, 0.978, f"{valid_dt_local.strftime('%A')} {h12}:00 {ampm} PT {LEVEL_HPA} mb Heights & Temp",
              fontsize=19, fontproperties=poppins_reg, color="#2b2a26", ha="left", va="top")
    fig.text(0.03, 0.941, "WindBorne WM-6 Ensemble Mean  ·  Heights in dam", fontsize=12.5,
              fontproperties=poppins_semibold, color="#3a3835", ha="left", va="top")
    fig.text(0.03, 0.910, f"Init {init_dt.strftime('%Y-%m-%d %H')}z  ·  Valid {valid_dt_utc.strftime('%Y-%m-%d %H')}z",
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
        description="Build an Ingalls Weather WM-6 ensemble mean 850 mb height & temperature map.")
    parser.add_argument("--date", type=str, default=None,
                         help="Target date, YYYY-MM-DD, local (Pacific) time (default: tomorrow).")
    parser.add_argument("--hour", type=int, default=12,
                         help="Target local hour, 0-23 (default: 12, i.e. noon PT).")
    parser.add_argument("--file", type=Path, default=None,
                         help="Render from a local saved snapshot (.npz) instead of fetching live.")
    parser.add_argument("--out", type=Path, default=None,
                         help="Output PNG path (default: output/wm6_850mb_<date>_<hour>.png).")
    args = parser.parse_args()

    if not (0 <= args.hour <= 23):
        parser.error("--hour must be between 0 and 23.")

    if args.file and not args.file.exists():
        sys.exit(f"--file {args.file} not found.")

    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        target_date = datetime.now(LOCAL_TZ).date() + timedelta(days=1)

    out_path = args.out or (OUTPUT_DIR / f"wm6_850mb_{target_date.isoformat()}_{args.hour:02d}.png")
    build_map(target_date, args.hour, out_path, override_path=args.file)

"""
WM-6 Ensemble Mean Total Precipitable Water Map -- one-off builder
Ingalls Weather

Styled map spanning Hawaii (SW) to central Alberta/Saskatchewan (NE) --
the North Pacific, US West Coast, Great Basin, and Western Canada in one
frame:
  - Shading: WindBorne WeatherMesh-6 (global, 0.25 deg) ensemble-mean total
    column water vapour (total precipitable water), for a single valid
    time. Below the color table's 0.5" floor is left unshaded.
  - Contours: ensemble-mean MSLP isobars, every 4 hPa, for the same valid
    time.

USAGE
-----
    python build_map.py                        # tomorrow, 12:00 PM Pacific
    python build_map.py --date 2026-07-30 --hour 12
    python build_map.py --file snapshot.npz     # render from a saved fetch

Requires WB_API_KEY in the environment (see
https://app.windbornesystems.com/api_tokens).

WM-6's gridded endpoint only serves per-variable/per-distribution subsets
for forecast hours still in "hot" storage; every run this was tested
against had already moved to archived storage by the time it was
requested, at which point the API only serves the complete per-hour
archive (all variables/levels/products, ~2 GB compressed) via a presigned
URL (`as_url=true`) -- see fetch_tcwv_mean()'s docstring for how this
script avoids downloading the whole thing.

REQUIRES (already checked into /maps at repo root, shared across all
Ingalls Weather map projects):
    states_lakes_slim.json, admin0_boundary_lines.json, countries_slim.json
  countries_slim.json (full country polygons, not just the coastline-only
  land_slim.json, which is clipped to the Pacific Northwest and doesn't
  reach Hawaii) draws both the coastline and doubles as the land layer.
  Sourced from raw.githubusercontent.com/martynafford/natural-earth-geojson.

Logo is read from /assets/ingalls_weather_logo.png at repo root.
"""

import argparse
import json
import math
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
from scipy.ndimage import label, maximum_filter, minimum_filter, uniform_filter

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

# Basemap fill colors -- drawn beneath the TPW field (see build_map()),
# which fades in from fully transparent at its 0.5" floor, so both stay
# visible under sparse/dry data instead of the map reading as blank there.
LAND_COLOR = "#F5E7B3"
OCEAN_COLOR = "#D2E8F3"

POPPINS_REG_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf"
POPPINS_MED_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf"
# Bold + genuinely rounded (unlike Poppins, whose rounded-looking body
# text still has fairly square letterforms) -- used only for the L/H
# pressure-center markers, where the shape of a single big letter is much
# more noticeable than in running text. Checked into /assets (unlike the
# Poppins weights above, which setup.sh installs system-wide) since
# fm.FontProperties(fname=...) loads a TTF directly from any path, no
# system font install needed -- committing it means rendering this map
# doesn't depend on Google Fonts being reachable at setup time for a font
# that, being variable-only upstream, couldn't be fetched as a raw static
# file the way Poppins' setup.sh step does anyway.
BALOO_BOLD_PATH = ASSETS_DIR / "fonts" / "Baloo2-Bold.ttf"

LOCAL_TZ = ZoneInfo("America/Los_Angeles")

# ---------------------------------------------------------------------------
# WindBorne API
# ---------------------------------------------------------------------------
WB_BASE = "https://api.windbornesystems.com/forecasts/v1/wm-6"
VARIABLE = "total_column_water_vapour"
MSLP_VARIABLE = "pressure_msl"

# Isobars are contoured every 4 hPa (the standard surface-analysis
# interval), at whatever levels the map's actual MSLP range crosses --
# unlike the TPW color table, there's no fixed enhancement curve to keep
# consistent map to map, so the levels are computed from the data itself
# (see build_map()).
MSLP_CONTOUR_INTERVAL_HPA = 4

# Minimum separation, in degrees, required between two pressure-center
# ("L"/"H") markers -- see find_pressure_extrema(). Sized for this map's
# domain (54 deg lon x 44 deg lat): small enough to catch two genuinely
# distinct synoptic-scale centers, large enough that a single broad
# low/high doesn't get tagged twice off two adjacent grid cells that are
# both very close to its true extremum.
PRESSURE_EXTREMA_MIN_SEPARATION_DEG = 6.0

# ---------------------------------------------------------------------------
# Figure geometry. Under LambertConformal (see build_map()'s note on
# projection choice) the visible curved area doesn't fill the rectangular
# axes box the way it would under PlateCarree -- cartopy still fits the
# projection's true aspect ratio within AXES_RECT, so a mismatched
# FIG_WIDTH_IN/FIG_HEIGHT_IN just means more/less unfilled margin around
# the curved frame rather than a hard visual bug. This ratio was tuned by
# eye against the actual domain below.
# ---------------------------------------------------------------------------
FIG_WIDTH_IN, FIG_HEIGHT_IN = 8.66, 9.5
FIG_DPI = 200
AXES_RECT = [0.03, 0.17, 0.94, 0.70]  # [left, bottom, width, height], figure fraction
MAP_FRAME_INSET_PX = 22

# ---------------------------------------------------------------------------
# Map domain -- Hawaii (SW) to central Alberta/Saskatchewan (NE). Zoomed in
# and centered a little southwest of this map's first pass (which ran all
# the way to Saskatchewan's northwest corner, ~60N/110W); trading a bit of
# that far-NE coverage for a tighter, more zoomed-in frame overall.
# ---------------------------------------------------------------------------
LON_MIN, LON_MAX = -166.0, -112.0
LAT_MIN, LAT_MAX = 12.5, 56.5
CENTER_LON, CENTER_LAT = (LON_MIN + LON_MAX) / 2, (LAT_MIN + LAT_MAX) / 2

# A rectangular lon/lat crop is NOT enough padding for a conic
# projection: meridians converge toward the pole, so the same +/-N degrees
# of longitude covers much less east-west ground at LAT_MAX than at
# LAT_MIN. LambertConformal's projected top edge (running through
# CENTER_LON at LAT_MAX) sits higher up than the top corners (running
# through LON_MIN/LON_MAX at LAT_MAX), which is exactly what makes the
# visible area a trapezoid -- and it means the screen-rows near the top of
# the *bounding rectangle* need real data from well past LON_MIN/LON_MAX
# to reach the frame's left/right edges, not just past LAT_MAX. Padding
# longitude much more generously than latitude fills in the blank
# corners with real, correctly-located data instead of leaving them
# empty. Unlike a true perspective/satellite-view projection (which has a
# hard horizon cutoff -- see this map's earlier NearsidePerspective pass),
# LambertConformal is conic and has no such cutoff: inverse-transforming
# the axes' actual bounding-box corners back to lon/lat gives a real,
# finite answer even at the very top corners (verified directly -- the
# worst case, exactly at the top-left/top-right corner pixels, needs
# ~18.4 deg of *extra* longitude beyond LON_MIN/LON_MAX), so with enough
# padding the corners really can be filled completely, not just mostly.
# FETCH_PAD_LON_DEG can safely be pushed past 180 - LON_MIN or LON_MAX +
# 180 (i.e. wrapping across the antimeridian) since fetch_tcwv_mean()
# crops using longitude unwrapped around CENTER_LON rather than a naive
# -180..180 range check.
#
# The bottom two corners need the opposite kind of slack: standard
# parallels convergence means the bounding rectangle's bottom edge dips
# *below* LAT_MIN out at its left/right corners (the same "bounding box
# pokes out past the curved trapezoid's actual edges" effect that drives
# FETCH_PAD_LON_DEG at the top, just along the other axis) -- verified the
# same way, by inverse-transforming the axes' bottom-corner pixels back to
# lon/lat: worst case needs ~3.4 deg *below* LAT_MIN, versus the top
# corners needing only ~0.02 deg *above* LAT_MAX. FETCH_PAD_LAT_DEG is
# sized for that south-corner worst case (with margin) since it pads both
# edges symmetrically.
FETCH_PAD_LON_DEG = 26.0
FETCH_PAD_LAT_DEG = 4.5

# Basemap geometries (country/state/border-line datasets) are sourced from
# files that extend well past this map's domain -- fine for PlateCarree,
# but reprojecting a line with far-off vertices into LambertConformal
# can bow it into a visibly wrong shape or, worse, cut across the frame
# entirely. Padded the same asymmetric amount as the data fetch above, for
# the same reason -- clipping every geometry to this box before handing it
# to add_geometries keeps every vertex within (or just outside) the
# visible area -- see clip_to_map(). (Unlike the data fetch, this doesn't
# unwrap across the antimeridian -- basemap files store plain -180..180
# coordinates -- but nothing of interest to this map sits out there.)
MAP_CLIP_BOX = box(LON_MIN - FETCH_PAD_LON_DEG, LAT_MIN - FETCH_PAD_LAT_DEG,
                    LON_MAX + FETCH_PAD_LON_DEG, LAT_MAX + FETCH_PAD_LAT_DEG)

# WM-6's native 0.25 deg spacing (~28 km) is coarser than a single screen
# pixel once zoomed to this map's domain -- upsampled via linear
# interpolation (see resample_to_finer_grid()) so the curved
# LambertConformal warp has dense enough source data to fill the frame
# smoothly instead of showing a blocky/native-pixel-grid look.
RESAMPLE_FACTOR = 6

# ---------------------------------------------------------------------------
# Total precipitable water color table -- fixed inch-to-RGB control points
# (not rescaled per map), taken from Ingalls Weather's standard TPW palette
# (cream/dry through green-teal through blue to dark navy/very moist).
# Bottom of the scale is 0.5" (below that reads as dry/uninteresting for
# TPW purposes -- see build_map()'s alpha fade-in, TPW_ALPHA_FADE_END_IN
# below, for how sub-floor cells are handled) and the top is 3.5". The 9
# palette colors aren't spaced evenly across that range: TPW_IN_MID pulls
# the *middle* color down to 1.5" (rather than the range's actual
# midpoint, 2.0"), so more of the ramp's color variation falls across the
# more common lower/moderate range and the upper range is comparatively
# compressed. WM-6's field itself comes back in kg/m^2 (numerically ==
# mm), so the control points are converted to mm once here for comparison
# against the fetched data.
# ---------------------------------------------------------------------------
TPW_RGB_COLORS = [
    [255, 255, 221],
    [239, 248, 185],
    [206, 232, 184],
    [145, 203, 188],
    [101, 180, 195],
    [69, 143, 188],
    [50, 92, 164],
    [41, 52, 142],
    [13, 30, 86],
]
TPW_IN_MIN = 0.5
TPW_IN_MAX = 3.5
TPW_IN_MID = 1.5

# The TPW field fades in rather than cutting on/off hard at TPW_IN_MIN --
# fully transparent (alpha 0) below it, ramping linearly from
# TPW_ALPHA_FADE_START to TPW_ALPHA_FADE_END between TPW_IN_MIN and
# TPW_ALPHA_FADE_END_IN, then held at TPW_ALPHA_FADE_END (fully opaque)
# above that -- so the land/ocean basemap colors show through increasingly
# faintly near the dry floor instead of the data switching on abruptly.
TPW_ALPHA_FADE_END_IN = 0.75
TPW_ALPHA_FADE_START = 0.30
TPW_ALPHA_FADE_END = 1.0


def _tpw_in_stops():
    """Power-law-spaced control-point values (one per TPW_RGB_COLORS
    entry) running TPW_IN_MIN..TPW_IN_MAX, with the middle entry landing
    on TPW_IN_MID instead of the range's linear midpoint."""
    n = len(TPW_RGB_COLORS)
    mid_t = (n // 2) / (n - 1)
    span = TPW_IN_MAX - TPW_IN_MIN
    power = math.log((TPW_IN_MID - TPW_IN_MIN) / span) / math.log(mid_t)
    return [TPW_IN_MIN + span * (i / (n - 1)) ** power for i in range(n)]


TPW_COLOR_TABLE_IN = list(zip(_tpw_in_stops(), TPW_RGB_COLORS))
TPW_COLOR_TABLE_MM = [(inch * 25.4, rgb) for inch, rgb in TPW_COLOR_TABLE_IN]
TPW_MM_MIN = TPW_COLOR_TABLE_MM[0][0]
TPW_MM_MAX = TPW_COLOR_TABLE_MM[-1][0]


def build_tpw_colormap():
    span = TPW_MM_MAX - TPW_MM_MIN
    stops = [((mm - TPW_MM_MIN) / span, [c / 255 for c in rgb]) for mm, rgb in TPW_COLOR_TABLE_MM]
    return LinearSegmentedColormap.from_list("ingalls_tpw", stops, N=256)


def mm_to_in(mm):
    return mm / 25.4


def in_to_mm(inch):
    return inch * 25.4


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
    zip into a local directory tree, then open it with zarr -- lets zarr's
    codec pipeline (WM-6's TCWV field uses zstd/blosc + zarr v3 sharding)
    handle decoding, without pulling in the rest of the archive."""
    entries = [n for n in names if n == f"{array_path}/zarr.json" or n.startswith(f"{array_path}/c")]
    for name in entries:
        dest = tmp_dir / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(remote_zip.read(name))
    return zarr.open_array(store=str(tmp_dir), path=array_path, mode="r")[:]


def fetch_wm6_fields(valid_time_utc, api_key):
    """Fetch the WM-6 ensemble-mean total column water vapour and MSLP
    grids valid nearest to valid_time_utc, cropped to the map bbox, in a
    single remote-zip session (both fields come out of the same archived
    run, so there's no reason to open the presigned URL's remote zip index
    twice for two separate fetches).

    WM-6's gridded endpoint archives each run shortly after it finishes,
    and once archived, `variable=`/`include_distribution=` filtering is no
    longer honored server-side -- a request naming a specific variable is
    rejected outright ("Variable filtering is not available for archived
    forecasts. Use variable=all..."), even with `as_url=true`. The
    complete per-forecast-hour file (every variable, level, and product:
    deterministic, ensemble mean/std, members, percentiles) is still
    servable via a presigned URL by passing `variable=all` explicitly
    (docs: "points to the full archived Zarr file -- variable and level
    filtering are not applied"). That file runs ~2 GB compressed. Rather
    than downloading the whole thing, this uses `remotezip` to make HTTP
    range requests against the presigned URL for just the handful of
    entries this map needs -- the latitude/longitude coordinate arrays and
    the TCWV/MSLP ensemble-mean fields -- a few MB total.

    Returns (lat_1d, lon_1d, tcwv_mm_2d, mslp_hpa_2d, meta dict with
    initialization_time/valid_time/forecast_hour)."""
    url_info = wb_get("gridded", api_key, variable="all",
                       time=valid_time_utc.strftime("%Y-%m-%dT%H:%M:%SZ"), as_url="true")
    print(f"Opening archived WM-6 run via presigned URL (range-request fetch, not a full download)...")

    with RemoteZip(url_info["url"]) as rz:
        names = rz.namelist()
        root_meta = json.loads(rz.read("zarr.json"))["attributes"]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            lat = fetch_zarr_array(rz, names, tmp_dir, "latitude")
            lon = fetch_zarr_array(rz, names, tmp_dir, "longitude")
            tcwv = fetch_zarr_array(rz, names, tmp_dir, f"ensemble_mean/{VARIABLE}")
            mslp_pa = fetch_zarr_array(rz, names, tmp_dir, f"ensemble_mean/{MSLP_VARIABLE}")

    # Longitude is unwrapped around CENTER_LON (rather than compared as
    # plain -180..180 values) before cropping, so a generous
    # FETCH_PAD_LON_DEG can cross the antimeridian without the crop window
    # splitting into two disjoint, wrongly-ordered pieces -- see
    # FETCH_PAD_LON_DEG's comment for why that padding needs to be large.
    # Sorting lon_idx by the unwrapped value (not by raw array index, which
    # can run in the "wrong" direction across that same antimeridian
    # crossing) keeps lon_crop strictly ascending, which
    # resample_to_finer_grid()'s RegularGridInterpolator requires.
    lon_unwrapped = ((lon - CENTER_LON + 180) % 360) - 180 + CENTER_LON
    lat_idx = np.where((lat >= LAT_MIN - FETCH_PAD_LAT_DEG) & (lat <= LAT_MAX + FETCH_PAD_LAT_DEG))[0]
    lon_mask = (lon_unwrapped >= LON_MIN - FETCH_PAD_LON_DEG) & (lon_unwrapped <= LON_MAX + FETCH_PAD_LON_DEG)
    lon_idx = np.where(lon_mask)[0]
    lon_idx = lon_idx[np.argsort(lon_unwrapped[lon_idx])]
    lat_crop = lat[lat_idx]
    lon_crop = lon_unwrapped[lon_idx]
    tcwv_crop = tcwv[np.ix_(lat_idx, lon_idx)]
    mslp_crop = mslp_pa[np.ix_(lat_idx, lon_idx)] / 100.0  # Pa -> hPa

    # WM-6's latitude axis runs north-to-south (90 down to -89.75); flip to
    # ascending so downstream imshow(..., origin="lower") behaves like
    # every other map builder in this repo.
    if lat_crop[0] > lat_crop[-1]:
        lat_crop = lat_crop[::-1]
        tcwv_crop = tcwv_crop[::-1, :]
        mslp_crop = mslp_crop[::-1, :]

    meta = {
        "initialization_time": root_meta["initialization_time"],
        "valid_time": root_meta["valid_time"],
        "forecast_hour": root_meta["forecast_hour"],
    }
    return lat_crop, lon_crop, tcwv_crop, mslp_crop, meta


def resample_to_finer_grid(lat, lon, values, factor=RESAMPLE_FACTOR):
    """Upsample a regular (lat, lon, values) grid by `factor` via linear
    interpolation -- see RESAMPLE_FACTOR's comment for why."""
    interp = RegularGridInterpolator((lat, lon), values, method="linear")
    fine_lat = np.linspace(lat[0], lat[-1], len(lat) * factor)
    fine_lon = np.linspace(lon[0], lon[-1], len(lon) * factor)
    fine_lon_grid, fine_lat_grid = np.meshgrid(fine_lon, fine_lat)
    fine_values = interp((fine_lat_grid, fine_lon_grid))
    return fine_lat, fine_lon, fine_values


def find_pressure_extrema(lat, lon, mslp_hpa):
    """Find local minima ("L") and maxima ("H") pressure centers in the
    native-resolution MSLP grid -- run before resample_to_finer_grid(),
    since upsampling doesn't add any real new extrema, just many more
    near-duplicate grid cells right next to the true one. Searches the
    full fetched-and-padded grid (real data, not just this map's declared
    LON_MIN/LON_MAX/LAT_MIN/LAT_MAX box) so a genuine extremum near the
    domain's edge isn't missed or distorted by the search window running
    off the edge of the array, but only returns extrema that land inside
    the visible box -- a center just outside it wouldn't have anywhere
    sensible to draw its label anyway.

    A sliding min/max filter sized to PRESSURE_EXTREMA_MIN_SEPARATION_DEG
    finds grid cells that are already the most extreme value in their own
    neighborhood; this smooth an ensemble-mean field often has several
    adjacent cells tied at that same extreme value (a small flat plateau
    at a center's true peak/trough) rather than a single sharp cell, so
    connected-component labeling collapses each such plateau to one
    point (its centroid) instead of one marker per tied cell.

    Not every such local extremum is a real pressure center worth
    marking -- this field has plenty of small, sub-isobar-interval
    ripples (terrain-driven MSLP-reduction noise over the Great
    Basin/Rockies, mainly) that are local extrema in the strict sense but
    would draw an "L"/"H" floating over a patch with no actual closed
    isobar anywhere near it, which would look like a labeling bug rather
    than a real feature. Filtered by prominence: each candidate is
    compared against the mean field over a much wider window (3x the
    separation window) centered on it, and only kept if it clears
    MSLP_CONTOUR_INTERVAL_HPA -- i.e. if it's extreme enough that at
    least one drawn isobar could plausibly close a loop around it, which
    is the same bar a human analyst marking centers by eye would use.

    Returns a list of (lon, lat, value_hpa, "L" or "H") tuples."""
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


def imshow_antimeridian_safe(ax, data, lon, lat, transform, **imshow_kwargs):
    """Like ax.imshow(data, transform=transform, origin="lower",
    extent=[lon[0], lon[-1], lat[0], lat[-1]], ...), but safe for a lon
    array that extends past the standard -180..180 range -- which
    FETCH_PAD_LON_DEG's antimeridian-crossing padding produces for this
    map's domain. A single imshow call with an out-of-range extent
    silently fails to warp the out-of-range portion (cartopy's
    img_transform assumes a plain -180..180 source extent), leaving that
    part of the curved frame blank even though the source data is right
    there -- confirmed by comparing a single call against this split
    version, which fills the frame's corners completely. Converting to
    standard signed longitude and splitting into contiguous pieces
    wherever that wraps (there's at most one wrap for this map's domain,
    but this handles the general case) avoids the bug. Each internal
    piece boundary is pinned to just past +/-180 (boundary_overlap_deg)
    rather than the nearest grid column's actual value (a hair short of
    +/-180) -- pinning to the exact boundary still left a faint, hairline
    gap at the seam (matplotlib/cartopy edge antialiasing, not a real data
    gap) that read as a thin dotted line; the small deliberate overlap
    between pieces (harmless -- it's the same data on both sides) papers
    over that antialiasing gap instead."""
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
# Basemap layers
# ---------------------------------------------------------------------------
def clip_to_map(geom):
    # segmentize first: a real, mostly-straight-in-lon/lat run (the
    # US/Canada border tracks the 49th parallel dead straight for ~2000
    # km) can be represented with very few vertices, which is fine under
    # PlateCarree but draws as a visibly wrong straight chord once
    # reprojected into LambertConformal's curved view -- adding
    # intermediate vertices every ~0.5 deg gives the reprojection enough
    # points to bend it into its true curved shape.
    clipped = shapely.segmentize(geom, max_segment_length=0.5).intersection(MAP_CLIP_BOX)
    return None if clipped.is_empty else clipped


def clip_outline_to_map(geom):
    """Like clip_to_map, but for a polygon that's only ever drawn as an
    outline (facecolor="none"): clips its boundary LineString rather than
    the polygon itself, so truncating a polygon that extends past
    MAP_CLIP_BOX doesn't add the clip box's own straight edge as a fake
    coastline/border segment across the box's cut line."""
    return clip_to_map(geom.boundary)


def _load_country_geoms():
    with open(COUNTRIES_FILE) as f:
        data = json.load(f)
    return [shape(feat["geometry"]) for feat in data["features"]
            if feat["properties"].get("NAME") in TARGET_COUNTRIES]


def load_countries():
    """Full country polygons (not just a coastline-only dataset) -- the
    only basemap layer in /maps that reaches Hawaii, since it's drawn per
    country rather than clipped to a Pacific Northwest bounding box.
    Doubles as the coastline: drawn outline-only so TPW shading over water
    stays visible. Clips each country's *boundary* rather than the polygon
    itself -- see clip_outline_to_map() -- so a straight MAP_CLIP_BOX edge
    cutting through a country doesn't get drawn as a fake coastline/border
    segment. Use load_countries_filled() instead for the land fill layer."""
    return [g for g in (clip_outline_to_map(g) for g in _load_country_geoms()) if g is not None]


def load_countries_filled():
    """Country polygons clipped to MAP_CLIP_BOX, keeping polygon area (not
    just the boundary line) -- for the land fill layer. Reusing
    load_countries()'s boundary-only geometries for a facecolor fill looked
    fine everywhere the boundary clip stayed a closed ring, but wherever
    MAP_CLIP_BOX actually cuts a country open (this domain's northern edge,
    for instance), matplotlib auto-closes that open line with a straight
    chord for fill purposes -- visible as a diagonal bite out of the land
    fill near the box edge, even though the polygon itself has real area
    all the way out to the box. Clipping the polygon (not its boundary)
    keeps that area intact."""
    return [g for g in (clip_to_map(g) for g in _load_country_geoms()) if g is not None]


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
        lat, lon, tcwv_mm, mslp_hpa = npz["lat"], npz["lon"], npz["tcwv_mm"], npz["mslp_hpa"]
        meta = npz["meta"].item()
    else:
        api_key = os.environ.get("WB_API_KEY")
        if not api_key:
            sys.exit("WB_API_KEY not set -- get a token at "
                      "https://app.windbornesystems.com/api_tokens, or pass --file "
                      "to render from a saved snapshot instead.")
        lat, lon, tcwv_mm, mslp_hpa, meta = fetch_wm6_fields(valid_time_utc, api_key)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        np.savez(OUTPUT_DIR / f"snapshot_{date.isoformat()}_{hour:02d}.npz",
                  lat=lat, lon=lon, tcwv_mm=tcwv_mm, mslp_hpa=mslp_hpa, meta=meta)

    print(f"TPW range in fetched crop: {tcwv_mm.min():.0f} - {tcwv_mm.max():.0f} mm")
    print(f"MSLP range in fetched crop: {mslp_hpa.min():.0f} - {mslp_hpa.max():.0f} hPa")
    pressure_extrema = find_pressure_extrema(lat, lon, mslp_hpa)
    print(f"Pressure centers found: {', '.join(f'{k}{v:.0f}' for _, _, v, k in pressure_extrema) or 'none'}")
    print(f"Resampling from {lat.size}x{lon.size} native grid...")
    lat_r, lon_r, tcwv_mm = resample_to_finer_grid(lat, lon, tcwv_mm)
    _, _, mslp_hpa = resample_to_finer_grid(lat, lon, mslp_hpa)
    lat, lon = lat_r, lon_r

    print("Loading basemap layers...")
    country_geoms = load_countries()
    country_fill_geoms = load_countries_filled()
    state_geoms = load_states()
    admin0_lines = load_boundary_lines(ADMIN0_LINES_FILE)

    # LambertConformal (the standard NOAA/NWS projection for regional
    # weather maps), not PlateCarree -- shows the earth's actual curvature
    # (converging meridians, bowed parallels) rather than a flat lon/lat
    # rectangle, and is conformal (preserves local shapes/angles), unlike
    # the NearsidePerspective satellite view tried earlier. At this
    # domain's size (54 deg lon x 44 deg lat, Hawaii to central Alberta/
    # Saskatchewan), the projected shape is a curved trapezoid that doesn't
    # fill a rectangular frame -- unlike ../dew-point-storm-map/build_map.py's
    # much smaller domain, no standard_parallels choice avoids that. The
    # axes patch is colored as the ocean (below) rather than left
    # transparent, so any hairline of residual unfilled corner (see
    # FETCH_PAD_LON_DEG) reads as more ocean instead of a gap -- the
    # curved geo spine (below) reads as the map's actual border, the same
    # way published trapezoid-framed regional Lambert Conformal maps look.
    pc = ccrs.PlateCarree()
    proj = ccrs.LambertConformal(central_longitude=CENTER_LON, central_latitude=CENTER_LAT,
                                  standard_parallels=(LAT_MIN, LAT_MAX))

    fig = plt.figure(figsize=(FIG_WIDTH_IN, FIG_HEIGHT_IN), dpi=FIG_DPI)
    fig.patch.set_facecolor("#f7f6f2")

    ax = fig.add_axes(AXES_RECT, projection=proj)
    ax.set_extent([LON_MIN, LON_MAX, LAT_MIN, LAT_MAX], crs=pc)
    ax.patch.set_facecolor(OCEAN_COLOR)

    # Land -- filled beneath the TPW field (zorder 1) so the fade-in near
    # TPW_IN_MIN shows a hint of land color through the data rather than
    # data floating over nothing. Drawn again further down, outline-only,
    # on top of the TPW field for a coastline that stays crisp regardless
    # of the data's opacity there.
    ax.add_geometries(country_fill_geoms, crs=pc, facecolor=LAND_COLOR, edgecolor="none", zorder=0.5)

    # TPW field -- a fixed mm-to-color enhancement curve (not rescaled to
    # this map's data range), so color reads consistently across every map
    # this script renders, faded in via per-pixel alpha (rather than
    # clamped to the lightest color or masked hard on/off) between
    # TPW_IN_MIN and TPW_ALPHA_FADE_END_IN -- see TPW_ALPHA_FADE_END_IN's
    # comment -- so the land/ocean basemap colors show through
    # increasingly faintly near the dry floor instead of the data
    # switching on abruptly. Built as an explicit RGBA array (rather than
    # letting imshow apply cmap/norm/a single scalar alpha) since alpha
    # here varies per pixel. Cartopy warps this regular grid into the
    # curved LambertConformal view internally (a source-raster ->
    # screen-pixel inverse lookup, which is why cartopy's img_transform
    # needs scipy -- see requirements.txt), split at the antimeridian by
    # imshow_antimeridian_safe() -- see its docstring for why a single
    # imshow call can't be used here.
    tpw_cmap = build_tpw_colormap()
    tpw_norm = Normalize(vmin=TPW_MM_MIN, vmax=TPW_MM_MAX)
    tpw_rgba = tpw_cmap(tpw_norm(tcwv_mm))

    fade_start_mm = TPW_MM_MIN
    fade_end_mm = TPW_ALPHA_FADE_END_IN * 25.4
    fade_ratio = np.clip((tcwv_mm - fade_start_mm) / (fade_end_mm - fade_start_mm), 0, 1)
    alpha = TPW_ALPHA_FADE_START + (TPW_ALPHA_FADE_END - TPW_ALPHA_FADE_START) * fade_ratio
    tpw_rgba[..., 3] = np.where(tcwv_mm < fade_start_mm, 0.0, alpha)

    imshow_antimeridian_safe(ax, tpw_rgba, lon, lat, pc, zorder=1)

    ax.add_geometries(country_geoms, crs=pc, facecolor="none", edgecolor="#4a6b7a", linewidth=0.8, zorder=1.5)
    ax.add_geometries(state_geoms, crs=pc, facecolor="none", edgecolor="#5a4632", linewidth=0.8, zorder=2)
    ax.add_geometries(admin0_lines, crs=pc, facecolor="none", edgecolor="#3a2f21", linewidth=1.1, zorder=2.5)

    # MSLP isobars -- drawn above every other layer so they stay legible
    # over both the TPW shading and the basemap. Levels are computed from
    # this map's actual MSLP range (not a fixed enhancement curve like the
    # TPW color table) at the standard 4 hPa surface-analysis interval, so
    # a flatter or stormier day gets fewer or more lines rather than a
    # fixed set that might not cross the data at all. contour() transforms
    # each vertex through the CRS directly (unlike imshow's raster warp --
    # see imshow_antimeridian_safe()'s docstring), so it handles this
    # domain's antimeridian-crossing, CENTER_LON-unwrapped lon array
    # without needing the same per-segment split.
    level_start = np.floor(mslp_hpa.min() / MSLP_CONTOUR_INTERVAL_HPA) * MSLP_CONTOUR_INTERVAL_HPA
    level_end = np.ceil(mslp_hpa.max() / MSLP_CONTOUR_INTERVAL_HPA) * MSLP_CONTOUR_INTERVAL_HPA
    mslp_levels = np.arange(level_start, level_end + MSLP_CONTOUR_INTERVAL_HPA, MSLP_CONTOUR_INTERVAL_HPA)
    isobars = ax.contour(lon, lat, mslp_hpa, levels=mslp_levels, transform=pc,
                          colors="#4a4a4a", linewidths=0.9, zorder=3)
    ax.clabel(isobars, inline=True, fontsize=7, fmt="%d", colors="#4a4a4a")

    # Pressure center ("L"/"H") markers -- red for lows, blue for highs
    # (the common public-facing convention), in Baloo 2 Bold rather than
    # this map's usual Poppins: at the size a single big letter gets drawn
    # here, Poppins' fairly square, business-document letterforms read
    # differently than Baloo 2's genuinely rounded, chunky ones, which fit
    # a friendly weather-map marker better -- a true bold weight too,
    # unlike Poppins' Regular/Medium (see BALOO_BOLD_PATH). White halo
    # just keeps the letter legible over the shading/basemap rather than
    # reading as its own outline. Projected to axes data coordinates once
    # via proj.transform_point() rather than passing transform=pc through
    # to text, since px/py is reused if a second element (e.g. a value
    # label) is ever added back here -- see find_pressure_extrema() for
    # how these centers were found.
    for ex_lon, ex_lat, _, kind in pressure_extrema:
        color = "#c0392b" if kind == "L" else "#1f5fa8"
        px, py = proj.transform_point(ex_lon, ex_lat, pc)
        ax.text(px, py, kind, ha="center", va="center", fontsize=22,
                 color=color, zorder=4, fontproperties=baloo_bold,
                 path_effects=[pe.withStroke(linewidth=1.8, foreground="white")])

    ax.spines['geo'].set_edgecolor('black')
    ax.spines['geo'].set_linewidth(1.6)

    # Colorbar -- below the map, centered on the rendered map frame.
    # Primary (bottom) axis is inches, ticked at each 0.5" color-table stop
    # (the unit the color table -- and PWAT/TPW products generally -- are
    # defined in); a secondary (top) axis mirrors it in mm.
    fig.canvas.draw()
    frame_px = ax.get_window_extent()
    frame_left = frame_px.x0 / (FIG_WIDTH_IN * FIG_DPI)
    frame_right = frame_px.x1 / (FIG_WIDTH_IN * FIG_DPI)
    cbar_width, cbar_height = (frame_right - frame_left) * 0.55, 0.016
    cbar_left = (frame_left + frame_right) / 2 - cbar_width / 2
    cbar_bottom = 0.085

    gradient_mm = np.linspace(TPW_MM_MIN, TPW_MM_MAX, 256).reshape(1, -1)
    cax = fig.add_axes([cbar_left, cbar_bottom, cbar_width, cbar_height])
    cax.imshow(gradient_mm, aspect="auto", cmap=tpw_cmap, norm=tpw_norm,
               extent=[TPW_IN_MIN, TPW_IN_MAX, 0, 1])
    cax.set_yticks([])
    for spine in cax.spines.values():
        spine.set_edgecolor("#8a887e")
        spine.set_linewidth(0.6)

    # Ticked at clean 0.5" steps -- not at the color table's own (now
    # unevenly power-law-spaced, see TPW_IN_MID) control points, which
    # would make for a cluttered, oddly-numbered axis.
    in_ticks = np.arange(TPW_IN_MIN, TPW_IN_MAX + 0.01, 0.5)
    cax.set_xticks(in_ticks)
    cax.set_xticklabels([f'{inch:g}"' for inch in in_ticks])
    cax.tick_params(labelsize=8.5, color="#8a887e", labelcolor="#2b2a26")
    for label in cax.get_xticklabels():
        label.set_fontproperties(poppins_reg)
    cax.set_xlabel("Total Precipitable Water (in)", fontsize=8.5, fontproperties=poppins_reg, color="#5a584f")

    cax_mm = cax.secondary_xaxis("top", functions=(in_to_mm, mm_to_in))
    cax_mm.xaxis.set_major_formatter(lambda mm, _: f"{mm:.0f}")
    cax_mm.tick_params(labelsize=8.5, color="#8a887e", labelcolor="#2b2a26")
    for label in cax_mm.get_xticklabels():
        label.set_fontproperties(poppins_reg)

    # Title & subtitle above the map -- titled off the actual valid time
    # (WM-6's 3-hourly steps mean it's not always exactly the requested
    # hour) rather than the requested one, so there's no need to spell out
    # the substitution.
    init_dt = datetime.fromisoformat(meta["initialization_time"].replace("Z", "+00:00"))
    valid_dt_utc = datetime.fromisoformat(meta["valid_time"].replace("Z", "+00:00"))
    valid_dt_local = valid_dt_utc.astimezone(LOCAL_TZ)

    h12 = valid_dt_local.hour % 12 or 12
    ampm = "AM" if valid_dt_local.hour < 12 else "PM"
    fig.text(0.03, 0.978, f"{valid_dt_local.strftime('%A')} {h12}:00 {ampm} PT Precipitable Water", fontsize=19,
              fontproperties=poppins_reg, color="#2b2a26", ha="left", va="top")
    fig.text(0.03, 0.943, "WindBorne WM-6 Ensemble Mean", fontsize=12.5,
              fontproperties=poppins_semibold, color="#3a3835", ha="left", va="top")
    fig.text(0.03, 0.914, f"Init {init_dt.strftime('%Y-%m-%d %H')}z",
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
        description="Build an Ingalls Weather WM-6 ensemble mean total precipitable water map.")
    parser.add_argument("--date", type=str, default=None,
                         help="Target date, YYYY-MM-DD, local (Pacific) time (default: tomorrow).")
    parser.add_argument("--hour", type=int, default=12,
                         help="Target local hour, 0-23 (default: 12, i.e. noon PT).")
    parser.add_argument("--file", type=Path, default=None,
                         help="Render from a local saved snapshot (.npz) instead of fetching live.")
    parser.add_argument("--out", type=Path, default=None,
                         help="Output PNG path (default: output/tpw_wm6_ensemble_<date>_<hour>.png).")
    args = parser.parse_args()

    if not (0 <= args.hour <= 23):
        parser.error("--hour must be between 0 and 23.")

    if args.file and not args.file.exists():
        sys.exit(f"--file {args.file} not found.")

    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        target_date = datetime.now(LOCAL_TZ).date() + timedelta(days=1)

    out_path = args.out or (OUTPUT_DIR / f"tpw_wm6_ensemble_{target_date.isoformat()}_{args.hour:02d}.png")
    build_map(target_date, args.hour, out_path, override_path=args.file)

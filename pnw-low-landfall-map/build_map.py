"""
WM-6 Ensemble Surface Low Landfall Map -- reusable builder for any
Pacific low approaching the Pacific Northwest coast
Ingalls Weather

Styled Instagram-portrait (4:5) map of a Pacific surface low approaching
the Pacific Northwest coast, from all 128 members of WindBorne's
WeatherMesh-6 global ensemble:
  - Thin lines: each member's surface-low track (center of the member's own
    MSLP minimum, followed 3-hourly), ending where it crosses the coast.
  - Bold line(s): the ensemble mean track -- or, when the members' landfall
    points split into two well-separated groups (see cluster_landfalls()),
    one mean track per cluster instead of a single mean that would run up
    the gap between them.
  - Colored coastline: the chance (fraction of all 128 members) that the
    low's center makes landfall within 100 km of each point on the outer
    coast, with a callout at a handful of coastal towns.

USAGE
-----
    python build_map.py                         # latest run, next 72 h, auto seed
    python build_map.py --start 2026-09-24T06 --end 2026-09-26T06
    python build_map.py --seed 42 -134.5         # follow a different low
    python build_map.py --file output/snapshot_<init>.npz   # no re-fetch

Requires WB_API_KEY in the environment (see
https://app.windbornesystems.com/api_tokens).

Member fields aren't offered as a per-variable subset by the gridded
endpoint -- see fetch_member_mslp()'s docstring for how this script reads
just the handful of MSLP member tiles it needs out of each forecast hour's
full zarr archive.

REQUIRES (already checked into /maps at repo root, shared across all
Ingalls Weather map projects):
    countries_slim.json, states_lakes_slim.json, admin0_boundary_lines.json
  countries_slim.json doubles as the land layer, the coastline, and the
  source of the outer-coast line the landfall math runs against (see
  build_outer_coast()).

Logo is read from /assets/ingalls_weather_logo.png at repo root.
"""

import argparse
import json
import math
import os
import re
import struct
import sys
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
from matplotlib.transforms import offset_copy
from matplotlib.lines import Line2D
import numpy as np
import requests
import zarr
from numcodecs import Blosc
from remotezip import RemoteZip
from scipy.ndimage import gaussian_filter, minimum_filter, uniform_filter

import cartopy.crs as ccrs
import shapely
from shapely.geometry import shape, box, LineString, Point
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

COUNTRIES_FILE = MAPS_DIR / "countries_slim.json"
STATES_LAKES_FILE = MAPS_DIR / "states_lakes_slim.json"
ADMIN0_LINES_FILE = MAPS_DIR / "admin0_boundary_lines.json"
ADMIN1_LINES_FILE = MAPS_DIR / "admin1_boundary_lines.json"
LOGO_FILE = ASSETS_DIR / "ingalls_weather_logo.png"

TARGET_COUNTRIES = {"United States of America", "Canada"}

# Land is the same soft warm gray as ../columbia-basin-lightning-map, so
# the probability band's yellows/oranges are the only warm color on the
# map; ocean stays a pale blue so the coastline reads at a glance.
LAND_COLOR = "#e3e1da"
OCEAN_COLOR = "#dbe9f0"

POPPINS_REG_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf"
POPPINS_MED_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf"
# Same Baloo 2 Bold as ../tpw-wm6-ensemble-map's pressure-center markers,
# used here for the "L" at the start of the mean track.
BALOO_BOLD_PATH = ASSETS_DIR / "fonts" / "Baloo2-Bold.ttf"

LOCAL_TZ = ZoneInfo("America/Los_Angeles")

# ---------------------------------------------------------------------------
# WindBorne API
# ---------------------------------------------------------------------------
WB_BASE = "https://api.windbornesystems.com/forecasts/v1/wm-6"
MEMBER_ARRAY = "members/pressure_msl"
N_MEMBERS_EXPECTED = 128
STEP_HOURS = 3  # WM-6 global's gridded output cadence
FETCH_WORKERS = 6

# ---------------------------------------------------------------------------
# Figure geometry -- 4:5 portrait, Instagram's tallest feed aspect, at 2x
# Instagram's 1080x1350 upload size (1728x2160 px). Projection is the same
# NearsidePerspective "satellite view" as ../columbia-basin-lightning-map
# (see build_map()); the domain below is sized so its projected shape
# fills AXES_RECT's width with no side gutters.
# ---------------------------------------------------------------------------
FIG_WIDTH_IN, FIG_HEIGHT_IN = 8.64, 10.8
FIG_DPI = 200
AXES_RECT = [0.03, 0.150, 0.94, 0.730]  # [left, bottom, width, height], figure fraction
MAP_FRAME_INSET_PX = 22

# ---------------------------------------------------------------------------
# Map domain -- NE Pacific from where the low is tracked from, east across
# the Cascades, Cape Mendocino (S) to northern Vancouver Island (N).
# ---------------------------------------------------------------------------
LON_MIN, LON_MAX = -141.5, -118.5
LAT_MIN, LAT_MAX = 35.5, 53.8

# Member MSLP is fetched over a slightly larger box than the map so a low
# near the frame edge still has a full local-minimum search window around
# it (see find_local_minima()).
FETCH_PAD_DEG = 3.0
FETCH_BOX = (LON_MIN - FETCH_PAD_DEG, LAT_MIN - FETCH_PAD_DEG,
             LON_MAX + FETCH_PAD_DEG, LAT_MAX + FETCH_PAD_DEG)

# Zoomed view (see fit_view_extent()): padding around the tracks/coast/L,
# a minimum height, room east of the coast band for town callouts, and
# room around the "L" for its label and the bottom-left logo -- the
# fractions are of the view's own width/height, since labels and logo are
# fixed-size on the page whatever the zoom.
VIEW_PAD_DEG = 1.0
VIEW_MIN_LAT_SPAN_DEG = 8.0
VIEW_LABEL_FRAC = 0.17
VIEW_L_MARGIN_LON_FRAC = 0.08
VIEW_L_MARGIN_LAT_FRAC = 0.20

# Basemap geometries are clipped to a box padded well past the map: the
# perspective view's rectangular frame reaches further in lon/lat at its
# corners than LON_MIN/LON_MAX/LAT_MIN/LAT_MAX do along its edges, and the
# land fill has to reach all the way out into them.
BASEMAP_PAD_DEG = 8.0
MAP_CLIP_BOX = box(LON_MIN - BASEMAP_PAD_DEG, LAT_MIN - BASEMAP_PAD_DEG,
                   LON_MAX + BASEMAP_PAD_DEG, LAT_MAX + BASEMAP_PAD_DEG)

# Same satellite height as ../columbia-basin-lightning-map.
SATELLITE_HEIGHT_M = 4_000_000

# ---------------------------------------------------------------------------
# Tracking window & seed. The low is found at the window's first step in
# the ensemble mean -- the deepest MSLP minimum inside SEED_BOX, the
# offshore approach to the PNW coast -- and each member's track starts from
# its own nearest local minimum to that point. By default the window starts
# at the current 3-hourly step (or the run's forecast zero, if later) and
# runs DEFAULT_WINDOW_HOURS: tracks stop at landfall anyway, so a generous
# window just costs a few more fetched steps. For a low that isn't the
# deepest thing in SEED_BOX yet, or isn't there at the window's start,
# pass --start (when it's offshore) and/or --seed (where it is then).
# ---------------------------------------------------------------------------
DEFAULT_WINDOW_HOURS = 72
SEED_BOX = (-140.0, 38.0, -126.0, 50.0)  # lon_min, lat_min, lon_max, lat_max
SEED_MAX_KM = 400.0

# ---------------------------------------------------------------------------
# Tracker settings -- see track_member().
# ---------------------------------------------------------------------------
# Light smoothing (in 0.25 deg grid cells) before looking for minima, so a
# single-cell ripple in a member's field doesn't pull its track around.
SMOOTH_SIGMA_CELLS = 1.0
# A local minimum must be the lowest value within this window (cells;
# 7 = +/-0.75 deg) ...
LOCAL_MIN_WINDOW_CELLS = 7
# ... and sit at least this far below the mean of a much wider window
# (cells; 25 = ~6 deg) -- i.e. a real closed-ish center, not a flat spot in
# a trough.
LOCAL_MIN_PROMINENCE_HPA = 0.5
LOCAL_MIN_BG_WINDOW_CELLS = 25
# Max distance from the first-guess position (last position extrapolated
# by the last step's motion) a center can be matched to. The low moves up
# to ~200 km per 3 h as it accelerates into the coast.
MAX_STEP_KM = 300.0
# A member whose low loses its closed center before crossing the coast
# still counts as making landfall, at the nearest coast point, if its last
# tracked position was within this distance of the coast -- it's filling
# as it comes ashore, which is still that coastline's storm.
LANDFALL_DECAY_KM = 50.0

# ---------------------------------------------------------------------------
# Outer coast & landfall probability -- see build_outer_coast().
# ---------------------------------------------------------------------------
COAST_LAT_MIN, COAST_LAT_MAX = 39.0, 50.75
COAST_SCAN_STEP_DEG = 0.02
# Running-westernmost window (deg lat) applied to the scanned coast --
# wide enough to close off the Strait of Juan de Fuca (~0.2 deg wide at its
# mouth), Grays Harbor, and the Columbia's mouth, so the coast line runs
# straight across them rather than tracing up into the Salish Sea.
COAST_SMOOTH_LAT_DEG = 0.15
LANDFALL_RADIUS_KM = 100.0

# Callout towns along the outer coast -- (name, lat, lon, label side).
# Probability shown is the value at the nearest outer-coast point.
COAST_TOWNS = [
    ("Tofino", 49.153, -125.906),
    ("Neah Bay", 48.368, -124.625),
    ("La Push", 47.908, -124.636),
    ("Westport", 46.890, -124.104),
    ("Astoria", 46.188, -123.831),
    ("Tillamook", 45.456, -123.844),
    ("Newport", 44.637, -124.053),
    ("Coos Bay", 43.367, -124.218),
    ("Crescent City", 41.756, -124.201),
    ("Eureka", 40.802, -124.164),
]

# Probability color table -- fixed bins (not rescaled per map), running
# from a neutral "very unlikely" gray through yellow/orange/red to deep
# purple. Tracks are drawn in blues so they never read as part of this
# scale.
# Coast below PROB_MIN_SHOWN_PCT isn't highlighted at all (and gets no
# town callout) -- a 1-in-128 member landfall isn't a real signal.
PROB_MIN_SHOWN_PCT = 2
PROB_BOUNDS = [PROB_MIN_SHOWN_PCT, 5, 10, 20, 30, 40, 50, 60, 70, 100]
PROB_COLORS = ["#fef3c7", "#fde68a", "#fbbf24", "#f59e0b", "#ea580c",
               "#dc2626", "#b91c1c", "#9d174d", "#581c87"]

TRACK_COLOR = "#1f5fa8"
CLUSTER_COLORS = ["#1f5fa8", "#0f8b8d"]  # north, south
MEMBER_TRACK_ALPHA = 0.30

# The "L" marker (and its three-line label beneath it) needs to be at
# least this far inside the frame's west/south edges -- the latitude
# margin also keeps it above the logo in the bottom-left corner.
L_MARKER_MARGIN_LON_DEG = 1.0
L_MARKER_MARGIN_LAT_DEG = 3.5
# "L" size, and the central-pressure label under it: its size, and how far
# below the L's center its top sits (points) -- scale the offset with
# L_MARKER_FONTSIZE, since the letter's bottom edge moves with it.
L_MARKER_FONTSIZE = 52
L_PRESSURE_FONTSIZE = 17
L_PRESSURE_OFFSET_PT = 13.5

# ---------------------------------------------------------------------------
# NOAA analyzed low position for the "L" -- see fetch_noaa_lows(). The "L"
# marks where NOAA's own surface analysis puts the low, not a model
# position, whenever one of these analyses has a low matching the tracked
# system.
#   - OPC High Seas Forecast, NE Pacific (FZPN02 KWBC / HSFEPI): OPC's
#     6-hourly analyzed lows N of 30N, whole-degree positions.
#   - WPC coded surface analysis, high-res (ASUS02 KWBC / CODSUS): the
#     3-hourly unified surface analysis, tenth-degree positions -- but its
#     lows only reach out to ~135W, so a low still well offshore is
#     usually OPC-only.
# ---------------------------------------------------------------------------
OPC_HSF_URL = "https://tgftp.nws.noaa.gov/data/raw/fz/fzpn02.kwbc.hsf.epi.txt"
WPC_CODSUS_URL = "https://tgftp.nws.noaa.gov/data/raw/as/asus02.kwbc.cod.sus.txt"
# An analyzed low matches the tracked system if it's within this distance
# of the ensemble mean track's position at the analysis time.
NOAA_MATCH_KM = 400.0
# Analyses older than this aren't "current" -- fall back to the mean track.
NOAA_MAX_AGE_HOURS = 12

# Two landfall groups are drawn as separate clusters only when a
# 2-component Gaussian mixture fit to landfall latitude beats a single
# Gaussian by at least CLUSTER_MIN_BIC_GAIN (BIC; 10 = "very strong"
# evidence), its components are separated by Ashman's D >= 2 (the standard
# threshold for a genuinely bimodal mixture), and the smaller component
# holds at least CLUSTER_MIN_SHARE of landfalling members. (Ashman's D on
# the halves of a best split is NOT a test on its own: splitting a single
# normal distribution at its median already gives D ~2.7.)
CLUSTER_MIN_BIC_GAIN = 10.0
CLUSTER_MIN_ASHMAN_D = 2.0
CLUSTER_MIN_SHARE = 0.15


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------
EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = (np.sin((lat2 - lat1) / 2) ** 2
         + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2)
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def _load_country_geoms():
    with open(COUNTRIES_FILE) as f:
        data = json.load(f)
    return [shape(feat["geometry"]) for feat in data["features"]
            if feat["properties"].get("NAME") in TARGET_COUNTRIES]


def build_outer_coast(land):
    """The open-ocean-facing coastline as a single south-to-north
    LineString, for the landfall math and the probability band.

    Scans west-to-east along each latitude row (every COAST_SCAN_STEP_DEG)
    for the first land it hits, then takes a running westernmost value over
    +/-COAST_SMOOTH_LAT_DEG. The full land boundary won't do here: it
    traces every inlet and all of the Salish Sea, so a low entering the
    Strait of Juan de Fuca would "cross the coast" somewhere near Seattle,
    and Puget Sound's shoreline would light up on the probability band for
    a landfall 150 km away on the open coast. The running-westernmost step
    closes off the strait (and Grays Harbor, the Columbia mouth, etc.) with
    a straight line across its mouth instead."""
    lats = np.arange(COAST_LAT_MIN, COAST_LAT_MAX + 1e-9, COAST_SCAN_STEP_DEG)
    west = np.full(lats.shape, np.nan)
    for i, la in enumerate(lats):
        hit = land.intersection(LineString([(LON_MIN - FETCH_PAD_DEG, la), (LON_MAX, la)]))
        if not hit.is_empty:
            west[i] = hit.bounds[0]
    keep = ~np.isnan(west)
    lats, west = lats[keep], west[keep]
    half = int(round(COAST_SMOOTH_LAT_DEG / COAST_SCAN_STEP_DEG))
    smoothed = np.array([west[max(0, i - half):i + half + 1].min() for i in range(len(west))])
    # Then a running mean over the same window, which takes the stair-step
    # edges off the running-min output along BC's and NorCal's ragged coast.
    smoothed = np.array([smoothed[max(0, i - half):i + half + 1].mean() for i in range(len(smoothed))])
    return LineString(np.column_stack([smoothed, lats]))


# ---------------------------------------------------------------------------
# WindBorne WM-6 fetch
# ---------------------------------------------------------------------------
def wb_get(path, api_key, **params):
    headers = {"Authorization": f"Bearer {api_key}"}
    resp = requests.get(f"{WB_BASE}/{path}", headers=headers, params=params, timeout=60)
    resp.raise_for_status()
    return resp.json()


def fetch_zarr_array(remote_zip, names, tmp_dir, array_path):
    """Same as ../tpw-wm6-ensemble-map's: copy one small array's entries out
    of the remote zip and let zarr decode it."""
    entries = [n for n in names if n == f"{array_path}/zarr.json" or n.startswith(f"{array_path}/c")]
    for name in entries:
        dest = tmp_dir / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(remote_zip.read(name))
    return zarr.open_array(store=str(tmp_dir), path=array_path, mode="r")[:]


def http_range(session, url, start, end):
    """Bytes [start, end) of url."""
    resp = session.get(url, headers={"Range": f"bytes={start}-{end - 1}"}, timeout=120)
    resp.raise_for_status()
    if len(resp.content) != end - start:
        raise RuntimeError(f"Short range read: wanted {end - start} bytes, got {len(resp.content)}")
    return resp.content


def fetch_member_mslp(init_time, forecast_hour, api_key):
    """All 128 members' MSLP for one forecast hour, cropped to FETCH_BOX.

    Members aren't available as a per-variable subset from the gridded
    endpoint -- `variable=all` + `as_url=true` hands back a presigned URL
    to that hour's full zarr zip (every variable/product, several GB).
    Like ../tpw-wm6-ensemble-map, this range-reads just what it needs, but
    goes one level deeper: `members/pressure_msl` is a single ~170 MB
    zarr v3 shard (128 x 720 x 1440, sharding_indexed with 128 x 45 x 45
    inner chunks, i.e. 11.25 deg tiles), so rather than pulling that
    whole entry through remotezip this reads the shard's index off its
    tail and fetches only the inner chunks overlapping FETCH_BOX (six
    tiles, ~2 MB), decoding each with Blosc directly. The zip entry is
    STORED (uncompressed), which is what makes byte offsets inside it
    addressable -- checked below rather than assumed.

    The member grid's coordinates are the same 0.25 deg latitude/longitude
    arrays as the rest of the file (latitude 90 -> -89.75; longitude
    0 -> 179.75 then -180 -> -0.25, so compared mod 360 here) -- verified
    against the ensemble_mean MSLP field (the member mean matches it to
    ~0.003 hPa) -- read from the zip rather than hard-coded.

    Returns (lat_1d ascending, lon_1d -180..180 ascending,
    mslp_hpa [member, lat, lon], meta dict)."""
    url_info = wb_get("gridded", api_key, variable="all", initialization_time=init_time,
                      forecast_hour=forecast_hour, as_url="true")
    url = url_info["url"]

    with RemoteZip(url) as rz:
        names = rz.namelist()
        root_meta = json.loads(rz.read("zarr.json"))["attributes"]
        array_meta = json.loads(rz.read(f"{MEMBER_ARRAY}/zarr.json"))
        shard_info = rz.getinfo(f"{MEMBER_ARRAY}/c/0/0/0")
        with tempfile.TemporaryDirectory() as tmp:
            lat = fetch_zarr_array(rz, names, Path(tmp), "latitude")
            lon = fetch_zarr_array(rz, names, Path(tmp), "longitude")

    if shard_info.compress_type != zipfile.ZIP_STORED:
        raise RuntimeError(f"{MEMBER_ARRAY} shard is compressed inside the zip; can't range-read it")
    shape_ = array_meta["shape"]
    (sharding,) = [c for c in array_meta["codecs"] if c["name"] == "sharding_indexed"]
    inner = sharding["configuration"]["chunk_shape"]
    if array_meta["chunk_grid"]["configuration"]["chunk_shape"] != shape_ or inner[0] != shape_[0]:
        raise RuntimeError(f"Unexpected {MEMBER_ARRAY} layout: {array_meta['chunk_grid']}, inner {inner}")
    if (len(lat), len(lon)) != tuple(shape_[1:]):
        raise RuntimeError("Member grid doesn't match the file's latitude/longitude arrays")
    n_mem, ny, nx = shape_
    cy, cx = inner[1], inner[2]
    n_cy, n_cx = ny // cy, nx // cx

    session = requests.Session()
    # Local file header: 30 fixed bytes, then filename and extra field.
    header = http_range(session, url, shard_info.header_offset, shard_info.header_offset + 30)
    name_len, extra_len = struct.unpack("<HH", header[26:30])
    data_start = shard_info.header_offset + 30 + name_len + extra_len
    data_end = data_start + shard_info.compress_size

    # Shard index (index_location "end"): one (offset, nbytes) uint64 pair
    # per inner chunk in C order, then a 4-byte crc32c.
    index_len = n_cy * n_cx * 16 + 4
    index = np.frombuffer(http_range(session, url, data_end - index_len, data_end)[:-4],
                          dtype="<u8").reshape(n_cy, n_cx, 2)

    lon_min_360, lon_max_360 = FETCH_BOX[0] % 360, FETCH_BOX[2] % 360
    lat_rows = np.where((lat >= FETCH_BOX[1]) & (lat <= FETCH_BOX[3]))[0]
    lon_360 = lon % 360
    lon_cols = np.where((lon_360 >= lon_min_360) & (lon_360 <= lon_max_360))[0]
    tiles_y = range(lat_rows.min() // cy, lat_rows.max() // cy + 1)
    tiles_x = range(lon_cols.min() // cx, lon_cols.max() // cx + 1)

    fill = float(array_meta.get("fill_value", 0.0))
    block = np.full((n_mem, len(tiles_y) * cy, len(tiles_x) * cx), fill, dtype=np.float32)
    blosc = Blosc()
    for a, ty in enumerate(tiles_y):
        for b, tx in enumerate(tiles_x):
            offset, nbytes = (int(v) for v in index[ty, tx])
            if offset == 2 ** 64 - 1:  # empty chunk -> fill value
                continue
            raw = blosc.decode(http_range(session, url, data_start + offset, data_start + offset + nbytes))
            block[:, a * cy:(a + 1) * cy, b * cx:(b + 1) * cx] = np.frombuffer(raw, "<f4").reshape(n_mem, cy, cx)

    row0, col0 = tiles_y[0] * cy, tiles_x[0] * cx
    mslp = block[:, lat_rows - row0][:, :, lon_cols - col0] / 100.0  # Pa -> hPa
    lat_crop = lat[lat_rows]
    lon_crop = ((lon[lon_cols] + 180) % 360) - 180
    if lat_crop[0] > lat_crop[-1]:
        lat_crop, mslp = lat_crop[::-1], mslp[:, ::-1, :]

    meta = {k: root_meta[k] for k in ("initialization_time", "forecast_zero", "valid_time", "forecast_hour")}
    return lat_crop, lon_crop, np.ascontiguousarray(mslp), meta


def fetch_all(start_utc, end_utc, api_key):
    """Fetch every member's MSLP for each 3-hourly step from start_utc to
    end_utc, all pinned to one WM-6 run (the latest complete one) so the
    steps don't straddle two runs as WM-6 updates hourly. start_utc None =
    the latest 00/06/12/18Z synoptic time (not before the run's forecast
    zero); end_utc None = DEFAULT_WINDOW_HOURS after the start."""
    run = wb_get("run_information", api_key)
    if run.get("in_progress"):
        sys.exit("Latest WM-6 run is still in progress -- try again in a few minutes.")
    init_time = run["initialization_time"]
    forecast_zero = datetime.fromisoformat(run["forecast_zero"].replace("Z", "+00:00"))
    available = {a["forecast_hour"] for a in run["available"]}
    if start_utc is None:
        # The latest 00/06/12/18Z synoptic time -- the time OPC's most
        # recent analysis is valid for, so the tracks start where the
        # NOAA-analyzed "L" is (see fetch_noaa_lows()).
        now = datetime.now(timezone.utc)
        synoptic = now.replace(hour=now.hour - now.hour % 6, minute=0, second=0, microsecond=0)
        start_utc = max(forecast_zero, synoptic)
    if end_utc is None:
        end_utc = start_utc + timedelta(hours=DEFAULT_WINDOW_HOURS)

    first = math.ceil((start_utc - forecast_zero).total_seconds() / 3600 / STEP_HOURS) * STEP_HOURS
    last = math.floor((end_utc - forecast_zero).total_seconds() / 3600 / STEP_HOURS) * STEP_HOURS
    fhs = [fh for fh in range(max(first, 0), last + 1, STEP_HOURS)]
    missing = [fh for fh in fhs if fh not in available]
    if not fhs or missing:
        sys.exit(f"Run {init_time} doesn't cover the requested window (missing hours: {missing or 'all'}).")

    print(f"WM-6 run init {init_time} (forecast zero {run['forecast_zero']}): "
          f"fetching {len(fhs)} steps, fh {fhs[0]}-{fhs[-1]}...")

    def one(fh):
        out = fetch_member_mslp(init_time, fh, api_key)
        print(f"  fh {fh:3d}  valid {out[3]['valid_time']}", flush=True)
        return out

    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        results = list(pool.map(one, fhs))

    lat, lon = results[0][0], results[0][1]
    mslp = np.stack([r[2] for r in results])  # [step, member, lat, lon]
    valid_times = [r[3]["valid_time"] for r in results]
    meta = {"initialization_time": results[0][3]["initialization_time"],
            "forecast_zero": results[0][3]["forecast_zero"]}
    return lat, lon, mslp, valid_times, meta


# ---------------------------------------------------------------------------
# NOAA analyzed lows
# ---------------------------------------------------------------------------
MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


def parse_opc_hsf(text):
    """Analyzed lows from an OPC High Seas Forecast: every "LOW ..." /
    "... CENTER ..." position in an entry that isn't an "NN HOUR
    FORECAST", valid at the product's SYNOPSIS VALID time. Returns
    [(valid_utc, lat, lon, hpa, "OPC")]."""
    issued = re.search(r"\d{4} UTC \w{3} (\w{3}) (\d{1,2}) (\d{4})", text)
    syn = re.search(r"SYNOPSIS VALID (\d{2})00 UTC (\w{3}) (\d{1,2})", text)
    if not issued or not syn:
        return []
    year = int(issued.group(3))
    if MONTHS[syn.group(2)] > MONTHS[issued.group(1)]:  # Dec synopsis in a Jan issuance
        year -= 1
    valid = datetime(year, MONTHS[syn.group(2)], int(syn.group(3)), int(syn.group(1)), tzinfo=timezone.utc)
    lows = []
    # Entries start with "." at the beginning of a line.
    for entry in re.split(r"\n(?=\.)", text):
        entry = " ".join(entry.split())
        if re.match(r"\.\d+ HOUR FORECAST", entry):
            continue
        for m in re.finditer(
                r"(?:LOW|CENTER)\s+(?:NEAR\s+)?(\d{1,2}(?:\.\d)?)N\s*(\d{1,3}(?:\.\d)?)([EW])\s+(\d{3,4})\s*MB", entry):
            lon = float(m.group(2)) * (-1 if m.group(3) == "W" else 1)
            lows.append((valid, float(m.group(1)), lon, float(m.group(4)), "OPC"))
    return lows


def parse_wpc_codsus(text):
    """Lows from WPC's high-res coded surface bulletin ("LOWS <hPa>
    <LLLOOOO> ...": lat*10 then W lon*10), valid at its "VALID MMDDHHZ"
    time. Returns [(valid_utc, lat, lon, hpa, "WPC")]."""
    head = re.search(r"VALID (\d{2})(\d{2})(\d{2})Z", text)
    year = re.search(r" (\d{4})\s*$", text[:head.start()] if head else "", re.M)
    if not head or not year:
        return []
    valid = datetime(int(year.group(1)), int(head.group(1)), int(head.group(2)), int(head.group(3)),
                     tzinfo=timezone.utc)
    keywords = {"HIGHS", "LOWS", "COLD", "WARM", "STNRY", "OCFNT", "TROF", "$$"}
    tokens = text[head.end():].split()
    lows, in_lows, i = [], False, 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in keywords:
            in_lows = tok == "LOWS"
        elif in_lows and i + 1 < len(tokens) and len(tokens[i + 1]) == 7 and tokens[i + 1].isdigit():
            code = tokens[i + 1]
            lows.append((valid, int(code[:3]) / 10, -int(code[3:]) / 10, float(tok), "WPC"))
            i += 1
        i += 1
    return lows


def fetch_noaa_lows():
    """Current NOAA analyzed lows from OPC and WPC (see OPC_HSF_URL /
    WPC_CODSUS_URL). A source that can't be fetched or parsed is skipped
    with a note -- the map then falls back to the mean track for the
    "L"."""
    lows = []
    for name, url, parser in [("OPC High Seas Forecast", OPC_HSF_URL, parse_opc_hsf),
                              ("WPC coded surface analysis", WPC_CODSUS_URL, parse_wpc_codsus)]:
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            found = parser(resp.text)
            print(f"  {name}: {len(found)} analyzed lows"
                  + (f", valid {found[0][0]:%Y-%m-%d %HZ}" if found else ""))
            lows += found
        except Exception as exc:  # network/format problems shouldn't block the map
            print(f"  NOTE: couldn't read {name} ({exc})")
    return lows


def match_noaa_low(noaa_lows, mean_positions, t0):
    """The most recent NOAA-analyzed low (OPC preferred on a tie) within
    NOAA_MATCH_KM of the ensemble mean track at its analysis time, and no
    older than NOAA_MAX_AGE_HOURS. `mean_positions` is [(hours since t0,
    lat, lon)]; an analysis up to 6 h before the track's start is compared
    against its first point. Returns (valid_utc, lat, lon, hpa, source) or
    None."""
    if not mean_positions:
        return None
    now = datetime.now(timezone.utc)
    hrs = np.array([p[0] for p in mean_positions])
    best = None
    for low in noaa_lows:
        valid, lat, lon, hpa, source = low
        if now - valid > timedelta(hours=NOAA_MAX_AGE_HOURS):
            continue
        h = (valid - t0).total_seconds() / 3600
        if h < hrs[0] - 6 or h > hrs[-1]:
            continue
        hc = min(max(h, hrs[0]), hrs[-1])
        ref_lat = np.interp(hc, hrs, [p[1] for p in mean_positions])
        ref_lon = np.interp(hc, hrs, [p[2] for p in mean_positions])
        if haversine_km(lat, lon, ref_lat, ref_lon) > NOAA_MATCH_KM:
            continue
        key = (valid, source == "OPC")
        if best is None or key > best[0]:
            best = (key, low)
    return best[1] if best else None


# ---------------------------------------------------------------------------
# Tracking
# ---------------------------------------------------------------------------
def find_local_minima(field):
    """(row, col) of each closed-ish MSLP center in a smoothed field -- see
    LOCAL_MIN_* for the criteria."""
    smooth = gaussian_filter(field, SMOOTH_SIGMA_CELLS)
    is_min = smooth == minimum_filter(smooth, size=LOCAL_MIN_WINDOW_CELLS, mode="nearest")
    background = uniform_filter(smooth, size=LOCAL_MIN_BG_WINDOW_CELLS, mode="nearest")
    rows, cols = np.where(is_min & (background - smooth >= LOCAL_MIN_PROMINENCE_HPA))
    return rows, cols, smooth


def crossing_point(coast, p0, p1):
    """First point where the segment p0 -> p1 (each (lat, lon)) crosses
    the coast line, with its fraction along the segment, or None."""
    seg = LineString([(p0[1], p0[0]), (p1[1], p1[0])])
    hit = seg.intersection(coast)
    if hit.is_empty:
        return None
    pts = [hit] if hit.geom_type == "Point" else [g for g in getattr(hit, "geoms", []) if g.geom_type == "Point"]
    if not pts:
        return None
    first = min(pts, key=lambda g: seg.project(g))
    return (first.y, first.x), seg.project(first) / seg.length


def seed_position(lat, lon, mean_field):
    """Deepest ensemble-mean MSLP inside SEED_BOX at the first step."""
    lon_g, lat_g = np.meshgrid(lon, lat)
    in_box = ((lon_g >= SEED_BOX[0]) & (lon_g <= SEED_BOX[2])
              & (lat_g >= SEED_BOX[1]) & (lat_g <= SEED_BOX[3]))
    i = np.argmin(np.where(in_box, mean_field, np.inf))
    return float(lat_g.flat[i]), float(lon_g.flat[i]), float(mean_field.flat[i])


def track_member(lat, lon, fields, hours, seed, coast):
    """Follow one member's low from `seed` through its 3-hourly fields
    (list of 2-D MSLP arrays, one per entry of `hours` -- hours since the
    first step).

    Each step matches the local minimum (find_local_minima()) nearest a
    first-guess position -- the last position pushed along by the last
    step's motion -- within MAX_STEP_KM. That's the standard
    persistence-first-guess approach: picking the *deepest* nearby minimum
    instead lets a track jump to a different, deeper low (the parent
    trough to the north here) as soon as one wanders into range.

    The track ends at whichever comes first:
      - it crosses the outer coast: the crossing point becomes the
        landfall, with its time interpolated along that 3-hour step;
      - no minimum is found (the low opened up into a trough): landfall
        at the nearest coast point if the last position was within
        LANDFALL_DECAY_KM of the coast, otherwise no landfall;
      - the window runs out.

    Returns dict(points=[(hour, lat, lon, hpa)], landfall=(hour, lat, lon)
    or None)."""
    points = []
    guess = seed
    for step, (hour, field) in enumerate(zip(hours, fields)):
        rows, cols, smooth = find_local_minima(field)
        if len(rows) == 0:
            break
        dist = haversine_km(guess[0], guess[1], lat[rows], lon[cols])
        radius = SEED_MAX_KM if step == 0 else MAX_STEP_KM
        j = np.argmin(dist)
        if dist[j] > radius:
            break
        pos = (float(lat[rows[j]]), float(lon[cols[j]]))
        hpa = float(field[rows[j], cols[j]])

        if points:
            cross = crossing_point(coast, points[-1][1:3], pos)
            if cross is not None:
                (c_lat, c_lon), frac = cross
                c_hour = points[-1][0] + frac * (hour - points[-1][0])
                points.append((c_hour, c_lat, c_lon, hpa))
                return {"points": points, "landfall": (c_hour, c_lat, c_lon)}

        points.append((hour, pos[0], pos[1], hpa))
        if len(points) >= 2:
            d_lat, d_lon = pos[0] - points[-2][1], pos[1] - points[-2][2]
            guess = (pos[0] + d_lat, pos[1] + d_lon)
        else:
            guess = pos

    if points:
        last = Point(points[-1][2], points[-1][1])
        near = coast.interpolate(coast.project(last))
        if haversine_km(last.y, last.x, near.y, near.x) <= LANDFALL_DECAY_KM:
            points.append((points[-1][0], near.y, near.x, points[-1][3]))
            return {"points": points, "landfall": (points[-1][0], near.y, near.x)}
    return {"points": points, "landfall": None}


def fit_gmm2(x, iters=300):
    """Two-component 1-D Gaussian mixture by EM, initialized from the best
    split of the sorted values. Returns (weights, means, variances,
    log-likelihood)."""
    s = np.sort(x)
    best = min(range(2, len(s) - 1), key=lambda c: s[:c].var() * c + s[c:].var() * (len(s) - c))
    w = np.array([best, len(s) - best]) / len(s)
    mu = np.array([s[:best].mean(), s[best:].mean()])
    var = np.maximum(np.array([s[:best].var(), s[best:].var()]), 1e-4)
    for _ in range(iters):
        dens = w * np.exp(-(x[:, None] - mu) ** 2 / (2 * var)) / np.sqrt(2 * np.pi * var)
        resp = dens / dens.sum(axis=1, keepdims=True)
        nk = resp.sum(axis=0)
        w = nk / len(x)
        mu = (resp * x[:, None]).sum(axis=0) / nk
        var = np.maximum((resp * (x[:, None] - mu) ** 2).sum(axis=0) / nk, 1e-4)
    dens = w * np.exp(-(x[:, None] - mu) ** 2 / (2 * var)) / np.sqrt(2 * np.pi * var)
    return w, mu, var, float(np.log(dens.sum(axis=1)).sum())


def cluster_landfalls(tracks):
    """Split landfalling members into a northern and southern group if
    their landfall latitudes are genuinely bimodal (see CLUSTER_MIN_*);
    otherwise one group.

    One-dimensional on landfall latitude on purpose: along this nearly
    north-south coast, where the low comes ashore is the question the map
    answers, and every member's track converges on its landfall point from
    the same general direction. Model choice is by BIC between one and two
    Gaussians (5 vs 2 parameters) -- a formal "is there really more than
    one mode" test, rather than always cutting the members in two.

    Returns a list of member-index lists, north first, and a short
    description of the decision for the console."""
    idx = [k for k, t in enumerate(tracks) if t["landfall"]]
    if len(idx) < 10:
        return [idx], "too few landfalls to cluster"
    x = np.array([tracks[k]["landfall"][1] for k in idx])
    n = len(x)
    ll1 = float(np.sum(-0.5 * np.log(2 * np.pi * x.var()) - (x - x.mean()) ** 2 / (2 * x.var())))
    w, mu, var, ll2 = fit_gmm2(x)
    bic_gain = (2 * math.log(n) - 2 * ll1) - (5 * math.log(n) - 2 * ll2)
    ashman_d = math.sqrt(2) * abs(mu[0] - mu[1]) / math.sqrt(var.sum())
    desc = (f"GMM components {mu[0]:.2f}N (w {w[0]:.0%}) / {mu[1]:.2f}N (w {w[1]:.0%}), "
            f"BIC gain {bic_gain:.1f}, Ashman's D {ashman_d:.2f}")
    if bic_gain >= CLUSTER_MIN_BIC_GAIN and ashman_d >= CLUSTER_MIN_ASHMAN_D and w.min() >= CLUSTER_MIN_SHARE:
        north_c = int(np.argmax(mu))
        dens = w * np.exp(-(x[:, None] - mu) ** 2 / (2 * var)) / np.sqrt(var)
        is_north = dens.argmax(axis=1) == north_c
        return ([idx[i] for i in range(n) if is_north[i]], [idx[i] for i in range(n) if not is_north[i]]), \
            "clustered -- " + desc
    return [idx], "single group -- " + desc


def smooth_track(points):
    """1-2-1 smoothing of a track's interior positions (endpoints -- the
    start and the landfall point -- stay put). Centers are found on the
    0.25 deg grid, so a raw track zig-zags by a grid cell here and there
    even when the low is moving steadily; this takes that stair-stepping
    out without moving the track anywhere it didn't go."""
    if len(points) < 3:
        return points
    arr = np.array([(p[1], p[2]) for p in points])
    sm = arr.copy()
    sm[1:-1] = 0.25 * arr[:-2] + 0.5 * arr[1:-1] + 0.25 * arr[2:]
    return [(p[0], la, lo, p[3]) for p, (la, lo) in zip(points, sm)]


def position_at(track, hour):
    """A member's (lat, lon) at `hour`. Past its landfall (or last tracked
    point) it's carried on along its last step's motion, so the mean of a
    set of members doesn't lurch back toward the coast as the first ones
    come ashore and stop -- it keeps moving the way they were going. None
    before the track starts or if it's a single point."""
    pts = track["points"]
    if len(pts) < 2 or hour < pts[0][0]:
        return None
    for a, b in zip(pts[:-1], pts[1:]):
        if a[0] <= hour <= b[0] and b[0] > a[0]:
            f = (hour - a[0]) / (b[0] - a[0])
            return a[1] + f * (b[1] - a[1]), a[2] + f * (b[2] - a[2])
    # Past the end: extrapolate from the last full 3-hour step.
    a, b = pts[-3] if len(pts) >= 3 and pts[-1][0] - pts[-2][0] < 1e-6 else pts[-2], pts[-1]
    dt = b[0] - a[0]
    if dt <= 0:
        return b[1], b[2]
    f = (hour - b[0]) / dt
    return b[1] + f * (b[1] - a[1]), b[2] + f * (b[2] - a[2])


def mean_track(tracks, members, coast, hours):
    """Mean position of `members` at each step (see position_at() for how
    members already ashore are carried along), until the mean position
    itself crosses the coast -- that crossing is the mean track's landfall.
    Averaging positions, rather than drawing the ensemble-mean field's own
    low, keeps the mean track honest where members' lows fill at different
    times. The last point is the coast crossing (hour interpolated); its
    pressure entry is NaN."""
    members = [k for k in members if len(tracks[k]["points"]) >= 2]
    if not members:
        return []
    out = []
    for hour in hours:
        pos = [position_at(tracks[k], hour) for k in members]
        pos = [p for p in pos if p is not None]
        if len(pos) < 0.5 * len(members):
            if out:
                break
            continue
        lat_m, lon_m = float(np.mean([p[0] for p in pos])), float(np.mean([p[1] for p in pos]))
        hpa = [p[3] for k in members for p in tracks[k]["points"] if p[0] == hour]
        if out:
            cross = crossing_point(coast, out[-1][1:3], (lat_m, lon_m))
            if cross is not None:
                (c_lat, c_lon), frac = cross
                out.append((out[-1][0] + frac * (hour - out[-1][0]), c_lat, c_lon, np.nan))
                return out
        out.append((hour, lat_m, lon_m, float(np.mean(hpa)) if hpa else np.nan))
    return out


def landfall_probability(coast_lat, coast_lon, tracks):
    """Fraction of *all* members (not just those making landfall) whose
    landfall point is within LANDFALL_RADIUS_KM of each coast point."""
    landed = np.array([t["landfall"][1:] for t in tracks if t["landfall"]])
    if len(landed) == 0:
        return np.zeros(len(coast_lat))
    d = haversine_km(coast_lat[:, None], coast_lon[:, None], landed[None, :, 0], landed[None, :, 1])
    return (d <= LANDFALL_RADIUS_KM).sum(axis=1) / len(tracks)


# ---------------------------------------------------------------------------
# Basemap layers -- same approach as ../tpw-wm6-ensemble-map.
# ---------------------------------------------------------------------------
def clip_to_map(geom):
    clipped = shapely.segmentize(geom, max_segment_length=0.5).intersection(MAP_CLIP_BOX)
    return None if clipped.is_empty else clipped


def load_land_boundary_lines(path, land):
    """Border lines (admin0 = international, admin1 = state/province)
    clipped to land. Both files carry maritime boundary segments too --
    the US/Canada line runs out through the Strait of Juan de Fuca and
    offshore, and state lines continue a way out to sea -- which drew as
    stray straight lines across the water here."""
    with open(path) as f:
        data = json.load(f)
    land_clip = land.intersection(MAP_CLIP_BOX)
    out = []
    for feat in data["features"]:
        g = clip_to_map(shape(feat["geometry"]))
        if g is None:
            continue
        g = g.intersection(land_clip)
        if not g.is_empty:
            out.append(g)
    return out


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def view_projection(view):
    """The NearsidePerspective projection centered on a (lon0, lon1,
    lat0, lat1) view."""
    return ccrs.NearsidePerspective(central_longitude=(view[0] + view[1]) / 2,
                                    central_latitude=(view[2] + view[3]) / 2,
                                    satellite_height=SATELLITE_HEIGHT_M)


def projected_aspect(view):
    """Width/height of the view's projected bounding box -- what set_extent
    fits into the axes (sampled along all four edges, since parallels bow
    under the perspective projection)."""
    lon0, lon1, lat0, lat1 = view
    n = 40
    edge_lon = np.concatenate([np.linspace(lon0, lon1, n), np.full(n, lon1),
                               np.linspace(lon1, lon0, n), np.full(n, lon0)])
    edge_lat = np.concatenate([np.full(n, lat0), np.linspace(lat0, lat1, n),
                               np.full(n, lat1), np.linspace(lat1, lat0, n)])
    xy = view_projection(view).transform_points(ccrs.PlateCarree(), edge_lon, edge_lat)
    return np.ptp(xy[:, 0]) / np.ptp(xy[:, 1])


def fit_view_extent(pts_lat, pts_lon, label_coast_lon, l_point):
    """A (lon0, lon1, lat0, lat1) view zoomed to this storm, that still
    fills the 4:5 frame edge to edge.

    Starts from the bounding box of everything that has to show -- every
    member track, the highlighted coast, and the "L" -- padded by
    VIEW_PAD_DEG, then:
      - leaves room east of the coast band for the town callouts
        (VIEW_LABEL_FRAC of the view's width) and around the "L" for its
        pressure label and the logo in the bottom-left corner
        (VIEW_L_MARGIN_*_FRAC of the view);
      - holds at least VIEW_MIN_LAT_SPAN_DEG tall, so a storm right at the
        coast doesn't zoom in to street level;
      - widens whichever dimension is short to match the axes' aspect
        ratio, since cartopy otherwise leaves gutters.
    Those depend on each other (label room is a fraction of the final
    width), so it iterates to a fixed point."""
    target = (AXES_RECT[2] * FIG_WIDTH_IN) / (AXES_RECT[3] * FIG_HEIGHT_IN)
    lon0, lon1 = min(pts_lon) - VIEW_PAD_DEG, max(pts_lon) + VIEW_PAD_DEG
    lat0, lat1 = min(pts_lat) - VIEW_PAD_DEG, max(pts_lat) + VIEW_PAD_DEG
    if l_point:
        lon0, lat0 = min(lon0, l_point[1] - VIEW_PAD_DEG), min(lat0, l_point[0] - VIEW_PAD_DEG)
    if lat1 - lat0 < VIEW_MIN_LAT_SPAN_DEG:
        mid = (lat0 + lat1) / 2
        lat0, lat1 = mid - VIEW_MIN_LAT_SPAN_DEG / 2, mid + VIEW_MIN_LAT_SPAN_DEG / 2
    for _ in range(50):
        w, h = lon1 - lon0, lat1 - lat0
        changed = False
        if label_coast_lon is not None and lon1 < label_coast_lon + VIEW_LABEL_FRAC * w:
            lon1 = label_coast_lon + VIEW_LABEL_FRAC * w + 1e-6
            changed = True
        if l_point:
            if l_point[1] < lon0 + VIEW_L_MARGIN_LON_FRAC * w:
                lon0 = l_point[1] - VIEW_L_MARGIN_LON_FRAC * w - 1e-6
                changed = True
            if l_point[0] < lat0 + VIEW_L_MARGIN_LAT_FRAC * h:
                lat0 = l_point[0] - VIEW_L_MARGIN_LAT_FRAC * h - 1e-6
                changed = True
        aspect = projected_aspect((lon0, lon1, lat0, lat1))
        if aspect < target * 0.995:
            grow = (lon1 - lon0) * (target / aspect - 1) / 2
            lon0, lon1 = lon0 - grow, lon1 + grow
            changed = True
        elif aspect > target * 1.005:
            grow = (lat1 - lat0) * (aspect / target - 1) / 2
            lat0, lat1 = lat0 - grow, lat1 + grow
            changed = True
        if not changed:
            break
    return (lon0, lon1, lat0, lat1)


def contiguous_runs(values):
    """Index lists of consecutive equal values in a 1-D array."""
    values = np.asarray(values)
    breaks = np.where(values[1:] != values[:-1])[0] + 1
    return [list(r) for r in np.split(np.arange(len(values)), breaks)]


def round_to_hour(dt):
    """Interpolated landfall times aren't good to the minute -- the tracks
    are 3-hourly -- so they're shown to the nearest hour."""
    return (dt + timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0)


def fmt_local(dt_utc, with_day=True):
    local = dt_utc.astimezone(LOCAL_TZ)
    return f"{local.strftime('%a')} {local:%H:%M}" if with_day else f"{local:%H:%M}"


def build_map(lat, lon, mslp, valid_times, meta, output_path, seed_override=None, noaa_lows=None,
              full_domain=False):
    poppins_reg = fm.FontProperties(fname=POPPINS_REG_PATH)
    poppins_med = fm.FontProperties(fname=POPPINS_MED_PATH)
    baloo_bold = fm.FontProperties(fname=BALOO_BOLD_PATH)

    n_members = mslp.shape[1]
    if n_members != N_MEMBERS_EXPECTED:
        print(f"NOTE: {n_members} members in this run (expected {N_MEMBERS_EXPECTED}).")
    t0 = datetime.fromisoformat(valid_times[0].replace("Z", "+00:00"))
    hours = [(datetime.fromisoformat(v.replace("Z", "+00:00")) - t0).total_seconds() / 3600 for v in valid_times]

    def hour_to_utc(h):
        return t0 + timedelta(hours=float(h))

    country_geoms = _load_country_geoms()
    land = unary_union(country_geoms)
    coast = build_outer_coast(land)

    if seed_override:
        seed = (seed_override[0], seed_override[1])
        print(f"Seed (from --seed): {seed[0]:.2f}N {seed[1]:.2f}")
    else:
        s_lat, s_lon, s_hpa = seed_position(lat, lon, mslp[0].mean(axis=0))
        seed = (s_lat, s_lon)
        print(f"Seed (ensemble-mean low at {valid_times[0]}): {s_lat:.2f}N {s_lon:.2f}, {s_hpa:.1f} hPa")

    tracks = [track_member(lat, lon, [mslp[s, k] for s in range(len(hours))], hours, seed, coast)
              for k in range(n_members)]
    for t in tracks:
        t["points"] = smooth_track(t["points"])
    n_landfall = sum(1 for t in tracks if t["landfall"])
    n_tracked = sum(1 for t in tracks if t["points"])
    print(f"Tracked {n_tracked}/{n_members} members; {n_landfall} make landfall.")
    if n_landfall:
        lf_lats = np.array([t["landfall"][1] for t in tracks if t["landfall"]])
        lf_hours = np.array([t["landfall"][0] for t in tracks if t["landfall"]])
        print(f"  landfall lat 10/50/90th pct: {np.percentile(lf_lats, [10, 50, 90]).round(2)}")
        print(f"  landfall time median: {fmt_local(hour_to_utc(np.median(lf_hours)))} PT")

    groups, cluster_desc = cluster_landfalls(tracks)
    print(f"Clustering: {cluster_desc}")
    clustered = len(groups) == 2
    member_color = {}
    for g, members in enumerate(groups):
        for k in members:
            member_color[k] = CLUSTER_COLORS[g] if clustered else TRACK_COLOR
    # Non-landfalling members join no cluster; drawn in the single-track
    # color either way.
    group_means = [mean_track(tracks, members, coast, hours) for members in groups]

    coast_xy = np.asarray(coast.coords)
    coast_lon, coast_lat = coast_xy[:, 0], coast_xy[:, 1]
    prob = landfall_probability(coast_lat, coast_lon, tracks)
    peak = int(np.argmax(prob))
    print(f"Peak landfall-within-{LANDFALL_RADIUS_KM:.0f}km chance: {prob[peak]:.0%} "
          f"at {coast_lat[peak]:.2f}N {coast_lon[peak]:.2f}")

    # "L" -- where NOAA (OPC/WPC) currently analyzes the low, when one of
    # their analyses has a low matching this system (match_noaa_low()).
    # Otherwise, the ensemble mean track's first point far enough inside
    # the frame (L_MARKER_MARGIN_*) to stay clear of the edge and logo,
    # labeled as the WM-6 position.
    def clear_of_edge(lat_, lon_):
        return lon_ >= LON_MIN + L_MARKER_MARGIN_LON_DEG and lat_ >= LAT_MIN + L_MARKER_MARGIN_LAT_DEG

    start_mean = [p for p in mean_track(tracks, list(range(n_members)), coast, hours) if not np.isnan(p[3])]
    l_point = None  # (lat, lon, hpa, valid_utc, source label)
    noaa = match_noaa_low(noaa_lows or [], [(p[0], p[1], p[2]) for p in start_mean], t0)
    if noaa and clear_of_edge(noaa[1], noaa[2]):
        l_point = (noaa[1], noaa[2], noaa[3], noaa[0], f"NOAA {noaa[4]} analysis")
        print(f"L: {noaa[4]} analyzed low {noaa[1]:.1f}N {-noaa[2]:.1f}W {noaa[3]:.0f} mb, "
              f"valid {noaa[0]:%Y-%m-%d %HZ}")
    else:
        if noaa:
            print("NOTE: NOAA-analyzed low is too close to the frame edge/logo to label; using the mean track.")
        else:
            print("NOTE: no current NOAA-analyzed low matches this system; L is on the WM-6 mean track.")
        for h, la, lo, hpa in start_mean:
            if clear_of_edge(la, lo):
                l_point = (la, lo, hpa, hour_to_utc(h), "WM-6 ens. mean")
                break

    # Map view -- zoomed to this storm (fit_view_extent()) unless
    # --full-domain, in which case the fixed LON_MIN..LAT_MAX domain.
    if full_domain:
        view = (LON_MIN, LON_MAX, LAT_MIN, LAT_MAX)
    else:
        shown_coast = 100 * prob > PROB_MIN_SHOWN_PCT
        pts_lat = [p[1] for t in tracks for p in t["points"]] + list(coast_lat[shown_coast])
        pts_lon = [p[2] for t in tracks for p in t["points"]] + list(coast_lon[shown_coast])
        view = fit_view_extent(pts_lat, pts_lon, coast_lon[shown_coast].max() if shown_coast.any() else None,
                               l_point)
    print(f"View: {view[0]:.1f} to {view[1]:.1f}E, {view[2]:.1f} to {view[3]:.1f}N")

    # ---- Figure ----
    # NearsidePerspective -- the same "satellite view" projection as
    # ../columbia-basin-lightning-map, centered on this domain. The frame
    # is still a rectangle (set_extent fits the projected bounding box of
    # the lon/lat extent), so the ocean is the axes background and the land
    # fill is clipped to the generously padded MAP_CLIP_BOX to reach its
    # corners.
    pc = ccrs.PlateCarree()
    proj = view_projection(view)
    fig = plt.figure(figsize=(FIG_WIDTH_IN, FIG_HEIGHT_IN), dpi=FIG_DPI)
    fig.patch.set_facecolor("#f7f6f2")
    ax = fig.add_axes(AXES_RECT, projection=proj)
    ax.set_extent(list(view), crs=pc)
    ax.patch.set_facecolor(OCEAN_COLOR)

    def pts_offset(dx, dy):
        """lon/lat data transform shifted by (dx, dy) points -- label
        offsets in points stay the same on the page whatever the zoom
        (fit_view_extent()), where a degree offset wouldn't."""
        return offset_copy(pc._as_mpl_transform(ax), fig=fig, x=dx, y=dy, units="points")

    fill_geoms = [g for g in (clip_to_map(g) for g in country_geoms) if g is not None]
    outline_geoms = [g for g in (clip_to_map(g.boundary) for g in country_geoms) if g is not None]
    ax.add_geometries(fill_geoms, crs=pc, facecolor=LAND_COLOR, edgecolor="none", zorder=0.5)
    ax.add_geometries(outline_geoms, crs=pc, facecolor="none", edgecolor="#7d8f99", linewidth=0.8, zorder=1.5)
    ax.add_geometries(load_land_boundary_lines(ADMIN1_LINES_FILE, land), crs=pc, facecolor="none",
                      edgecolor="#8a867a", linewidth=0.8, zorder=2)
    ax.add_geometries(load_land_boundary_lines(ADMIN0_LINES_FILE, land), crs=pc, facecolor="none",
                      edgecolor="#5f5b50", linewidth=1.1, zorder=2.5)

    # Member tracks -- thin, translucent, so where many overlap reads
    # darker (the ensemble's consensus corridor) without any extra
    # density layer.
    for k, t in enumerate(tracks):
        if len(t["points"]) < 2:
            continue
        pts = np.array([(p[2], p[1]) for p in t["points"]])
        ax.plot(pts[:, 0], pts[:, 1], color=member_color.get(k, TRACK_COLOR), alpha=MEMBER_TRACK_ALPHA,
                linewidth=0.75, solid_capstyle="round", transform=pc, zorder=3)

    # Landfall-probability coast band, only where the chance clears
    # PROB_MIN_SHOWN_PCT, over a dark underlay so the lightest bin still
    # separates from the land/ocean fills. Drawn as one polyline per run of
    # same-bin coast rather than one tiny segment per coast point: hundreds
    # of ~2 km butt-capped segments left faint antialiasing seams between
    # them that read as hatching across the band.
    prob_pct = 100 * prob
    bin_idx = np.digitize(prob_pct, PROB_BOUNDS) - 1  # -1 = below PROB_MIN_SHOWN_PCT
    shown = prob_pct > PROB_MIN_SHOWN_PCT
    for run in contiguous_runs(shown):
        if shown[run[0]] and len(run) > 1:
            ax.plot(coast_lon[run], coast_lat[run], color="#2b2a26", linewidth=8.2,
                    solid_capstyle="round", solid_joinstyle="round", transform=pc, zorder=4)
    for run in contiguous_runs(np.where(shown, bin_idx, -1)):
        b = bin_idx[run[0]] if shown[run[0]] else -1
        if b < 0:
            continue
        # Extend each run one point into its neighbor on both sides so
        # adjacent color runs meet with no gap.
        ext = list(range(max(run[0] - 1, 0), min(run[-1] + 2, len(coast_lat))))
        ax.plot(coast_lon[ext], coast_lat[ext], color=PROB_COLORS[min(b, len(PROB_COLORS) - 1)],
                linewidth=6.4, solid_capstyle="butt", solid_joinstyle="round", transform=pc, zorder=4.1)


    # Mean track(s) -- white-haloed, dotted every 6 h with a time label
    # every 12 h, ending in a ringed landfall marker.
    halo = [pe.withStroke(linewidth=4.2, foreground="white")]
    for g, mt in enumerate(group_means):
        if len(mt) < 2:
            continue
        color = CLUSTER_COLORS[g] if clustered else "#0d2f5e"
        arr = np.array([(p[2], p[1]) for p in mt])
        ax.plot(arr[:, 0], arr[:, 1], color=color, linewidth=2.6, solid_capstyle="round",
                path_effects=halo, transform=pc, zorder=5)
        for i, (h, la, lo, _) in enumerate(mt[:-1]):
            valid = hour_to_utc(h)
            if valid.hour % 6:
                continue
            ax.plot(lo, la, "o", color=color, markersize=4.5, markeredgecolor="white",
                    markeredgewidth=1.0, transform=pc, zorder=5.5)
            # Skip a time label that would land on top of the landfall
            # marker's or the "L" marker's own label.
            near_landfall = haversine_km(la, lo, mt[-1][1], mt[-1][2]) < 200
            near_l = l_point is not None and haversine_km(la, lo, l_point[0], l_point[1]) < 150
            if valid.hour % 12 == 0 and i > 0 and not near_landfall and not near_l:
                ax.text(lo, la, fmt_local(valid), fontsize=7.5, fontproperties=poppins_med,
                        color="#2b2a26", ha="center", va="bottom", transform=pts_offset(0, 8), zorder=6,
                        path_effects=[pe.withStroke(linewidth=2.2, foreground="white")])
        h_lf, la_lf, lo_lf, hpa_lf = mt[-1]
        if not np.isnan(hpa_lf):  # mean track never reached the coast
            continue
        ax.plot(lo_lf, la_lf, "o", color="white", markersize=11, markeredgecolor=color,
                markeredgewidth=2.4, transform=pc, zorder=6)
        ax.text(lo_lf, la_lf, f"Landfall\n~{fmt_local(round_to_hour(hour_to_utc(h_lf)))}",
                fontsize=8, fontproperties=poppins_med, color=color, ha="right", va="center",
                linespacing=1.1, transform=pts_offset(-12, 0), zorder=6.5,
                path_effects=[pe.withStroke(linewidth=2.4, foreground="white")])

    if l_point:
        la0, lo0, hpa0, valid0, source0 = l_point
        ax.text(lo0, la0, "L", fontsize=L_MARKER_FONTSIZE, fontproperties=baloo_bold, color="#c0392b",
                ha="center", va="center", transform=pc, zorder=7,
                path_effects=[pe.withStroke(linewidth=2.0, foreground="white")])
        # Central pressure only, just below the letter, the way surface
        # analyses label a low. (The source and time are in the console
        # output and, for a NOAA position, the footer credit.)
        # Offset in points (not degrees) so the gap under the letter is
        # the same whatever the map's scale.
        ax.text(lo0, la0, f"{hpa0:.0f}", fontsize=L_PRESSURE_FONTSIZE,
                fontproperties=poppins_med, color="#c0392b", ha="center", va="top",
                transform=pts_offset(0, -L_PRESSURE_OFFSET_PT),
                zorder=7, path_effects=[pe.withStroke(linewidth=2.6, foreground="white")])

    # Town callouts -- on the land side of the band.
    for name, t_lat, t_lon in COAST_TOWNS:
        if not (view[2] < t_lat < view[3] and view[0] < t_lon < view[1]):
            continue
        i = int(np.argmin(haversine_km(t_lat, t_lon, coast_lat, coast_lon)))
        if prob[i] * 100 <= PROB_MIN_SHOWN_PCT:
            continue
        ax.plot(t_lon, t_lat, "o", color="#2b2a26", markersize=2.6, transform=pc, zorder=7)
        # Anchored on whichever is further east, the coast band or the
        # town itself (Astoria sits up the Columbia, east of the band).
        ax.text(max(coast_lon[i], t_lon), t_lat, f"{name}  {prob[i] * 100:.0f}%", fontsize=8,
                fontproperties=poppins_med, color="#2b2a26", ha="left", va="center", transform=pts_offset(9, 0),
                zorder=7, path_effects=[pe.withStroke(linewidth=2.4, foreground=LAND_COLOR)])

    ax.spines["geo"].set_edgecolor("black")
    ax.spines["geo"].set_linewidth(1.6)

    # ---- Legend + colorbar below the map ----
    fig.canvas.draw()
    frame_px = ax.get_window_extent()
    fig_w_px, fig_h_px = FIG_WIDTH_IN * FIG_DPI, FIG_HEIGHT_IN * FIG_DPI
    frame_left, frame_right = frame_px.x0 / fig_w_px, frame_px.x1 / fig_w_px
    frame_bottom = frame_px.y0 / fig_h_px

    n_no_landfall = n_members - n_landfall
    if clustered:
        handles = [Line2D([0], [0], color=CLUSTER_COLORS[g], linewidth=2.6,
                          path_effects=[pe.withStroke(linewidth=4.2, foreground="white")],
                          label=f"{name} cluster mean ({len(groups[g])} members)")
                   for g, name in enumerate(["Northern", "Southern"])]
    else:
        handles = [Line2D([0], [0], color="#0d2f5e", linewidth=2.6, label="Ensemble mean track")]
    handles.insert(0, Line2D([0], [0], color=TRACK_COLOR, alpha=0.6, linewidth=0.9,
                             label=f"{n_members} individual member tracks"))
    leg = fig.legend(handles=handles, loc="center", frameon=False, fontsize=8.5,
                     ncol=2 if len(handles) > 2 else len(handles), prop=poppins_reg, handlelength=2.2, columnspacing=1.6,
                     bbox_to_anchor=((frame_left + frame_right) / 2, frame_bottom - 0.019))
    for text in leg.get_texts():
        text.set_color("#2b2a26")

    cbar_width, cbar_height = (frame_right - frame_left) * 0.62, 0.014
    cbar_left = (frame_left + frame_right) / 2 - cbar_width / 2
    cbar_bottom = frame_bottom - 0.073
    cax = fig.add_axes([cbar_left, cbar_bottom, cbar_width, cbar_height])
    # Equal-width boxes per bin (the 70-100% bin would otherwise swamp the
    # bar), labeled at the bin edges.
    for i, c in enumerate(PROB_COLORS):
        cax.axvspan(i, i + 1, color=c)
    cax.set_xlim(0, len(PROB_COLORS))
    cax.set_yticks([])
    cax.set_xticks(range(len(PROB_BOUNDS)))
    cax.set_xticklabels([f"{b}%" for b in PROB_BOUNDS])
    cax.tick_params(labelsize=8.5, color="#8a887e", labelcolor="#2b2a26", length=3)
    for label in cax.get_xticklabels():
        label.set_fontproperties(poppins_reg)
    for spine in cax.spines.values():
        spine.set_edgecolor("#8a887e")
        spine.set_linewidth(0.6)
    fig.text((frame_left + frame_right) / 2, cbar_bottom + cbar_height + 0.008,
             f"Chance the low's center makes landfall within {LANDFALL_RADIUS_KM:.0f} km",
             fontsize=9, fontproperties=poppins_med, color="#3a3835", ha="center", va="bottom")
    if n_no_landfall == 0:
        offshore_note = f"All {n_members} members' lows reach the coast."
    elif n_no_landfall == 1:
        offshore_note = "1 member's low fills or stays offshore before reaching the coast."
    else:
        offshore_note = f"{n_no_landfall} members' lows fill or stay offshore before reaching the coast."
    fig.text((frame_left + frame_right) / 2, cbar_bottom - 0.027,
             f"Share of all {n_members} members. {offshore_note}", fontsize=7.5, fontproperties=poppins_reg,
             color="#5a584f", ha="center", va="top")

    # ---- Title ----
    init_dt = datetime.fromisoformat(meta["initialization_time"].replace("Z", "+00:00"))
    lf_hours_all = [t["landfall"][0] for t in tracks if t["landfall"]]
    day = hour_to_utc(np.median(lf_hours_all)).astimezone(LOCAL_TZ).strftime("%A") if lf_hours_all else ""
    fig.text(0.03, 0.978, f"{day} Pacific Low: Where Will It Land?".strip(), fontsize=19,
             fontproperties=poppins_reg, color="#2b2a26", ha="left", va="top")
    fig.text(0.03, 0.947, f"WindBorne WM-6 Ensemble • {n_members} Member Surface Low Tracks", fontsize=12.5,
             fontproperties=poppins_med, color="#3a3835", ha="left", va="top")
    fig.text(0.03, 0.922, f"Init {init_dt.strftime('%Y-%m-%d %H')}z • Times Pacific",
             fontsize=10.5, fontproperties=poppins_reg, color="#5a584f", ha="left", va="top")

    credit = "WindBorne WM-6"
    if l_point and l_point[4].startswith("NOAA"):
        credit += f" • Current low: {l_point[4]}"
    fig.text(0.5, 0.012, f"{credit} — Ingalls Weather", fontsize=9,
             fontproperties=poppins_reg, color="#8a887e", ha="center", va="bottom")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, facecolor=fig.get_facecolor(), dpi=FIG_DPI)
    plt.close(fig)
    print(f"Saved base map to {output_path}")

    # ---- Composite logo, bottom-left, snug inside the frame ----
    if LOGO_FILE.exists():
        base = Image.open(output_path).convert("RGB")
        bw, bh = base.size
        f_left = int(round(frame_px.x0))
        f_bottom = int(round(bh - frame_px.y0))
        logo = Image.open(LOGO_FILE).convert("RGB")
        target_w = int(bw * 0.08)
        target_h = int(logo.height * target_w / logo.width)
        logo_resized = logo.resize((target_w, target_h), Image.LANCZOS)
        pos = (f_left + MAP_FRAME_INSET_PX, f_bottom - MAP_FRAME_INSET_PX - target_h)
        base.paste(logo_resized, pos)
        base.save(output_path)
        print(f"Composited logo at {pos}")
    else:
        print(f"NOTE: logo not found at {LOGO_FILE}, skipping (map saved without logo).")


def parse_utc(s):
    return datetime.strptime(s, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build an Ingalls Weather WM-6 ensemble surface-low landfall map.")
    parser.add_argument("--start", type=str, default=None,
                        help="Track start, UTC, YYYY-MM-DDTHH (default: the current 3-hourly step).")
    parser.add_argument("--end", type=str, default=None,
                        help=f"Track end, UTC, YYYY-MM-DDTHH (default: {DEFAULT_WINDOW_HOURS} h after --start).")
    parser.add_argument("--seed", type=float, nargs=2, metavar=("LAT", "LON"), default=None,
                        help="Start the tracks from this position instead of the deepest "
                             "ensemble-mean low in SEED_BOX.")
    parser.add_argument("--full-domain", action="store_true",
                        help="Show the whole fixed LON_MIN..LAT_MAX domain instead of zooming to the storm.")
    parser.add_argument("--no-noaa", action="store_true",
                        help="Don't look up NOAA's (OPC/WPC) analyzed low position for the L marker.")
    parser.add_argument("--file", type=Path, default=None,
                        help="Render from a saved snapshot (.npz) instead of fetching live.")
    parser.add_argument("--out", type=Path, default=None,
                        help="Output PNG path (default: output/pnw_low_landfall_<init>.png).")
    args = parser.parse_args()

    if args.file:
        if not args.file.exists():
            sys.exit(f"--file {args.file} not found.")
        print(f"Using local snapshot: {args.file}")
        npz = np.load(args.file, allow_pickle=True)
        lat, lon = npz["lat"], npz["lon"]
        mslp = npz["mslp_offset"].astype(np.float32) / 100.0 + 900.0
        valid_times, meta = list(npz["valid_times"]), npz["meta"].item()
    else:
        api_key = os.environ.get("WB_API_KEY")
        if not api_key:
            sys.exit("WB_API_KEY not set -- get a token at "
                     "https://app.windbornesystems.com/api_tokens, or pass --file "
                     "to render from a saved snapshot instead.")
        lat, lon, mslp, valid_times, meta = fetch_all(parse_utc(args.start) if args.start else None,
                                                       parse_utc(args.end) if args.end else None, api_key)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        init_tag = meta["initialization_time"][:13].replace("-", "").replace("T", "_")
        # Stored as int16 hundredths of a hPa above 900 hPa -- exact to the
        # field's own quantization, a quarter the size of float32.
        np.savez_compressed(OUTPUT_DIR / f"snapshot_{init_tag}.npz", lat=lat, lon=lon,
                            mslp_offset=np.round((mslp - 900.0) * 100).astype(np.int16),
                            valid_times=np.array(valid_times), meta=meta)

    init_tag = meta["initialization_time"][:13].replace("-", "").replace("T", "_")
    out_path = args.out or (OUTPUT_DIR / f"pnw_low_landfall_{init_tag}.png")
    noaa_lows = None
    if not args.no_noaa:
        print("Reading NOAA analyzed lows for the L marker...")
        noaa_lows = fetch_noaa_lows()
    build_map(lat, lon, mslp, valid_times, meta, out_path, seed_override=args.seed, noaa_lows=noaa_lows,
              full_domain=args.full_domain)

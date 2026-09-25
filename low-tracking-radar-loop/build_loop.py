"""
Low-Tracking Radar Loop -- Facebook Reel builder
Ingalls Weather

An animated NEXRAD reflectivity loop (default KLGX / Langley Hill, WA) on
a satellite basemap, where the *camera follows a surface low* instead of
the low sliding across a fixed map. Built for a coastal low making
landfall on the Washington/Oregon coast. Output is a 1080x1920 (9:16)
H.264 MP4 sized for a Facebook Reel, full-bleed (no margin), plus a PNG
of the final frame for use as the reel's cover image.

DATA SOURCES
------------
  Radar: NEXRAD Level II volumes from the Unidata/AWS open-data bucket
    (unidata-nexrad-level2), lowest-tilt super-res reflectivity only.
  Low center: NOAA HRRR hourly analyses (f00) of MSLP (MAPS reduction,
    "MSLMA"), from the NOAA/AWS open-data bucket (noaa-hrrr-bdp-pds).
    Only the MSLMA GRIB message is fetched, via byte range from the .idx.
    Hours past the latest analysis that's posted are filled from the
    latest HRRR run's f01/f02, so the loop can run right up to the newest
    radar scan.
  Basemap: Esri World Imagery tiles.

See README.md for methodology (tracking, smoothing, the camera, clutter
filtering) and usage.
"""

import argparse
import io
import json
import logging
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from multiprocessing import Pool
from zoneinfo import ZoneInfo

import numpy as np
import requests
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
import matplotlib.patches
from matplotlib.colors import LinearSegmentedColormap, Normalize
from PIL import Image
from pyproj import Geod, Transformer
from scipy.interpolate import UnivariateSpline
from scipy.ndimage import gaussian_filter, uniform_filter
from shapely.geometry import Point, shape
from shapely.ops import unary_union
from shapely.prepared import prep

# ---------- fonts ----------
FONT_DIR = "/usr/share/fonts/truetype/google-fonts/"


def _font(name):
    path = FONT_DIR + f"Poppins-{name}.ttf"
    if os.path.exists(path):
        return fm.FontProperties(fname=path)
    return fm.FontProperties(family="Montserrat", weight=name.lower())


f_bold = _font("Bold")
f_semi = _font("SemiBold")
f_med = _font("Medium")
f_reg = _font("Regular")

HERE = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(HERE, "output")
CACHE_DIR = os.path.join(OUTPUT_DIR, "cache")
LOGO_PATH = os.path.join(HERE, "..", "assets", "ingalls_weather_logo.png")
MAPS_DIR = os.path.join(HERE, "..", "maps")

LOCAL_TZ = ZoneInfo("America/Los_Angeles")

# ---------- frame ----------
# Facebook Reel: 1080x1920, 9:16, full-bleed.
FRAME_W, FRAME_H = 1080, 1920
DPI = 200
# Width of the view in true (ground) km. Height follows from 9:16. 300 km
# is wide enough to show the low's whole comma head and the coast around
# it, tight enough that the lowest tilt's super-res detail still reads.
VIEW_KM = 300
# Where the low sits vertically, as a fraction of the frame from the top.
# A bit above center, since the bottom ~35% of a reel is covered by the
# caption/username overlay.
LOW_SCREEN_Y = 0.46

# Facebook's reel UI covers roughly the top 14% and bottom 35% of the
# frame -- all text/overlays sit between them.
SAFE_TOP = 0.14
# Bottom of the title/legend block (fraction of frame height from the
# bottom); town labels fade out as they scroll up into it.
HEADER_BOTTOM = 0.69

# ---------- radar ----------
S3_RADAR = "https://unidata-nexrad-level2.s3.amazonaws.com"
# Gates with correlation coefficient under this are non-meteorological
# (sea/ground clutter, birds/bugs, AP) and get dropped. Rain sits at 0.95+;
# 0.85 (on smoothed CC, see load_sweep) leaves a margin for melting-layer and low-SNR gates.
RHO_MIN = 0.85
RHO_WINDOW = (3, 7)  # radials x gates
DBZ_MIN = 12.0
SPECKLE_MIN_NEIGHBORS = 4
# Only include scans while the low is within this range of the radar --
# past this the lowest tilt overshoots most of the precip shield and the
# frame shows mostly the edge of coverage.
MAX_LOW_RANGE_KM = 330

# TV-style continuous reflectivity palette (dBZ, hex, alpha). Weak echoes
# fade in semi-transparent so they don't wall off the satellite imagery.
REF_STOPS = [
    (12, "#7be08a", 0.35),
    (18, "#3ccb4a", 0.70),
    (25, "#17a534", 0.82),
    (31, "#0c7a26", 0.86),
    (35, "#f4e21a", 0.90),
    (40, "#f7a41d", 0.92),
    (45, "#ef5a1b", 0.94),
    (50, "#c8101e", 0.95),
    (56, "#8e0a3a", 0.95),
    (60, "#e02ad8", 0.95),
    (70, "#ffffff", 0.95),
]
DBZ_MAX = REF_STOPS[-1][0]

# ---------- HRRR ----------
S3_HRRR = "https://noaa-hrrr-bdp-pds.s3.amazonaws.com"
# The MSLMA field is smoothed before searching for the minimum -- raw
# 3 km HRRR MSLP has small-scale noise (esp. terrain-reduced over land
# after landfall) that makes the grid-point minimum jitter around.
MSLP_SMOOTH_SIGMA = 4  # grid points (~12 km)
# Search radius around the persistence-extrapolated previous position.
TRACK_SEARCH_KM = 120
# Initial search radius around the radar for the first hour, if no --seed.
SEED_SEARCH_KM = 600
# Positional noise (deg) the track spline is allowed to smooth out.
TRACK_SMOOTH_DEG = 0.06
# Crop box for cached MSLP (keeps the cache small).
HRRR_CROP = (38.0, 54.0, -136.0, -115.0)  # lat0, lat1, lon0, lon1

# ---------- basemap ----------
ESRI_URL = ("https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}")
TILE_ZOOM = 10
# Satellite imagery is darkened a touch so the radar colors pop.
SAT_BRIGHTNESS = 0.78

# ---------- towns ----------
# (name, lat, lon, side) -- side is where the label goes relative to the dot.
TOWNS = [
    ("Forks", 47.9504, -124.3855, "right"),
    ("Taholah", 47.3418, -124.2896, "left"),
    ("Ocean Shores", 46.9737, -124.1563, "left"),
    ("Aberdeen", 46.9754, -123.8157, "right"),
    ("Westport", 46.8901, -124.1040, "left"),
    ("Olympia", 47.0379, -122.9007, "right"),
    ("Raymond", 46.6865, -123.7329, "right"),
    ("Long Beach", 46.3523, -124.0543, "left"),
    ("Astoria", 46.1879, -123.8313, "right"),
    ("Longview", 46.1382, -122.9382, "right"),
    ("Seaside", 45.9932, -123.9226, "right"),
    ("Tillamook", 45.4562, -123.8440, "right"),
    ("Lincoln City", 44.9582, -124.0179, "right"),
    ("Newport", 44.6368, -124.0535, "right"),
    ("Portland", 45.5152, -122.6784, "right"),
]

geod = Geod(ellps="WGS84")
to_merc = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
from_merc = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
MERC_HALF = 20037508.342789244


def log(msg):
    print(msg, flush=True)


def get(url, **kw):
    for attempt in range(4):
        try:
            r = requests.get(url, timeout=60, **kw)
            if r.status_code in (200, 206):
                return r
            if r.status_code in (403, 404):
                return None
        except requests.RequestException:
            pass
    return None


# =====================================================================
# Radar
# =====================================================================

def list_scans(site, start, end):
    """Level II volume keys for `site` with start in [start, end]."""
    scans = []
    day = start.date()
    while day <= end.date():
        prefix = f"{day:%Y/%m/%d}/{site}/"
        token = None
        while True:
            params = {"list-type": "2", "prefix": prefix}
            if token:
                params["continuation-token"] = token
            r = get(S3_RADAR + "/", params=params)
            if r is None:
                break
            text = r.text
            for key in _xml_all(text, "Key"):
                name = key.rsplit("/", 1)[-1]
                if name.endswith("_MDM") or not name.startswith(site):
                    continue
                try:
                    t = datetime.strptime(name[4:19], "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                if start <= t <= end:
                    scans.append((t, key))
            token = next(iter(_xml_all(text, "NextContinuationToken")), None)
            if not token:
                break
        day += timedelta(days=1)
    return sorted(scans)


def _xml_all(text, tag):
    out, i = [], 0
    open_t, close_t = f"<{tag}>", f"</{tag}>"
    while True:
        a = text.find(open_t, i)
        if a < 0:
            return out
        b = text.find(close_t, a)
        out.append(text[a + len(open_t):b])
        i = b


def fetch_sweep(key):
    """Download one volume and cache its lowest-tilt REF (+RHO) as .npz."""
    name = key.rsplit("/", 1)[-1]
    cache = os.path.join(CACHE_DIR, f"{name}.npz")
    if os.path.exists(cache):
        return cache
    logging.getLogger("metpy").setLevel(logging.ERROR)
    from metpy.io import Level2File

    r = get(f"{S3_RADAR}/{key}")
    if r is None:
        return None
    try:
        f = Level2File(io.BytesIO(r.content))
    except Exception as e:  # truncated/partial upload
        print(f"  skip {name}: {e}", flush=True)
        return None
    sweep = f.sweeps[0]
    ref_hdr = sweep[0][4][b"REF"][0]
    ngates = ref_hdr.num_gates
    az = np.array([ray[0].az_angle for ray in sweep], dtype=np.float32)
    ref = np.full((len(sweep), ngates), np.nan, dtype=np.float32)
    rho = np.full((len(sweep), ngates), np.nan, dtype=np.float32)
    for i, ray in enumerate(sweep):
        d = ray[4][b"REF"][1]
        ref[i, :len(d)] = d
        if b"RHO" in ray[4]:
            d = ray[4][b"RHO"][1]
            rho[i, :len(d)] = d
    vol = sweep[0][1]
    t = f.dt.replace(tzinfo=timezone.utc)
    np.savez_compressed(
        cache, az=az, ref=ref.astype(np.float16), rho=rho.astype(np.float16),
        first_gate=ref_hdr.first_gate, gate_width=ref_hdr.gate_width,
        lat=vol.lat, lon=vol.lon, time=t.isoformat(),
        elev=sweep[0][0].el_angle)
    return cache


def load_sweep(path):
    d = np.load(path)
    ref = d["ref"].astype(np.float32)
    rho = d["rho"].astype(np.float32)
    # Drop non-met echo (low CC). CC is averaged over a small polar window
    # first -- per-gate CC is noisy in light rain, and masking on it raw
    # punches pinholes all through real echo. Where CC wasn't recorded
    # (past its shorter range), keep the gate.
    has = np.isfinite(rho)
    w = uniform_filter(has.astype(np.float32), size=RHO_WINDOW, mode=("wrap", "constant"))
    rs = uniform_filter(np.where(has, rho, 0), size=RHO_WINDOW, mode=("wrap", "constant"))
    rho_s = np.where(w > 0.2, rs / np.maximum(w, 1e-6), np.nan)
    ref[(rho_s < RHO_MIN) & np.isfinite(rho_s)] = np.nan
    ref[ref < DBZ_MIN] = np.nan
    # Speckle filter: drop gates with fewer than SPECKLE_MIN_NEIGHBORS of
    # their 8 neighbors (az wraps) also carrying echo.
    valid = np.isfinite(ref).astype(np.float32)
    neigh = uniform_filter(valid, size=3, mode=("wrap", "constant")) * 9 - valid
    ref[(valid > 0) & (neigh < SPECKLE_MIN_NEIGHBORS - 0.01)] = np.nan
    return dict(az=d["az"], ref=ref, first_gate=float(d["first_gate"]),
                gate_width=float(d["gate_width"]), lat=float(d["lat"]),
                lon=float(d["lon"]), time=datetime.fromisoformat(str(d["time"])),
                elev=float(d["elev"]))


# =====================================================================
# HRRR low tracking
# =====================================================================

def hrrr_mslp(run, fhr):
    """(lat, lon, mslp_hPa) cropped to HRRR_CROP, or None if not posted."""
    tag = f"hrrr_{run:%Y%m%d%H}_f{fhr:02d}_mslma"
    cache = os.path.join(CACHE_DIR, tag + ".npz")
    if os.path.exists(cache):
        d = np.load(cache)
        return d["lat"], d["lon"], d["p"]
    url = f"{S3_HRRR}/hrrr.{run:%Y%m%d}/conus/hrrr.t{run:%H}z.wrfsfcf{fhr:02d}.grib2"
    r = get(url + ".idx")
    if r is None:
        return None
    lines = r.text.splitlines()
    rng = None
    for i, line in enumerate(lines):
        if ":MSLMA:" in line and i + 1 < len(lines):
            rng = (int(line.split(":")[1]), int(lines[i + 1].split(":")[1]) - 1)
    if rng is None:
        return None
    r = get(url, headers={"Range": f"bytes={rng[0]}-{rng[1]}"})
    if r is None:
        return None
    import pygrib
    tmp = cache + ".grib2"
    with open(tmp, "wb") as fh:
        fh.write(r.content)
    try:
        grb = pygrib.open(tmp).read(1)[0]
        p = grb.values / 100.0
        lat, lon = grb.latlons()
    except Exception:
        return None
    finally:
        os.remove(tmp)
    lat0, lat1, lon0, lon1 = HRRR_CROP
    m = (lat >= lat0) & (lat <= lat1) & (lon >= lon0) & (lon <= lon1)
    rows = np.where(m.any(axis=1))[0]
    cols = np.where(m.any(axis=0))[0]
    sl = (slice(rows[0], rows[-1] + 1), slice(cols[0], cols[-1] + 1))
    lat, lon, p = lat[sl].astype(np.float32), lon[sl].astype(np.float32), p[sl].astype(np.float32)
    np.savez_compressed(cache, lat=lat, lon=lon, p=p)
    return lat, lon, p


def hrrr_fields(start, end):
    """Hourly MSLP fields covering [start, end]: analyses where posted,
    then the latest run's short-range forecasts to fill the rest."""
    fields = []
    t = start.replace(minute=0, second=0, microsecond=0)
    last_run = None
    while t <= end + timedelta(hours=1):
        f = hrrr_mslp(t, 0)
        if f is None:
            break
        fields.append((t, f, "analysis"))
        last_run = t
        t += timedelta(hours=1)
    if last_run is not None:
        fhr = 1
        while t <= end + timedelta(hours=1) and fhr <= 6:
            f = hrrr_mslp(last_run, fhr)
            if f is None:
                break
            fields.append((t, f, f"{last_run:%H}Z f{fhr:02d}"))
            t += timedelta(hours=1)
            fhr += 1
    return fields


def track_low(fields, radar_lat, radar_lon, seed=None):
    """Follow the MSLP minimum hour to hour. Returns list of
    (time, lat, lon, p_min)."""
    track = []
    for t, (lat, lon, p), src in fields:
        ps = gaussian_filter(p, MSLP_SMOOTH_SIGMA, mode="nearest")
        if track:
            # Persistence guess: previous position + last hour's motion.
            if len(track) >= 2:
                glat = 2 * track[-1][1] - track[-2][1]
                glon = 2 * track[-1][2] - track[-2][2]
            else:
                glat, glon = track[-1][1], track[-1][2]
            radius = TRACK_SEARCH_KM
        elif seed:
            glat, glon = seed
            radius = TRACK_SEARCH_KM * 2
        else:
            glat, glon = radar_lat, radar_lon
            radius = SEED_SEARCH_KM
        _, _, dist = geod.inv(np.full(lat.shape, glon), np.full(lat.shape, glat), lon, lat)
        cand = np.where(dist <= radius * 1000, ps, np.inf)
        k = np.unravel_index(np.argmin(cand), cand.shape)
        # Sub-grid refinement: pressure-weighted centroid of the smoothed
        # field's lowest ~0.3 hPa around the minimum.
        pmin = ps[k]
        near = (dist <= radius * 1000) & (ps <= pmin + 0.3)
        _, _, dk = geod.inv(np.full(lat.shape, lon[k]), np.full(lat.shape, lat[k]), lon, lat)
        near &= dk <= 40_000
        w = (pmin + 0.3 - ps[near]) + 1e-3
        clat = float(np.sum(lat[near] * w) / w.sum())
        clon = float(np.sum(lon[near] * w) / w.sum())
        # Report the raw (unsmoothed) central pressure near the center.
        core = dk <= 25_000
        p_center = float(p[core].min())
        track.append((t, clat, clon, p_center))
        log(f"  {t:%H}Z ({src:>9}): {clat:.2f}N {-clon:.2f}W  {p_center:.1f} hPa")
    return track


class SmoothTrack:
    """Smoothing splines through the hourly track, for a camera path with
    no hour-to-hour jitter."""

    def __init__(self, track):
        self.t0 = track[0][0]
        h = np.array([(t - self.t0).total_seconds() / 3600 for t, *_ in track])
        lat = np.array([x[1] for x in track])
        lon = np.array([x[2] for x in track])
        p = np.array([x[3] for x in track])
        k = min(3, len(h) - 1)
        s = len(h) * TRACK_SMOOTH_DEG ** 2
        self.lat = UnivariateSpline(h, lat, k=k, s=s)
        self.lon = UnivariateSpline(h, lon, k=k, s=s)
        self.h, self.p = h, p
        self.start = track[0][0]
        self.end = track[-1][0]

    def at(self, t):
        h = (t - self.t0).total_seconds() / 3600
        return float(self.lat(h)), float(self.lon(h)), float(np.interp(h, self.h, self.p))


# =====================================================================
# Basemap
# =====================================================================

def fetch_satellite(x0, x1, y0, y1):
    """Esri World Imagery mosaic covering the mercator box, at TILE_ZOOM.
    Returns (rgb uint8, extent [x0, x1, y0, y1])."""
    z = TILE_ZOOM
    n = 2 ** z
    tile_m = 2 * MERC_HALF / n
    tx0 = int((x0 + MERC_HALF) // tile_m)
    tx1 = int((x1 + MERC_HALF) // tile_m)
    ty0 = int((MERC_HALF - y1) // tile_m)
    ty1 = int((MERC_HALF - y0) // tile_m)
    tile_dir = os.path.join(CACHE_DIR, "tiles", str(z))
    os.makedirs(tile_dir, exist_ok=True)

    def one(xy):
        tx, ty = xy
        path = os.path.join(tile_dir, f"{tx}_{ty}.jpg")
        if not os.path.exists(path):
            r = get(ESRI_URL.format(z=z, x=tx, y=ty))
            if r is None:
                return xy, None
            with open(path, "wb") as fh:
                fh.write(r.content)
        return xy, Image.open(path).convert("RGB")

    xs, ys = range(tx0, tx1 + 1), range(ty0, ty1 + 1)
    mosaic = Image.new("RGB", (256 * len(xs), 256 * len(ys)))
    log(f"  {len(xs) * len(ys)} tiles at zoom {z}")
    with ThreadPoolExecutor(16) as ex:
        for (tx, ty), im in ex.map(one, [(x, y) for x in xs for y in ys]):
            if im is not None:
                mosaic.paste(im, (256 * (tx - tx0), 256 * (ty - ty0)))
    ext = [-MERC_HALF + tx0 * tile_m, -MERC_HALF + (tx1 + 1) * tile_m,
           MERC_HALF - (ty1 + 1) * tile_m, MERC_HALF - ty0 * tile_m]
    return mosaic, ext


def build_grid(x0, x1, y0, y1, res):
    """Pixel-center coordinates of a north-up mercator grid at `res` m/px."""
    nx = int(np.ceil((x1 - x0) / res))
    ny = int(np.ceil((y1 - y0) / res))
    xs = x0 + (np.arange(nx) + 0.5) * res
    ys = y1 - (np.arange(ny) + 0.5) * res  # row 0 = north
    return xs, ys


# =====================================================================
# Main
# =====================================================================

def parse_time(s, default):
    if not s:
        return default
    t = datetime.fromisoformat(s)
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(timezone.utc)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--site", default="KLGX")
    ap.add_argument("--start", help="ISO time (UTC unless offset given). "
                    "Default: local midnight today (Pacific).")
    ap.add_argument("--end", help="ISO time. Default: now (newest scan).")
    ap.add_argument("--seed", help="LAT,LON first guess for the low center "
                    "(default: deepest MSLP within 600 km of the radar)")
    ap.add_argument("--view-km", type=float, default=VIEW_KM)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--frames-per-scan", type=int, default=4,
                    help="output frames each radar scan is on screen; the "
                    "camera glides between scans (default 4 at 30 fps)")
    ap.add_argument("--hold", type=float, default=2.0,
                    help="seconds to hold the final frame")
    ap.add_argument("--title", default="Low Pressure Makes Landfall")
    ap.add_argument("--max-frames", type=int, help="debug: render only N scans")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 4)
    args = ap.parse_args()

    os.makedirs(CACHE_DIR, exist_ok=True)
    now = datetime.now(timezone.utc)
    local_midnight = datetime.now(LOCAL_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    start = parse_time(args.start, local_midnight.astimezone(timezone.utc))
    end = parse_time(args.end, now)
    site = args.site.upper()

    # ---- radar scan list ----
    log(f"Listing {site} scans {start:%Y-%m-%d %H:%M} - {end:%H:%M} UTC ...")
    scans = list_scans(site, start, end)
    if not scans:
        sys.exit("No radar scans found in window.")
    log(f"  {len(scans)} volumes")

    # One volume first, for the radar's location.
    first = fetch_sweep(scans[0][1])
    s0 = load_sweep(first)
    rlat, rlon = s0["lat"], s0["lon"]

    # ---- track the low ----
    log("Tracking the low in HRRR MSLP ...")
    fields = hrrr_fields(start - timedelta(hours=1), scans[-1][0])
    if len(fields) < 2:
        sys.exit("Not enough HRRR hours posted to track the low.")
    seed = tuple(float(v) for v in args.seed.split(",")) if args.seed else None
    track = track_low(fields, rlat, rlon, seed)
    trk = SmoothTrack(track)

    # Keep scans covered by the track and with the low in radar range.
    keep = []
    for t, key in scans:
        if not (trk.start <= t <= trk.end):
            continue
        la, lo, _ = trk.at(t)
        _, _, d = geod.inv(rlon, rlat, lo, la)
        if d / 1000 <= MAX_LOW_RANGE_KM:
            keep.append((t, key))
    if args.max_frames:
        keep = keep[-args.max_frames:]
    if not keep:
        sys.exit("No scans with the low inside radar range.")
    log(f"  {len(keep)} scans in loop: {keep[0][0]:%H:%M} - {keep[-1][0]:%H:%M} UTC")

    # ---- fetch radar ----
    log("Fetching radar volumes ...")
    with Pool(args.workers) as pool:
        paths = pool.map(fetch_sweep, [k for _, k in keep])
    frames = [(t, p) for (t, _), p in zip(keep, paths) if p]
    log(f"  {len(frames)} sweeps ready")

    # ---- landfall ----
    land = json.load(open(os.path.join(MAPS_DIR, "land_slim.json")))
    land_geom = prep(unary_union([shape(f["geometry"]) for f in land["features"]]))
    landfall = None
    t = frames[0][0]
    was_land = land_geom.contains(Point(trk.at(t)[1], trk.at(t)[0]))
    while t <= frames[-1][0] and not was_land:
        la, lo, _ = trk.at(t)
        if land_geom.contains(Point(lo, la)):
            landfall = t
            break
        t += timedelta(minutes=1)
    if landfall:
        log(f"  landfall ~{landfall.astimezone(LOCAL_TZ):%-I:%M %p %Z}")

    # ---- camera geometry (web mercator) ----
    mid_lat = np.mean([trk.at(t)[0] for t, _ in frames])
    view_w = args.view_km * 1000 / np.cos(np.radians(mid_lat))  # mercator m
    view_h = view_w * FRAME_H / FRAME_W
    res = view_w / FRAME_W  # mercator m per output pixel

    def camera(t):
        la, lo, p = trk.at(t)
        x, y = to_merc.transform(lo, la)
        cy = y - (0.5 - LOW_SCREEN_Y) * view_h  # low above center
        return x, cy, x, y, p

    cams = [camera(t) for t, _ in frames]
    pad = 20 * res
    gx0 = min(c[0] for c in cams) - view_w / 2 - pad
    gx1 = max(c[0] for c in cams) + view_w / 2 + pad
    gy0 = min(c[1] for c in cams) - view_h / 2 - pad
    gy1 = max(c[1] for c in cams) + view_h / 2 + pad
    xs, ys = build_grid(gx0, gx1, gy0, gy1, res)
    log(f"Grid {len(xs)}x{len(ys)} px at {res:.0f} m/px (mercator)")

    # ---- basemap onto the grid ----
    log("Fetching satellite basemap ...")
    mosaic, mext = fetch_satellite(gx0, gx1, gy0, gy1)
    mres = (mext[1] - mext[0]) / mosaic.width
    crop = mosaic.crop((int((xs[0] - res / 2 - mext[0]) / mres),
                        int((mext[3] - (ys[0] + res / 2)) / mres),
                        int(np.ceil((xs[-1] + res / 2 - mext[0]) / mres)),
                        int(np.ceil((mext[3] - (ys[-1] - res / 2)) / mres))))
    sat = np.asarray(crop.resize((len(xs), len(ys)), Image.LANCZOS), dtype=np.float32) / 255
    sat *= SAT_BRIGHTNESS

    # ---- per-pixel radar polar coordinates (fixed for the whole loop) ----
    log("Computing radar geometry ...")
    XX, YY = np.meshgrid(xs, ys)
    lon_g, lat_g = from_merc.transform(XX, YY)
    az_g, _, dist_g = geod.inv(np.full(lon_g.shape, rlon), np.full(lon_g.shape, rlat), lon_g, lat_g)
    del XX, YY, lon_g, lat_g
    azbin_g = (np.mod(az_g, 360) * 10).astype(np.int16) % 3600
    rng_km = dist_g / 1000
    gate_g = np.round((rng_km - s0["first_gate"]) / s0["gate_width"]).astype(np.int32)
    del az_g, dist_g, rng_km

    cmap = LinearSegmentedColormap.from_list(
        "ref", [((d - DBZ_MIN) / (DBZ_MAX - DBZ_MIN),
                 (*matplotlib.colors.to_rgb(c), a)) for d, c, a in REF_STOPS])
    norm = Normalize(DBZ_MIN, DBZ_MAX)

    def composite(sw):
        """Sweep -> RGB image on the grid (radar over satellite)."""
        az = sw["az"]
        order = np.argsort(az)
        az_sorted = az[order]
        centers = (np.arange(3600) + 0.5) / 10
        j = np.searchsorted(az_sorted, centers) % len(az_sorted)
        jm = (j - 1) % len(az_sorted)
        dj = np.abs(((az_sorted[j] - centers) + 180) % 360 - 180)
        djm = np.abs(((az_sorted[jm] - centers) + 180) % 360 - 180)
        table = np.where(dj < djm, order[j], order[jm])
        ref = sw["ref"]
        g = gate_g
        ok = (g >= 0) & (g < ref.shape[1])
        vals = np.full(g.shape, np.nan, dtype=np.float32)
        vals[ok] = ref[table[azbin_g[ok]], g[ok]]
        rgba = cmap(norm(vals))
        rgba[np.isnan(vals)] = 0
        a = rgba[..., 3:4]
        return sat * (1 - a) + rgba[..., :3] * a

    # ---- figure ----
    fig = plt.figure(figsize=(FRAME_W / DPI, FRAME_H / DPI), dpi=DPI)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    img = ax.imshow(sat, extent=[xs[0] - res / 2, xs[-1] + res / 2,
                                 ys[-1] - res / 2, ys[0] + res / 2],
                    interpolation="bilinear", zorder=1)

    # Towns
    # Each label is (artists, label-center x, y) so it can fade out as it
    # scrolls under the header block or the L (see fade_labels below).
    halo = [pe.withStroke(linewidth=2.4, foreground="#101418")]
    labels = []
    for name, la, lo, side in TOWNS:
        x, y = to_merc.transform(lo, la)
        dot, = ax.plot(x, y, "o", ms=4.2, mfc="white", mec="#101418", mew=0.9, zorder=5)
        sign = 1 if side == "right" else -1
        txt = ax.text(x + sign * 7 * res, y, name, ha="left" if side == "right" else "right",
                      va="center", fontproperties=f_med, fontsize=10.5, color="white",
                      path_effects=halo, zorder=6, clip_on=True)
        labels.append(([dot, txt], x + sign * (7 + 8 * len(name)) * res, y))
    # Radar site
    x, y = to_merc.transform(rlon, rlat)
    dot, = ax.plot(x, y, "^", ms=6.5, mfc="#ffd84d", mec="#101418", mew=0.9, zorder=5)
    txt = ax.text(x + 8 * res, y - 16 * res, site, ha="left", va="center",
                  fontproperties=f_semi, fontsize=8.5, color="#ffd84d",
                  path_effects=halo, zorder=6, clip_on=True)
    labels.append(([dot, txt], x + 30 * res, y - 8 * res))

    def fade_labels(cy, lx, ly):
        for artists, x, y in labels:
            fy = (y - (cy - view_h / 2)) / view_h  # 0 bottom .. 1 top
            a_head = np.clip((HEADER_BOTTOM - fy) / 0.02, 0, 1)
            d_px = np.hypot((x - lx) / res, (y - ly) / res)
            a_low = np.clip((d_px - 60) / 40, 0, 1)
            a = float(min(a_head, a_low))
            for art in artists:
                art.set_alpha(a)
                art.set_visible(a > 0)

    # Past track + low center marker
    trail, = ax.plot([], [], color="white", lw=1.6, alpha=0.8, ls=(0, (4, 3)),
                     zorder=7, solid_capstyle="round")
    trail.set_path_effects([pe.withStroke(linewidth=3.2, foreground="#101418", alpha=0.45)])
    low_L = ax.text(0, 0, "L", ha="center", va="center", fontproperties=f_bold,
                    fontsize=40, color="#e3262d", zorder=9,
                    path_effects=[pe.withStroke(linewidth=4, foreground="white")])
    low_p = ax.text(0, 0, "", ha="center", va="top", fontproperties=f_bold,
                    fontsize=13, color="white", zorder=9,
                    path_effects=[pe.withStroke(linewidth=3, foreground="#101418")])

    # Top scrim (gradient) so the title reads over any imagery.
    scrim_ax = fig.add_axes([0, 0.62, 1, 0.38], zorder=10)
    grad = np.clip(np.linspace(-0.1, 1.4, 256), 0, 1)[:, None] ** 1.2
    scrim = np.zeros((256, 1, 4))
    scrim[..., 3] = 0.72 * grad
    scrim_ax.imshow(scrim, aspect="auto", extent=[0, 1, 0, 1], origin="lower")
    scrim_ax.set_axis_off()

    left = 0.055
    top = 1 - SAFE_TOP
    fig.text(left, top, args.title.upper(), fontproperties=f_bold, fontsize=19,
             color="white", va="top", zorder=11)
    t_text = fig.text(left, top - 0.037, "", fontproperties=f_semi, fontsize=13,
                      color="white", va="top", zorder=11)
    fig.text(left, top - 0.063, f"{site} radar · lowest tilt reflectivity",
             fontproperties=f_reg, fontsize=9.5, color="#d9dde2", va="top", zorder=11)

    # Color bar (dBZ)
    cb_ax = fig.add_axes([left, top - 0.094, 0.52, 0.008], zorder=11)
    cb_rgba = cmap(norm(np.linspace(DBZ_MIN, DBZ_MAX, 256)[None, :]))
    cb_rgba[..., 3] = 1
    cb_ax.imshow(cb_rgba, aspect="auto", extent=[DBZ_MIN, DBZ_MAX, 0, 1])
    cb_ax.set_yticks([])
    for sp in cb_ax.spines.values():
        sp.set_visible(False)
    cb_ax.set_xticks([15, 25, 35, 45, 55, 65])
    cb_ax.tick_params(axis="x", length=0, pad=2, colors="white")
    for lab in cb_ax.get_xticklabels():
        lab.set_fontproperties(f_reg)
        lab.set_fontsize(7.5)
    fig.text(left + 0.535, top - 0.090, "dBZ", fontproperties=f_med, fontsize=8,
             color="white", va="center", zorder=11)
    fig.text(left, top - 0.121,
             "NEXRAD Level II · HRRR MSLP · Imagery: Esri, Maxar, Earthstar Geographics",
             fontproperties=f_reg, fontsize=6, color="#c4c9cf", va="top", zorder=11)

    # Shown once the center crosses the coast.
    badge = fig.text(left + 0.004, top - 0.150, "", fontproperties=f_bold, fontsize=10.5,
                     color="white", va="top", zorder=11, visible=False,
                     bbox=dict(boxstyle="round,pad=0.4", fc="#e3262d", ec="none"))

    # Logo (right of the title block), cropped to a round badge.
    if os.path.exists(LOGO_PATH):
        logo = plt.imread(LOGO_PATH)
        lw = 0.17
        lh = lw * FRAME_W / FRAME_H
        lax = fig.add_axes([1 - left - lw, top - 0.034 - lh, lw, lh], zorder=11)
        im = lax.imshow(logo)
        h, w = logo.shape[:2]
        circ = matplotlib.patches.Circle((w / 2, h / 2), min(w, h) / 2 - 2,
                                         transform=lax.transData)
        im.set_clip_path(circ)
        lax.add_patch(matplotlib.patches.Circle((w / 2, h / 2), min(w, h) / 2 - 2,
                                                fill=False, ec="white", lw=1.5))
        lax.set_axis_off()
    else:
        log(f"NOTE: no logo found at {LOGO_PATH} -- skipping logo placement.")

    # ---- render ----
    out_mp4 = os.path.join(OUTPUT_DIR, f"{site.lower()}_low_tracking_{frames[-1][0]:%Y%m%d_%H%M}.mp4")
    out_png = out_mp4[:-4] + "_cover.png"
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    proc = subprocess.Popen(
        [ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba",
         "-s", f"{FRAME_W}x{FRAME_H}", "-r", str(args.fps), "-i", "-",
         "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", out_mp4],
        stdin=subprocess.PIPE)

    track_pts = []  # mercator trail, sampled every 10 min from loop start
    tt = frames[0][0]
    while tt <= frames[-1][0] + timedelta(minutes=10):
        la, lo, _ = trk.at(tt)
        track_pts.append((tt, *to_merc.transform(lo, la)))
        tt += timedelta(minutes=10)

    n = len(frames)
    fps_scan = args.frames_per_scan
    total = n * fps_scan
    hold = int(round(args.hold * args.fps))
    log(f"Rendering {total + hold} frames ({(total + hold) / args.fps:.1f} s) ...")
    cur_i, cur_img = -1, None
    for k in range(total + hold):
        kk = min(k, total - 1) if k < total else total - 1
        i = kk // fps_scan
        frac = (kk % fps_scan) / fps_scan
        t_scan = frames[i][0]
        if i + 1 < n:
            t_cam = t_scan + (frames[i + 1][0] - t_scan) * frac
        else:
            t_cam = t_scan
        if k >= total:
            t_cam = frames[-1][0]
        if i != cur_i:
            cur_img = composite(load_sweep(frames[i][1]))
            cur_i = i
            img.set_data(cur_img)
        cx, cy, lx, ly, p = camera(t_cam)
        ax.set_xlim(cx - view_w / 2, cx + view_w / 2)
        ax.set_ylim(cy - view_h / 2, cy + view_h / 2)

        fade_labels(cy, lx, ly)
        low_L.set_position((lx, ly))
        low_p.set_position((lx, ly - 30 * res))
        low_p.set_text(f"{p:.0f} mb")
        pts = [(x, y) for tt, x, y in track_pts if tt <= t_cam] + [(lx, ly)]
        trail.set_data([q[0] for q in pts], [q[1] for q in pts])

        lt = t_scan.astimezone(LOCAL_TZ)
        t_text.set_text(f"{lt:%a %b %-d} · {lt:%-I:%M %p %Z}")
        badge.set_visible(bool(landfall and t_cam >= landfall))
        if landfall:
            badge.set_text(f"LANDFALL ~{landfall.astimezone(LOCAL_TZ):%-I:%M %p}")

        fig.canvas.draw()
        buf = fig.canvas.buffer_rgba()
        proc.stdin.write(bytes(buf))
        if k == total - 1:
            fig.savefig(out_png, dpi=DPI)
        if k % 40 == 0:
            log(f"  frame {k}/{total + hold}  {t_scan:%H:%M}Z")
    proc.stdin.close()
    proc.wait()
    log(f"saved {out_mp4}")
    log(f"saved {out_png}")


if __name__ == "__main__":
    main()

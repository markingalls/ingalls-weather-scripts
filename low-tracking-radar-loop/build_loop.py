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
from matplotlib.collections import LineCollection
from matplotlib.colors import LinearSegmentedColormap, Normalize
from PIL import Image, ImageDraw
from pyproj import Geod, Transformer
from scipy.interpolate import UnivariateSpline
from scipy.ndimage import gaussian_filter, uniform_filter

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
# Width of the view in true (ground) km. Height follows from 9:16. 265 km
# is wide enough to show the low's whole comma head and the coast around
# it, tight enough that the lowest tilt's super-res detail still reads.
VIEW_KM = 265
# The camera centers this far due north of the low's center, so the
# frame favors the Washington coast / Puget Sound side of the circulation
# over open ocean to the south.
CAMERA_NORTH_KM = 50

# Facebook's reel UI covers roughly the top 14% and bottom 35% of the
# frame -- all text/overlays sit between them.
SAFE_TOP = 0.14
LOGO_WIDTH = 0.13  # fraction of frame width
# Town labels fade out within this many px of any header element.
LABEL_HEADER_GAP_PX = 6

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
    (17, "#3ccb4a", 0.70),
    (22, "#17a534", 0.82),
    (26, "#0c7a26", 0.86),
    (30, "#f4e21a", 0.90),
    (36, "#f7a41d", 0.92),
    (42, "#ef5a1b", 0.94),
    (48, "#c8101e", 0.95),
    (54, "#8e0a3a", 0.95),
    (60, "#e02ad8", 0.95),
    (70, "#ffffff", 0.95),
]
DBZ_MAX = REF_STOPS[-1][0]

# Base velocity (kt): inbound greens, outbound reds, a narrow gray band
# at zero -- the standard radar-app convention. Weak outbound turns
# clearly red right away, so a weak couplet embedded in inbound flow
# (green next to a few kt outbound) still reads as green/red, not just
# "less green". Brightest at the extremes.
MS_TO_KT = 1.943844
VEL_STOPS = [
    (-64, "#d4ffb0", 0.95),
    (-50, "#33ff33", 0.95),
    (-36, "#00d000", 0.93),
    (-24, "#00a000", 0.90),
    (-12, "#006b00", 0.88),
    (-2, "#365c36", 0.85),
    (0, "#6e6e6e", 0.85),
    (2, "#5c3636", 0.85),
    (12, "#8a0000", 0.88),
    (24, "#c40000", 0.90),
    (36, "#ff1a1a", 0.93),
    (50, "#ff6e8a", 0.95),
    (64, "#ffc4d9", 0.95),
]
VEL_MAX = VEL_STOPS[-1][0]

# Warning polygons (NWS storm-based warnings, from the IEM archive). Each
# is drawn only while it was valid. Outline color by phenomena.
IEM_SBW_URL = "https://mesonet.agron.iastate.edu/geojson/sbw.geojson"
WARNING_COLORS = {"TO": "#ff2525", "SV": "#ffd21f", "FF": "#33e06b", "MA": "#ff8c1a"}

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

# ---------- highways ----------
# Shared OSM motorway/trunk extracts in ../maps/, styled like the
# Columbia Basin maps (pastel blue motorways over pastel orange trunks).
ROAD_FILES = ["washington_roads.geojson", "oregon_roads.geojson", "idaho_roads_north.geojson"]
MOTORWAY_TYPES = {"motorway", "motorway_link"}
TRUNK_TYPES = {"trunk", "trunk_link"}
MOTORWAY_COLOR = "#8FB8E0"  # pastel blue
TRUNK_COLOR = "#F2B880"     # pastel orange

# ---------- basemap ----------
ESRI_URL = ("https://server.arcgisonline.com/ArcGIS/rest/services/"
            "World_Imagery/MapServer/tile/{z}/{y}/{x}")
TILE_ZOOM = 10
# Satellite imagery is darkened a touch so the radar colors pop.
SAT_BRIGHTNESS = 0.78

# ---------- towns ----------
# (name, lat, lon, side) -- side is where the label goes relative to the dot.
# Two presets (--towns): "coast" for the WA/OR coast at the ~265 km
# synoptic zoom, "puget" for storm-scale loops (~100 km) over Puget Sound,
# where the coast set's few labels would be too sparse and a denser set
# at 265 km would collide.
TOWNS_COAST = [
    ("Forks", 47.9504, -124.3855, "right"),
    ("Taholah", 47.3418, -124.2896, "left"),
    ("Ocean Shores", 46.9737, -124.1563, "left"),
    ("Aberdeen", 46.9754, -123.8157, "right"),
    ("Westport", 46.8901, -124.1040, "left"),
    ("Olympia", 47.0379, -122.9007, "right"),
    ("Tacoma", 47.2529, -122.4443, "right"),
    ("Seattle", 47.6062, -122.3321, "right"),
    ("Everett", 47.9790, -122.2021, "right"),
    ("Oak Harbor", 48.2932, -122.6432, "right"),
    ("Port Angeles", 48.1181, -123.4307, "right"),
    ("Shelton", 47.2151, -123.1007, "right"),
    ("Centralia", 46.7162, -122.9543, "right"),
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
TOWNS_PUGET = [
    ("Everett", 47.9790, -122.2021, "right"),
    ("Seattle", 47.6062, -122.3321, "left"),
    ("Bellevue", 47.6101, -122.2015, "right"),
    ("Redmond", 47.6740, -122.1215, "right"),
    ("Bremerton", 47.5673, -122.6326, "left"),
    ("Belfair", 47.4507, -122.8265, "right"),
    ("Shelton", 47.2151, -123.1007, "right"),
    ("Olympia", 47.0379, -122.9007, "right"),
    ("Gig Harbor", 47.3293, -122.5801, "left"),
    ("Tacoma", 47.2529, -122.4443, "left"),
    ("Federal Way", 47.3223, -122.3126, "left"),
    ("Renton", 47.4829, -122.2171, "right"),
    ("Kent", 47.3809, -122.2348, "right"),
    ("Auburn", 47.3073, -122.2285, "right"),
    ("Puyallup", 47.1854, -122.2929, "right"),
    ("Enumclaw", 47.2043, -121.9915, "right"),
    ("Issaquah", 47.5301, -122.0326, "left"),
    ("Snoqualmie", 47.5287, -121.8254, "right"),
    ("North Bend", 47.4957, -121.7868, "right"),
]
TOWN_SETS = {"coast": TOWNS_COAST, "puget": TOWNS_PUGET}

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


def _sweep_time(ray):
    h = ray[0]
    return (datetime(1970, 1, 1, tzinfo=timezone.utc)
            + timedelta(days=h.date - 1, milliseconds=h.time_ms))


def fetch_sweeps(job):
    """Download one volume and cache its lowest-tilt sweep(s) of `product`
    as .npz. Returns [(sweep start time, path), ...].

    job = (key, product, all_low). product "ref" takes the surveillance
    cut (REF + CC); "vel" takes the Doppler cut (VEL). With all_low, every
    cut at the lowest elevation is kept -- SAILS/MRLE repeat it two or
    three times a volume -- otherwise just the first."""
    key, product, all_low = job
    name = key.rsplit("/", 1)[-1]
    index = os.path.join(CACHE_DIR, f"{name}_{product}{'_all' if all_low else ''}.json")
    if os.path.exists(index):
        with open(index) as fh:
            return [(datetime.fromisoformat(t), p) for t, p in json.load(fh)]
    logging.getLogger("metpy").setLevel(logging.ERROR)
    from metpy.io import Level2File

    r = get(f"{S3_RADAR}/{key}")
    if r is None:
        return []
    try:
        f = Level2File(io.BytesIO(r.content))
    except Exception as e:  # truncated/partial upload
        print(f"  skip {name}: {e}", flush=True)
        return []
    els = [float(np.median([ray[0].el_angle for ray in sw])) for sw in f.sweeps]
    low = [i for i, e in enumerate(els) if e < min(els) + 0.25]
    moment = b"REF" if product == "ref" else b"VEL"
    # Surveillance cuts carry CC; Doppler cuts carry VEL.
    want = [i for i in low if (b"RHO" in f.sweeps[i][0][4]) == (product == "ref")
            and moment in f.sweeps[i][0][4]]
    if not all_low:
        want = want[:1]
    out = []
    for n, i in enumerate(want):
        sweep = f.sweeps[i]
        hdr = sweep[0][4][moment][0]
        ngates = max(len(ray[4][moment][1]) for ray in sweep if moment in ray[4])
        az = np.array([ray[0].az_angle for ray in sweep], dtype=np.float32)
        data = np.full((len(sweep), ngates), np.nan, dtype=np.float32)
        rho = np.full((len(sweep), ngates), np.nan, dtype=np.float32)
        for j, ray in enumerate(sweep):
            if moment in ray[4]:
                d = ray[4][moment][1]
                data[j, :len(d)] = d
            if b"RHO" in ray[4]:
                d = ray[4][b"RHO"][1][:ngates]
                rho[j, :len(d)] = d
        vol = sweep[0][1]
        t = _sweep_time(sweep[0])
        path = os.path.join(CACHE_DIR, f"{name}_{product}_{n}.npz")
        np.savez_compressed(
            path, product=product, az=az, data=data.astype(np.float16),
            rho=rho.astype(np.float16), first_gate=hdr.first_gate,
            gate_width=hdr.gate_width, lat=vol.lat, lon=vol.lon,
            time=t.isoformat(), elev=els[i])
        out.append((t, path))
    with open(index, "w") as fh:
        json.dump([(t.isoformat(), p) for t, p in out], fh)
    return out


def load_sweep(path, storm_motion=None):
    """storm_motion=(from_deg, kt) turns velocity storm-relative: the
    storm's own motion projected onto each radial is subtracted, so a
    rotation couplet isn't swamped by the flow carrying the storm."""
    d = np.load(path)
    product = str(d["product"])
    data = d["data"].astype(np.float32)
    if product == "ref":
        _filter_ref(data, d["rho"].astype(np.float32))
    else:
        data *= MS_TO_KT
        if storm_motion:
            toward = np.radians(storm_motion[0] + 180)
            data -= storm_motion[1] * np.cos(np.radians(d["az"])[:, None] - toward)
    # Speckle filter: drop gates with fewer than SPECKLE_MIN_NEIGHBORS of
    # their 8 neighbors (az wraps) also carrying echo.
    valid = np.isfinite(data).astype(np.float32)
    neigh = uniform_filter(valid, size=3, mode=("wrap", "constant")) * 9 - valid
    data[(valid > 0) & (neigh < SPECKLE_MIN_NEIGHBORS - 0.01)] = np.nan
    return dict(product=product, az=d["az"], data=data,
                first_gate=float(d["first_gate"]), gate_width=float(d["gate_width"]),
                lat=float(d["lat"]), lon=float(d["lon"]),
                time=datetime.fromisoformat(str(d["time"])), elev=float(d["elev"]))


def _filter_ref(ref, rho):
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


def parse_waypoints(text):
    """"ISO,lat,lon;ISO,lat,lon;..." -> track list for SmoothTrack."""
    pts = []
    for item in text.split(";"):
        t, la, lo = [v.strip() for v in item.split(",")]
        pts.append((parse_time(t, None), float(la), float(lo), np.nan))
    if len(pts) < 2:
        sys.exit("--waypoints needs at least two points")
    return sorted(pts)


# =====================================================================
# Warnings
# =====================================================================

def fetch_warnings(start, end, phenomena):
    """Storm-based warning polygons valid any time in [start, end], from
    the IEM archive: [(phenomena, begin, end, [(lon, lat), ...]), ...].
    Uses each polygon's own valid window (polygon_begin/end), so a
    warning whose polygon was cut back by a follow-up statement shows each
    version only for its own span."""
    tag = f"sbw_{start:%Y%m%d%H%M}_{end:%Y%m%d%H%M}.json"
    cache = os.path.join(CACHE_DIR, tag)
    if os.path.exists(cache):
        with open(cache) as fh:
            gj = json.load(fh)
    else:
        r = get(IEM_SBW_URL, params={"sts": f"{start:%Y-%m-%dT%H:%MZ}",
                                     "ets": f"{end:%Y-%m-%dT%H:%MZ}"})
        if r is None:
            log("  NOTE: couldn't fetch warnings from IEM -- none drawn.")
            return []
        gj = r.json()
        with open(cache, "w") as fh:
            json.dump(gj, fh)
    out = []
    for f in gj.get("features", []):
        p = f["properties"]
        if p.get("phenomena") not in phenomena or p.get("significance") != "W":
            continue
        b = datetime.fromisoformat(p["polygon_begin"].replace("Z", "+00:00"))
        e = datetime.fromisoformat(p["polygon_end"].replace("Z", "+00:00"))
        geom = f["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        for poly in polys:
            out.append((p["phenomena"], b, e, poly[0]))
    return out


# =====================================================================
# Basemap
# =====================================================================

def fetch_satellite(x0, x1, y0, y1, res):
    """Esri World Imagery mosaic covering the mercator box, at the
    coarsest zoom (but at least TILE_ZOOM) whose pixels are no bigger than
    ~0.75 output pixel, so the Lanczos downsample stays sharp at any view
    width. Returns (rgb uint8, extent [x0, x1, y0, y1])."""
    z = max(TILE_ZOOM, int(np.ceil(np.log2(2 * MERC_HALF / (256 * 0.75 * res)))))
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


def load_highways(lon0, lon1, lat0, lat1):
    """Motorway and trunk segments overlapping the lon/lat box, in web
    mercator: (motorways, trunks), each a list of (N, 2) arrays."""
    out = {"motorway": [], "trunk": []}
    for name in ROAD_FILES:
        path = os.path.join(MAPS_DIR, name)
        if not os.path.exists(path):
            continue
        with open(path) as fh:
            gj = json.load(fh)
        for f in gj["features"]:
            hwy = f["properties"].get("highway")
            kind = "motorway" if hwy in MOTORWAY_TYPES else "trunk" if hwy in TRUNK_TYPES else None
            if kind is None:
                continue
            geom = f["geometry"]
            lines = geom["coordinates"] if geom["type"] == "MultiLineString" else [geom["coordinates"]]
            for line in lines:
                c = np.asarray(line, dtype=float)
                if (c[:, 0].max() < lon0 or c[:, 0].min() > lon1
                        or c[:, 1].max() < lat0 or c[:, 1].min() > lat1):
                    continue
                x, y = to_merc.transform(c[:, 0], c[:, 1])
                out[kind].append(np.column_stack([x, y]))
    return out["motorway"], out["trunk"]


def build_grid(x0, x1, y0, y1, res):
    """Pixel-center coordinates of a north-up mercator grid at `res` m/px."""
    nx = int(np.ceil((x1 - x0) / res))
    ny = int(np.ceil((y1 - y0) / res))
    xs = x0 + (np.arange(nx) + 0.5) * res
    ys = y1 - (np.arange(ny) + 0.5) * res  # row 0 = north
    return xs, ys


# =====================================================================
# Logo
# =====================================================================

LOGO_BG = np.array([224, 234, 223], dtype=np.float32)   # the PNG's pale-green square
LOGO_CREAM = np.array([255, 246, 231], dtype=np.float32)  # the emblem's own fill


def logo_badge(path, size=512, ring="#ffffff", ring_frac=0.035):
    """The logo on an anti-aliased round cream badge with a white ring.
    The source PNG is a pale-green square with a non-circular cream emblem,
    so a plain circular crop shows flat emblem edges -- key the background
    to the emblem's cream instead and put it all on a larger disc."""
    src = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
    h, w = src.shape[:2]
    # Recolor the background to the emblem's cream (soft keyed on color
    # distance, so the anti-aliased edges of the artwork survive).
    d = np.abs(src - LOGO_BG).sum(-1)
    k = np.clip((d - 14) / 24, 0, 1)[..., None]
    rgb = src * k + LOGO_CREAM * (1 - k)
    # The PNG's outermost rows/columns are off-color (a visible seam once
    # the square sits on a cream disc) -- blank them to cream.
    b = 12
    rgb[:b], rgb[-b:], rgb[:, :b], rgb[:, -b:] = LOGO_CREAM, LOGO_CREAM, LOGO_CREAM, LOGO_CREAM
    # Disc: centered on the artwork, radius reaching its farthest point
    # (the sun's rays) plus a margin.
    cx, cy, r = 0.492 * w, 0.502 * h, 0.585 * w
    ss = 4
    D = int(2 * r) + 2
    canvas = np.empty((D, D, 3), dtype=np.float32)
    canvas[:] = LOGO_CREAM
    ox, oy = int(round(r - cx)), int(round(r - cy))
    canvas[oy:oy + h, ox:ox + w] = rgb
    img = Image.fromarray(canvas.astype(np.uint8)).resize((size, size), Image.LANCZOS)
    # Anti-aliased masks via supersampling.
    big = size * ss
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, big - 1, big - 1), fill=255)
    ring_mask = Image.new("L", (big, big), 0)
    rw = int(big * ring_frac)
    dr = ImageDraw.Draw(ring_mask)
    dr.ellipse((0, 0, big - 1, big - 1), fill=255)
    dr.ellipse((rw, rw, big - 1 - rw, big - 1 - rw), fill=0)
    mask = mask.resize((size, size), Image.LANCZOS)
    ring_mask = ring_mask.resize((size, size), Image.LANCZOS)
    ring_img = Image.new("RGB", (size, size), ring)
    img = Image.composite(ring_img, img, ring_mask)
    img.putalpha(mask)
    return img


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
    ap.add_argument("--waypoints", help="follow a fixed track instead of an "
                    "HRRR-tracked low: 'ISO,lat,lon;ISO,lat,lon;...' (times "
                    "UTC unless an offset is given; extrapolated past the ends)")
    ap.add_argument("--product", choices=["ref", "vel"], default="ref",
                    help="lowest-tilt reflectivity or base velocity")
    ap.add_argument("--storm-motion", help="FROM_DEG/KT, e.g. 249/24 (as in a "
                    "warning's motion line): with --product vel, show "
                    "storm-relative velocity instead of base velocity")
    ap.add_argument("--sails", action="store_true",
                    help="use every lowest-tilt cut in a volume (SAILS/MRLE "
                    "repeats it), not just the first -- ~2 min updates")
    ap.add_argument("--warnings", default="",
                    help="comma list of warning phenomena to draw while valid, "
                    "e.g. TO or TO,SV (default: none)")
    ap.add_argument("--highways", action="store_true",
                    help="draw motorways/trunks from ../maps/")
    ap.add_argument("--minutes-per-sec", type=float,
                    help="play at a constant pace of this many real minutes per "
                    "video second, each scan held until the next arrives "
                    "(default: every scan gets --frames-per-scan frames, so "
                    "the pace speeds up wherever scans are sparser)")
    ap.add_argument("--towns", choices=sorted(TOWN_SETS), default="coast",
                    help="town label preset (default %(default)s)")
    ap.add_argument("--view-km", type=float, default=VIEW_KM,
                    help="frame width in ground km (default %(default)s)")
    ap.add_argument("--north-km", type=float, default=CAMERA_NORTH_KM,
                    help="center the camera this far north of the low; "
                    "negative is south (default %(default)s)")
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
    storm_motion = None
    if args.storm_motion:
        storm_motion = tuple(float(v) for v in args.storm_motion.split("/"))
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
    first = fetch_sweeps((scans[0][1], args.product, args.sails))
    if not first:
        sys.exit(f"Couldn't read {scans[0][1]}")
    s0 = load_sweep(first[0][1])
    rlat, rlon = s0["lat"], s0["lon"]

    if args.waypoints:
        # ---- fixed track (e.g. a storm cell's motion) ----
        trk = SmoothTrack(parse_waypoints(args.waypoints))
        keep = scans
    else:
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
    log(f"  {len(keep)} volumes in loop: {keep[0][0]:%H:%M} - {keep[-1][0]:%H:%M} UTC")

    # ---- fetch radar ----
    log("Fetching radar volumes ...")
    with Pool(args.workers) as pool:
        swept = pool.map(fetch_sweeps, [(k, args.product, args.sails) for _, k in keep])
    frames = sorted(x for vol in swept for x in vol if start <= x[0] <= end)
    if args.max_frames:
        frames = frames[-args.max_frames:]
    if not frames:
        sys.exit("No sweeps in window.")
    log(f"  {len(frames)} sweeps ready: {frames[0][0]:%H:%M:%S} - {frames[-1][0]:%H:%M:%S} UTC")

    phenomena = [v.strip().upper() for v in args.warnings.split(",") if v.strip()]
    warnings = []
    if phenomena:
        log(f"Fetching {'/'.join(phenomena)} warnings ...")
        # Only polygons within radar range -- IEM returns the whole country.
        warnings = [w for w in fetch_warnings(frames[0][0], frames[-1][0], phenomena)
                    if geod.inv(rlon, rlat, w[3][0][0], w[3][0][1])[2] < 460_000]
        for ph, wb, we, _ in warnings:
            log(f"  {ph}.W polygon valid {wb:%H:%M}-{we:%H:%M}Z")

    # ---- camera geometry (web mercator) ----
    mid_lat = np.mean([trk.at(t)[0] for t, _ in frames])
    view_w = args.view_km * 1000 / np.cos(np.radians(mid_lat))  # mercator m
    view_h = view_w * FRAME_H / FRAME_W
    res = view_w / FRAME_W  # mercator m per output pixel

    def camera(t):
        la, lo, _ = trk.at(t)
        lo, la, _ = geod.fwd(lo, la, 0, args.north_km * 1000)
        return to_merc.transform(lo, la)

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
    mosaic, mext = fetch_satellite(gx0, gx1, gy0, gy1, res)
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
    rng_g = (dist_g / 1000).astype(np.float32)
    del az_g, dist_g

    if args.product == "ref":
        stops, vmin, vmax = REF_STOPS, DBZ_MIN, DBZ_MAX
    else:
        stops, vmin, vmax = VEL_STOPS, -VEL_MAX, VEL_MAX
    cmap = LinearSegmentedColormap.from_list(
        args.product, [((d - vmin) / (vmax - vmin),
                        (*matplotlib.colors.to_rgb(c), a)) for d, c, a in stops])
    norm = Normalize(vmin, vmax)

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
        data = sw["data"]
        g = np.round((rng_g - sw["first_gate"]) / sw["gate_width"]).astype(np.int32)
        ok = (g >= 0) & (g < data.shape[1])
        vals = np.full(g.shape, np.nan, dtype=np.float32)
        vals[ok] = data[table[azbin_g[ok]], g[ok]]
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

    if args.highways:
        lon_a, lat_a = from_merc.transform([gx0, gx1], [gy0, gy1])
        motorways, trunks = load_highways(lon_a[0], lon_a[1], lat_a[0], lat_a[1])
        halo_road = [pe.withStroke(linewidth=2.4, foreground="#101418", alpha=0.45)]
        for segs, color, lw, z in ((trunks, TRUNK_COLOR, 1.0, 2.0), (motorways, MOTORWAY_COLOR, 1.3, 2.1)):
            lc = LineCollection(segs, colors=color, linewidths=lw, zorder=z,
                                capstyle="round", joinstyle="round")
            lc.set_path_effects(halo_road)
            ax.add_collection(lc)
        log(f"  {len(motorways)} motorway / {len(trunks)} trunk segments")

    # Towns
    # Each label is (artists, label-center x, y) so it can fade out as it
    # scrolls under the header block or the L (see fade_labels below).
    halo = [pe.withStroke(linewidth=2.4, foreground="#101418")]
    labels = []
    for name, la, lo, side in TOWN_SETS[args.towns]:
        x, y = to_merc.transform(lo, la)
        dot, = ax.plot(x, y, "o", ms=4.2, mfc="white", mec="#101418", mew=0.9, zorder=5)
        sign = 1 if side == "right" else -1
        txt = ax.text(x + sign * 7 * res, y, name, ha="left" if side == "right" else "right",
                      va="center", fontproperties=f_med, fontsize=10.5, color="white",
                      path_effects=halo, zorder=6, clip_on=True)
        labels.append(([dot, txt], x, y))
    # Radar site
    x, y = to_merc.transform(rlon, rlat)
    dot, = ax.plot(x, y, "^", ms=6.5, mfc="#ffd84d", mec="#101418", mew=0.9, zorder=5)
    txt = ax.text(x + 8 * res, y - 16 * res, site, ha="left", va="center",
                  fontproperties=f_semi, fontsize=8.5, color="#ffd84d",
                  path_effects=halo, zorder=6, clip_on=True)
    labels.append(([dot, txt], x, y))

    # Warning polygons, each shown only while valid (see the render loop).
    warn_artists = []
    for ph, wb, we, ring in warnings:
        wx, wy = to_merc.transform([c[0] for c in ring], [c[1] for c in ring])
        line, = ax.plot(wx, wy, color=WARNING_COLORS.get(ph, "white"), lw=2.6,
                        zorder=4, solid_joinstyle="round", visible=False,
                        path_effects=[pe.withStroke(linewidth=4.6, foreground="#101418")])
        warn_artists.append((line, wb, we))

    # Top scrim (gradient) so the title reads over any imagery.
    scrim_ax = fig.add_axes([0, 0.62, 1, 0.38], zorder=10)
    grad = np.clip(np.linspace(-0.1, 1.4, 256), 0, 1)[:, None] ** 1.2
    scrim = np.zeros((256, 1, 4))
    scrim[..., 3] = 0.72 * grad
    scrim_ax.imshow(scrim, aspect="auto", extent=[0, 1, 0, 1], origin="lower")
    scrim_ax.set_axis_off()

    left = 0.055
    top = 1 - SAFE_TOP
    title = fig.text(left, top, args.title.upper(), fontproperties=f_bold, fontsize=19,
                     color="white", va="top", zorder=11)
    t_text = fig.text(left, top - 0.037, "", fontproperties=f_semi, fontsize=13,
                      color="white", va="top", zorder=11)
    what = ("reflectivity" if args.product == "ref" else
            "storm-relative velocity" if storm_motion else "base velocity")
    subtitle = fig.text(left, top - 0.063, f"{site} radar · lowest tilt {what}",
                        fontproperties=f_reg, fontsize=9.5, color="#d9dde2", va="top", zorder=11)
    header_artists = [title, t_text, subtitle]  # what town labels must stay clear of

    # Color bar
    cb_ax = fig.add_axes([left, top - 0.094, 0.52, 0.008], zorder=11)
    cb_rgba = cmap(norm(np.linspace(vmin, vmax, 256)[None, :]))
    cb_rgba[..., 3] = 1
    cb_ax.imshow(cb_rgba, aspect="auto", extent=[vmin, vmax, 0, 1])
    cb_ax.set_yticks([])
    for sp in cb_ax.spines.values():
        sp.set_visible(False)
    cb_ax.set_xticks([20, 30, 40, 50, 60] if args.product == "ref" else [-60, -30, 0, 30, 60])
    cb_ax.tick_params(axis="x", length=0, pad=2, colors="white")
    for lab in cb_ax.get_xticklabels():
        lab.set_fontproperties(f_reg)
        lab.set_fontsize(7.5)
    unit = "dBZ" if args.product == "ref" else "kt"
    dbz = fig.text(left + 0.535, top - 0.090, unit, fontproperties=f_med, fontsize=8,
                   color="white", va="center", zorder=11)
    credit = fig.text(left, top - 0.121,
                      "Ingalls Weather · NEXRAD Level II · Imagery: Esri, Maxar, Earthstar Geographics",
                      fontproperties=f_reg, fontsize=6, color="#c4c9cf", va="top", zorder=11)
    header_artists += [cb_ax, dbz, credit]

    # Logo (right of the title block), as a round badge.
    if os.path.exists(LOGO_PATH):
        lw = LOGO_WIDTH
        lh = lw * FRAME_W / FRAME_H
        lax = fig.add_axes([1 - left - lw, top - 0.030 - lh, lw, lh], zorder=11)
        lax.imshow(logo_badge(LOGO_PATH, size=int(round(lw * FRAME_W * 2))),
                   interpolation="antialiased")
        lax.set_axis_off()
        header_artists.append(lax)
    else:
        log(f"NOTE: no logo found at {LOGO_PATH} -- skipping logo placement.")

    # ---- label fading ----
    # A town label fades out only where it would overlap part of the
    # header (title, time, legend, credits, logo), so
    # labels can still show in the gaps -- some towns sit behind
    # the header band for the whole loop. Boxes are in figure pixels.
    t_text.set_text("Fri Sep 25 · 23:59 PDT")  # widest case, for measuring
    ax.set_xlim(gx0, gx0 + view_w)
    ax.set_ylim(gy0, gy0 + view_h)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    header_boxes = [a.get_tightbbox(renderer) for a in header_artists]
    label_boxes = []  # per label: (x0, y0, x1, y1) offsets from its dot, px
    for artists, x, y in labels:
        px, py = ax.transData.transform((x, y))
        boxes = [a.get_window_extent(renderer) for a in artists]
        label_boxes.append((min(b.x0 for b in boxes) - px, min(b.y0 for b in boxes) - py,
                            max(b.x1 for b in boxes) - px, max(b.y1 for b in boxes) - py))

    def fade_labels(cx, cy):
        for (artists, x, y), (ox0, oy0, ox1, oy1) in zip(labels, label_boxes):
            px = (x - (cx - view_w / 2)) / res
            py = (y - (cy - view_h / 2)) / res
            lx0, ly0, lx1, ly1 = px + ox0, py + oy0, px + ox1, py + oy1
            gap = np.inf  # px between the label and the nearest header box
            for b in header_boxes:
                gx = max(b.x0 - lx1, lx0 - b.x1, 0)
                gy = max(b.y0 - ly1, ly0 - b.y1, 0)
                gap = min(gap, np.hypot(gx, gy))
            a = float(np.clip((gap - LABEL_HEADER_GAP_PX) / 12, 0, 1))
            for art in artists:
                art.set_alpha(a)
                art.set_visible(a > 0)

    # ---- render ----
    out_mp4 = os.path.join(OUTPUT_DIR, f"{site.lower()}_{'srv' if storm_motion else args.product}_loop_{frames[-1][0]:%Y%m%d_%H%M}.mp4")
    out_png = out_mp4[:-4] + "_cover.png"
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    proc = subprocess.Popen(
        [ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba",
         "-s", f"{FRAME_W}x{FRAME_H}", "-r", str(args.fps), "-i", "-",
         "-c:v", "libx264", "-preset", "slow", "-crf", "23", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", out_mp4],
        stdin=subprocess.PIPE)

    # Video timeline: (scan index, camera time) per output frame.
    n = len(frames)
    timeline = []
    if args.minutes_per_sec:
        # Constant pace: real time advances the same amount every frame;
        # each scan stays up until the next one's start time.
        step = timedelta(minutes=args.minutes_per_sec / args.fps)
        scan_times = [t for t, _ in frames]
        t = frames[0][0]
        while t <= frames[-1][0]:
            i = int(np.searchsorted([x.timestamp() for x in scan_times], t.timestamp(), side="right")) - 1
            timeline.append((max(i, 0), t))
            t += step
    else:
        # Every scan gets frames_per_scan frames; the camera glides
        # between scan times.
        for i in range(n):
            for f in range(args.frames_per_scan):
                t_cam = frames[i][0]
                if i + 1 < n:
                    t_cam += (frames[i + 1][0] - frames[i][0]) * (f / args.frames_per_scan)
                timeline.append((i, t_cam))
    total = len(timeline)
    hold = int(round(args.hold * args.fps))
    timeline += [(n - 1, frames[-1][0])] * hold
    log(f"Rendering {total + hold} frames ({(total + hold) / args.fps:.1f} s) ...")
    cur_i, cur_img = -1, None
    for k, (i, t_cam) in enumerate(timeline):
        t_scan = frames[i][0]
        if i != cur_i:
            cur_img = composite(load_sweep(frames[i][1], storm_motion))
            cur_i = i
            img.set_data(cur_img)
        cx, cy = camera(t_cam)
        ax.set_xlim(cx - view_w / 2, cx + view_w / 2)
        ax.set_ylim(cy - view_h / 2, cy + view_h / 2)

        fade_labels(cx, cy)
        for line, wb, we in warn_artists:
            line.set_visible(wb <= t_scan < we)

        lt = t_scan.astimezone(LOCAL_TZ)
        t_text.set_text(f"{lt:%a %b %-d} · {lt:%H:%M %Z}")

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

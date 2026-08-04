"""
Western U.S. NOAA Outlooks — map builder
Ingalls Weather

Renders any of several NOAA outlook products over the same Western U.S.
frame/style. Pick one with --product:

    heat_d8_14    CPC Day 8-14 Extreme Heat outlook (probabilistic,
                  falls back to categorical if unavailable)
    temp_6_10     CPC 6-10 Day Temperature Outlook
    precip_6_10   CPC 6-10 Day Precipitation Outlook
    temp_8_14     CPC 8-14 Day Temperature Outlook
    precip_8_14   CPC 8-14 Day Precipitation Outlook
    temp_wk34     CPC Week 3-4 Temperature Outlook
    precip_wk34   CPC Week 3-4 Precipitation Outlook
    spc_fire      SPC Day 1 Fire Weather Outlook
    spc_fire_day2 SPC Day 2 Fire Weather Outlook
    spc_severe    SPC Day 1 Categorical (Severe Weather) Outlook
    spc_convective_day2  SPC Day 2 Categorical (Severe Weather) Outlook
    spc_convective_day3  SPC Day 3 Categorical (Severe Weather) Outlook
    spc_tornado_day1  SPC Day 1 Tornado Probability Outlook
    spc_tornado_day2  SPC Day 2 Tornado Probability Outlook
    spc_wind_day1 SPC Day 1 Wind Probability Outlook
    spc_wind_day2 SPC Day 2 Wind Probability Outlook
    spc_hail_day1 SPC Day 1 Hail Probability Outlook
    spc_hail_day2 SPC Day 2 Hail Probability Outlook
    wpc_precip    WPC Day 1 Excessive Rainfall Outlook
    drought_monitor  U.S. Drought Monitor (NDMC weekly D0-D4 categories)

USAGE
-----
    python build_map.py --product temp_8_14

Each product's current KML/KMZ is fetched live over HTTPS (all of the
sources above publish a stable, non-dated "latest" URL — see PRODUCTS
below). Output PNG lands in western-us-noaa-outlooks/output/.

To render from a KML/KMZ you already have on disk instead of fetching
(useful for testing, or if a source is temporarily down), pass
--file path/to/thing.kml.

REQUIRES (already checked into /maps at repo root, shared across all
Ingalls Weather map projects):
    land_slim.json, states_lakes_slim.json (lake polygons only -- state and
    country borders come from admin1_boundary_lines.json and
    admin0_boundary_lines.json instead, see the comment above
    GEOM_SIMPLIFY_TOLERANCE_DEG for why)
  Sourced from raw.githubusercontent.com/martynafford/natural-earth-geojson
  (10m), clipped down to North America.

Logo is read from /assets/ingalls_weather_logo.png at repo root.
"""

import argparse
import io
import json
import re
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
import matplotlib.colors as mcolors
from matplotlib.patches import Patch, PathPatch
from matplotlib.axes import Axes
import numpy as np
import requests
import shapefile

import cartopy.crs as ccrs
from cartopy.mpl.path import shapely_to_path
import shapely
from shapely.geometry import shape, box, Polygon as ShPolygon, MultiPolygon as ShMultiPolygon
from shapely.ops import unary_union
from PIL import Image

# ---------------------------------------------------------------------------
# Paths (relative to this script's location: western-us-noaa-outlooks/)
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
MAPS_DIR = REPO_ROOT / "maps"
ASSETS_DIR = REPO_ROOT / "assets"
THIS_DIR = Path(__file__).resolve().parent
DATA_DIR = THIS_DIR / "data"
OUTPUT_DIR = THIS_DIR / "output"

LAND_FILE = MAPS_DIR / "land_slim.json"
STATES_LAKES_FILE = MAPS_DIR / "states_lakes_slim.json"
ADMIN1_LINES_FILE = MAPS_DIR / "admin1_boundary_lines.json"
ADMIN0_LINES_FILE = MAPS_DIR / "admin0_boundary_lines.json"
LOGO_FILE = ASSETS_DIR / "ingalls_weather_logo.png"

TARGET_COUNTRIES = {"United States of America", "Canada", "Mexico"}

# A descriptive User-Agent, same spirit as fetch_forecast.py's for
# api.weather.gov, is a normal, honest thing to send on every request.
# (It was first tried as a fix for the droplet's spc.noaa.gov 403s; a
# curl -sv capture later showed those came from a CloudFront/WAF edge
# block on the droplet's IP range, not a User-Agent rule -- see the IEM
# fetch/parse comment below for the actual fix.)
FETCH_HEADERS = {"User-Agent": "(ingallswx.com, contact@ingallswx.com)"}

# State/province and country borders are drawn from admin1_boundary_lines.json
# / admin0_boundary_lines.json -- dedicated line datasets -- rather than
# derived by outlining Natural Earth's admin-1 *polygons*
# (states_lakes_slim.json). Two things drove this, one that panned out and
# one that didn't:
#  - A sliver-shaped gap right at the Idaho/Utah/Wyoming tripoint looked
#    exactly like a classic "independently-stroked polygons don't quite
#    meet" artifact, and switching to line data was the obvious fix to try.
#    Turned out to be a red herring: it's a real small lake sitting almost
#    exactly on the state line (confirmed by outlining it) -- the original
#    polygon-outline approach was already rendering that tripoint cleanly.
#  - What line data actually did fix: admin1_boundary_lines.json includes a
#    state's international-facing edge as an ordinary line -- e.g.
#    Washington's northern border through the San Juan Islands is in there
#    like any other state boundary -- and it isn't vertex-matched to
#    admin0_boundary_lines.json's own line for that same physical stretch.
#    Drawing both showed as two visibly diverging lines along the WA/BC
#    border. See load_state_lines() for how the duplicate stretch gets
#    trimmed out. Lake polygons still come from states_lakes_slim.json
#    (they need to be filled, not just outlined), so that file isn't fully
#    retired even though state/country borders no longer come from it.
GEOM_SIMPLIFY_TOLERANCE_DEG = 0.02  # land layer's .simplify() tolerance

# Simplifying can leave a very long, nearly-straight run reduced to just its
# two endpoints (e.g. Montana's entire ~12-degree-long northern border).
# Under this map's curved perspective projection a 2-point chord that long
# visibly cuts the corner relative to a neighboring line/polygon that
# happens to keep more points along the same stretch, reading as a second,
# offset line even though the underlying geography matches. Re-densifying
# afterwards so no straight run exceeds this length fixes the projected curve.
BORDER_DENSIFY_SEGMENT_DEG = 0.5

# Snaps land-polygon and lake-polygon vertices to a shared coordinate grid
# (well below GEOM_SIMPLIFY_TOLERANCE_DEG, so it doesn't affect actual
# shape) before simplifying, closing tiny sub-tolerance gaps between
# features that should touch exactly. State/country borders don't need
# this -- see the comment above -- but land/lake polygons still derive
# from admin-1-style polygon data, so kept here for those.
COORD_SNAP_GRID_DEG = 0.001

# How far state lines get trimmed back from a country line before drawing
# both -- see load_state_lines(). Needs to comfortably clear the observed
# divergence between the two datasets' paths through the San Juan Islands
# (measured up to roughly 0.03 deg); tested up to 0.12 deg with no adverse
# effect on genuinely-internal state lines elsewhere, so this has real
# margin without being so large it could eat a state line that legitimately
# runs close and parallel to a country line for a stretch.
STATE_COUNTRY_DEDUP_BUFFER_DEG = 0.08

# Cutoff for excluding a state line as an offshore maritime boundary rather
# than a real land border -- see load_state_lines(). Measured every
# offshore boundary segment within this map's frame at >=0.026 deg from the
# (unsimplified) land layer, and every genuine state line at essentially
# 0.0, so this sits with wide margin in the untouched gap between the two.
OFFSHORE_LINE_DISTANCE_DEG = 0.02

POPPINS_REG_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf"
POPPINS_MED_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf"

# ---------------------------------------------------------------------------
# Figure geometry -- shared by the legend (bottom-left) and the logo
# (bottom-right) so both sit the same distance from the map frame's corner.
# ---------------------------------------------------------------------------
FIG_WIDTH_IN, FIG_HEIGHT_IN = 10, 8.9
FIG_DPI = 200
AXES_RECT = [0.03, 0.045, 0.94, 0.855]  # [left, bottom, width, height], figure fraction
MAP_FRAME_INSET_PX = 22

# ---------------------------------------------------------------------------
# Map domain (western US) — do not change this when adding new cities;
# cities right at the edge often still render fine thanks to the curved
# projection. Only change this if you deliberately want a wider/narrower map.
#
# LON_MIN and AXES_RECT above are tuned together, empirically, so the
# rendered map frame's left/right edges land within ~2px of AXES_RECT's own
# left/right edges (0.03/0.97 figure-fraction -- matching the title's 0.03
# left inset on both sides). Cartopy auto-centers the frame within
# AXES_RECT to preserve true aspect ratio at whatever height AXES_RECT
# allows, so widening the frame took two coordinated changes: widening
# AXES_RECT itself (both edges, staying centered) AND widening LON_MIN
# westward enough that the frame's natural width grows to fill that wider
# box almost exactly, leaving ~0 leftover centering margin -- extending
# LON_MIN alone would've just centered a wider frame with the same
# unwanted margins, not moved its edges out to meet the box. If you need
# to retune this (e.g. a taller/shorter FIG_HEIGHT_IN), render a test
# image and measure the frame border's actual pixel x-range (a plain
# horizontal scan for near-black pixels through the image's vertical
# middle works) rather than assuming AXES_RECT's numbers are the final
# on-screen position.
# ---------------------------------------------------------------------------
LON_MIN, LON_MAX = -133.7, -98.0
LAT_MIN, LAT_MAX = 28.0, 51.5
CENTER_LON, CENTER_LAT = -113.5, 39.5

# National products (CPC temp/precip, SPC, WPC) carry shading well outside
# this frame; padded slightly beyond the visible extent so edge-clipped
# polygons still count as "present" for the legend.
MAP_BBOX = box(LON_MIN - 3, LAT_MIN - 3, LON_MAX + 3, LAT_MAX + 3)

# ---------------------------------------------------------------------------
# City labels: (name, lon, lat, label position: "left" | "right" | "above" | "below")
# ---------------------------------------------------------------------------
CITIES = [
    ("Seattle", -122.33, 47.61, "left"),
    ("Portland", -122.68, 45.52, "left"),
    ("Bend", -121.31, 44.06, "left"),
    ("Sacramento", -121.49, 38.58, "right"),
    ("San Francisco", -122.42, 37.77, "left"),
    ("Los Angeles", -118.24, 34.05, "right"),
    ("San Diego", -117.16, 32.72, "left"),
    ("Las Vegas", -115.14, 36.17, "right"),
    ("Phoenix", -112.07, 33.45, "right"),
    ("Salt Lake City", -111.89, 40.76, "right"),
    ("Boise", -116.20, 43.62, "left"),
    ("Idaho Falls", -112.03, 43.49, "right"),
    ("Denver", -104.99, 39.74, "right"),
    ("Cheyenne", -104.82, 41.14, "right"),
    ("Billings", -108.50, 45.78, "right"),
    ("Rapid City", -103.23, 44.08, "right"),
    ("Bismarck", -100.78, 46.81, "right"),
    ("Albuquerque", -106.65, 35.08, "right"),
    ("El Paso", -106.49, 31.76, "right"),
    ("Spokane", -117.43, 47.66, "right"),
    ("Tri-Cities", -119.28, 46.26, "right"),
    ("Warroad", -95.31, 48.91, "left"),
]

# ---------------------------------------------------------------------------
# KML parsing — NOAA centers export two different flavors of KML. Each
# product below picks whichever of these two matches its source:
#
#   parse_kml_named          Placemark has a <name> (sometimes blank, in
#                             which case we fall back to the "KML Label"
#                             field in its description table) plus an
#                             optional label/value description table.
#                             Covers CPC's heat/temp/precip outlooks and
#                             WPC's Excessive Rainfall Outlook.
#
#   parse_kml_extended_data  Placemark has no <name>; category + styling
#                             live in ExtendedData, as either
#                             <Data name="X"><value>Y</value></Data> or
#                             schema-based <SimpleData name="X">Y</SimpleData>.
#                             Covers SPC's fire weather + categorical
#                             severe outlooks.
# ---------------------------------------------------------------------------

def _parse_rings(placemark_xml):
    rings = []
    for block in re.findall(r"<coordinates>(.*?)</coordinates>", placemark_xml, re.S):
        pts = []
        for triplet in block.split():
            parts = triplet.split(",")
            if len(parts) < 2:
                continue
            pts.append((float(parts[0]), float(parts[1])))
        if len(pts) >= 3:
            rings.append(pts)
    return rings


def parse_kml_named(text):
    placemarks = re.findall(r"<Placemark[ >].*?</Placemark>", text, re.S)
    results = []
    for pm in placemarks:
        m = re.search(r"<name>(.*?)</name>", pm, re.S)
        name = unescape(m.group(1)).strip() if m else ""
        fields = {k.strip(): unescape(v).strip()
                  for k, v in re.findall(r"<td>([^<]+)</td>\s*<td[^>]*>([^<]*)</td>", pm)}
        if not name:
            name = fields.get("KML Label", "")
        rings = _parse_rings(pm)
        if not rings or not name:
            continue
        results.append({"name": name, "fields": fields, "rings": rings})
    return results


def parse_kml_extended_data(text):
    placemarks = re.findall(r"<Placemark[ >].*?</Placemark>", text, re.S)
    results = []
    for pm in placemarks:
        fields = {}
        for k, v in re.findall(r'<Data name="([^"]+)"><value>(.*?)</value></Data>', pm, re.S):
            fields[k] = unescape(v).strip()
        for k, v in re.findall(r'<SimpleData name="([^"]+)">(.*?)</SimpleData>', pm, re.S):
            fields[k] = unescape(v).strip()
        rings = _parse_rings(pm)
        if not rings or "LABEL" not in fields:
            continue
        results.append({"fields": fields, "rings": rings})
    return results


def parse_usdm_geojson(text):
    """U.S. Drought Monitor's ArcGIS FeatureServer returns plain GeoJSON
    rather than KML: one feature per DM category (0-4), each already the
    full cumulative extent of that category or worse. Only exterior rings
    are kept per part (holes are dropped), matching the same simplification
    the KML parsers above make for polygons with interior boundaries."""
    data = json.loads(text)
    results = []
    for feat in data.get("features", []):
        geom = feat.get("geometry")
        if not geom:
            continue
        if geom["type"] == "Polygon":
            parts = [geom["coordinates"]]
        elif geom["type"] == "MultiPolygon":
            parts = geom["coordinates"]
        else:
            continue
        rings = [part[0] for part in parts if part and len(part[0]) >= 3]
        if not rings:
            continue
        results.append({"fields": feat.get("properties", {}), "rings": rings})
    return results


# ---------------------------------------------------------------------------
# IEM fetch/parse -- SPC's own site (spc.noaa.gov) is fronted by a
# CloudFront distribution whose WAF flatly blocks the droplet's hosting-
# provider IP range (confirmed via curl -sv: "server: CloudFront",
# "x-cache: Error from cloudfront" -- the block happens at the CDN edge,
# before the request ever reaches SPC's origin, so no User-Agent or header
# trick gets around it; CPC and the drought monitor's ArcGIS source aren't
# affected). Iowa Environmental Mesonet mirrors the same SPC outlook data
# as bulk shapefiles and isn't behind that block, so all eleven SPC-domain
# products fetch from IEM instead. Confirmed live against IEM:
#   - type=C (convective) for a given day bundles CATEGORICAL, TORNADO,
#     WIND, and HAIL together in one shapefile -- SPC issues them as a
#     single product -- filtered here by the CATEGORY field. Day 3 only
#     carries CATEGORICAL and ANY SEVERE (no separate tornado/wind/hail),
#     matching SPC's own Day 3 product.
#   - type=F (fire weather) THRESHOLD comes through directly as
#     ELEV/CRIT/EXTM/IDRT under one category, "FIRE WEATHER CATEGORICAL" --
#     dry thunderstorm risk (IDRT) is NOT a separate category as originally
#     assumed, it's just another THRESHOLD value alongside the fire-index
#     tiers, so it maps onto SPC_FIRE_STYLE with no special-casing needed.
#   - TORNADO/WIND/HAIL THRESHOLD is a fraction ("0.05", "0.15", ...) rather
#     than a bare percentage, and "CIG1"/"CIG2" for the significant tier(s)
#     (matching spc_prob_style's existing "CIG" check exactly -- CIG2 is
#     rare, seen on only a handful of the most active outbreak days across
#     a season and a half of history checked, but the same "startswith"
#     check picks it up with no extra handling needed).
# ---------------------------------------------------------------------------

IEM_OUTLOOKS_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/gis/outlooks.py"

# A bulk request over this window can span several issuance cycles (SPC
# reissues Day 1 outlooks multiple times a day); fetch_iem_outlook() keeps
# only the most-recently-issued cycle's records, so this just needs to
# comfortably bracket the longest gap between cycles, not match it exactly.
IEM_FETCH_WINDOW_HOURS = 48


def _iem_iso(yyyymmddhhmm):
    return datetime.strptime(yyyymmddhhmm, "%Y%m%d%H%M").replace(tzinfo=timezone.utc).isoformat()


def _shapefile_rings(shp):
    """pyshp gives one flat points list per shape plus part-start indices --
    convert to a list of rings. Like parse_usdm_geojson's exterior-only
    simplification, this doesn't distinguish holes from exterior rings, but
    SPC outlook polygons essentially never have donut holes in practice."""
    parts = list(shp.parts) + [len(shp.points)]
    return [shp.points[parts[i]:parts[i + 1]] for i in range(len(parts) - 1)
            if parts[i + 1] - parts[i] >= 3]


def fetch_iem_outlook(day, iem_type, category, hazard_label=None):
    """Fetches one SPC outlook product from IEM's bulk shapefile mirror and
    returns placemarks in the same {"fields": {...}, "rings": [...]} shape
    the KML parsers produce, so the existing style/date functions
    (spc_style, spc_prob_style, date_from_valid_expire_iso) work unchanged.

    `category` is the IEM CATEGORY value to keep ("CATEGORICAL", "WIND",
    "HAIL", or "FIRE WEATHER CATEGORICAL"). WIND/HAIL need hazard_label
    ("wind"/"hail") to build a human-readable LABEL2 -- IEM has no
    equivalent of SPC's own KML LABEL2 field."""
    now = datetime.now(timezone.utc)
    params = {
        "d": day,
        "type": iem_type,
        "sts": (now - timedelta(hours=IEM_FETCH_WINDOW_HOURS)).strftime("%Y-%m-%dT%H:%MZ"),
        "ets": (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%MZ"),
        "geom": "geom_layers",
    }
    print(f"Fetching {IEM_OUTLOOKS_URL} (day={day}, type={iem_type}, category={category}) ...")
    resp = requests.get(IEM_OUTLOOKS_URL, headers=FETCH_HEADERS, params=params, timeout=60)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        base = next(n[:-4] for n in zf.namelist() if n.lower().endswith(".shp"))
        shp_bytes = io.BytesIO(zf.read(base + ".shp"))
        shx_bytes = io.BytesIO(zf.read(base + ".shx"))
        dbf_bytes = io.BytesIO(zf.read(base + ".dbf"))
    reader = shapefile.Reader(shp=shp_bytes, shx=shx_bytes, dbf=dbf_bytes)

    # "Latest cycle" has to be anchored across ALL categories in the
    # shapefile, not just `category`'s own rows -- CATEGORICAL is always
    # issued every cycle, but TORNADO/WIND/HAIL are sometimes omitted
    # entirely from a cycle's product when SPC has zero probability
    # anywhere in the country for that hazard. Confirmed live: a quiet day
    # can have TORNADO rows only for a stale, already-expired cycle from
    # over 24h earlier while WIND/HAIL/CATEGORICAL have a same-day one.
    # Anchoring to `category`'s own max ISSUE would silently show that
    # stale cycle as if current; anchoring to the whole shapefile's max
    # ISSUE instead means an empty `category` at the true latest cycle
    # correctly renders as "no risk this cycle" (see the not-styled ->
    # no-risk-map path in build_map), not old data.
    all_records = list(reader.iterShapeRecords())
    if not all_records:
        # No rows for ANY category across the whole fetch window -- unlike
        # `category` itself being empty at the latest cycle (a legitimate
        # zero-probability result, handled below), this means IEM had
        # nothing at all to mirror for this day/type, which over a 48h
        # window is a real problem (feed outage, bad params), not weather.
        sys.exit(f"IEM returned no outlook data at all for day={day}, type={iem_type} "
                 f"within the last {IEM_FETCH_WINDOW_HOURS}h -- feed issue, not a quiet day.")
    latest_issue = max(sr.record["ISSUE"] for sr in all_records)
    rows = [sr for sr in all_records if sr.record["CATEGORY"] == category and sr.record["ISSUE"] == latest_issue]

    placemarks = []
    for sr in rows:
        rings = _shapefile_rings(sr.shape)
        if not rings:
            continue
        threshold = sr.record["THRESHOLD"]
        label2 = None
        if hazard_label and not threshold.startswith("CIG"):
            pct = f"{float(threshold) * 100:.0f}"
            label, label2 = pct, f"{pct}% {hazard_label.title()} Risk"
        else:
            label = threshold
        fields = {
            "LABEL": label,
            "VALID_ISO": _iem_iso(sr.record["ISSUE"]),
            "EXPIRE_ISO": _iem_iso(sr.record["EXPIRE"]),
        }
        if label2:
            fields["LABEL2"] = label2
        placemarks.append({"fields": fields, "rings": rings})
    return placemarks


# ---------------------------------------------------------------------------
# Date formatting per source
# ---------------------------------------------------------------------------

def _format_range(s, e):
    if s.month == e.month:
        return f"valid {s.strftime('%b')} {s.day}–{e.day}, {e.year}"
    return f"valid {s.strftime('%b %d')}–{e.strftime('%b %d')}, {e.year}"


def date_from_fields(start_key, end_key):
    """CPC's date fields land in each placemark's description table, just
    under a different label per product line ("Start_Date" for the heat
    outlook, "Start Date" for the temp/precip outlooks)."""
    def fn(placemarks, fetched_at):
        starts, ends = [], []
        for pm in placemarks:
            f = pm["fields"]
            if f.get(start_key):
                starts.append(datetime.strptime(f[start_key], "%m/%d/%Y"))
            if f.get(end_key):
                ends.append(datetime.strptime(f[end_key], "%m/%d/%Y"))
        if not starts or not ends:
            return "valid date range unavailable"
        return _format_range(min(starts), max(ends))
    return fn


def date_from_valid_expire_iso(placemarks, fetched_at):
    valids, expires = [], []
    for pm in placemarks:
        f = pm["fields"]
        if f.get("VALID_ISO"):
            valids.append(datetime.fromisoformat(f["VALID_ISO"]))
        if f.get("EXPIRE_ISO"):
            expires.append(datetime.fromisoformat(f["EXPIRE_ISO"]))
    if not valids or not expires:
        return "valid period unavailable"
    v, e = min(valids), max(expires)
    return f"valid {v.strftime('%b %d, %H')}Z–{e.strftime('%b %d, %H')}Z"


def date_from_fetch_time(placemarks, fetched_at):
    """WPC's Excessive Rainfall Outlook KML carries no embedded date --
    fall back to today (the outlook is always for the current cycle)."""
    return f"issued {datetime.now().strftime('%b %d, %Y')}"


def date_from_usdm_fields(placemarks, fetched_at):
    """USDM's ValidStart/ValidEnd come through as epoch-millisecond ints
    (ArcGIS's GeoJSON date encoding), one pair per DM feature but always
    the same pair -- the whole weekly release shares one valid period."""
    starts, ends = [], []
    for pm in placemarks:
        f = pm["fields"]
        if f.get("ValidStart") is not None:
            starts.append(datetime.utcfromtimestamp(f["ValidStart"] / 1000))
        if f.get("ValidEnd") is not None:
            ends.append(datetime.utcfromtimestamp(f["ValidEnd"] / 1000))
    if not starts or not ends:
        return "valid date range unavailable"
    return _format_range(min(starts), max(ends))


# ---------------------------------------------------------------------------
# Overlap striping -- for products with more than one independent hazard
# axis (e.g. SPC's fire-weather-index tiers vs. its separate dry-thunderstorm
# risk), alpha-stacking two overlapping fills blends into a color matching
# neither hazard. Same diagonal-candy-stripe technique as
# columbia-basin-alerts-map uses for overlapping NWS alerts.
# ---------------------------------------------------------------------------

def hex_to_rgb(hexcolor):
    hexcolor = hexcolor.lstrip("#")
    return tuple(int(hexcolor[i:i+2], 16) for i in (0, 2, 4))


# Degree^2 area floor for keeping a polygon from an overlay op. Real slivers
# of interest are many orders of magnitude bigger than this; anything under
# it is floating-point noise from touching boundaries.
MIN_POLY_AREA = 1e-8


def polygons_only(geom):
    """Drop degenerate Point/LineString/near-zero-area slivers that
    shapely's intersection and difference ops leave behind at touching
    polygon boundaries. Left in, cartopy's projection code can't cut a
    degenerate ring cleanly and falls back to covering the entire
    projection disk instead of the sliver's true (near-zero) extent --
    which is what made overlap-stripe fills bleed across the whole map."""
    if geom.geom_type == "GeometryCollection":
        parts = [g for g in geom.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
        geom = unary_union(parts) if parts else ShPolygon()
    if geom.geom_type not in ("Polygon", "MultiPolygon"):
        return ShPolygon()
    polys = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
    kept = [p for p in polys if p.area > MIN_POLY_AREA]
    if not kept:
        return ShPolygon()
    return unary_union(kept) if len(kept) > 1 else kept[0]


def make_stripe_image(colors, width_px, height_px, stripe_px=20):
    """Diagonal candy-stripe raster alternating full-opacity bands of
    each color in `colors`, sized to cover width_px x height_px."""
    yy, xx = np.mgrid[0:height_px, 0:width_px]
    band = ((xx + yy) // stripe_px) % len(colors)
    img = np.zeros((height_px, width_px, 3), dtype=np.uint8)
    for i, c in enumerate(colors):
        img[band == i] = hex_to_rgb(c)
    return img


def draw_hazard_layers(ax, pc, styled, ax_w_px, ax_h_px):
    """Draw the parsed hazard polygons, partitioned into disjoint regions
    first rather than alpha-stacked directly, so a region covered by more
    than one same-severity-scale polygon (e.g. Critical nested inside
    Elevated, or Slight nested inside Marginal inside General Thunder)
    renders as one solid color instead of the more severe polygon's
    semi-transparent fill letting the less severe one's color show through
    underneath. Regions where two different hazard axes overlap (see the
    "axis" style field -- e.g. SPC's fire-weather-index tiers vs. its
    separate dry-thunderstorm risk) get a candy-stripe fill instead, since
    neither axis is "more severe" than the other."""
    # Union polygons sharing a label (defensive -- each category is
    # typically already a single placemark) before partitioning.
    by_label = {}
    for item in styled:
        entry = by_label.setdefault(item["label"], {**item, "geoms": []})
        entry["geoms"].append(item["geom"])
    labels = []
    for label, entry in by_label.items():
        geom = entry["geoms"][0] if len(entry["geoms"]) == 1 else unary_union(entry["geoms"])
        labels.append({**entry, "geom": geom})
    labels.sort(key=lambda d: d["order_key"])

    # Partition into disjoint regions, each tagged with the labels covering it.
    partition = []  # list of (geom, tuple of label dicts)
    for lab in labels:
        next_partition = []
        remaining = lab["geom"]
        for cell_geom, cell_labels in partition:
            overlap = polygons_only(cell_geom.intersection(remaining))
            if not overlap.is_empty:
                next_partition.append((overlap, cell_labels + (lab,)))
            rest = polygons_only(cell_geom.difference(remaining))
            if not rest.is_empty:
                next_partition.append((rest, cell_labels))
            remaining = polygons_only(remaining.difference(cell_geom))
        if not remaining.is_empty:
            next_partition.append((remaining, (lab,)))
        partition = next_partition

    OVERLAP_EDGE = "#4a4a4a"
    for i, (geom, cell_labels) in enumerate(partition):
        if geom.is_empty:
            continue
        axes_present = {l.get("axis", "primary") for l in cell_labels}
        if len(axes_present) <= 1:
            # Single axis (including the common single-label case) -- the
            # most severe category's solid color wins, same as unstriped.
            top = max(cell_labels, key=lambda l: l["order_key"])
            ax.add_geometries([geom], crs=pc, facecolor=top["color"], edgecolor=top["color"],
                               linewidth=1.2, alpha=top["alpha"], zorder=3 + i)
            continue

        # Cross-axis overlap: stripe with one representative (most severe
        # within its own axis) color per axis present.
        rep_by_axis = {}
        for l in cell_labels:
            axis = l.get("axis", "primary")
            if axis not in rep_by_axis or l["order_key"] > rep_by_axis[axis]["order_key"]:
                rep_by_axis[axis] = l
        colors = [rep_by_axis[a]["color"] for a in sorted(rep_by_axis)]
        alpha = max(l["alpha"] for l in cell_labels)
        stripe_img = make_stripe_image(colors, ax_w_px, ax_h_px)
        proj_geom = ax.projection.project_geometry(geom, pc)
        clip_path = shapely_to_path(proj_geom)
        clip_patch = PathPatch(clip_path, transform=ax.transData)
        # GeoAxes overrides imshow to require a CRS transform; this is
        # plain axes-fraction space, so call the base Axes.imshow.
        im = Axes.imshow(ax, stripe_img, extent=(0, 1, 0, 1), transform=ax.transAxes,
                          origin="upper", interpolation="nearest", alpha=alpha, zorder=3 + i)
        im.set_clip_path(clip_patch)
        ax.add_geometries([geom], crs=pc, facecolor="none", edgecolor=OVERLAP_EDGE,
                           linewidth=1.2, alpha=1.0, zorder=3 + i + 0.05)


# ---------------------------------------------------------------------------
# Styling per source. Each style function takes a parsed placemark and
# returns None (skip / unrecognized) or a dict with:
#   color, alpha, order_key (severity, for zorder + legend ordering), label
# ---------------------------------------------------------------------------

NORMAL_COLOR = "#b2b2b2"

HEAT_STYLE_MAP = {
    "Slight Risk of Extreme Heat":   {"color": "#f2a341", "alpha": 0.55, "order_key": 1, "label": "Slight Risk"},
    "Moderate Risk of Extreme Heat": {"color": "#d1382b", "alpha": 0.60, "order_key": 2, "label": "Moderate Risk"},
    "High Risk of Extreme Heat":     {"color": "#9c1f4a", "alpha": 0.65, "order_key": 3, "label": "High Risk"},
    "Extreme Heat":                  {"color": "#d1382b", "alpha": 0.60, "order_key": 2, "label": "Extreme Heat"},
}


def heat_style(pm):
    sty = HEAT_STYLE_MAP.get(pm["name"])
    if sty is None:
        print(f"WARNING: unrecognized heat category '{pm['name']}', skipping. Add it to HEAT_STYLE_MAP.")
        return None
    return dict(sty)


# CPC temperature/precipitation outlooks are a continuous probability (33-90%)
# rather than a handful of fixed categories, so instead of hand-picking a
# swatch per tier we sample a colormap by probability. Below/Above use
# different colormaps per variable (temp: blue/red: dry precip: brown, wet
# precip: green), matching CPC's own outlook color convention.
TEMP_CMAP = {"Above": matplotlib.colormaps["YlOrRd"], "Below": matplotlib.colormaps["Blues"]}
PRECIP_CMAP = {"Above": matplotlib.colormaps["Greens"], "Below": matplotlib.colormaps["YlOrBr"]}


def _prob_ramp_color(cmap, probability):
    t = 0.30 + 0.60 * max(0.0, min(1.0, (probability - 33.0) / (90.0 - 33.0)))
    return mcolors.to_hex(cmap(t))


def cpc_prob_style(cmap_by_direction):
    def style(pm):
        fields = pm["fields"]
        category = fields.get("Category", "").strip()
        try:
            probability = float(fields.get("Probability", 0))
        except ValueError:
            probability = 0.0
        if category in ("Normal", "EC", ""):
            label = "Equal Chances" if category == "EC" else "Near Normal"
            return {"color": NORMAL_COLOR, "alpha": 0.55, "order_key": 0, "label": label}
        if category not in ("Above", "Below"):
            print(f"WARNING: unrecognized outlook category '{category}', skipping.")
            return None
        color = _prob_ramp_color(cmap_by_direction[category], probability)
        order_key = probability if category == "Above" else -probability
        label = f"{probability:.0f}% {category} Normal"
        return {"color": color, "alpha": 0.68, "order_key": order_key, "label": label}
    return style


SPC_FIRE_STYLE = {
    # Official SPC categorical colors, from the fire_weather/SPC_firewx
    # MapServer renderer (mapservices.weather.noaa.gov) rather than a
    # hand-picked approximation. "axis" marks which independent hazard
    # dimension a category belongs to -- see draw_hazard_layers.
    "ELEV": {"color": "#e69800", "alpha": 0.65, "order_key": 1, "label": "Elevated", "axis": "index"},
    "CRIT": {"color": "#ff0000", "alpha": 0.65, "order_key": 2, "label": "Critical", "axis": "index"},
    "EXTM": {"color": "#e600a9", "alpha": 0.65, "order_key": 3, "label": "Extreme", "axis": "index"},
    # Dry thunderstorm risk is a separate hazard axis (lightning without
    # rain), not a more severe fire-weather-index tier -- distinct hue.
    # ("Iso DryT" in SPC's own renderer; "Scattered DryT" reuses Critical's red.)
    "IDRT": {"color": "#732600", "alpha": 0.55, "order_key": 4, "label": "Isolated Dry Thunderstorms",
              "axis": "dry_thunder"},
}

SPC_SEVERE_STYLE = {
    "TSTM": {"color": "#8fc48f", "alpha": 0.55, "order_key": 1, "label": "General Thunder"},
    "MRGL": {"color": "#3f8f4f", "alpha": 0.58, "order_key": 2, "label": "Marginal"},
    "SLGT": {"color": "#e8c84b", "alpha": 0.62, "order_key": 3, "label": "Slight"},
    "ENH":  {"color": "#e2872f", "alpha": 0.64, "order_key": 4, "label": "Enhanced"},
    "MDT":  {"color": "#c23b2b", "alpha": 0.66, "order_key": 5, "label": "Moderate"},
    "HIGH": {"color": "#b23b9c", "alpha": 0.68, "order_key": 6, "label": "High"},
}


def spc_style(style_map, warning_label):
    def style(pm):
        code = pm["fields"].get("LABEL", "")
        sty = style_map.get(code)
        if sty is None:
            print(f"WARNING: unrecognized {warning_label} category '{code}', skipping.")
            return None
        return dict(sty)
    return style


# SPC's own KML embeds each tornado/wind/hail probability tier's fill/stroke
# hex directly in ExtendedData; IEM's shapefile mirror (fetch_iem_outlook)
# has no color fields at all. Only the 5% and 15% tiers are confirmed
# against a real spc.noaa.gov KML capture (fill #C5A392/#FFEB7F, stroke
# #8B4726/#FF9600) -- SPC doesn't publish hex values for the rest of the
# scale anywhere findable (its own info page and two mapservices.weather.gov
# MapServer legend endpoints both 404'd), so this interpolates a smooth ramp
# through those two confirmed anchors and on toward warmer, more saturated
# hues at the higher tiers -- the same tan-to-magenta progression
# SPC_SEVERE_STYLE uses across its own MRGL->HIGH tiers, extended down to
# 2% for tornado's lowest tier (wind/hail bottom out at 5%). Used as a
# fallback only when a placemark has no real fill/stroke (i.e. every
# IEM-sourced product).
SPC_PROB_FILL_RAMP = mcolors.LinearSegmentedColormap.from_list(
    "spc_prob_fill", ["#C5A392", "#FFEB7F", "#FFA733", "#FF6B35", "#C81E3A"])
SPC_PROB_STROKE_RAMP = mcolors.LinearSegmentedColormap.from_list(
    "spc_prob_stroke", ["#8B4726", "#FF9600", "#E85D04", "#C1272D", "#7A0C1E"])
SPC_PROB_MIN, SPC_PROB_MAX = 2.0, 60.0


def _spc_prob_ramp_color(cmap, probability):
    t = max(0.0, min(1.0, (probability - SPC_PROB_MIN) / (SPC_PROB_MAX - SPC_PROB_MIN)))
    return mcolors.to_hex(cmap(t))


def spc_prob_style(hazard_label):
    """Style for SPC's Day 1/2 Tornado, Wind, and Hail probabilistic
    outlooks. Unlike the fixed categorical tiers above (SPC_FIRE_STYLE,
    SPC_SEVERE_STYLE), these are a probability scale (2/5/15/30/45/60%,
    tornado only goes down to 2%) plus a "CIG1"/"CIG2" tier -- SPC's
    current names for what's commonly called "significant" risk, confirmed
    against a live fetch. Prefers the fill/stroke colors NOAA embeds
    directly in its own KML when present, falling back to
    SPC_PROB_FILL_RAMP/_STROKE_RAMP for IEM-sourced placemarks, which carry
    no color fields. CIG* gets its own "axis" (same stripe-on-overlap
    mechanism spc_fire uses for dry-thunderstorm risk) since it can overlap
    a probability polygon rather than nesting inside it like the fixed
    categorical tiers do."""
    def style(pm):
        fields = pm["fields"]
        code = fields.get("LABEL", "")
        label = fields.get("LABEL2") or code
        if code.startswith("CIG"):
            color = fields.get("stroke") or fields.get("fill") \
                or mcolors.to_hex(SPC_PROB_STROKE_RAMP(1.0))
            return {"color": color, "alpha": 0.35, "order_key": 99,
                    "label": f"Significant {hazard_label.title()} Risk", "axis": "significant"}
        try:
            probability = float(code)
        except ValueError:
            print(f"WARNING: unrecognized {hazard_label} category '{code}', skipping.")
            return None
        fill = fields.get("fill") or _spc_prob_ramp_color(SPC_PROB_FILL_RAMP, probability)
        return {"color": fill, "alpha": 0.7, "order_key": probability, "label": label, "axis": "index"}
    return style


WPC_ERO_STYLE = [
    ("Marginal", {"color": "#6fae6f", "alpha": 0.58}),
    ("Slight",   {"color": "#e0c84b", "alpha": 0.62}),
    ("Moderate", {"color": "#d9622f", "alpha": 0.65}),
    ("High",     {"color": "#a83b9c", "alpha": 0.68}),
]


def wpc_ero_style(pm):
    name = pm["name"]
    for i, (key, sty) in enumerate(WPC_ERO_STYLE):
        if name.startswith(key):
            return {**sty, "order_key": i + 1, "label": name}
    print(f"WARNING: unrecognized excessive rainfall category '{name}', skipping.")
    return None


# Official USDM palette (droughtmonitor.unl.edu legend). Categories are
# cumulative -- each DM polygon is "this category or worse" -- so, like the
# SPC severe tiers, drawing least to most severe with the more severe one on
# top is exactly right with no overlap striping needed.
USDM_STYLE = {
    0: {"color": "#ffff00", "alpha": 0.65, "order_key": 1, "label": "D0 — Abnormally Dry"},
    1: {"color": "#fcd37f", "alpha": 0.65, "order_key": 2, "label": "D1 — Moderate Drought"},
    2: {"color": "#ffaa00", "alpha": 0.65, "order_key": 3, "label": "D2 — Severe Drought"},
    3: {"color": "#e60000", "alpha": 0.65, "order_key": 4, "label": "D3 — Extreme Drought"},
    4: {"color": "#730000", "alpha": 0.65, "order_key": 5, "label": "D4 — Exceptional Drought"},
}


def usdm_style(pm):
    dm = pm["fields"].get("DM")
    sty = USDM_STYLE.get(dm)
    if sty is None:
        print(f"WARNING: unrecognized drought category DM={dm}, skipping.")
        return None
    return dict(sty)


# ---------------------------------------------------------------------------
# Product registry
# ---------------------------------------------------------------------------

PRODUCTS = {
    "heat_d8_14": dict(
        title="Western U.S. Extreme Heat Hazard",
        subtitle_prefix="NWS Climate Prediction Center — Day 8–14 Outlook",
        agency="CPC",
        urls=[
            "https://www.cpc.ncep.noaa.gov/products/predictions/threats/excess_heat_prob_D8_14.kml",
            "https://www.cpc.ncep.noaa.gov/products/predictions/threats/temp_D8_14.kml",
        ],
        parser=parse_kml_named,
        style=heat_style,
        date=date_from_fields("Start_Date", "End_Date"),
        output="western_us_extreme_heat_hazard.png",
    ),
    "temp_6_10": dict(
        title="Western U.S. 6–10 Day Temperature Outlook",
        subtitle_prefix="NWS Climate Prediction Center — 6–10 Day Outlook",
        agency="CPC",
        urls=["https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/610temp_latest.kmz"],
        parser=parse_kml_named,
        style=cpc_prob_style(TEMP_CMAP),
        date=date_from_fields("Start Date", "End Date"),
        output="western_us_temp_6_10.png",
    ),
    "precip_6_10": dict(
        title="Western U.S. 6–10 Day Precipitation Outlook",
        subtitle_prefix="NWS Climate Prediction Center — 6–10 Day Outlook",
        agency="CPC",
        urls=["https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/610prcp_latest.kmz"],
        parser=parse_kml_named,
        style=cpc_prob_style(PRECIP_CMAP),
        date=date_from_fields("Start Date", "End Date"),
        output="western_us_precip_6_10.png",
    ),
    "temp_8_14": dict(
        title="Western U.S. 8–14 Day Temperature Outlook",
        subtitle_prefix="NWS Climate Prediction Center — 8–14 Day Outlook",
        agency="CPC",
        urls=["https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/814temp_latest.kmz"],
        parser=parse_kml_named,
        style=cpc_prob_style(TEMP_CMAP),
        date=date_from_fields("Start Date", "End Date"),
        output="western_us_temp_8_14.png",
    ),
    "precip_8_14": dict(
        title="Western U.S. 8–14 Day Precipitation Outlook",
        subtitle_prefix="NWS Climate Prediction Center — 8–14 Day Outlook",
        agency="CPC",
        urls=["https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/814prcp_latest.kmz"],
        parser=parse_kml_named,
        style=cpc_prob_style(PRECIP_CMAP),
        date=date_from_fields("Start Date", "End Date"),
        output="western_us_precip_8_14.png",
    ),
    "temp_wk34": dict(
        title="Western U.S. Week 3–4 Temperature Outlook",
        subtitle_prefix="NWS Climate Prediction Center — Week 3–4 Outlook",
        agency="CPC",
        urls=["https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/wk34temp_latest.kmz"],
        parser=parse_kml_named,
        style=cpc_prob_style(TEMP_CMAP),
        date=date_from_fields("Start Date", "End Date"),
        output="western_us_temp_wk34.png",
    ),
    "precip_wk34": dict(
        title="Western U.S. Week 3–4 Precipitation Outlook",
        subtitle_prefix="NWS Climate Prediction Center — Week 3–4 Outlook",
        agency="CPC",
        urls=["https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/wk34prcp_latest.kmz"],
        parser=parse_kml_named,
        style=cpc_prob_style(PRECIP_CMAP),
        date=date_from_fields("Start Date", "End Date"),
        output="western_us_precip_wk34.png",
    ),
    "spc_fire": dict(
        title="Western U.S. Fire Weather Outlook",
        subtitle_prefix="NWS Storm Prediction Center — Day 1 Outlook",
        agency="SPC",
        iem=dict(day=1, iem_type="F", category="FIRE WEATHER CATEGORICAL"),
        style=spc_style(SPC_FIRE_STYLE, "fire outlook"),
        date=date_from_valid_expire_iso,
        output="western_us_spc_fire.png",
    ),
    "spc_fire_day2": dict(
        title="Western U.S. Fire Weather Outlook — Day 2",
        subtitle_prefix="NWS Storm Prediction Center — Day 2 Outlook",
        agency="SPC",
        iem=dict(day=2, iem_type="F", category="FIRE WEATHER CATEGORICAL"),
        style=spc_style(SPC_FIRE_STYLE, "fire outlook"),
        date=date_from_valid_expire_iso,
        output="western_us_spc_fire_day2.png",
    ),
    "spc_severe": dict(
        title="Western U.S. Severe Weather Outlook",
        subtitle_prefix="NWS Storm Prediction Center — Day 1 Categorical Outlook",
        agency="SPC",
        iem=dict(day=1, iem_type="C", category="CATEGORICAL"),
        style=spc_style(SPC_SEVERE_STYLE, "severe outlook"),
        date=date_from_valid_expire_iso,
        output="western_us_spc_severe.png",
    ),
    "spc_convective_day2": dict(
        title="Western U.S. Severe Weather Outlook — Day 2",
        subtitle_prefix="NWS Storm Prediction Center — Day 2 Categorical Outlook",
        agency="SPC",
        iem=dict(day=2, iem_type="C", category="CATEGORICAL"),
        style=spc_style(SPC_SEVERE_STYLE, "severe outlook"),
        date=date_from_valid_expire_iso,
        output="western_us_spc_convective_day2.png",
    ),
    "spc_convective_day3": dict(
        title="Western U.S. Severe Weather Outlook — Day 3",
        subtitle_prefix="NWS Storm Prediction Center — Day 3 Categorical Outlook",
        agency="SPC",
        iem=dict(day=3, iem_type="C", category="CATEGORICAL"),
        style=spc_style(SPC_SEVERE_STYLE, "severe outlook"),
        date=date_from_valid_expire_iso,
        output="western_us_spc_convective_day3.png",
    ),
    "spc_tornado_day1": dict(
        title="Western U.S. Tornado Outlook",
        subtitle_prefix="NWS Storm Prediction Center — Day 1 Tornado Probability Outlook",
        agency="SPC",
        iem=dict(day=1, iem_type="C", category="TORNADO", hazard_label="tornado"),
        style=spc_prob_style("tornado"),
        date=date_from_valid_expire_iso,
        output="western_us_spc_tornado_day1.png",
    ),
    "spc_tornado_day2": dict(
        title="Western U.S. Tornado Outlook — Day 2",
        subtitle_prefix="NWS Storm Prediction Center — Day 2 Tornado Probability Outlook",
        agency="SPC",
        iem=dict(day=2, iem_type="C", category="TORNADO", hazard_label="tornado"),
        style=spc_prob_style("tornado"),
        date=date_from_valid_expire_iso,
        output="western_us_spc_tornado_day2.png",
    ),
    "spc_wind_day1": dict(
        title="Western U.S. Wind Outlook",
        subtitle_prefix="NWS Storm Prediction Center — Day 1 Wind Probability Outlook",
        agency="SPC",
        iem=dict(day=1, iem_type="C", category="WIND", hazard_label="wind"),
        style=spc_prob_style("wind"),
        date=date_from_valid_expire_iso,
        output="western_us_spc_wind_day1.png",
    ),
    "spc_wind_day2": dict(
        title="Western U.S. Wind Outlook — Day 2",
        subtitle_prefix="NWS Storm Prediction Center — Day 2 Wind Probability Outlook",
        agency="SPC",
        iem=dict(day=2, iem_type="C", category="WIND", hazard_label="wind"),
        style=spc_prob_style("wind"),
        date=date_from_valid_expire_iso,
        output="western_us_spc_wind_day2.png",
    ),
    "spc_hail_day1": dict(
        title="Western U.S. Hail Outlook",
        subtitle_prefix="NWS Storm Prediction Center — Day 1 Hail Probability Outlook",
        agency="SPC",
        iem=dict(day=1, iem_type="C", category="HAIL", hazard_label="hail"),
        style=spc_prob_style("hail"),
        date=date_from_valid_expire_iso,
        output="western_us_spc_hail_day1.png",
    ),
    "spc_hail_day2": dict(
        title="Western U.S. Hail Outlook — Day 2",
        subtitle_prefix="NWS Storm Prediction Center — Day 2 Hail Probability Outlook",
        agency="SPC",
        iem=dict(day=2, iem_type="C", category="HAIL", hazard_label="hail"),
        style=spc_prob_style("hail"),
        date=date_from_valid_expire_iso,
        output="western_us_spc_hail_day2.png",
    ),
    "wpc_precip": dict(
        title="Western U.S. Excessive Rainfall Outlook",
        subtitle_prefix="NWS Weather Prediction Center — Day 1 Outlook",
        agency="WPC",
        urls=["https://www.wpc.ncep.noaa.gov/kml/ero/Day_1_Excessive_Rainfall_Outlook.kmz"],
        parser=parse_kml_named,
        style=wpc_ero_style,
        date=date_from_fetch_time,
        output="western_us_wpc_precip.png",
    ),
    "drought_monitor": dict(
        title="Western U.S. Drought Monitor",
        subtitle_prefix="National Drought Mitigation Center — U.S. Drought Monitor",
        agency="NDMC",
        urls=[
            "https://services5.arcgis.com/0OTVzJS4K09zlixn/arcgis/rest/services/"
            "USDM_current/FeatureServer/0/query?where=1%3D1&outFields=DM,ValidStart,ValidEnd"
            "&returnGeometry=true&outSR=4326&f=geojson"
        ],
        parser=parse_usdm_geojson,
        style=usdm_style,
        date=date_from_usdm_fields,
        output="western_us_drought_monitor.png",
    ),
}


def fetch_source(cfg, override_path):
    """Returns (kml_text, fetched_at_header_or_None)."""
    if override_path:
        print(f"Using local file: {override_path}")
        raw = Path(override_path).read_bytes()
        fetched_at = None
    else:
        raw, fetched_at, last_err = None, None, None
        for url in cfg["urls"]:
            try:
                print(f"Fetching {url} ...")
                resp = requests.get(url, headers=FETCH_HEADERS, timeout=30)
                resp.raise_for_status()
                raw = resp.content
                fetched_at = resp.headers.get("Last-Modified")
                break
            except requests.RequestException as e:
                last_err = e
                print(f"  failed: {e}")
        if raw is None:
            sys.exit(
                "Could not fetch data from any source:\n  " + "\n  ".join(cfg["urls"]) +
                f"\nLast error: {last_err}"
            )
    if raw[:2] == b"PK":  # zip (kmz)
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            kml_name = next(n for n in zf.namelist() if n.lower().endswith(".kml"))
            text = zf.read(kml_name).decode("utf-8", errors="ignore")
    else:
        text = raw.decode("utf-8", errors="ignore")
    return text, fetched_at


def load_land():
    with open(LAND_FILE) as f:
        data = json.load(f)
    return [shapely.set_precision(shape(feat["geometry"]), grid_size=COORD_SNAP_GRID_DEG)
                    .simplify(GEOM_SIMPLIFY_TOLERANCE_DEG, preserve_topology=True)
                    .segmentize(BORDER_DENSIFY_SEGMENT_DEG)
            for feat in data["features"] if feat.get("geometry")]


def load_lakes():
    with open(STATES_LAKES_FILE) as f:
        data = json.load(f)
    return [shapely.set_precision(shape(feat["geometry"]), grid_size=COORD_SNAP_GRID_DEG)
                    .segmentize(BORDER_DENSIFY_SEGMENT_DEG)
            for feat in data["features"] if "Lake" in feat["properties"].get("featurecla", "")]


def load_boundary_lines(path, country_filter):
    """Load a Natural Earth boundary-line dataset, keeping only segments
    country_filter accepts (a function over each feature's properties).
    See the comment above GEOM_SIMPLIFY_TOLERANCE_DEG for why borders come
    from these dedicated line files rather than from outlining
    states_lakes_slim.json's admin-1 polygons."""
    with open(path) as f:
        data = json.load(f)
    return [shape(feat["geometry"]).segmentize(BORDER_DENSIFY_SEGMENT_DEG)
            for feat in data["features"] if country_filter(feat["properties"])]


def load_state_lines(country_lines):
    """State/province border lines, with any segment that duplicates an
    international border trimmed out. admin1_boundary_lines.json includes
    a state's international-facing edge as an ordinary line (e.g.
    Washington's northern border through the San Juan Islands is in there
    as if it were ANY other state boundary), independently of and not
    vertex-matched to admin0_boundary_lines.json's own line for that same
    physical stretch -- drawing both showed as two visibly diverging lines
    along the WA/BC border. Buffering the country lines out slightly and
    subtracting that from every state line removes the duplicate stretch,
    leaving the single, more-authoritative country line to represent it.

    Also drops each coastal state's 3-nautical-mile offshore maritime
    boundary (its state-waters extent, e.g. California/Oregon/Washington),
    which Natural Earth includes as ordinary admin-1 boundary lines running
    parallel to, but detached from, the actual coastline -- confirmed by
    distance from the (unsimplified, for an accurate coastline reference)
    land layer: every offshore boundary segment in this frame sits >=0.026
    deg out, while every genuine land-touching state line sits right on it,
    a clean, wide margin either side of OFFSHORE_LINE_DISTANCE_DEG."""
    lines = load_boundary_lines(ADMIN1_LINES_FILE, lambda props: props.get("adm0_name") in TARGET_COUNTRIES)
    country_buffer = unary_union(country_lines).buffer(STATE_COUNTRY_DEDUP_BUFFER_DEG)
    trimmed = (line.difference(country_buffer) for line in lines)
    trimmed = [g for g in trimmed if not g.is_empty]

    with open(LAND_FILE) as f:
        land_data = json.load(f)
    land_union = unary_union([shape(feat["geometry"]) for feat in land_data["features"] if feat.get("geometry")])
    return [g for g in trimmed if g.distance(land_union) <= OFFSHORE_LINE_DISTANCE_DEG]


def load_country_lines():
    return load_boundary_lines(
        ADMIN0_LINES_FILE,
        lambda props: props.get("adm0_left") in TARGET_COUNTRIES and props.get("adm0_right") in TARGET_COUNTRIES,
    )


def build_map(product_key, output_path, override_path=None):
    cfg = PRODUCTS[product_key]
    poppins_reg = fm.FontProperties(fname=POPPINS_REG_PATH)
    poppins_semibold = fm.FontProperties(fname=POPPINS_MED_PATH)

    if "iem" in cfg:
        placemarks = fetch_iem_outlook(**cfg["iem"])
        fetched_at = None
    else:
        text, fetched_at = fetch_source(cfg, override_path)
        placemarks = cfg["parser"](text)
        # Only the KML path treats an empty result as a hard failure --
        # those sources essentially always emit some placemark structurally
        # (e.g. an all-clear "Equal Chances" category), so empty usually
        # means something didn't parse right. fetch_iem_outlook already
        # distinguishes "IEM has nothing at all" (raises there) from
        # "this hazard is genuinely at zero right now" (returns [] here,
        # on purpose) -- the latter should fall through to the ordinary
        # not-styled -> no-risk-map path below, same as any other quiet day.
        if not placemarks:
            sys.exit(f"No placemarks found for '{product_key}' — is the source format as expected?")

    styled = []
    for pm in placemarks:
        sty = cfg["style"](pm)
        if sty is None:
            continue
        polys = [ShPolygon(ring) for ring in pm["rings"]]
        geom = polys[0] if len(polys) == 1 else ShMultiPolygon(polys)
        if not geom.is_valid:
            # Self-intersecting rings (seen in USDM's multi-hundred-part
            # category polygons) make matplotlib/cartopy fill well beyond
            # the geometry's real extent -- e.g. D0 bled into Canada,
            # Mexico, and the Pacific despite genuinely stopping at the
            # US border. make_valid resolves the self-intersections rather
            # than papering over them with a buffer(0) hull-ish fudge.
            geom = polygons_only(shapely.make_valid(geom))
        if not geom.intersects(MAP_BBOX):
            continue  # outside the Western US frame -- drop so it doesn't pad out the legend
        styled.append({**sty, "geom": geom})
    if not styled:
        # A legitimate "no risk anywhere in the frame today" result -- common
        # outside severe weather season, or for narrower products like hail
        # on a quiet day -- not an error. Render a normal, current map with
        # no shaded areas and a small note instead of a legend, rather than
        # failing the run and leaving a stale, possibly-misleading previous
        # map (with old shading) published in its place.
        print(f"No recognized categories for '{product_key}' within the map frame -- rendering a no-risk map.")
    styled.sort(key=lambda d: d["order_key"])

    date_str = cfg["date"](placemarks, fetched_at)
    print(f"Parsed {len(styled)} shaded areas across {len(set(d['label'] for d in styled))} categories. {date_str}")

    print("Loading basemap layers...")
    land_geoms = load_land()
    lake_geoms = load_lakes()
    country_lines = load_country_lines()
    state_lines = load_state_lines(country_lines)

    proj = ccrs.NearsidePerspective(central_longitude=CENTER_LON, central_latitude=CENTER_LAT,
                                     satellite_height=4_000_000)
    pc = ccrs.PlateCarree()

    fig = plt.figure(figsize=(FIG_WIDTH_IN, FIG_HEIGHT_IN), dpi=FIG_DPI)
    fig.patch.set_facecolor("#f7f6f2")

    ax = fig.add_axes(AXES_RECT, projection=proj)
    ax.set_extent([LON_MIN, LON_MAX, LAT_MIN, LAT_MAX], crs=pc)
    ax.patch.set_facecolor("white")

    # Pixel size of the map's plotted area, used for candy-stripe fills
    # (draw_hazard_layers) at a consistent on-screen stripe width.
    fig.canvas.draw()
    ax_bbox = ax.get_window_extent()
    ax_w_px, ax_h_px = int(ax_bbox.width), int(ax_bbox.height)

    ax.add_geometries(land_geoms, crs=pc, facecolor="#e3e1da", edgecolor="none", linewidth=0, zorder=1)
    ax.add_geometries(state_lines, crs=pc, facecolor="none", edgecolor="#b9b6ac", linewidth=0.7, zorder=2)
    ax.add_geometries(lake_geoms, crs=pc, facecolor="white", edgecolor="#b9b6ac", linewidth=0.7, zorder=2.2)
    ax.add_geometries(country_lines, crs=pc, facecolor="none", edgecolor="#9a978c", linewidth=1.1, zorder=2.5)

    # Outlook polygons, partitioned so overlapping same-axis categories
    # render as one solid color (most severe wins) and cross-axis overlaps
    # get striped -- see draw_hazard_layers.
    draw_hazard_layers(ax, pc, styled, ax_w_px, ax_h_px)

    # City labels
    for name, lon, lat, pos in CITIES:
        ax.plot(lon, lat, marker="o", markersize=5.0, color="#3b3a35", zorder=100,
                mec="white", mew=0.7, transform=pc)
        dx = 0.3 if pos == "right" else (-0.3 if pos == "left" else 0)
        dy = 0.38 if pos == "above" else (-0.52 if pos == "below" else 0)
        ha = "left" if pos == "right" else ("right" if pos == "left" else "center")
        va = "bottom" if pos == "above" else ("top" if pos == "below" else "center")
        txt = ax.text(lon + dx, lat + dy, name, fontsize=14.01, fontproperties=poppins_semibold,
                       color="#2b2a26", ha=ha, va=va, zorder=101, transform=pc)
        txt.set_path_effects([pe.withStroke(linewidth=1.65, foreground=(1, 1, 1, 0.6))])

    ax.spines['geo'].set_edgecolor('black')
    ax.spines['geo'].set_linewidth(1.6)

    # Legend — one swatch per distinct label actually present, most severe first.
    # Anchor position is the same MAP_FRAME_INSET_PX away from the axes
    # frame's lower-left corner as the logo sits from the frame's
    # lower-right corner. Cartopy shrinks the axes box to preserve the
    # projection's aspect ratio, so the rendered frame doesn't sit at
    # AXES_RECT's raw figure-fraction position -- ask the canvas where it
    # actually landed instead of assuming.
    fig.canvas.draw()
    frame_px = ax.get_window_extent()
    legend_anchor = (
        (frame_px.x0 + MAP_FRAME_INSET_PX) / (FIG_WIDTH_IN * FIG_DPI),
        (frame_px.y0 + MAP_FRAME_INSET_PX) / (FIG_HEIGHT_IN * FIG_DPI),
    )
    if not styled:
        fig.text(legend_anchor[0], legend_anchor[1], "No areas of concern",
                  fontsize=8.25, fontproperties=poppins_reg, color="#5a584f",
                  ha="left", va="bottom",
                  bbox=dict(facecolor="white", alpha=0.7, edgecolor="none", boxstyle="round,pad=0.35"))
    else:
        legend_by_label = {}
        for item in styled:
            legend_by_label.setdefault(item["label"], item)
        ordered = sorted(legend_by_label.values(), key=lambda d: d["order_key"], reverse=True)
        handles = [Patch(facecolor=d["color"], edgecolor=d["color"], alpha=d["alpha"], label=d["label"])
                   for d in ordered]
        # Products with more than a handful of categories (e.g. the drought
        # monitor's five D0-D4 tiers) get a second column so the box stays
        # short enough not to grow up into a city label near the bottom-left
        # corner, instead of just getting taller.
        legend_ncols = 2 if len(handles) > 4 else 1
        leg = fig.legend(handles=handles, loc="lower left", frameon=True, fontsize=8.25,
                          prop=poppins_reg, handlelength=1.05, handleheight=1.05, borderpad=0.3,
                          facecolor="white", framealpha=0.7, edgecolor="none", ncols=legend_ncols,
                          bbox_to_anchor=legend_anchor)
        for text in leg.get_texts():
            text.set_color("#2b2a26")

    # Title & subtitle above the map
    fig.text(0.03, 0.975, cfg["title"], fontsize=22,
              fontproperties=poppins_reg, color="#2b2a26", ha="left", va="top")
    fig.text(0.03, 0.935, f"{cfg['subtitle_prefix']}, {date_str}",
              fontsize=12, fontproperties=poppins_reg, color="#5a584f", ha="left", va="top")

    # Attribution
    fig.text(0.5, 0.012, f"NOAA / {cfg['agency']} — Ingalls Weather", fontsize=9,
              fontproperties=poppins_reg, color="#8a887e", ha="center", va="bottom")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, facecolor=fig.get_facecolor(), dpi=200)
    plt.close(fig)
    print(f"Saved base map to {output_path}")

    # ---- Composite logo, bottom-right, snug inside the frame ----
    if LOGO_FILE.exists():
        base = Image.open(output_path).convert("RGB")
        bw, bh = base.size
        # Locate the black map frame so the logo sits just inside it
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
    parser = argparse.ArgumentParser(description="Build an Ingalls Weather Western U.S. NOAA outlook map.")
    parser.add_argument("--product", choices=sorted(PRODUCTS), default="heat_d8_14",
                         help="Which outlook to render (default: heat_d8_14). See module docstring for the list.")
    parser.add_argument("--file", type=Path, default=None,
                         help="Render from a local KML/KMZ instead of fetching the current one live.")
    parser.add_argument("--out", type=Path, default=None,
                         help="Output PNG path (default: output/<product's default filename>).")
    args = parser.parse_args()

    if args.file and not args.file.exists():
        sys.exit(f"--file {args.file} not found.")

    out_path = args.out or (OUTPUT_DIR / PRODUCTS[args.product]["output"])
    build_map(args.product, out_path, override_path=args.file)

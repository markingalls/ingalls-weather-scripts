"""
Current Wildfires Map -- canonical map builder
Ingalls Weather

Same domain as ../dew-point-storm-map/ (Prince George BC to Winnemucca NV,
Bella Coola BC to Yellowstone WY), plotting currently active wildfires
from four separate government sources, merged into one map since none of
them individually covers the whole domain. Markers are colored gray if
contained ("Being Held" or better -- see "Containment coloring" near
NEW_FIRE_HOURS below for why this is a status-category proxy, not a
literal percentage, for every source except CA), else red if reported in
the last 24h, else orange. Fires over 25,000 acres get a dashed black
outline ring, over 100,000 acres a solid one (see LARGE_FIRE_ACRES/
MEGA_FIRE_ACRES below). Small (<10ac) or stale (90+ days no update)
contained fires, small *and* stale (28+ days) existing fires, and any
existing fire stale 60+ days regardless of size, are dropped after
merging to cut clutter, except new fires, always shown at any size (see
STALE_CONTAINED_DAYS/STALE_EXISTING_SMALL_DAYS/STALE_EXISTING_ANY_DAYS/
MIN_VISIBLE_ACRES/is_visible below).

  US (WA/OR/ID/w.MT/n.NV/n.UT/nw.WY): WildCAD-E, the interagency dispatch
    CAD system used by essentially every US wildland fire dispatch center.
    There's no single national feed -- each dispatch center publishes its
    own incident list, so this queries every center whose area overlaps
    the domain and merges the results.
  California: WildCAD-E doesn't cover CA, but the domain's southern edge
    dips into the northernmost strip of it -- filled in from NIFC's
    nationwide WFIGS feature service, scoped to CA only (see CALFIRE_URL
    below for why WFIGS instead of CAL FIRE's own site).
  British Columbia: BC Wildfire Service's public "Fire Locations - Current"
    ArcGIS feature service.
  Alberta: Alberta Wildfire's public "wildfire_location_active" ArcGIS
    feature service (pre-filtered to active fires by the service itself).

DATA SOURCES
------------
WildCAD-E's public web app (wildwebe.net) calls a REST API at
    https://snknmqmon6.execute-api.us-west-2.amazonaws.com/centers/<DC>/incidents?fromDate=...&toDate=...
(found by inspecting the app's JS bundle -- there's no published API doc).
Each dispatch center returns every incident of every type (Wildfire, Smoke
Check, False Alarm, Debris Fire, Vehicle Fire, Structure Fire, etc.) it
logged in the date window, each with a fire_status JSON blob carrying
out/contain/control timestamps. "Currently active" is inferred, not an
explicit flag: type == "Wildfire" and fire_status.control is null (not yet
declared controlled). WildCAD's "out" timestamp turns out to be
essentially never populated even for fires contained/controlled weeks ago,
so it's useless as an activity filter -- "control" is the more reliable
signal that suppression is effectively over. The API also has a bug: it
returns longitude as a bare positive magnitude with no western-hemisphere
sign, worked around by negating unconditionally (safe since every US
dispatch center queried here is west of the prime meridian).

BC Wildfire Service (found via its ArcGIS Hub listing, "Fire Locations -
Current"):
    https://services6.arcgis.com/ubm4tcTYICKBpist/arcgis/rest/services/BCWS_ActiveFires_PublicView/FeatureServer/0
Every fire this season is a point in this layer, active or not, each with
an explicit FIRE_STATUS ("Out", "Out of Control", "Being Held", "Under
Control", "Fire of Note"). "Currently active" here = FIRE_STATUS != "Out"
-- a different (looser) definition than WildCAD's "not yet controlled"
because BC's status model doesn't map cleanly onto WildCAD's, and BC's own
"Out" is a clean, explicit signal WildCAD's field of the same name isn't.
Size (CURRENT_SIZE) is in hectares; converted to acres (x2.47105) for a
consistent legend with the US side.

Alberta Wildfire (found via its public Experience Builder app's embedded
data sources, "wildfire_location_active"):
    https://services.arcgis.com/Eb8P5h4CJk8utIBz/arcgis/rest/services/wildfire_location_active/FeatureServer/0
This layer is already curated to active fires only (its name says so, and
querying it shows no "Out"-equivalent status among its ~9 current
records), so no extra activity filtering is applied. Size (AREA_ESTIMATE)
is in hectares, converted to acres the same way as BC's.

California, via NIFC's WFIGS "Incident Locations Current" layer (the same
IRWIN-backed data CAL FIRE's own map draws from -- CAL FIRE's own site
returned "Access Denied" to unauthenticated requests during development):
    https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/WFIGS_Incident_Locations_Current/FeatureServer/0
This is a nationwide layer, so it's queried with where=POOState='US-CA'
to pull only the California fires -- every other state in the domain is
already covered by WildCAD-E, and querying this layer unscoped would just
duplicate those fires under a different ID. Already pre-filtered to
current/active incidents (every CA record's FireOutDateTime is null here,
same unreliable-as-a-filter behavior as WildCAD's own "out" field, so it's
not used). Size (IncidentSize) is already in acres, no conversion needed.
Unlike the other three sources, this one actually publishes a real percent-
contained figure (PercentContained), so CA's gray/contained threshold is a
literal >75%, not a status-category proxy.

USAGE
-----
    python build_map.py                         # current wildfires
    python build_map.py --lookback-days 120     # widen the WildCAD-E query window
    python build_map.py --file snapshot.json    # render from a saved fetch

REQUIRES (already checked into /maps at repo root, shared across all
Ingalls Weather map projects):
    land_slim.json, states_lakes_slim.json, admin0_boundary_lines.json
  Sourced from raw.githubusercontent.com/martynafford/natural-earth-geojson
  (10m), already clipped to US/Canada/Mexico.

Logo is read from /assets/ingalls_weather_logo.png at repo root.
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
import matplotlib.patches as mpatches
from matplotlib.legend_handler import HandlerPatch
from matplotlib.lines import Line2D
from matplotlib.transforms import offset_copy
import numpy as np
import requests

import cartopy.crs as ccrs
from shapely.geometry import shape
from PIL import Image

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
MAPS_DIR = REPO_ROOT / "maps"
ASSETS_DIR = REPO_ROOT / "assets"
THIS_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = THIS_DIR / "output"

LAND_FILE = MAPS_DIR / "land_slim.json"
STATES_LAKES_FILE = MAPS_DIR / "states_lakes_slim.json"
ADMIN0_LINES_FILE = MAPS_DIR / "admin0_boundary_lines.json"
LOGO_FILE = ASSETS_DIR / "ingalls_weather_logo.png"

# Land fill + state lines + country lines are identical from one run to
# the next -- only the fire markers/perimeters overlaid above them
# actually change. Rendered once into a cached *transparent* RGBA raster
# (transparent wherever land_geoms doesn't cover, same as the live
# vector-drawn version, so the ocean-colored ax.patch still shows through
# at sea) and imshow-ed back at zorder=1 on every subsequent run, instead
# of re-adding the vector geometries each time -- see
# _get_basemap_raster(). Single fixed extent (no REGIONS dict), so
# there's one cache entry. Not committed to git (regenerable build
# output, like the rendered PNGs); see _basemap_cache_key() for the
# self-healing invalidation story.
BASEMAP_CACHE_DIR = THIS_DIR / "basemap_cache"

TARGET_COUNTRIES = {"United States of America", "Canada"}

POPPINS_REG_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf"
POPPINS_MED_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf"

LOCAL_TZ = ZoneInfo("America/Los_Angeles")

# ---------------------------------------------------------------------------
# Figure geometry / map domain -- same LON/LAT domain and axes box size
# (in inches) as ../dew-point-storm-map/build_map.py, so the two products
# read as a matched pair, but a shorter FIG_HEIGHT_IN/taller AXES_RECT
# fraction: this map's bottom area only needs three compact legend/caption
# rows, not a colorbar with two tick axes, so it doesn't need as much room
# below the map frame.
# ---------------------------------------------------------------------------
FIG_WIDTH_IN, FIG_HEIGHT_IN = 8.4, 8.5
FIG_DPI = 200
AXES_RECT = [0.03, 0.149, 0.94, 0.716]
MAP_FRAME_INSET_PX = 22

LON_MIN, LON_MAX = -128.2, -108.8
LAT_MIN, LAT_MAX = 39.7, 55.2
CENTER_LON, CENTER_LAT = -118.5, 47.45

CITIES = [
    ("Bella Coola", -126.7659, 52.3728, "right"),
    ("Wells", -121.5589, 53.1058, "right"),
    ("Vancouver", -123.1207, 49.2827, "left"),
    ("Victoria", -123.3656, 48.4284, "left"),
    ("Kelowna", -119.4960, 49.8880, "right"),
    ("Kamloops", -120.3273, 50.6745, "right"),
    ("Prince George", -122.7497, 53.9171, "right"),
    ("Cranbrook", -115.7697, 49.5097, "right"),
    ("Williams Lake", -122.1417, 52.1417, "left"),
    ("Seattle", -122.3321, 47.6062, "left"),
    ("Spokane", -117.4260, 47.6588, "left"),
    ("Tri-Cities", -119.2781, 46.2565, "right"),
    ("Portland", -122.6784, 45.5152, "left"),
    ("Bend", -121.3153, 44.0582, "left"),
    ("Eugene", -123.0868, 44.0521, "left"),
    ("Medford", -122.8756, 42.3265, "left"),
    ("Redding", -122.3917, 40.5865, "left"),
    ("Burns", -119.0541, 43.5866, "right"),
    ("Boise", -116.2023, 43.6150, "left"),
    ("Twin Falls", -114.4609, 42.5629, "left"),
    ("Idaho Falls", -112.0362, 43.4917, "right"),
    ("Winnemucca", -117.7357, 40.9730, "left"),
    ("Salt Lake City", -111.8910, 40.7608, "right"),
    ("Bozeman", -111.0429, 45.6770, "right"),
    ("Missoula", -113.9940, 46.8721, "left"),
    ("Great Falls", -111.3008, 47.5053, "right"),
    ("Calgary", -114.0719, 51.0447, "right"),
    ("Red Deer", -113.8112, 52.2681, "right"),
    ("Edmonton", -113.4938, 53.5461, "right"),
    ("Lethbridge", -112.8418, 49.6935, "right"),
]

# ---------------------------------------------------------------------------
# WildCAD-E dispatch centers whose area of responsibility falls inside (or
# close enough to matter at) the map domain. Every US Wildfire-type,
# still-active incident from these is queried, then filtered again to the
# exact LON/LAT box below -- so a center's whole coverage area doesn't need
# to line up perfectly with the domain, just overlap it. No BC/Alberta
# centers exist -- WildCAD is a US-only system.
# ---------------------------------------------------------------------------
WILDCAD_API_BASE = "https://snknmqmon6.execute-api.us-west-2.amazonaws.com"

DISPATCH_CENTERS = [
    # Washington (all -- state fits entirely inside the domain)
    "WACAC", "WACCC", "WACWC", "WANDC", "WANEC", "WAOLC", "WAPCC", "WAPSC", "WASPC",
    # Oregon (all -- state fits entirely inside the domain)
    "OR712C", "OR71C", "ORBIC", "ORBMC", "ORCOC", "OREIC", "ORJDCC", "ORLFC",
    "ORORC", "ORRICC", "ORRVC", "ORVAC",
    # Idaho (all -- state fits entirely inside the domain)
    "IDBDC", "IDCDC", "IDCIC", "IDEIC", "IDGVC", "IDPAC", "IDSCC",
    # Montana (western/central -- domain's east edge cuts off Billings/
    # Miles City/Lewistown territory)
    "MTMDC", "MTKIC", "MTBRC", "MTHDC", "MTGDC", "MTDDC", "MTKDC",
    # Northern Nevada (domain's south edge cuts through here)
    "NVEIC", "NVCNC", "NVSFC", "NVECC",
    # Northern Utah (Salt Lake City corner of the domain)
    "UTNUC",
    # NW Wyoming (Yellowstone/Teton corner of the domain)
    "WYTDC",
]

# type == "Wildfire" and fire_status.control is null (see module docstring
# for why "control", not "out").
INCLUDED_TYPES = {"Wildfire"}

# ---------------------------------------------------------------------------
# Canadian sources (see module docstring for how these URLs were found and
# how each one's activity/status field is interpreted).
# ---------------------------------------------------------------------------
BC_FIRES_URL = "https://services6.arcgis.com/ubm4tcTYICKBpist/arcgis/rest/services/BCWS_ActiveFires_PublicView/FeatureServer/0/query"
AB_FIRES_URL = "https://services.arcgis.com/Eb8P5h4CJk8utIBz/arcgis/rest/services/wildfire_location_active/FeatureServer/0/query"
HECTARES_TO_ACRES = 2.47105

# ---------------------------------------------------------------------------
# California -- WildCAD-E doesn't cover CA (it's a PNW interagency dispatch
# system), but the map domain's southern edge (LAT_MIN 39.7) dips into the
# northernmost strip of CA (Redding / Shasta-Trinity-Siskiyou-Modoc area).
# CAL FIRE's own site (fire.ca.gov) returned "Access Denied" to
# unauthenticated requests during development, so this pulls from NIFC's
# nationwide WFIGS "Incident Locations Current" layer instead -- the same
# IRWIN-backed incident data CAL FIRE's own map draws from -- filtered to
# POOState='US-CA' only, since every other state in the domain is already
# covered by WildCAD-E/BC/Alberta and including them here too would just
# duplicate those fires under a different ID.
# ---------------------------------------------------------------------------
CALFIRE_URL = "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/WFIGS_Incident_Locations_Current/FeatureServer/0/query"
CALFIRE_CONTAINED_PCT = 75

# BC's and Alberta's "Stage of Control"/"Fire Status" values that count as
# "Being Held or better" for the gray contained-fire category (see
# "Containment coloring" below) -- neither "Out of Control" (not contained
# at all) nor "Out" (not shown here in the first place, excluded upstream).
CONTAINED_STATUSES = {"Being Held", "Under Control"}

# ---------------------------------------------------------------------------
# Marker sizing -- area (not radius) scales with acres so the *visual*
# footprint reads proportionally, log-scaled since fire size spans several
# orders of magnitude (0.1 to 10,000+ acres) in the same dataset.
# ---------------------------------------------------------------------------
def marker_size_pts2(acres):
    a = max(acres or 0.1, 0.1)
    return float(np.clip(18 + 55 * np.log10(a + 1), 18, 260))


SIZE_LEGEND_ACRES = [1, 25, 500, 5000]

# ---------------------------------------------------------------------------
# Age coloring -- red for a fire first reported within NEW_FIRE_HOURS,
# orange otherwise (including unknown age -- see fetch_all_fires callers).
# Containment coloring (checked first -- see build_map()) overrides age:
# gray for a fire at "Being Held" or better. None of the three sources
# publishes an actual percent-contained figure -- BC/Alberta only expose a
# handful of named status categories, and WildCAD only a contain/control
# timestamp pair -- so this is a status-category proxy, not a literal
# percentage threshold. "contained" per source (see fetch_*_fires()):
#   WildCAD    fire_status.contain is set (control is always unset here,
#              since fires WildCAD itself marks controlled are filtered
#              out entirely as no longer active)
#   BC/Alberta FIRE_STATUS in CONTAINED_STATUSES ("Being Held" or "Under
#              Control")
# ---------------------------------------------------------------------------
NEW_FIRE_HOURS = 24.0
NEW_COLOR, NEW_EDGE = "#e6231e", "#7a0e0a"
EXISTING_COLOR, EXISTING_EDGE = "#f2892b", "#8a4b0a"
CONTAINED_COLOR, CONTAINED_EDGE = "#9a9a92", "#5a5a52"

# ---------------------------------------------------------------------------
# Large-fire outline rings -- an extra black ring traced around a fire's own
# marker (same size, drawn on top) so a genuinely major fire stands out
# regardless of what color its age/containment status happens to give it.
# Two tiers, checked large-first so a >100k-acre fire gets the solid ring,
# not the dashed one.
# ---------------------------------------------------------------------------
LARGE_FIRE_ACRES = 25_000
MEGA_FIRE_ACRES = 100_000

# ---------------------------------------------------------------------------
# Decluttering filters -- applied once, after merging all sources (see
# fetch_all_fires()). New fires (see NEW_FIRE_HOURS above) are exempt from
# both -- a fire that's genuinely new is worth showing at any size or
# staleness. Missing data never triggers either filter (same "unknown
# doesn't mean drop it" bias as the rest of this file, e.g. age coloring
# above) -- both only fire on a concrete acres/last_update_hours value that
# actually clears the threshold. "Last update" per source, since only CA
# (ModifiedOnDateTime_dt) exposes a true one (see fetch_*_fires() for each
# source's proxy):
#   WildCAD    the fire_status.contain timestamp if contained, else age
#   BC         IGNITION_DATE (no per-fire edit-date field exists in the
#              public layer -- falls back to age, a known imperfection)
#   Alberta    FIRE_STATUS_DATE (already the last-status-change field)
#   CA         ModifiedOnDateTime_dt, a real last-modified field
#   - STALE_CONTAINED_DAYS: a contained (gray) fire whose last update is
#     older than this is dropped outright, any size -- it's not still being
#     worked and its own record hasn't moved either, so it's just clutter
#     at this point.
#   - MIN_VISIBLE_ACRES: a non-new, non-contained (existing/orange) fire
#     under this size is dropped once it's *also* stale by
#     STALE_EXISTING_SMALL_DAYS -- a small fire that's still getting fresh
#     updates is still worth showing, just not once it goes quiet too. A
#     contained fire is small-checked unconditionally above instead (its
#     own, longer, staleness allowance already covers it).
#   - STALE_EXISTING_ANY_DAYS: an existing fire this stale is dropped
#     outright regardless of size -- a backstop for a fire whose record
#     just stopped getting touched, even a large one. Deliberately much
#     longer than STALE_EXISTING_SMALL_DAYS: for 3 of the 4 sources,
#     "last update" on a non-contained fire is really just time-since-
#     first-reported (see the per-source list above), and a large fire
#     still uncontained after weeks is often exactly the one most worth
#     keeping visible, not hiding -- so this only fires once a fire's been
#     sitting long enough that it's very unlikely to still be a live,
#     tracked incident.
#   - STALE_EXISTING_SMALL_DAYS is shorter than STALE_CONTAINED_DAYS on
#     purpose: an existing fire going quiet for a few weeks is more likely
#     to just be under-reported (still burning, no update filed) than
#     genuinely done, so it's dropped sooner if it's also small; a
#     contained fire going quiet is a much stronger done-with-it signal,
#     so it gets more benefit of the doubt before being dropped outright.
# ---------------------------------------------------------------------------
STALE_CONTAINED_DAYS = 90
STALE_EXISTING_SMALL_DAYS = 28
STALE_EXISTING_ANY_DAYS = 60
MIN_VISIBLE_ACRES = 10


def is_visible(f):
    """Decluttering filter (see STALE_CONTAINED_DAYS/STALE_EXISTING_SMALL_DAYS/
    STALE_EXISTING_ANY_DAYS/MIN_VISIBLE_ACRES above), applied once in
    fetch_all_fires() after merging every source. Mirrors fire_color()'s
    own contained-then-new priority in build_map() so a fire's filtering
    and its display color always agree: a contained fire is checked (and
    can be dropped) as contained even if it's also technically <24h old,
    since it would render gray, not red, either way."""
    small = f["acres"] is not None and f["acres"] < MIN_VISIBLE_ACRES
    if f["contained"]:
        stale = f["last_update_hours"] is not None and f["last_update_hours"] > STALE_CONTAINED_DAYS * 24
        return not (stale or small)
    is_new = f["age_hours"] is not None and f["age_hours"] <= NEW_FIRE_HOURS
    if is_new:
        return True
    if f["last_update_hours"] is not None:
        if f["last_update_hours"] > STALE_EXISTING_ANY_DAYS * 24:
            return False
        if small and f["last_update_hours"] > STALE_EXISTING_SMALL_DAYS * 24:
            return False
    return True


def load_land():
    with open(LAND_FILE) as f:
        data = json.load(f)
    return [shape(feat["geometry"]) for feat in data["features"] if feat.get("geometry")]


def load_states():
    with open(STATES_LAKES_FILE) as f:
        data = json.load(f)
    state_geoms = []
    for feat in data["features"]:
        props = feat["properties"]
        if "Lake" in props.get("featurecla", ""):
            continue
        if props.get("admin") in TARGET_COUNTRIES:
            state_geoms.append(shape(feat["geometry"]))
    return state_geoms


def load_boundary_lines(path):
    with open(path) as f:
        data = json.load(f)
    return [shape(feat["geometry"]) for feat in data["features"]]


def fetch_center_incidents(dc, from_date, to_date):
    """Raw incident records for one dispatch center, or [] on any failure
    (a center being down/renamed shouldn't take out the whole map). One
    retry on transient 5xx errors -- individual centers occasionally
    503 briefly under this API."""
    url = f"{WILDCAD_API_BASE}/centers/{dc}/incidents"
    params = {"fromDate": from_date, "toDate": to_date}
    last_err = None
    for attempt in range(2):
        try:
            resp = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
            resp.raise_for_status()
            payload = resp.json()
            return (payload[0].get("data") or []) if payload else []
        except Exception as e:
            last_err = e
    print(f"  WARNING: {dc} fetch failed ({last_err}), skipping.")
    return []


def fetch_wildcad_fires(lookback_days, now):
    """US fires from every WildCAD-E dispatch center in DISPATCH_CENTERS,
    keyed by inc_num/uuid (namespaced so they can't collide with the
    Canadian sources' own ID spaces)."""
    from_date = (now - timedelta(days=lookback_days)).strftime("%Y-%m-%dT00:00:00.000Z")
    to_date = now.strftime("%Y-%m-%dT23:59:59.000Z")

    by_key = {}
    for dc in DISPATCH_CENTERS:
        print(f"Fetching {dc} ...")
        for rec in fetch_center_incidents(dc, from_date, to_date):
            if rec.get("type") not in INCLUDED_TYPES:
                continue
            try:
                # WildCAD-E's API returns longitude as a bare positive
                # magnitude (no western-hemisphere sign) -- confirmed
                # against known fire locations, e.g. a Chelan County, WA
                # fire reporting longitude "120.297895" (should be
                # -120.297895). Every center in DISPATCH_CENTERS is west
                # of the prime meridian, so negating unconditionally is
                # safe here.
                lat, lon = float(rec["latitude"]), -abs(float(rec["longitude"]))
            except (TypeError, ValueError, KeyError):
                continue
            if not (LON_MIN <= lon <= LON_MAX and LAT_MIN <= lat <= LAT_MAX):
                continue
            try:
                status = json.loads(rec.get("fire_status") or "{}")
            except json.JSONDecodeError:
                status = {}
            if status.get("control"):
                continue  # declared controlled -- no longer an active fire
            # A "contain" timestamp is WildCAD's rough equivalent of BC/
            # Alberta's "Being Held" -- perimeter lined, not yet declared
            # fully controlled (control is always null here, see above).
            contained = bool(status.get("contain"))
            try:
                acres = float(rec["acres"]) if rec.get("acres") not in (None, "") else None
            except (TypeError, ValueError):
                acres = None
            # rec["date"] is the incident's initial report timestamp (it's
            # what fromDate/toDate filter on), naive with no offset -- WildCAD
            # dispatch centers log in local (Pacific/Mountain) time, not UTC,
            # so treating it as UTC here is off by a few hours. Acceptable
            # imprecision for a coarse 24-hour new-vs-existing bucket.
            age_hours = None
            if rec.get("date"):
                try:
                    ignition = datetime.fromisoformat(rec["date"]).replace(tzinfo=timezone.utc)
                    age_hours = (now - ignition).total_seconds() / 3600
                except ValueError:
                    pass
            # For a contained fire, the contain timestamp itself is the best
            # available "last update" signal (see STALE_CONTAINED_DAYS above)
            # -- same naive-timestamp-treated-as-UTC caveat as "date" above.
            last_update_hours = age_hours
            if status.get("contain"):
                try:
                    contained_dt = datetime.fromisoformat(status["contain"]).replace(tzinfo=timezone.utc)
                    last_update_hours = (now - contained_dt).total_seconds() / 3600
                except ValueError:
                    pass
            key = "WC:" + (rec.get("inc_num") or rec.get("uuid") or "")
            by_key[key] = {
                "name": (rec.get("name") or "UNNAMED").strip(),
                "lat": lat, "lon": lon, "acres": acres,
                "age_hours": age_hours, "last_update_hours": last_update_hours,
                "contained": contained, "source": dc,
            }
    return by_key


def fetch_bc_fires(now):
    """BC Wildfire Service's public 'Fire Locations - Current' layer --
    every fire this season, active or not, so filtered here to
    FIRE_STATUS != 'Out' (see module docstring for why that's a looser
    definition of "active" than the WildCAD/Alberta sides use)."""
    print("Fetching BC Wildfire Service ...")
    by_key = {}
    try:
        resp = requests.get(BC_FIRES_URL, params={
            "where": "1=1",
            "outFields": "FIRE_ID,FIRE_STATUS,LATITUDE,LONGITUDE,CURRENT_SIZE,"
                          "INCIDENT_NAME,GEOGRAPHIC_DESCRIPTION,IGNITION_DATE",
            "f": "geojson",
        }, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        resp.raise_for_status()
        features = resp.json().get("features", [])
    except Exception as e:
        print(f"  WARNING: BC Wildfire Service fetch failed ({e}), skipping.")
        return by_key

    for feat in features:
        p = feat["properties"]
        if p.get("FIRE_STATUS") == "Out":
            continue
        try:
            lat, lon = float(p["LATITUDE"]), float(p["LONGITUDE"])
        except (TypeError, ValueError, KeyError):
            continue
        if not (LON_MIN <= lon <= LON_MAX and LAT_MIN <= lat <= LAT_MAX):
            continue
        acres = p["CURRENT_SIZE"] * HECTARES_TO_ACRES if p.get("CURRENT_SIZE") is not None else None
        name = p.get("INCIDENT_NAME") or p.get("GEOGRAPHIC_DESCRIPTION") or "UNNAMED"
        # IGNITION_DATE is epoch milliseconds UTC (standard Esri date field).
        age_hours = None
        if p.get("IGNITION_DATE") is not None:
            ignition = datetime.fromtimestamp(p["IGNITION_DATE"] / 1000, tz=timezone.utc)
            age_hours = (now - ignition).total_seconds() / 3600
        contained = p.get("FIRE_STATUS") in CONTAINED_STATUSES
        # No per-fire edit/status-date field exists in this public layer --
        # IGNITION_DATE (age) is the best available "last update" stand-in
        # (see STALE_CONTAINED_DAYS above), a known imperfection since it
        # doesn't actually move when a fire's status changes.
        by_key[f"BC:{p.get('FIRE_ID')}"] = {
            "name": name.strip(), "lat": lat, "lon": lon, "acres": acres,
            "age_hours": age_hours, "last_update_hours": age_hours,
            "contained": contained, "source": "BCWS",
        }
    return by_key


def fetch_ab_fires(now):
    """Alberta Wildfire's public 'wildfire_location_active' layer -- already
    curated to active fires only, so no extra status filtering here."""
    print("Fetching Alberta Wildfire ...")
    by_key = {}
    try:
        resp = requests.get(AB_FIRES_URL, params={
            "where": "1=1",
            "outFields": "FIRE_NUMBER,LATITUDE,LONGITUDE,AREA_ESTIMATE,LABEL,FIRE_STATUS_DATE,FIRE_STATUS",
            "f": "geojson",
        }, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        resp.raise_for_status()
        features = resp.json().get("features", [])
    except Exception as e:
        print(f"  WARNING: Alberta Wildfire fetch failed ({e}), skipping.")
        return by_key

    for feat in features:
        p = feat["properties"]
        try:
            lat, lon = float(p["LATITUDE"]), float(p["LONGITUDE"])
        except (TypeError, ValueError, KeyError):
            continue
        if not (LON_MIN <= lon <= LON_MAX and LAT_MIN <= lat <= LAT_MAX):
            continue
        acres = p["AREA_ESTIMATE"] * HECTARES_TO_ACRES if p.get("AREA_ESTIMATE") is not None else None
        name = p.get("FIRE_NUMBER") or p.get("LABEL") or "UNNAMED"
        # Alberta's service exposes no true ignition/discovery date field --
        # FIRE_STATUS_DATE (last status change, "YYYY/MM/DD HH:MM:SS", no
        # offset -- treated as UTC here, actually Alberta local time, so off
        # by a few hours) is the best available proxy. For a genuinely new
        # fire this is usually close to its actual start time since the
        # first status is set on initial report; for an old fire that just
        # had a status change, it can understate age. Documented caveat, not
        # correctable without a better field.
        age_hours = None
        if p.get("FIRE_STATUS_DATE"):
            try:
                status_dt = datetime.strptime(p["FIRE_STATUS_DATE"], "%Y/%m/%d %H:%M:%S").replace(tzinfo=timezone.utc)
                age_hours = (now - status_dt).total_seconds() / 3600
            except ValueError:
                pass
        contained = p.get("FIRE_STATUS") in CONTAINED_STATUSES
        # FIRE_STATUS_DATE is already a last-status-change field, so it
        # doubles as the "last update" signal (see STALE_CONTAINED_DAYS
        # above) with no extra imprecision beyond what age_hours already has.
        by_key[f"AB:{p.get('FIRE_NUMBER')}"] = {
            "name": name.strip(), "lat": lat, "lon": lon, "acres": acres,
            "age_hours": age_hours, "last_update_hours": age_hours,
            "contained": contained, "source": "ABWildfire",
        }
    return by_key


def fetch_calfire_fires(now):
    """California fires -- via NIFC's WFIGS layer, scoped to POOState=
    'US-CA' only (see CALFIRE_URL comment for why WFIGS and why CA-only)."""
    print("Fetching California (WFIGS) ...")
    by_key = {}
    try:
        resp = requests.get(CALFIRE_URL, params={
            "where": "POOState='US-CA' AND IncidentTypeCategory IN ('WF','CX')",
            "outFields": "IrwinID,IncidentName,InitialLatitude,InitialLongitude,IncidentSize,"
                          "FireDiscoveryDateTime,PercentContained,ModifiedOnDateTime_dt",
            "f": "geojson",
        }, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        resp.raise_for_status()
        features = resp.json().get("features", [])
    except Exception as e:
        print(f"  WARNING: California (WFIGS) fetch failed ({e}), skipping.")
        return by_key

    for feat in features:
        p = feat["properties"]
        try:
            lat, lon = float(p["InitialLatitude"]), float(p["InitialLongitude"])
        except (TypeError, ValueError, KeyError):
            continue
        if not (LON_MIN <= lon <= LON_MAX and LAT_MIN <= lat <= LAT_MAX):
            continue
        acres = p.get("IncidentSize")
        name = p.get("IncidentName") or "UNNAMED"
        # FireDiscoveryDateTime is epoch milliseconds UTC (standard Esri date field).
        age_hours = None
        if p.get("FireDiscoveryDateTime") is not None:
            discovery = datetime.fromtimestamp(p["FireDiscoveryDateTime"] / 1000, tz=timezone.utc)
            age_hours = (now - discovery).total_seconds() / 3600
        # Unlike WildCAD/BC/Alberta, this source actually publishes a real
        # percent-contained figure, so CA fires use that literal threshold
        # instead of the status-category proxy the other sources need (see
        # CONTAINED_STATUSES above). Missing percent reads as not-contained
        # -- same "safer default on missing data" rule used everywhere else
        # in this file.
        pct = p.get("PercentContained")
        contained = pct is not None and pct >= CALFIRE_CONTAINED_PCT
        # ModifiedOnDateTime_dt is a real last-modified field (epoch ms UTC)
        # -- unlike the other three sources, no proxy needed here.
        last_update_hours = age_hours
        if p.get("ModifiedOnDateTime_dt") is not None:
            modified = datetime.fromtimestamp(p["ModifiedOnDateTime_dt"] / 1000, tz=timezone.utc)
            last_update_hours = (now - modified).total_seconds() / 3600
        by_key[f"CA:{p.get('IrwinID')}"] = {
            "name": name.strip(), "lat": lat, "lon": lon, "acres": acres,
            "age_hours": age_hours, "last_update_hours": last_update_hours,
            "contained": contained, "source": "CAL FIRE/WFIGS",
        }
    return by_key


def fetch_all_fires(lookback_days):
    now = datetime.now(timezone.utc)
    by_key = {}
    by_key.update(fetch_wildcad_fires(lookback_days, now))
    by_key.update(fetch_bc_fires(now))
    by_key.update(fetch_ab_fires(now))
    by_key.update(fetch_calfire_fires(now))

    all_fires = list(by_key.values())
    fires = sorted((f for f in all_fires if is_visible(f)), key=lambda f: -(f["acres"] or 0))
    print(f"{len(fires)} active wildfires in domain after filtering/dedup "
          f"({len(all_fires) - len(fires)} decluttered: stale/small contained "
          f"or small existing).")
    return fires, now


class HandlerCircle(HandlerPatch):
    """Legend handler so a Circle patch (incl. its linestyle -- dashed/solid
    ring) renders as a small circle in the legend, matching how the other
    two legend rows already use round marker handles."""

    def create_artists(self, legend, orig_handle, xdescent, ydescent, width, height, fontsize, trans):
        center = (width - xdescent) / 2, (height - ydescent) / 2
        p = mpatches.Circle(center, radius=height / 2.4)
        self.update_prop(p, orig_handle, legend)
        p.set_transform(trans)
        return [p]


def _basemap_cache_key():
    """Hash of everything that affects the cached raster's pixel content:
    the fixed map geometry/extent constants, plus the mtime+size (cheap
    os.stat, not a full re-read) of every source file the static layers
    are drawn from. Regenerating a shared maps/ file changes this hash
    automatically -- the cache self-invalidates and rebuilds on the next
    run, no manual "remember to rebuild" step to forget."""
    parts = [CENTER_LON, CENTER_LAT, LON_MIN, LON_MAX, LAT_MIN, LAT_MAX,
             FIG_WIDTH_IN, FIG_HEIGHT_IN, FIG_DPI, tuple(AXES_RECT)]
    for path in [LAND_FILE, STATES_LAKES_FILE, ADMIN0_LINES_FILE]:
        st = path.stat()
        parts.append((str(path), st.st_mtime_ns, st.st_size))
    return hashlib.sha256(repr(parts).encode()).hexdigest()[:16]


def _get_basemap_raster(proj, pc):
    """Returns (rgba_array, native_extent) for the cached land/state-line/
    country-line raster, rebuilding it first if the cache is missing or
    stale (see _basemap_cache_key). Captured with a fully transparent
    background (fig/axes patch alpha 0) so the ocean-colored ax.patch
    still shows through everywhere land_geoms doesn't cover, same as the
    live vector-drawn version. native_extent is in the axes' own
    projected coordinates (ax.get_extent(crs=proj)), not lon/lat --
    imshow-ing the raster back with transform=proj and this extent is a
    direct pixel placement, not a re-projection, which is what makes
    reusing it fast."""
    BASEMAP_CACHE_DIR.mkdir(exist_ok=True)
    key = _basemap_cache_key()
    png_path = BASEMAP_CACHE_DIR / "basemap.png"
    meta_path = BASEMAP_CACHE_DIR / "basemap.json"

    if png_path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text())
        if meta.get("key") == key:
            return plt.imread(png_path), tuple(meta["native_extent"])

    land_geoms = load_land()
    state_geoms = load_states()
    admin0_lines = load_boundary_lines(ADMIN0_LINES_FILE)

    cache_fig = plt.figure(figsize=(FIG_WIDTH_IN, FIG_HEIGHT_IN), dpi=FIG_DPI)
    cache_fig.patch.set_alpha(0.0)
    cache_ax = cache_fig.add_axes([0, 0, 1, 1], projection=proj)
    cache_ax.patch.set_alpha(0.0)
    cache_ax.set_extent([LON_MIN, LON_MAX, LAT_MIN, LAT_MAX], crs=pc)
    cache_ax.add_geometries(land_geoms, crs=pc, facecolor="#d7dcd0", edgecolor="#4a6b7a", linewidth=0.8, zorder=1)
    cache_ax.add_geometries(state_geoms, crs=pc, facecolor="none", edgecolor="#8a8578", linewidth=0.8, zorder=2)
    cache_ax.add_geometries(admin0_lines, crs=pc, facecolor="none", edgecolor="#3a2f21", linewidth=1.1, zorder=2.5)
    cache_fig.canvas.draw()
    native_extent = cache_ax.get_extent(crs=proj)

    # GeoAxes keeps aspect=1 (equal) between its data extent and its own
    # display box -- when the box's shape (from its [x0,y0,w,h] fraction)
    # doesn't already match the data's true aspect ratio, cartopy shrinks
    # the axes' rendered box within its allocated space rather than
    # distorting the projection (see columbia-basin-lightning-map's
    # _get_basemap_raster for the full writeup -- same mechanism here).
    # Crop to the axes' actual post-shrink pixel box so the saved raster
    # is pure content, with zero built-in margin, matching what
    # native_extent actually spans.
    pos = cache_ax.get_position()
    fig_w_px, fig_h_px = (cache_fig.get_size_inches() * cache_fig.dpi).astype(int)
    x0, x1 = int(round(pos.x0 * fig_w_px)), int(round(pos.x1 * fig_w_px))
    y0, y1 = int(round((1 - pos.y1) * fig_h_px)), int(round((1 - pos.y0) * fig_h_px))
    buf = np.asarray(cache_fig.canvas.buffer_rgba())[y0:y1, x0:x1, :]

    # imsave (not fig.savefig) writes exactly this pixel buffer, no
    # further DPI/bbox reinterpretation -- what's captured is what gets
    # replayed. imsave preserves the alpha channel for an (H, W, 4) array.
    plt.imsave(png_path, buf)
    plt.close(cache_fig)
    meta_path.write_text(json.dumps({"key": key, "native_extent": list(native_extent)}))
    return plt.imread(png_path), native_extent


def build_map(fires, fetched_at, output_path, new_only=False):
    """new_only=True renders only fires first reported within the last
    NEW_FIRE_HOURS, for the companion "what's new" product -- same
    fire_color() rule as the standard map (containment still wins over
    age), so a new fire already reported contained still draws gray, not
    red. "Existing" (orange) structurally can't appear in this filtered
    set -- every fire left has age_hours <= NEW_FIRE_HOURS by
    construction, so fire_color()'s age check always matches before ever
    falling through to the orange branch -- so that legend entry is
    dropped rather than shown for a color nothing on the map ever uses."""
    if new_only:
        fires = [f for f in fires if f["age_hours"] is not None and f["age_hours"] <= NEW_FIRE_HOURS]

    poppins_reg = fm.FontProperties(fname=POPPINS_REG_PATH)
    poppins_semibold = fm.FontProperties(fname=POPPINS_MED_PATH)

    pc = ccrs.PlateCarree()
    proj = pc

    fig = plt.figure(figsize=(FIG_WIDTH_IN, FIG_HEIGHT_IN), dpi=FIG_DPI)
    fig.patch.set_facecolor("#f7f6f2")

    ax = fig.add_axes(AXES_RECT, projection=proj)
    ax.set_extent([LON_MIN, LON_MAX, LAT_MIN, LAT_MAX], crs=pc)
    ax.patch.set_facecolor("#bfe1ef")  # pastel ocean -- shows through wherever the basemap raster doesn't cover

    # Cached raster, not redrawn from vector data every run -- see
    # _get_basemap_raster's docstring. zorder=1 matches the land fill's
    # original zorder, below the city labels (10+) and fire markers (50+).
    basemap_img, basemap_native_extent = _get_basemap_raster(proj, pc)
    ax.imshow(basemap_img, origin="upper", extent=basemap_native_extent,
              transform=proj, zorder=1)

    geodetic_transform = pc._as_mpl_transform(ax)
    city_stroke = [pe.withStroke(linewidth=1.5, foreground=(1, 1, 1, 0.85))]
    for name, lon_c, lat_c, pos in CITIES:
        if not (LON_MIN <= lon_c <= LON_MAX and LAT_MIN <= lat_c <= LAT_MAX):
            continue
        ax.plot(lon_c, lat_c, marker="o", markersize=3.6, color="#3a3835", zorder=10,
                mec="white", mew=0.6, transform=pc)
        dx_pt = 6 if pos == "right" else -6
        ha = "left" if pos == "right" else "right"
        name_transform = offset_copy(geodetic_transform, fig=fig, x=dx_pt, y=0, units="points")
        txt = ax.text(lon_c, lat_c, name, fontsize=8.25, fontproperties=poppins_semibold,
                       color="#3a3835", ha=ha, va="center", zorder=11, transform=name_transform)
        txt.set_path_effects(city_stroke)

    # Fire markers -- filled circle, area scaled (log) by acres. Color:
    # gray for a contained fire (checked first -- containment is the more
    # decision-relevant fact, so it wins over a fire also happening to be
    # new), else red if first reported within the last NEW_FIRE_HOURS,
    # else orange -- including any fire whose age can't be determined
    # (safer default than implying "new" on missing data). No name labels
    # -- with ~300+ fires active across this domain in a typical
    # mid-season snapshot, any label-density threshold worth using still
    # reads as clutter; the size/color alone (plus the legends) carries
    # the useful signal.
    def fire_color(f):
        if f["contained"]:
            return CONTAINED_COLOR, CONTAINED_EDGE, 0
        if f["age_hours"] is not None and f["age_hours"] <= NEW_FIRE_HOURS:
            return NEW_COLOR, NEW_EDGE, 2
        return EXISTING_COLOR, EXISTING_EDGE, 1

    # Draw order stacks red on top of orange on top of gray -- a new fire
    # is the most operationally urgent thing to see first, gray the least
    # -- sorted ascending by that draw_priority so higher-priority colors
    # are drawn later (on top). Acres (descending) is the tiebreaker
    # within a color tier, same as before, so a small fire still isn't
    # buried under a same-colored large one nearby.
    fires_to_draw = sorted(
        ((f, *fire_color(f)) for f in fires),
        key=lambda t: (t[3], -(t[0]["acres"] or 0)),
    )
    for f, color, edge, _priority in fires_to_draw:
        size = marker_size_pts2(f["acres"])
        ax.scatter(f["lon"], f["lat"], s=size, color=color, edgecolor=edge,
                   linewidth=0.7, alpha=0.85, zorder=50, transform=pc)
        acres = f["acres"] or 0
        if acres > MEGA_FIRE_ACRES:
            ax.scatter(f["lon"], f["lat"], s=size, facecolors="none", edgecolors="black",
                       linewidth=1.3, zorder=51, transform=pc)
        elif acres > LARGE_FIRE_ACRES:
            ax.scatter(f["lon"], f["lat"], s=size, facecolors="none", edgecolors="black",
                       linewidth=1.1, linestyle=(0, (2.5, 1.8)), zorder=51, transform=pc)

    ax.spines['geo'].set_edgecolor('black')
    ax.spines['geo'].set_linewidth(1.6)

    # Legends -- below the map: age/color on top, size/acreage below it.
    fig.canvas.draw()
    frame_px = ax.get_window_extent()
    frame_left = frame_px.x0 / (FIG_WIDTH_IN * FIG_DPI)
    frame_right = frame_px.x1 / (FIG_WIDTH_IN * FIG_DPI)
    frame_center = (frame_left + frame_right) / 2

    age_handles = [
        Line2D([0], [0], marker="o", linestyle="none", color=NEW_COLOR, markeredgecolor=NEW_EDGE,
               markeredgewidth=0.7, alpha=0.85, markersize=7, label=f"New (<{NEW_FIRE_HOURS:.0f}h)"),
    ]
    if not new_only:
        # "Existing" (orange) can't appear in the new_only-filtered set --
        # see build_map()'s docstring -- so it's only meaningful to show
        # on the standard map.
        age_handles.append(
            Line2D([0], [0], marker="o", linestyle="none", color=EXISTING_COLOR, markeredgecolor=EXISTING_EDGE,
                   markeredgewidth=0.7, alpha=0.85, markersize=7, label="Existing"))
    age_handles.append(
        Line2D([0], [0], marker="o", linestyle="none", color=CONTAINED_COLOR, markeredgecolor=CONTAINED_EDGE,
               markeredgewidth=0.7, alpha=0.85, markersize=7, label="Contained (Being Held+)"))
    age_leg = fig.legend(handles=age_handles, loc="center", frameon=False, fontsize=8.75,
                          prop=poppins_reg, ncol=len(age_handles), handletextpad=0.6, columnspacing=1.4,
                          bbox_to_anchor=(frame_center, 0.121))
    for text in age_leg.get_texts():
        text.set_color("#2b2a26")

    size_handles = [
        Line2D([0], [0], marker="o", linestyle="none", color=EXISTING_COLOR, markeredgecolor=EXISTING_EDGE,
               markeredgewidth=0.7, alpha=0.85, markersize=np.sqrt(marker_size_pts2(a)),
               label=f"{a:,} ac")
        for a in SIZE_LEGEND_ACRES
    ]
    size_leg = fig.legend(handles=size_handles, loc="center", frameon=False, fontsize=8.75,
                           prop=poppins_reg, ncol=len(size_handles), handletextpad=0.6, columnspacing=1.4,
                           bbox_to_anchor=(frame_center, 0.078))
    for text in size_leg.get_texts():
        text.set_color("#2b2a26")

    outline_handles = [
        mpatches.Circle((0, 0), radius=1, facecolor="none", edgecolor="black", linewidth=1.1,
                         linestyle=(0, (2.5, 1.8)), label=f">{LARGE_FIRE_ACRES:,} ac"),
        mpatches.Circle((0, 0), radius=1, facecolor="none", edgecolor="black", linewidth=1.3,
                         linestyle="solid", label=f">{MEGA_FIRE_ACRES:,} ac"),
    ]
    outline_leg = fig.legend(handles=outline_handles, handler_map={mpatches.Circle: HandlerCircle()},
                              loc="center", frameon=False, fontsize=8.75, prop=poppins_reg,
                              ncol=len(outline_handles), handletextpad=0.6, columnspacing=1.4,
                              bbox_to_anchor=(frame_center, 0.042))
    for text in outline_leg.get_texts():
        text.set_color("#2b2a26")

    # Title & subtitle above the map
    now_local = fetched_at.astimezone(LOCAL_TZ)
    title = f"New Wildfires (Last {NEW_FIRE_HOURS:.0f}h)" if new_only else f"{now_local.strftime('%A')} Active Wildfires"
    count_label = f"{len(fires)} new fires" if new_only else f"{len(fires)} fires"
    fig.text(0.03, 0.977, title, fontsize=19,
              fontproperties=poppins_reg, color="#2b2a26", ha="left", va="top")
    fig.text(0.03, 0.940, f"{count_label} • WildCAD-E (US) + CAL FIRE + BC Wildfire Service + Alberta Wildfire",
              fontsize=11.5, fontproperties=poppins_semibold, color="#3a3835", ha="left", va="top")
    fig.text(0.03, 0.909, f"Fetched {now_local.strftime('%Y-%m-%d %H:%M')} Pacific",
              fontsize=10.5, fontproperties=poppins_reg, color="#5a584f", ha="left", va="top")

    fig.text(0.5, 0.014, "WildCAD-E, CAL FIRE, BC Wildfire Service, Alberta Wildfire — Ingalls Weather", fontsize=9,
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
        description="Build an Ingalls Weather current-wildfires map (WildCAD-E).")
    parser.add_argument("--lookback-days", type=int, default=90,
                         help="How many days back to query each dispatch center for incidents "
                              "(default: 90, matching STALE_CONTAINED_DAYS -- see module "
                              "docstring). Wider windows catch large fires that started earlier "
                              "in the season but are still uncontrolled; a narrower window risks "
                              "silently missing one at the fetch stage, before the decluttering "
                              "filters (which are the right place to drop stale/small ones) ever "
                              "see it.")
    parser.add_argument("--file", type=Path, default=None,
                         help="Render from a local saved snapshot (.json) instead of fetching live.")
    parser.add_argument("--new-only", action="store_true",
                         help="Render only fires first reported within the last NEW_FIRE_HOURS "
                              "(24h), for the companion 'what's new' map -- see build_map()'s "
                              "docstring.")
    parser.add_argument("--out", type=Path, default=None,
                         help="Output PNG path (default: output/wildcad_fires_<date>.png, or "
                              "output/wildcad_new_fires_<date>.png with --new-only).")
    args = parser.parse_args()

    if args.file and not args.file.exists():
        sys.exit(f"--file {args.file} not found.")

    if args.file:
        print(f"Using local snapshot: {args.file}")
        snapshot = json.loads(args.file.read_text())
        fires = snapshot["fires"]
        fetched_at = datetime.fromisoformat(snapshot["fetched_at"])
    else:
        fires, fetched_at = fetch_all_fires(args.lookback_days)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        snapshot_path = OUTPUT_DIR / f"snapshot_{fetched_at.strftime('%Y-%m-%dT%H%M%SZ')}.json"
        snapshot_path.write_text(json.dumps({"fires": fires, "fetched_at": fetched_at.isoformat()}))

    default_name = f"wildcad_new_fires_{fetched_at.strftime('%Y-%m-%d')}.png" if args.new_only \
        else f"wildcad_fires_{fetched_at.strftime('%Y-%m-%d')}.png"
    out_path = args.out or (OUTPUT_DIR / default_name)
    build_map(fires, fetched_at, out_path, new_only=args.new_only)

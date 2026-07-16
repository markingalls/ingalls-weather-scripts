"""
Current Wildfires Map -- one-off builder
Ingalls Weather

Same domain as ../dew-point-storm-map/ (Prince George BC to Winnemucca NV,
Bella Coola BC to Yellowstone WY), plotting currently active wildfires
from three separate government sources, merged into one map since none of
them individually covers the whole domain:

  US (WA/OR/ID/w.MT/n.NV/n.UT/nw.WY): WildCAD-E, the interagency dispatch
    CAD system used by essentially every US wildland fire dispatch center.
    There's no single national feed -- each dispatch center publishes its
    own incident list, so this queries every center whose area overlaps
    the domain and merges the results.
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

USAGE
-----
    python build_map.py                        # current wildfires
    python build_map.py --lookback-days 45      # widen the WildCAD-E query window
    python build_map.py --file snapshot.json    # render from a saved fetch

REQUIRES (already checked into /maps at repo root, shared across all
Ingalls Weather map projects):
    land_slim.json, states_lakes_slim.json, admin0_boundary_lines.json
  Sourced from raw.githubusercontent.com/martynafford/natural-earth-geojson
  (10m), already clipped to US/Canada/Mexico.

Logo is read from /assets/ingalls_weather_logo.png at repo root.
"""

import argparse
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

TARGET_COUNTRIES = {"United States of America", "Canada"}

POPPINS_REG_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf"
POPPINS_MED_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf"

LOCAL_TZ = ZoneInfo("America/Los_Angeles")

# ---------------------------------------------------------------------------
# Figure geometry / map domain -- identical to ../dew-point-storm-map/
# build_map.py, so the two products read as a matched pair.
# ---------------------------------------------------------------------------
FIG_WIDTH_IN, FIG_HEIGHT_IN = 8.4, 9.0
FIG_DPI = 200
AXES_RECT = [0.03, 0.17, 0.94, 0.70]
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
# Marker sizing -- area (not radius) scales with acres so the *visual*
# footprint reads proportionally, log-scaled since fire size spans several
# orders of magnitude (0.1 to 10,000+ acres) in the same dataset.
# ---------------------------------------------------------------------------
def marker_size_pts2(acres):
    a = max(acres or 0.1, 0.1)
    return float(np.clip(18 + 55 * np.log10(a + 1), 18, 260))


SIZE_LEGEND_ACRES = [1, 25, 500, 5000]


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
            try:
                acres = float(rec["acres"]) if rec.get("acres") not in (None, "") else None
            except (TypeError, ValueError):
                acres = None
            key = "WC:" + (rec.get("inc_num") or rec.get("uuid") or "")
            by_key[key] = {
                "name": (rec.get("name") or "UNNAMED").strip(),
                "lat": lat, "lon": lon, "acres": acres,
                "date": rec.get("date"), "source": dc,
            }
    return by_key


def fetch_bc_fires():
    """BC Wildfire Service's public 'Fire Locations - Current' layer --
    every fire this season, active or not, so filtered here to
    FIRE_STATUS != 'Out' (see module docstring for why that's a looser
    definition of "active" than the WildCAD/Alberta sides use)."""
    print("Fetching BC Wildfire Service ...")
    by_key = {}
    try:
        resp = requests.get(BC_FIRES_URL, params={
            "where": "1=1",
            "outFields": "FIRE_ID,FIRE_STATUS,LATITUDE,LONGITUDE,CURRENT_SIZE,INCIDENT_NAME,GEOGRAPHIC_DESCRIPTION",
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
        by_key[f"BC:{p.get('FIRE_ID')}"] = {
            "name": name.strip(), "lat": lat, "lon": lon, "acres": acres,
            "date": None, "source": "BCWS",
        }
    return by_key


def fetch_ab_fires():
    """Alberta Wildfire's public 'wildfire_location_active' layer -- already
    curated to active fires only, so no extra status filtering here."""
    print("Fetching Alberta Wildfire ...")
    by_key = {}
    try:
        resp = requests.get(AB_FIRES_URL, params={
            "where": "1=1",
            "outFields": "FIRE_NUMBER,LATITUDE,LONGITUDE,AREA_ESTIMATE,LABEL",
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
        by_key[f"AB:{p.get('FIRE_NUMBER')}"] = {
            "name": name.strip(), "lat": lat, "lon": lon, "acres": acres,
            "date": None, "source": "ABWildfire",
        }
    return by_key


def fetch_all_fires(lookback_days):
    now = datetime.now(timezone.utc)
    by_key = {}
    by_key.update(fetch_wildcad_fires(lookback_days, now))
    by_key.update(fetch_bc_fires())
    by_key.update(fetch_ab_fires())

    fires = sorted(by_key.values(), key=lambda f: -(f["acres"] or 0))
    print(f"{len(fires)} active wildfires in domain after filtering/dedup.")
    return fires, now


def build_map(fires, fetched_at, output_path):
    poppins_reg = fm.FontProperties(fname=POPPINS_REG_PATH)
    poppins_semibold = fm.FontProperties(fname=POPPINS_MED_PATH)

    print("Loading basemap layers...")
    land_geoms = load_land()
    state_geoms = load_states()
    admin0_lines = load_boundary_lines(ADMIN0_LINES_FILE)

    pc = ccrs.PlateCarree()
    proj = pc

    fig = plt.figure(figsize=(FIG_WIDTH_IN, FIG_HEIGHT_IN), dpi=FIG_DPI)
    fig.patch.set_facecolor("#f7f6f2")

    ax = fig.add_axes(AXES_RECT, projection=proj)
    ax.set_extent([LON_MIN, LON_MAX, LAT_MIN, LAT_MAX], crs=pc)
    ax.patch.set_facecolor("#bfe1ef")  # pastel ocean -- shows through wherever land_geoms doesn't cover

    ax.add_geometries(land_geoms, crs=pc, facecolor="#d7dcd0", edgecolor="#4a6b7a", linewidth=0.8, zorder=1)
    ax.add_geometries(state_geoms, crs=pc, facecolor="none", edgecolor="#8a8578", linewidth=0.8, zorder=2)
    ax.add_geometries(admin0_lines, crs=pc, facecolor="none", edgecolor="#3a2f21", linewidth=1.1, zorder=2.5)

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

    # Fire markers -- filled circle, area scaled (log) by acres, drawn
    # largest-first (zorder by size) so small fires never get buried under
    # a big one's marker. No name labels -- with ~300+ fires active across
    # this domain in a typical mid-season snapshot, any label-density
    # threshold worth using still reads as clutter; the size/color alone
    # (plus the acreage legend) carries the useful signal.
    fires_by_size = sorted(fires, key=lambda f: -(f["acres"] or 0))
    for f in fires_by_size:
        size = marker_size_pts2(f["acres"])
        ax.scatter(f["lon"], f["lat"], s=size, color="#e6231e", edgecolor="#7a0e0a",
                   linewidth=0.7, alpha=0.85, zorder=50, transform=pc)

    ax.spines['geo'].set_edgecolor('black')
    ax.spines['geo'].set_linewidth(1.6)

    # Size legend -- below the map, matching bubble scale to marker_size_pts2.
    fig.canvas.draw()
    frame_px = ax.get_window_extent()
    frame_left = frame_px.x0 / (FIG_WIDTH_IN * FIG_DPI)
    frame_right = frame_px.x1 / (FIG_WIDTH_IN * FIG_DPI)
    legend_handles = [
        Line2D([0], [0], marker="o", linestyle="none", color="#e6231e", markeredgecolor="#7a0e0a",
               markeredgewidth=0.7, alpha=0.85, markersize=np.sqrt(marker_size_pts2(a)),
               label=f"{a:,} ac")
        for a in SIZE_LEGEND_ACRES
    ]
    leg = fig.legend(handles=legend_handles, loc="center", frameon=False, fontsize=8.75,
                      prop=poppins_reg, ncol=len(legend_handles), handletextpad=0.6, columnspacing=1.4,
                      bbox_to_anchor=((frame_left + frame_right) / 2, 0.115))
    for text in leg.get_texts():
        text.set_color("#2b2a26")

    # Title & subtitle above the map
    now_local = fetched_at.astimezone(LOCAL_TZ)
    fig.text(0.03, 0.978, f"{now_local.strftime('%A')} Active Wildfires", fontsize=19,
              fontproperties=poppins_reg, color="#2b2a26", ha="left", va="top")
    fig.text(0.03, 0.943, f"{len(fires)} fires • WildCAD-E (US) + BC Wildfire Service + Alberta Wildfire",
              fontsize=12.5, fontproperties=poppins_semibold, color="#3a3835", ha="left", va="top")
    fig.text(0.03, 0.914, f"Fetched {now_local.strftime('%Y-%m-%d %H:%M')} Pacific",
              fontsize=10.5, fontproperties=poppins_reg, color="#5a584f", ha="left", va="top")

    fig.text(0.5, 0.012, "WildCAD-E, BC Wildfire Service, Alberta Wildfire — Ingalls Weather", fontsize=9,
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
    parser.add_argument("--lookback-days", type=int, default=30,
                         help="How many days back to query each dispatch center for incidents "
                              "(default: 30). Wider windows catch large fires that started "
                              "earlier in the season but are still uncontrolled.")
    parser.add_argument("--file", type=Path, default=None,
                         help="Render from a local saved snapshot (.json) instead of fetching live.")
    parser.add_argument("--out", type=Path, default=None,
                         help="Output PNG path (default: output/wildcad_fires_<date>.png).")
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

    out_path = args.out or (OUTPUT_DIR / f"wildcad_fires_{fetched_at.strftime('%Y-%m-%d')}.png")
    build_map(fires, fetched_at, out_path)

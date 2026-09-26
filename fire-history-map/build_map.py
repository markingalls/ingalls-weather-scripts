"""
Fire History Map
Ingalls Weather

All wildfire burn perimeters from a given year that intersect a fixed
map domain -- unlike ../fire-perimeter-map/ (one incident, map centered
and zoomed on it), this holds the domain fixed and shows every fire that
falls inside it, each a different color, clipped to the frame wherever a
perimeter extends past it (cartopy's set_extent does this automatically --
no explicit clipping needed). Defaults to the same domain as the Second
Street Fire's zoomed-in fire-perimeter-map render (Benton City, WA,
2026), reusing that exact center/zoom rather than re-deriving it.

DATA SOURCES
------------
Fire perimeters -- NIFC's public WFIGS "Interagency Perimeters
YearToDate" feature service (a sibling of the "Current" layer
../fire-perimeter-map/ uses, but year-to-date coverage instead of one
current polygon per still-tracked incident -- exactly what a season
retrospective needs, since a fire that's since closed out drops off
Current but stays here):
    https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/WFIGS_Interagency_Perimeters_YearToDate/FeatureServer/0
Queried by bounding-box intersection (geometryType=esriGeometryEnvelope,
spatialRel=esriSpatialRelIntersects), not by name -- the point is to find
every fire in the domain, not one named incident. Each result is also
filtered by attr_FireDiscoveryDateTime's year, defensively -- the YTD
layer is expected to already be this-year-only, but that isn't
documented/guaranteed, so a stray older record wouldn't silently sneak
in un-checked.

Roads and towns -- same live OpenStreetMap Overpass approach as
../fire-perimeter-map/ (see that script's docstring for the mirror-retry
logic and the state-aware minor-highway ref filter); the road/town
fetch/render code below is a near-duplicate of that script's, kept
separate rather than imported since this repo's convention is
self-contained project directories, not cross-project imports.

Counties (counties_wa_or_id.geojson) are the shared ../maps/ file, same
WA/OR/ID-only caveat as ../fire-perimeter-map/.

USAGE
-----
    python build_map.py                        # Benton City, WA, 2026 (default)
    python build_map.py --year 2025
    python build_map.py --center-lon -120.5 --center-lat 46.6 --label "Yakima" \
        --zoom-lon-deg 1.0 --zoom-lat-deg 0.5

REQUIRES (shared, checked into ../maps/ at repo root):
    counties_wa_or_id.geojson

Logo is read from ../assets/ingalls_weather_logo.png at repo root.
"""

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.transforms import offset_copy
import numpy as np
import requests

import cartopy.crs as ccrs
from shapely.geometry import shape, LineString
from PIL import Image

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
MAPS_DIR = REPO_ROOT / "maps"
ASSETS_DIR = REPO_ROOT / "assets"
THIS_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = THIS_DIR / "output"

COUNTIES_FILE = MAPS_DIR / "counties_wa_or_id.geojson"
LOGO_FILE = ASSETS_DIR / "ingalls_weather_logo.png"

POPPINS_REG_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf"
POPPINS_MED_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf"

LOCAL_TZ = ZoneInfo("America/Los_Angeles")

# ---------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------
YTD_PERIMETER_URL = ("https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/"
                      "services/WFIGS_Interagency_Perimeters_YearToDate/FeatureServer/0/query")

OVERPASS_URLS = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# Defaults reproduce fire-perimeter-map's Second Street Fire render
# exactly: its own bbox center, at the same 0.35 x 0.175 deg zoom the
# user asked for that map to be tightened to.
DEFAULT_CENTER_LON = -119.4310004185
DEFAULT_CENTER_LAT = 46.26172845850005
DEFAULT_ZOOM_LON_DEG = 0.35
DEFAULT_ZOOM_LAT_DEG = 0.175
DEFAULT_LABEL = "Benton City"
DEFAULT_YEAR = 2026
DEFAULT_MAX_TOWNS = 10
DEFAULT_STATE_FOR_ROADS = "WA"

# ---------------------------------------------------------------------------
# Figure layout constants -- see fire-perimeter-map/build_map.py's
# compute_layout() for the derivation this mirrors. BOTTOM_BLOCK_IN is
# bigger here than that script's: the fire legend can run to 2-3 rows
# (one entry per fire, wrapped at 4 per row) instead of always 1.
# ---------------------------------------------------------------------------
FIG_WIDTH_IN = 10.0
FIG_DPI = 200
AXES_X0_FRAC, AXES_WIDTH_FRAC = 0.03, 0.94
TOP_BLOCK_IN = 0.90
BOTTOM_BLOCK_IN = 1.55
TITLE1_OFFSET_IN = 0.1587
TITLE2_OFFSET_IN = 0.4968
FIRE_LEGEND_OFFSET_IN = 1.16
ROAD_LEGEND_OFFSET_IN = 0.50
CREDIT_OFFSET_IN = 0.0966
MAP_FRAME_INSET_PX = 22

MOTORWAY_COLOR = "#8FB8E0"
TRUNK_COLOR = "#F2B880"
MINOR_HWY_COLOR = "#E2707A"
LOCAL_ROAD_COLOR = "#9a9890"

# Muted, mutually-distinguishable per-fire colors -- cycles if a domain
# ever holds more fires than this.
FIRE_PALETTE = [
    "#c0392b", "#d98c3d", "#c9a227", "#6b8f3c",
    "#3f8f8f", "#4a72b0", "#7a5ea8", "#b0538e",
    "#8c6d46", "#5f7470",
]


def display_name(name):
    """Same all-caps fix as fire-perimeter-map/build_map.py -- WFIGS
    stores some incident names in shouting-caps."""
    return name.title() if name.isupper() else name


def fetch_fires_in_domain(lon_min, lon_max, lat_min, lat_max, year):
    """Every WFIGS YearToDate perimeter intersecting the bbox, filtered
    to attr_FireDiscoveryDateTime's year. Returns a list of dicts sorted
    by acres descending (largest first), each with geom/name/acres/
    discovered. An empty domain (no fires) is a valid, non-error result."""
    params = {
        "geometry": f"{lon_min},{lat_min},{lon_max},{lat_max}",
        "geometryType": "esriGeometryEnvelope",
        "spatialRel": "esriSpatialRelIntersects",
        "inSR": "4326",
        "outFields": "*",
        "outSR": "4326",
        "f": "geojson",
    }
    r = requests.get(YTD_PERIMETER_URL, params=params, timeout=30)
    r.raise_for_status()
    feats = r.json().get("features", [])

    def epoch_ms(v):
        return datetime.fromtimestamp(v / 1000, tz=timezone.utc) if v else None

    fires = []
    for f in feats:
        p = f["properties"]
        discovered = epoch_ms(p.get("attr_FireDiscoveryDateTime"))
        if discovered is not None and discovered.year != year:
            continue
        fires.append({
            "geom": shape(f["geometry"]),
            "name": display_name(p.get("poly_IncidentName") or "Unnamed"),
            "acres": p.get("poly_GISAcres") or 0,
            "discovered": discovered,
        })
    fires.sort(key=lambda x: -(x["acres"] or 0))
    return fires


def query_overpass(query, label):
    """Same mirror-retry logic as fire-perimeter-map/build_map.py."""
    for url in OVERPASS_URLS:
        try:
            r = requests.post(url, data={"data": query}, timeout=60)
            r.raise_for_status()
            elements = r.json().get("elements", [])
            print(f"  {len(elements)} {label} elements from {url}")
            return elements
        except (requests.RequestException, ValueError) as e:
            print(f"NOTE: Overpass mirror {url} failed ({e}), trying next...")
    print(f"NOTE: all Overpass mirrors failed, skipping {label}.")
    return []


def fetch_roads(lon_min, lon_max, lat_min, lat_max, state, include_local=False):
    """Same tiers/logic as fire-perimeter-map/build_map.py's fetch_roads
    -- see that script's docstring for the state-aware ref-filter and
    include_local rationale."""
    ref_pattern = f"^(SR|{state.upper()})\\s?\\d"
    secondary_clause = (f'way["highway"~"^(secondary|secondary_link)$"]["ref"~"{ref_pattern}"]'
                         f'({lat_min},{lon_min},{lat_max},{lon_max});')
    if include_local:
        secondary_clause = (f'way["highway"~"^(secondary|secondary_link)$"]'
                             f'({lat_min},{lon_min},{lat_max},{lon_max});')
    query = f"""
    [out:json][timeout:45];
    (
      way["highway"~"^(motorway|motorway_link)$"]({lat_min},{lon_min},{lat_max},{lon_max});
      way["highway"~"^(trunk|trunk_link)$"]({lat_min},{lon_min},{lat_max},{lon_max});
      way["highway"~"^(primary|primary_link)$"]({lat_min},{lon_min},{lat_max},{lon_max});
      {secondary_clause}
    );
    out geom;
    """
    elements = query_overpass(query, "road")
    roads = {"motorway": [], "trunk": [], "minor": [], "local": []}
    ref_re = re.compile(ref_pattern)
    for el in elements:
        geom = el.get("geometry")
        if not geom:
            continue
        tags = el.get("tags", {})
        hwy = tags.get("highway", "")
        line = LineString([(pt["lon"], pt["lat"]) for pt in geom])
        if hwy.startswith("motorway"):
            roads["motorway"].append(line)
        elif hwy.startswith("trunk"):
            roads["trunk"].append(line)
        elif hwy.startswith("secondary") and include_local and not ref_re.match(tags.get("ref") or ""):
            roads["local"].append(line)
        else:
            roads["minor"].append(line)
    return roads


PLACE_TIER = {"city": 0, "town": 1, "village": 2}


def fetch_towns(lon_min, lon_max, lat_min, lat_max, max_towns, exclude_names):
    """Same as fire-perimeter-map/build_map.py's fetch_towns."""
    query = f"""
    [out:json][timeout:45];
    node["place"~"^(city|town|village)$"]({lat_min},{lon_min},{lat_max},{lon_max});
    out body;
    """
    elements = query_overpass(query, "town")
    exclude_lower = {n.lower() for n in exclude_names}
    towns = []
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name or name.lower() in exclude_lower:
            continue
        pop = tags.get("population")
        pop = int(pop) if pop and pop.isdigit() else 0
        towns.append({
            "name": name,
            "lon": el["lon"],
            "lat": el["lat"],
            "_tier": PLACE_TIER.get(tags.get("place"), 9),
            "_pop": pop,
        })
    towns.sort(key=lambda t: (t["_tier"], -t["_pop"]))
    return [{"name": t["name"], "lon": t["lon"], "lat": t["lat"]} for t in towns[:max_towns]]


def compute_extent(center_lon, center_lat, lon_span, lat_span):
    return (center_lon - lon_span / 2, center_lon + lon_span / 2,
            center_lat - lat_span / 2, center_lat + lat_span / 2)


def compute_layout(lon_span, lat_span):
    domain_aspect = lon_span / lat_span
    box_width_in = FIG_WIDTH_IN * AXES_WIDTH_FRAC
    box_height_in = box_width_in / domain_aspect
    fig_height_in = box_height_in + TOP_BLOCK_IN + BOTTOM_BLOCK_IN
    return {
        "fig_height_in": fig_height_in,
        "axes_rect": [AXES_X0_FRAC, BOTTOM_BLOCK_IN / fig_height_in,
                      AXES_WIDTH_FRAC, box_height_in / fig_height_in],
        "title1_y": 1 - TITLE1_OFFSET_IN / fig_height_in,
        "title2_y": 1 - TITLE2_OFFSET_IN / fig_height_in,
        "fire_legend_y": FIRE_LEGEND_OFFSET_IN / fig_height_in,
        "road_legend_y": ROAD_LEGEND_OFFSET_IN / fig_height_in,
        "credit_y": CREDIT_OFFSET_IN / fig_height_in,
    }


def build_map(fires, roads, towns, extent, year, label, generated_at, output_path):
    lon_min, lon_max, lat_min, lat_max = extent
    layout = compute_layout(lon_max - lon_min, lat_max - lat_min)

    poppins_reg = fm.FontProperties(fname=POPPINS_REG_PATH)
    poppins_med = fm.FontProperties(fname=POPPINS_MED_PATH)

    print("Loading basemap layers...")
    import json
    counties = json.loads(COUNTIES_FILE.read_text())
    county_geoms = [shape(f["geometry"]) for f in counties["features"]]

    pc = ccrs.PlateCarree()
    fig = plt.figure(figsize=(FIG_WIDTH_IN, layout["fig_height_in"]), dpi=FIG_DPI)
    fig.patch.set_facecolor("#f7f6f2")

    ax = fig.add_axes(layout["axes_rect"], projection=pc)
    ax.set_extent([lon_min, lon_max, lat_min, lat_max], crs=pc)
    ax.patch.set_facecolor("#e9e6dc")

    ax.add_geometries(county_geoms, crs=pc, facecolor="none", edgecolor="#b9b6ac",
                       linewidth=0.8, zorder=2)

    if roads.get("local"):
        ax.add_geometries(roads["local"], crs=pc, facecolor="none", edgecolor=LOCAL_ROAD_COLOR,
                           linewidth=0.6, zorder=2.2)
    if roads["minor"]:
        ax.add_geometries(roads["minor"], crs=pc, facecolor="none", edgecolor=MINOR_HWY_COLOR,
                           linewidth=1.0, zorder=2.5)
    if roads["trunk"]:
        ax.add_geometries(roads["trunk"], crs=pc, facecolor="none", edgecolor=TRUNK_COLOR,
                           linewidth=1.3, zorder=3)
    if roads["motorway"]:
        ax.add_geometries(roads["motorway"], crs=pc, facecolor="none", edgecolor=MOTORWAY_COLOR,
                           linewidth=1.6, zorder=4)

    # Fire perimeters -- one color per fire, smallest drawn last (on top)
    # so a tiny fire near/overlapping a larger one is never hidden
    # underneath it (same draw-order principle as ../wildcad-fires-map/).
    fire_colors = {}
    for i, fire in enumerate(fires):
        fire_colors[id(fire)] = FIRE_PALETTE[i % len(FIRE_PALETTE)]
    for fire in sorted(fires, key=lambda f: -(f["acres"] or 0)):
        color = fire_colors[id(fire)]
        ax.add_geometries([fire["geom"]], crs=pc, facecolor=color, edgecolor=color,
                           linewidth=1.5, alpha=0.55, zorder=5)
        ax.add_geometries([fire["geom"]], crs=pc, facecolor="none", edgecolor=color,
                           linewidth=1.5, zorder=5.1)

    center_lon = (lon_min + lon_max) / 2
    geodetic_transform = pc._as_mpl_transform(ax)
    town_stroke = [pe.withStroke(linewidth=2.2, foreground=(1, 1, 1, 0.85))]
    for town in towns:
        lon_c, lat_c = town["lon"], town["lat"]
        if not (lon_min <= lon_c <= lon_max and lat_min <= lat_c <= lat_max):
            continue
        ax.plot(lon_c, lat_c, marker="o", markersize=4.2, color="#3a3835", zorder=10,
                mec="white", mew=0.7, transform=pc)
        side = "right" if lon_c < center_lon else "left"
        dx_pt = 7 if side == "right" else -7
        ha = "left" if side == "right" else "right"
        name_transform = offset_copy(geodetic_transform, fig=fig, x=dx_pt, y=0, units="points")
        txt = ax.text(lon_c, lat_c, town["name"], fontsize=9.5, fontproperties=poppins_med,
                       color="#2b2a26", ha=ha, va="center", zorder=11, transform=name_transform)
        txt.set_path_effects(town_stroke)

    ax.spines["geo"].set_edgecolor("black")
    ax.spines["geo"].set_linewidth(1.6)

    # ---- Legends: fires (color-coded, wraps to multiple rows), roads ----
    fig.canvas.draw()
    frame_px = ax.get_window_extent()
    frame_center = (frame_px.x0 + frame_px.x1) / 2 / (FIG_WIDTH_IN * FIG_DPI)

    fire_handles = [
        Patch(facecolor=fire_colors[id(fire)], edgecolor=fire_colors[id(fire)], alpha=0.7,
              linewidth=1.3, label=f"{fire['name']} ({fire['acres']:,.0f} ac)")
        for fire in fires
    ]
    if fire_handles:
        fire_leg = fig.legend(handles=fire_handles, loc="center", frameon=False, fontsize=8.75,
                               prop=poppins_reg, ncol=min(4, len(fire_handles)), handletextpad=0.6,
                               columnspacing=1.3, labelspacing=0.6,
                               bbox_to_anchor=(frame_center, layout["fire_legend_y"]))
        for text in fire_leg.get_texts():
            text.set_color("#2b2a26")
        fig.add_artist(fire_leg)

    road_handles = []
    if roads["motorway"]:
        road_handles.append(Line2D([0], [0], color=MOTORWAY_COLOR, linewidth=2.2, label="Freeway"))
    if roads["trunk"]:
        road_handles.append(Line2D([0], [0], color=TRUNK_COLOR, linewidth=2.0, label="Main highways"))
    if roads["minor"]:
        road_handles.append(Line2D([0], [0], color=MINOR_HWY_COLOR, linewidth=1.6, label="Minor highways"))
    if roads.get("local"):
        road_handles.append(Line2D([0], [0], color=LOCAL_ROAD_COLOR, linewidth=1.0, label="Local roads"))
    if road_handles:
        road_leg = fig.legend(handles=road_handles, loc="center", frameon=False, fontsize=9,
                               prop=poppins_reg, ncol=len(road_handles), handletextpad=0.6,
                               columnspacing=1.5, bbox_to_anchor=(frame_center, layout["road_legend_y"]))
        for text in road_leg.get_texts():
            text.set_color("#2b2a26")

    # ---- Title / caption ----
    total_acres = sum(f["acres"] or 0 for f in fires)
    updated_local = generated_at.astimezone(LOCAL_TZ)
    updated_str = updated_local.strftime("%Y-%m-%d %H:%M PT")

    fig.text(0.03, layout["title1_y"], f"{year} Wildfires Near {label}", fontsize=22,
              fontproperties=poppins_med, color="#2b2a26", ha="left", va="top")
    fig.text(0.03, layout["title2_y"],
              f"{len(fires)} fire{'s' if len(fires) != 1 else ''} • "
              f"{total_acres:,.0f} acres mapped • Updated: {updated_str}",
              fontsize=12.5, fontproperties=poppins_med, color="#3a3835", ha="left", va="top")

    fig.text(0.5, layout["credit_y"], "NIFC WFIGS Interagency Fire Perimeters, US Census (counties), "
                                       "OpenStreetMap (roads/towns) — Ingalls Weather", fontsize=9,
              fontproperties=poppins_reg, color="#8a887e", ha="center", va="bottom")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, facecolor=fig.get_facecolor(), dpi=FIG_DPI)
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
        description="Build an Ingalls Weather multi-fire annual burn-history map for a fixed domain.")
    parser.add_argument("--center-lon", type=float, default=DEFAULT_CENTER_LON,
                         help=f"Domain center longitude (default: {DEFAULT_CENTER_LON}).")
    parser.add_argument("--center-lat", type=float, default=DEFAULT_CENTER_LAT,
                         help=f"Domain center latitude (default: {DEFAULT_CENTER_LAT}).")
    parser.add_argument("--zoom-lon-deg", type=float, default=DEFAULT_ZOOM_LON_DEG,
                         help=f"Domain width in degrees longitude (default: {DEFAULT_ZOOM_LON_DEG}).")
    parser.add_argument("--zoom-lat-deg", type=float, default=DEFAULT_ZOOM_LAT_DEG,
                         help=f"Domain height in degrees latitude (default: {DEFAULT_ZOOM_LAT_DEG}).")
    parser.add_argument("--label", default=DEFAULT_LABEL,
                         help=f"Place name shown in the title, e.g. 'Near {{label}}' "
                              f"(default: {DEFAULT_LABEL!r}).")
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR,
                         help=f"Fire-discovery year to include (default: {DEFAULT_YEAR}).")
    parser.add_argument("--state", default=DEFAULT_STATE_FOR_ROADS,
                         help=f"Two-letter state code for the minor-highway ref filter "
                              f"(default: {DEFAULT_STATE_FOR_ROADS!r}).")
    parser.add_argument("--max-towns", type=int, default=DEFAULT_MAX_TOWNS,
                         help=f"Cap on auto-fetched town labels (default: {DEFAULT_MAX_TOWNS}).")
    parser.add_argument("--exclude-town", action="append", default=[],
                         help="Drop a town (by name) from the auto-fetched list. Repeatable.")
    parser.add_argument("--local-roads", action="store_true",
                         help="Also fetch unnumbered secondary roads as a narrow gray tier "
                              "(see fire-perimeter-map's --local-roads for the clutter trade-off).")
    parser.add_argument("--out", type=Path, default=None,
                         help="Output PNG path (default: output/<label>_fires_<year>.png).")
    args = parser.parse_args()

    extent = compute_extent(args.center_lon, args.center_lat, args.zoom_lon_deg, args.zoom_lat_deg)
    lon_min, lon_max, lat_min, lat_max = extent

    print(f"Fetching {args.year} fire perimeters in the {args.label} domain...")
    fires = fetch_fires_in_domain(lon_min, lon_max, lat_min, lat_max, args.year)
    if not fires:
        sys.exit(f"No {args.year} WFIGS perimeters found in this domain.")
    for f in fires:
        print(f"  {f['name']}: {f['acres']:,.1f} ac")

    print("Fetching roads (OSM Overpass)...")
    roads = fetch_roads(lon_min, lon_max, lat_min, lat_max, args.state, args.local_roads)

    print("Fetching towns (OSM Overpass)...")
    towns = fetch_towns(lon_min, lon_max, lat_min, lat_max, args.max_towns, args.exclude_town)

    now = datetime.now(tz=timezone.utc)
    out_path = args.out or (OUTPUT_DIR / f"{args.label.lower().replace(' ', '_')}"
                                          f"_fires_{args.year}.png")
    build_map(fires, roads, towns, extent, args.year, args.label, now, out_path)

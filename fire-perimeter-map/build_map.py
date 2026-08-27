"""
Fire Perimeter Map
Ingalls Weather

A zoomed local map of a single wildfire's current NIFC-mapped perimeter.
Shows the fire perimeter polygon itself -- not a point marker like
../wildcad-fires-map/ -- against county lines, a highway hierarchy
(interstate/main/minor), and nearby towns, so the footprint reads
against real terrain and roads at a scale a regional map can't provide.

Defaults to the Colwash Fire (Yakima County, WA) purely as a convenient
default. Every other data layer -- extent/zoom, roads, towns -- is fetched
live and computed from the queried fire's own location at runtime, not
hardcoded to Colwash, so pointing this at a different fire's --fire-name/
--state works without editing the script. See USAGE below for how to
patch a specific run (drop/add a town, widen the zoom) without touching
source, the same way the Colwash map itself was refined over several
rounds.

DATA SOURCES
------------
Fire perimeter -- NIFC's public WFIGS "Interagency Perimeters Current"
feature service (the same IRWIN-backed perimeter data NIFC's own
InciWeb/NIFC maps draw from), queried by incident name and state:
    https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/WFIGS_Interagency_Perimeters_Current/FeatureServer/0
This is the *current* perimeter layer (most recent mapped extent per fire),
not a full history -- exactly one polygon per active incident, which is
what a single-fire snapshot map wants. Attribute fields used: poly_GISAcres
(size), attr_PercentContained, attr_POOCounty/attr_POOJurisdictionalAgency,
poly_PolygonDateTime (when this perimeter was last mapped).
NOTE: a sibling service on the same host,
WFIGS_Interagency_Fire_Perimeters, returns "Token Required" (HTTP 200,
error body) -- it looks like a stale/renamed alias; Current is the one that
actually works unauthenticated.

Extent/zoom is computed at runtime: after the fire perimeter is fetched,
the map is centered on its bounding-box center, at a fixed
--zoom-lon-deg x --zoom-lat-deg degree window (default 1.00 x 0.50,
tuned for the Colwash Fire's own elongated footprint -- widen it for a
much larger or more compact fire). The figure's physical layout
(FIG_HEIGHT_IN, AXES_RECT, and the title block's exact y-positions) is
then derived from that window's aspect ratio at runtime too (see
compute_layout()), so a fire with a very different footprint shape than
Colwash's doesn't letterbox or misalign the title block.

Roads (all three tiers) and towns are both fetched live from OpenStreetMap
via Overpass, scoped to a bbox around the computed extent -- this
replaces an earlier version that read washington_roads.geojson for the
top two road tiers and a hand-curated town list, both of which only ever
worked for this one Washington fire. Best-effort like the rest of this
script's network calls: several public Overpass mirrors are tried in turn
(the primary overpass-api.de endpoint reset the connection outright when
this was built, for reasons unrelated to the query itself -- maps.mail.ru's
mirror is tried first since it's the one confirmed working here), and a
layer is silently skipped rather than blocking the map if every mirror
fails. Trade-off worth knowing: since roads no longer fall back to a
bundled file, an Overpass outage now means no roads at all, not just no
minor-highway tier.
  - Roads: motorway/motorway_link is "Interstate", trunk/trunk_link is
    "Main highways", primary/primary_link plus secondary/secondary_link
    *that carries a state-route ref* (e.g. SR 221 in Washington, OR 244 in
    Oregon) is "Minor highways" -- secondary is otherwise mostly unnumbered
    farm/county roads, so it's filtered to a ref pattern rather than
    pulled in wholesale, which would bury the actual state highways in
    clutter. The ref prefix OSM uses is state-specific -- "SR" in
    Washington, but the state's own postal code ("OR", confirmed against
    Oregon data) elsewhere -- so fetch_roads() matches "SR" or the
    queried --state code, not a fixed "^SR" (which would silently drop
    every Oregon route, as it originally did before the Hagen Fire map
    surfaced the gap).
  - Towns: every OSM place=city/town/village node inside the extent,
    ranked by place tier then population, capped at --max-towns (default
    10). This is a good default but, being automatic, won't always match
    what a human would pick by hand -- it can't know a specific hamlet
    (like Satus or Whitstran, hand-picked for the Colwash map) is locally
    relevant even though OSM doesn't tag it as a village/town, or that a
    specific place should be dropped for label crowding (Zillah, on the
    Colwash map). Use --exclude-town/--add-town to patch a single run
    without touching the script. Label side (left/right of the marker) is
    chosen automatically -- toward the extent's center, away from
    whichever frame edge the point is closer to.

Counties (counties_wa_or_id.geojson) are still the shared, static
../maps/ file -- it only covers WA/OR/ID, so a fire outside those three
states renders with no county lines (harmless: the layer just draws
nothing there, it doesn't error). Not generalized here since every fire
this repo has mapped so far has been in that footprint; revisit if that
changes.

Prosser (WA) specifically looked wrong -- north of I-82, the far side of
the freeway from its actual downtown -- during Colwash map development,
when its coordinate came from Nominatim's administrative-boundary search.
The Overpass place-node approach used now doesn't have that problem: a
place=town node is already a real town-center point, not a boundary
centroid.

USAGE
-----
    python build_map.py                                     # Colwash Fire, WA (default)
    python build_map.py --fire-name "Some Other Fire" --state OR
    python build_map.py --exclude-town Zillah --add-town "Satus,-120.1503,46.2701"
    python build_map.py --zoom-lon-deg 1.5 --zoom-lat-deg 0.8   # wider zoom
    python build_map.py --max-towns 6                           # fewer town labels

REQUIRES (shared, checked into ../maps/ at repo root):
    counties_wa_or_id.geojson

Logo is read from ../assets/ingalls_weather_logo.png at repo root.
"""

import argparse
import json
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
PERIMETER_URL = ("https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/"
                  "services/WFIGS_Interagency_Perimeters_Current/FeatureServer/0/query")

# Tried in order -- see module docstring for why mail.ru's mirror is first.
OVERPASS_URLS = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

DEFAULT_FIRE_NAME = "Colwash"
DEFAULT_STATE = "WA"
DEFAULT_ZOOM_LON_DEG = 1.00
DEFAULT_ZOOM_LAT_DEG = 0.50
DEFAULT_MAX_TOWNS = 10

# ---------------------------------------------------------------------------
# Figure layout constants. FIG_HEIGHT_IN/AXES_RECT/the title block's
# y-positions are NOT fixed -- compute_layout() derives them at runtime
# from the extent's aspect ratio, using these fixed pieces: a constant
# figure width, constant left/right margins, and a constant absolute
# (inches, not fraction) height for the text block above and below the
# map frame. Keeping those in inches rather than figure-fraction is what
# lets FIG_HEIGHT_IN itself vary with the extent's aspect ratio without
# the title/legend text changing size or cramming together.
# ---------------------------------------------------------------------------
FIG_WIDTH_IN = 10.0
FIG_DPI = 200
AXES_X0_FRAC, AXES_WIDTH_FRAC = 0.03, 0.94
TOP_BLOCK_IN = 0.90     # title + subtitle + gap, above the map frame
BOTTOM_BLOCK_IN = 0.986  # legend + credit line, below the map frame
TITLE1_OFFSET_IN = 0.1587   # fig-top to title baseline
TITLE2_OFFSET_IN = 0.4968   # fig-top to subtitle baseline
LEGEND_OFFSET_IN = 0.538    # fig-bottom to legend anchor
CREDIT_OFFSET_IN = 0.0966   # fig-bottom to credit-line anchor
MAP_FRAME_INSET_PX = 22

FIRE_FILL = "#e6231e"
FIRE_EDGE = "#7a0e0a"
MOTORWAY_COLOR = "#8FB8E0"
TRUNK_COLOR = "#F2B880"
MINOR_HWY_COLOR = "#E2707A"


def fetch_perimeter(fire_name, state):
    """Query WFIGS Interagency Perimeters Current for one incident's most
    recently mapped polygon. Raises if none/multiple ambiguous matches are
    found rather than silently guessing."""
    params = {
        "where": f"poly_IncidentName='{fire_name}' AND attr_POOState='US-{state}'",
        "outFields": "*",
        "outSR": "4326",
        "f": "geojson",
    }
    r = requests.get(PERIMETER_URL, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    feats = data.get("features", [])
    if not feats:
        sys.exit(f"No current WFIGS perimeter found for {fire_name!r} in {state}.")
    if len(feats) > 1:
        print(f"WARNING: {len(feats)} perimeters matched {fire_name!r}/{state} -- using the largest.")
        feats.sort(key=lambda f: f["properties"].get("poly_GISAcres") or 0, reverse=True)
    f = feats[0]
    p = f["properties"]

    def epoch_ms(v):
        return datetime.fromtimestamp(v / 1000, tz=timezone.utc) if v else None

    return {
        "geom": shape(f["geometry"]),
        "name": p.get("poly_IncidentName") or fire_name,
        "acres": p.get("poly_GISAcres"),
        "pct_contained": p.get("attr_PercentContained"),
        "county": p.get("attr_POOCounty"),
        "state": state,
        "jurisdiction": p.get("attr_POOJurisdictionalAgency"),
        "cause": p.get("attr_FireCause"),
        "discovered": epoch_ms(p.get("attr_FireDiscoveryDateTime")),
        "mapped": epoch_ms(p.get("poly_PolygonDateTime")),
        "map_method": p.get("poly_MapMethod"),
        "org": p.get("attr_IncidentManagementOrg"),
        "personnel": p.get("attr_TotalIncidentPersonnel"),
    }


def query_overpass(query, label):
    """Shared mirror-retry logic for every Overpass call this script
    makes. Returns the raw `elements` list, or [] (with a NOTE printed)
    if every mirror in OVERPASS_URLS fails -- callers treat that as
    "layer unavailable this run" and degrade gracefully, not as fatal."""
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


def fetch_roads(lon_min, lon_max, lat_min, lat_max, state):
    """OSM ways within the given bbox, categorized into this map's three
    road tiers -- see module docstring for the tier/ref rules. Returns
    {"motorway": [...], "trunk": [...], "minor": [...]} of shapely
    LineStrings; a tier with no hits (including every tier, if Overpass
    is unreachable) is just an empty list, not an error.

    The secondary-tier ref filter is state-aware: OSM tags a state route's
    ref with that state's own convention -- "SR ###" in Washington, but
    "OR ###" in Oregon (confirmed against Oregon data; every OSM ref in a
    WFIGS-state's secondary highways was one of "OR ###"/"US ###"/"CR ###",
    no "SR" at all) -- so a WA-only "^SR" filter would silently drop
    every Oregon state route. Matching "SR" or the queried --state's own
    postal code covers both known conventions; a state with some other
    convention would need this revisited, the same caveat as the
    WA/OR/ID-only counties layer below."""
    ref_pattern = f"^(SR|{state.upper()})\\s?\\d"
    query = f"""
    [out:json][timeout:45];
    (
      way["highway"~"^(motorway|motorway_link)$"]({lat_min},{lon_min},{lat_max},{lon_max});
      way["highway"~"^(trunk|trunk_link)$"]({lat_min},{lon_min},{lat_max},{lon_max});
      way["highway"~"^(primary|primary_link)$"]({lat_min},{lon_min},{lat_max},{lon_max});
      way["highway"~"^(secondary|secondary_link)$"]["ref"~"{ref_pattern}"]({lat_min},{lon_min},{lat_max},{lon_max});
    );
    out geom;
    """
    elements = query_overpass(query, "road")
    roads = {"motorway": [], "trunk": [], "minor": []}
    for el in elements:
        geom = el.get("geometry")
        if not geom:
            continue
        hwy = el.get("tags", {}).get("highway", "")
        line = LineString([(pt["lon"], pt["lat"]) for pt in geom])
        if hwy.startswith("motorway"):
            roads["motorway"].append(line)
        elif hwy.startswith("trunk"):
            roads["trunk"].append(line)
        else:
            roads["minor"].append(line)
    return roads


PLACE_TIER = {"city": 0, "town": 1, "village": 2}


def fetch_towns(lon_min, lon_max, lat_min, lat_max, max_towns, exclude_names):
    """OSM place=city/town/village nodes within the bbox, ranked by place
    tier then population (missing population sorts last within its
    tier), capped at max_towns. Names in exclude_names (case-insensitive)
    are dropped before the cap is applied, so excluding a small town lets
    a real one further down the ranking take its slot. Returns a list of
    {"name", "lon", "lat"} dicts -- label side is decided later in
    build_map(), once the extent's center is known."""
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
    """Derive every figure-geometry number this map needs (figure height,
    axes box, title/legend/credit y-positions) from the extent's aspect
    ratio, so the frame doesn't letterbox and the text block above/below
    it keeps a constant *physical* size regardless of that ratio -- see
    the FIG_WIDTH_IN/AXES_*/*_OFFSET_IN block comment above."""
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
        "legend_y": LEGEND_OFFSET_IN / fig_height_in,
        "credit_y": CREDIT_OFFSET_IN / fig_height_in,
    }


def build_map(fire, roads, towns, extent, generated_at, output_path):
    lon_min, lon_max, lat_min, lat_max = extent
    layout = compute_layout(lon_max - lon_min, lat_max - lat_min)

    poppins_reg = fm.FontProperties(fname=POPPINS_REG_PATH)
    poppins_med = fm.FontProperties(fname=POPPINS_MED_PATH)

    print("Loading basemap layers...")
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

    if roads["minor"]:
        ax.add_geometries(roads["minor"], crs=pc, facecolor="none", edgecolor=MINOR_HWY_COLOR,
                           linewidth=1.0, zorder=2.5)
    if roads["trunk"]:
        ax.add_geometries(roads["trunk"], crs=pc, facecolor="none", edgecolor=TRUNK_COLOR,
                           linewidth=1.3, zorder=3)
    if roads["motorway"]:
        ax.add_geometries(roads["motorway"], crs=pc, facecolor="none", edgecolor=MOTORWAY_COLOR,
                           linewidth=1.6, zorder=4)

    # Fire perimeter -- drawn last (before towns) so it reads as the
    # clear focal point against the roads/county context.
    ax.add_geometries([fire["geom"]], crs=pc, facecolor=FIRE_FILL, edgecolor=FIRE_EDGE,
                       linewidth=1.8, alpha=0.55, zorder=5)
    ax.add_geometries([fire["geom"]], crs=pc, facecolor="none", edgecolor=FIRE_EDGE,
                       linewidth=1.8, zorder=5.1)

    center_lon = (lon_min + lon_max) / 2
    geodetic_transform = pc._as_mpl_transform(ax)
    town_stroke = [pe.withStroke(linewidth=2.2, foreground=(1, 1, 1, 0.85))]
    for town in towns:
        lon_c, lat_c = town["lon"], town["lat"]
        if not (lon_min <= lon_c <= lon_max and lat_min <= lat_c <= lat_max):
            continue
        ax.plot(lon_c, lat_c, marker="o", markersize=4.2, color="#3a3835", zorder=10,
                mec="white", mew=0.7, transform=pc)
        # Label points inward (toward the extent's center), away from
        # whichever frame edge the marker sits closer to.
        side = "right" if lon_c < center_lon else "left"
        dx_pt = 7 if side == "right" else -7
        ha = "left" if side == "right" else "right"
        name_transform = offset_copy(geodetic_transform, fig=fig, x=dx_pt, y=0, units="points")
        txt = ax.text(lon_c, lat_c, town["name"], fontsize=9.5, fontproperties=poppins_med,
                       color="#2b2a26", ha=ha, va="center", zorder=11, transform=name_transform)
        txt.set_path_effects(town_stroke)

    ax.spines["geo"].set_edgecolor("black")
    ax.spines["geo"].set_linewidth(1.6)

    # ---- Legend ----
    fig.canvas.draw()
    frame_px = ax.get_window_extent()
    frame_center = (frame_px.x0 + frame_px.x1) / 2 / (FIG_WIDTH_IN * FIG_DPI)

    handles = [
        Patch(facecolor=FIRE_FILL, edgecolor=FIRE_EDGE, alpha=0.7, linewidth=1.3,
              label=f"{fire['name']} Fire perimeter"),
    ]
    if roads["motorway"]:
        handles.append(Line2D([0], [0], color=MOTORWAY_COLOR, linewidth=2.2, label="Interstate"))
    if roads["trunk"]:
        handles.append(Line2D([0], [0], color=TRUNK_COLOR, linewidth=2.0, label="Main highways"))
    if roads["minor"]:
        handles.append(Line2D([0], [0], color=MINOR_HWY_COLOR, linewidth=1.6, label="Minor highways"))
    leg = fig.legend(handles=handles, loc="center", frameon=False, fontsize=9,
                      prop=poppins_reg, ncol=len(handles), handletextpad=0.6,
                      columnspacing=1.5, bbox_to_anchor=(frame_center, layout["legend_y"]))
    for text in leg.get_texts():
        text.set_color("#2b2a26")

    # ---- Title / caption ----
    acres = fire["acres"] or 0
    pct = fire["pct_contained"]
    pct_str = f"{pct:.0f}% contained" if pct is not None else "containment unknown"
    updated_local = generated_at.astimezone(LOCAL_TZ)
    updated_str = updated_local.strftime("%Y-%m-%d %H:%M PT")

    fig.text(0.03, layout["title1_y"], f"{fire['name']} Fire", fontsize=22,
              fontproperties=poppins_med, color="#2b2a26", ha="left", va="top")
    fig.text(0.03, layout["title2_y"], f"{acres:,.0f} acres • {pct_str} • Updated: {updated_str}",
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


def parse_add_town(spec):
    parts = [p.strip() for p in spec.split(",")]
    if len(parts) != 3:
        sys.exit(f"--add-town expects 'Name,lon,lat', got {spec!r}")
    name, lon, lat = parts
    try:
        return {"name": name, "lon": float(lon), "lat": float(lat)}
    except ValueError:
        sys.exit(f"--add-town lon/lat must be numbers, got {spec!r}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build an Ingalls Weather single-fire NIFC perimeter map.")
    parser.add_argument("--fire-name", default=DEFAULT_FIRE_NAME,
                         help=f"WFIGS incident name to query (default: {DEFAULT_FIRE_NAME!r}).")
    parser.add_argument("--state", default=DEFAULT_STATE,
                         help=f"Two-letter state code, e.g. WA (default: {DEFAULT_STATE!r}).")
    parser.add_argument("--zoom-lon-deg", type=float, default=DEFAULT_ZOOM_LON_DEG,
                         help=f"Map width in degrees longitude, centered on the fire "
                              f"(default: {DEFAULT_ZOOM_LON_DEG}).")
    parser.add_argument("--zoom-lat-deg", type=float, default=DEFAULT_ZOOM_LAT_DEG,
                         help=f"Map height in degrees latitude, centered on the fire "
                              f"(default: {DEFAULT_ZOOM_LAT_DEG}).")
    parser.add_argument("--max-towns", type=int, default=DEFAULT_MAX_TOWNS,
                         help=f"Cap on auto-fetched town labels (default: {DEFAULT_MAX_TOWNS}).")
    parser.add_argument("--exclude-town", action="append", default=[],
                         help="Drop a town (by name) from the auto-fetched list. Repeatable.")
    parser.add_argument("--add-town", action="append", default=[],
                         help="Add a specific town not auto-fetched (e.g. a hamlet OSM doesn't "
                              "tag as a village): 'Name,lon,lat'. Repeatable.")
    parser.add_argument("--out", type=Path, default=None,
                         help="Output PNG path (default: output/<fire-name>_fire_<date>.png).")
    args = parser.parse_args()

    print(f"Fetching {args.fire_name!r} perimeter ({args.state})...")
    fire = fetch_perimeter(args.fire_name, args.state)
    print(f"  {fire['acres']:,.0f} ac, {fire['county']} County, "
          f"jurisdiction {fire['jurisdiction']}, mapped {fire['mapped']}")

    fire_min_lon, fire_min_lat, fire_max_lon, fire_max_lat = fire["geom"].bounds
    center_lon = (fire_min_lon + fire_max_lon) / 2
    center_lat = (fire_min_lat + fire_max_lat) / 2
    extent = compute_extent(center_lon, center_lat, args.zoom_lon_deg, args.zoom_lat_deg)
    lon_min, lon_max, lat_min, lat_max = extent

    print("Fetching roads (OSM Overpass)...")
    roads = fetch_roads(lon_min, lon_max, lat_min, lat_max, args.state)

    print("Fetching towns (OSM Overpass)...")
    towns = fetch_towns(lon_min, lon_max, lat_min, lat_max, args.max_towns, args.exclude_town)
    towns += [parse_add_town(spec) for spec in args.add_town]

    now = datetime.now(tz=timezone.utc)
    out_path = args.out or (OUTPUT_DIR / f"{args.fire_name.lower().replace(' ', '_')}"
                                          f"_fire_{now.strftime('%Y-%m-%d')}.png")
    build_map(fire, roads, towns, extent, now, out_path)

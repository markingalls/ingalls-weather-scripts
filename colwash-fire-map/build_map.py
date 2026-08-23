"""
Colwash Fire Perimeter Map
Ingalls Weather

A zoomed local map of a single wildfire's NIFC-mapped perimeter, defaulting
to the Colwash Fire (Yakima County, WA). Shows the fire perimeter polygon
itself -- not a point marker like ../wildcad-fires-map/ -- against county
lines, a highway hierarchy (interstate/main/minor), and nearby towns, so
the footprint reads against real terrain and roads at a scale a regional
map can't provide.

DATA SOURCES
------------
Fire perimeter -- NIFC's public WFIGS "Interagency Perimeters Current"
feature service (the same IRWIN-backed perimeter data NIFC's own
InciWeb/NIFC maps draw from), queried by incident name and state:
    https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/WFIGS_Interagency_Perimeters_Current/FeatureServer/0
This is the *current* perimeter layer (most recent mapped extent per fire),
not a full history -- exactly one polygon per active incident, which is
what a single-fire snapshot map wants. Attribute fields used: poly_GISAcres
(size), attr_PercentContained, attr_POOCounty/attr_POOJurisdictionalAgency
(shown in the caption), attr_FireDiscoveryDateTime, poly_PolygonDateTime
(when this perimeter was last mapped), attr_FireCause, poly_MapMethod
(mapping technique -- shown in the caption since accuracy varies a lot by
method, e.g. GPS-walked vs. infrared vs. modeled).
NOTE: a sibling service on the same host,
WFIGS_Interagency_Fire_Perimeters, returns "Token Required" (HTTP 200,
error body) -- it looks like a stale/renamed alias; Current is the one that
actually works unauthenticated.

Counties (counties_wa_or_id.geojson) and WA interstates/main highways
(washington_roads.geojson, already pre-filtered upstream to
motorway/trunk only) are shared basemap data from ../maps/, same
source/provenance as the rest of this repo's WA-domain maps.

Minor highways (the next OSM class(es) down -- "primary"/"primary_link",
plus "secondary"/"secondary_link" ways that carry a state-route ref like
SR 221 or SR 241, so numbered state highways show up without pulling in
every unnumbered farm/county road OSM also tags secondary --
washington_roads.geojson doesn't carry either tier at all, confirmed by
inspecting its highway-value distribution) are fetched live from
OpenStreetMap via Overpass, scoped to a bbox around EXTENT so the query
stays cheap. Best-effort like the town lookups below: several public
Overpass mirrors are tried in turn (the primary overpass-api.de endpoint
reset the connection outright when this was built, for reasons unrelated
to the query itself -- maps.mail.ru's mirror is tried first since it's the
one confirmed working here), and the layer is silently skipped rather
than blocking the map if every mirror fails.

Town label coordinates were looked up individually against OpenStreetMap
Nominatim (not carried over from another script's CITIES list -- this
map's zoom level needs small unincorporated-adjacent towns like Mabton and
Satus that a regional map has no reason to include). Prosser specifically
uses its downtown/city-hall coordinate, not the town's Nominatim
administrative-boundary centroid (which sits north of I-82, on the far
side of the freeway from the actual town center relative to this fire).

USAGE
-----
    python build_map.py                                   # Colwash Fire, WA
    python build_map.py --fire-name "Some Other Fire" --state OR

Re-running for a *different* fire will fetch the right perimeter, but
EXTENT/TOWNS below are still tuned to the Colwash Fire's south-central-WA
location -- a fire elsewhere would need those adjusted (see EXTENT
comment).

REQUIRES (shared, checked into ../maps/ at repo root):
    counties_wa_or_id.geojson, washington_roads.geojson

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
ROADS_FILE = MAPS_DIR / "washington_roads.geojson"
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

# ---------------------------------------------------------------------------
# Figure geometry / map domain -- same 1.00 x 0.50 deg zoom level as before,
# now centered on the fire perimeter's own bounding-box center (-119.979,
# 46.154) rather than padded out toward the nearest towns. FIG_WIDTH_IN/
# AXES_RECT's box aspect (9.4in / 4.70in = 2.00) is set to match EXTENT's
# degree aspect (1.00/0.50 = 2.00) so cartopy's set_extent doesn't have to
# letterbox the frame.
# ---------------------------------------------------------------------------
FIG_WIDTH_IN, FIG_HEIGHT_IN = 10.0, 6.58
FIG_DPI = 200
AXES_RECT = [0.03, 0.150, 0.94, 0.714]
MAP_FRAME_INSET_PX = 22

LON_MIN, LON_MAX = -120.4791, -119.4791
LAT_MIN, LAT_MAX = 45.9037, 46.4037

# (name, lon, lat, label side) -- looked up individually via OSM Nominatim,
# not reused from another script's CITIES list (see module docstring).
# Towns outside EXTENT are dropped automatically at draw time, not filtered
# out of this list -- e.g. Wapato and Bickleton, in frame at the previous
# (town-padded) extent, sit just outside this fire-centered one now.
# 5th field is an optional vertical label nudge in points (default 0).
TOWNS = [
    ("Granger", -120.1951, 46.3418, "right", 0),
    ("Toppenish", -120.3089, 46.3775, "left", 0),
    ("Wapato", -120.4203, 46.4476, "left", 0),
    ("Satus", -120.1503, 46.2701, "right", 0),
    ("Sunnyside", -120.0082, 46.3246, "right", 0),
    ("Grandview", -119.9017, 46.2510, "right", 0),
    ("Mabton", -119.9967, 46.2149, "left", 0),
    ("Prosser", -119.7692, 46.2067, "right", 0),
    ("Whitstran", -119.7062, 46.2358, "right", 0),
    ("Paterson", -119.6028, 45.9371, "right", 0),
    ("Bickleton", -120.3128, 46.0018, "right", 0),
]

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


def fetch_minor_highways(lon_min, lon_max, lat_min, lat_max):
    """Best-effort: OSM ways within the given bbox for the "minor highway"
    tier, as a list of shapely LineStrings. washington_roads.geojson has no
    tier below trunk, so this is the only source for it. Two OSM classes
    feed this layer: every highway=primary/primary_link way (no ref
    needed -- these read as the next tier down from trunk regardless of
    whether OSM gave them a route number), plus highway=secondary/
    secondary_link ways that *do* carry a state-route ref (e.g. SR 221,
    SR 241) -- secondary is otherwise mostly unnumbered farm/county roads,
    so it's filtered to ref~"^SR" rather than pulled in wholesale, which
    would bury the actual state highways in clutter. Tries each mirror in
    OVERPASS_URLS in turn; returns [] (map renders without this layer) if
    every mirror fails, rather than blocking the whole map on a
    third-party service that isn't this map's main data source."""
    query = f"""
    [out:json][timeout:25];
    (
      way["highway"="primary"]({lat_min},{lon_min},{lat_max},{lon_max});
      way["highway"="primary_link"]({lat_min},{lon_min},{lat_max},{lon_max});
      way["highway"="secondary"]["ref"~"^SR"]({lat_min},{lon_min},{lat_max},{lon_max});
      way["highway"="secondary_link"]["ref"~"^SR"]({lat_min},{lon_min},{lat_max},{lon_max});
    );
    out geom;
    """
    for url in OVERPASS_URLS:
        try:
            r = requests.post(url, data={"data": query}, timeout=30)
            r.raise_for_status()
            elements = r.json().get("elements", [])
            geoms = [LineString([(pt["lon"], pt["lat"]) for pt in el["geometry"]])
                     for el in elements if el.get("geometry")]
            print(f"  {len(geoms)} minor-highway segments from {url}")
            return geoms
        except (requests.RequestException, ValueError) as e:
            print(f"NOTE: Overpass mirror {url} failed ({e}), trying next...")
    print("NOTE: all Overpass mirrors failed, skipping minor highways layer.")
    return []


def build_map(fire, minor_hwy_geoms, generated_at, output_path):
    poppins_reg = fm.FontProperties(fname=POPPINS_REG_PATH)
    poppins_med = fm.FontProperties(fname=POPPINS_MED_PATH)

    print("Loading basemap layers...")
    counties = json.loads(COUNTIES_FILE.read_text())
    county_geoms = [shape(f["geometry"]) for f in counties["features"]]

    roads = json.loads(ROADS_FILE.read_text())
    motorway_geoms, trunk_geoms = [], []
    for f in roads["features"]:
        hwy = f["properties"].get("highway")
        geom = shape(f["geometry"])
        if hwy in ("motorway", "motorway_link"):
            motorway_geoms.append(geom)
        elif hwy in ("trunk", "trunk_link"):
            trunk_geoms.append(geom)

    pc = ccrs.PlateCarree()
    fig = plt.figure(figsize=(FIG_WIDTH_IN, FIG_HEIGHT_IN), dpi=FIG_DPI)
    fig.patch.set_facecolor("#f7f6f2")

    ax = fig.add_axes(AXES_RECT, projection=pc)
    ax.set_extent([LON_MIN, LON_MAX, LAT_MIN, LAT_MAX], crs=pc)
    ax.patch.set_facecolor("#e9e6dc")

    ax.add_geometries(county_geoms, crs=pc, facecolor="none", edgecolor="#b9b6ac",
                       linewidth=0.8, zorder=2)

    if minor_hwy_geoms:
        ax.add_geometries(minor_hwy_geoms, crs=pc, facecolor="none", edgecolor=MINOR_HWY_COLOR,
                           linewidth=1.0, zorder=2.5)

    ax.add_geometries(trunk_geoms, crs=pc, facecolor="none", edgecolor=TRUNK_COLOR,
                       linewidth=1.3, zorder=3)
    ax.add_geometries(motorway_geoms, crs=pc, facecolor="none", edgecolor=MOTORWAY_COLOR,
                       linewidth=1.6, zorder=4)

    # Fire perimeter -- drawn last (before towns) so it reads as the
    # clear focal point against the roads/county context.
    ax.add_geometries([fire["geom"]], crs=pc, facecolor=FIRE_FILL, edgecolor=FIRE_EDGE,
                       linewidth=1.8, alpha=0.55, zorder=5)
    ax.add_geometries([fire["geom"]], crs=pc, facecolor="none", edgecolor=FIRE_EDGE,
                       linewidth=1.8, zorder=5.1)

    geodetic_transform = pc._as_mpl_transform(ax)
    town_stroke = [pe.withStroke(linewidth=2.2, foreground=(1, 1, 1, 0.85))]
    for name, lon_c, lat_c, side, dy_pt in TOWNS:
        if not (LON_MIN <= lon_c <= LON_MAX and LAT_MIN <= lat_c <= LAT_MAX):
            continue
        ax.plot(lon_c, lat_c, marker="o", markersize=4.2, color="#3a3835", zorder=10,
                mec="white", mew=0.7, transform=pc)
        dx_pt = 7 if side == "right" else -7
        ha = "left" if side == "right" else "right"
        name_transform = offset_copy(geodetic_transform, fig=fig, x=dx_pt, y=dy_pt, units="points")
        txt = ax.text(lon_c, lat_c, name, fontsize=9.5, fontproperties=poppins_med,
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
        Line2D([0], [0], color=MOTORWAY_COLOR, linewidth=2.2, label="Interstate"),
        Line2D([0], [0], color=TRUNK_COLOR, linewidth=2.0, label="Main highways"),
    ]
    if minor_hwy_geoms:
        handles.append(Line2D([0], [0], color=MINOR_HWY_COLOR, linewidth=1.6, label="Minor highways"))
    leg = fig.legend(handles=handles, loc="center", frameon=False, fontsize=9,
                      prop=poppins_reg, ncol=len(handles), handletextpad=0.6,
                      columnspacing=1.5, bbox_to_anchor=(frame_center, 0.082))
    for text in leg.get_texts():
        text.set_color("#2b2a26")

    # ---- Title / caption ----
    acres = fire["acres"] or 0
    pct = fire["pct_contained"]
    pct_str = f"{pct:.0f}% contained" if pct is not None else "containment unknown"
    updated_local = generated_at.astimezone(LOCAL_TZ)
    updated_str = updated_local.strftime("%Y-%m-%d %H:%M PT")

    fig.text(0.03, 0.976, f"{fire['name']} Fire", fontsize=22,
              fontproperties=poppins_med, color="#2b2a26", ha="left", va="top")
    fig.text(0.03, 0.9245, f"{acres:,.0f} acres • {pct_str} • Updated: {updated_str}",
              fontsize=12.5, fontproperties=poppins_med, color="#3a3835", ha="left", va="top")

    fig.text(0.5, 0.015, "NIFC WFIGS Interagency Fire Perimeters, US Census (counties), "
                          "OpenStreetMap (roads) — Ingalls Weather", fontsize=9,
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
        description="Build an Ingalls Weather single-fire NIFC perimeter map.")
    parser.add_argument("--fire-name", default=DEFAULT_FIRE_NAME,
                         help=f"WFIGS incident name to query (default: {DEFAULT_FIRE_NAME!r}).")
    parser.add_argument("--state", default=DEFAULT_STATE,
                         help=f"Two-letter state code, e.g. WA (default: {DEFAULT_STATE!r}).")
    parser.add_argument("--out", type=Path, default=None,
                         help="Output PNG path (default: output/<fire-name>_fire_<date>.png).")
    args = parser.parse_args()

    print(f"Fetching {args.fire_name!r} perimeter ({args.state})...")
    fire = fetch_perimeter(args.fire_name, args.state)
    print(f"  {fire['acres']:,.0f} ac, {fire['county']} County, "
          f"jurisdiction {fire['jurisdiction']}, mapped {fire['mapped']}")

    print("Fetching minor highways (OSM Overpass)...")
    minor_hwy_geoms = fetch_minor_highways(LON_MIN, LON_MAX, LAT_MIN, LAT_MAX)

    now = datetime.now(tz=timezone.utc)
    out_path = args.out or (OUTPUT_DIR / f"{args.fire_name.lower().replace(' ', '_')}"
                                          f"_fire_{now.strftime('%Y-%m-%d')}.png")
    build_map(fire, minor_hwy_geoms, now, out_path)

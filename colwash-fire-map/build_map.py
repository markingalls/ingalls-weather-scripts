"""
Colwash Fire Perimeter Map
Ingalls Weather

A zoomed local map of a single wildfire's NIFC-mapped perimeter, defaulting
to the Colwash Fire (Yakama Reservation, Yakima County, WA). Shows the fire
perimeter polygon itself -- not a point marker like ../wildcad-fires-map/ --
against county lines, the Yakama Nation Reservation boundary (the fire's
jurisdiction is BIA), state/interstate highways, and nearby towns, so the
footprint reads against real terrain and roads at a scale a regional map
can't provide.

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
(the BIA/county line in the caption), attr_FireDiscoveryDateTime,
poly_PolygonDateTime (when this perimeter was last mapped), attr_FireCause,
poly_MapMethod (mapping technique -- shown in the caption since accuracy
varies a lot by method, e.g. GPS-walked vs. infrared vs. modeled).
NOTE: a sibling service on the same host,
WFIGS_Interagency_Fire_Perimeters, returns "Token Required" (HTTP 200,
error body) -- it looks like a stale/renamed alias; Current is the one that
actually works unauthenticated.

Yakama Nation Reservation boundary -- US Census TIGERweb, "Federal American
Indian Reservations" (Census2020/AIANNHA, layer 2), queried by name. Fetched
live rather than checked into ../maps/ since it's specific to this one fire's
location, unlike the shared statewide basemap layers. Best-effort: if the
fire in question isn't near a reservation, or the request fails, the
boundary is silently skipped rather than blocking the whole map.

Counties (counties_wa_or_id.geojson) and WA state/interstate highways
(washington_roads.geojson, already pre-filtered upstream to motorway/trunk
only) are shared basemap data from ../maps/, same source/provenance as the
rest of this repo's WA-domain maps.

Town label coordinates were looked up individually against OpenStreetMap
Nominatim (not carried over from another script's CITIES list -- this
map's zoom level needs small unincorporated-adjacent towns like Mabton and
Satus that a regional map has no reason to include).

USAGE
-----
    python build_map.py                                   # Colwash Fire, WA
    python build_map.py --fire-name "Some Other Fire" --state OR

Re-running for a *different* fire will fetch the right perimeter, but
EXTENT/CITIES/reservation lookup below are still tuned to the Colwash
Fire's south-central-WA location -- a fire elsewhere would need those
adjusted (see EXTENT comment).

REQUIRES (shared, checked into ../maps/ at repo root):
    counties_wa_or_id.geojson, washington_roads.geojson

Logo is read from ../assets/ingalls_weather_logo.png at repo root.
"""

import argparse
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
RESERVATION_URL = ("https://tigerweb.geo.census.gov/arcgis/rest/services/"
                    "Census2020/AIANNHA/MapServer/2/query")

DEFAULT_FIRE_NAME = "Colwash"
DEFAULT_STATE = "WA"
RESERVATION_NAME = "Yakama Nation Reservation"

# ---------------------------------------------------------------------------
# Figure geometry / map domain -- tuned to the Colwash Fire's footprint
# (roughly -120.18 to -119.77 lon, 46.12 to 46.19 lat), padded out to the
# nearest valley towns on each side. FIG_WIDTH_IN/AXES_RECT's box aspect
# (9.4in / 5.11in = 1.84) is set to match EXTENT's degree aspect (1.20/0.65
# = 1.85) so cartopy's set_extent doesn't have to letterbox the frame.
# ---------------------------------------------------------------------------
FIG_WIDTH_IN, FIG_HEIGHT_IN = 10.0, 7.3
FIG_DPI = 200
AXES_RECT = [0.03, 0.135, 0.94, 0.70]
MAP_FRAME_INSET_PX = 22

LON_MIN, LON_MAX = -120.75, -119.55
LAT_MIN, LAT_MAX = 45.95, 46.60

# (name, lon, lat, label side) -- looked up individually via OSM Nominatim,
# not reused from another script's CITIES list (see module docstring).
TOWNS = [
    ("Zillah", -120.2620, 46.4021, "left"),
    ("Granger", -120.1951, 46.3418, "right"),
    ("Toppenish", -120.3089, 46.3775, "left"),
    ("Wapato", -120.4203, 46.4476, "left"),
    ("Satus", -120.1503, 46.2701, "right"),
    ("Sunnyside", -120.0082, 46.3246, "right"),
    ("Grandview", -119.9017, 46.2510, "right"),
    ("Mabton", -119.9967, 46.2149, "left"),
    ("Prosser", -119.7686, 46.2532, "right"),
    ("Bickleton", -120.3128, 46.0018, "right"),
]

COUNTY_LABELS = [
    ("YAKIMA CO.", -120.62, 46.53),
    ("KLICKITAT CO.", -120.42, 46.02),
    ("BENTON CO.", -119.68, 46.03),
]

FIRE_FILL = "#e6231e"
FIRE_EDGE = "#7a0e0a"
RESERVATION_FILL = "#e8d9a8"
RESERVATION_EDGE = "#a68a3f"
MOTORWAY_COLOR = "#8FB8E0"
TRUNK_COLOR = "#F2B880"


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


def fetch_reservation(name):
    """Best-effort: returns a shapely geometry or None. A fire that isn't
    near a named reservation, or a request that fails, shouldn't block the
    rest of the map -- this layer is context, not the point of the map."""
    try:
        params = {
            "where": f"NAME='{name}'",
            "outFields": "NAME",
            "outSR": "4326",
            "f": "geojson",
        }
        r = requests.get(RESERVATION_URL, params=params, timeout=30)
        r.raise_for_status()
        feats = r.json().get("features", [])
        if not feats:
            print(f"NOTE: reservation {name!r} not found, skipping that layer.")
            return None
        return shape(feats[0]["geometry"])
    except requests.RequestException as e:
        print(f"NOTE: reservation lookup failed ({e}), skipping that layer.")
        return None


def build_map(fire, reservation_geom, output_path):
    poppins_reg = fm.FontProperties(fname=POPPINS_REG_PATH)
    poppins_med = fm.FontProperties(fname=POPPINS_MED_PATH)

    print("Loading basemap layers...")
    import json
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

    if reservation_geom is not None:
        ax.add_geometries([reservation_geom], crs=pc, facecolor=RESERVATION_FILL,
                           edgecolor=RESERVATION_EDGE, linewidth=1.1, alpha=0.45,
                           linestyle=(0, (5, 3)), zorder=1.5)

    ax.add_geometries(trunk_geoms, crs=pc, facecolor="none", edgecolor=TRUNK_COLOR,
                       linewidth=1.3, zorder=3)
    ax.add_geometries(motorway_geoms, crs=pc, facecolor="none", edgecolor=MOTORWAY_COLOR,
                       linewidth=1.6, zorder=4)

    # Fire perimeter -- drawn last (before towns) so it reads as the
    # clear focal point against the roads/reservation/county context.
    ax.add_geometries([fire["geom"]], crs=pc, facecolor=FIRE_FILL, edgecolor=FIRE_EDGE,
                       linewidth=1.8, alpha=0.55, zorder=5)
    ax.add_geometries([fire["geom"]], crs=pc, facecolor="none", edgecolor=FIRE_EDGE,
                       linewidth=1.8, zorder=5.1)

    geodetic_transform = pc._as_mpl_transform(ax)
    town_stroke = [pe.withStroke(linewidth=2.2, foreground=(1, 1, 1, 0.85))]
    for name, lon_c, lat_c, side in TOWNS:
        if not (LON_MIN <= lon_c <= LON_MAX and LAT_MIN <= lat_c <= LAT_MAX):
            continue
        ax.plot(lon_c, lat_c, marker="o", markersize=4.2, color="#3a3835", zorder=10,
                mec="white", mew=0.7, transform=pc)
        dx_pt = 7 if side == "right" else -7
        ha = "left" if side == "right" else "right"
        name_transform = offset_copy(geodetic_transform, fig=fig, x=dx_pt, y=0, units="points")
        txt = ax.text(lon_c, lat_c, name, fontsize=9.5, fontproperties=poppins_med,
                       color="#2b2a26", ha=ha, va="center", zorder=11, transform=name_transform)
        txt.set_path_effects(town_stroke)

    for label, lon_c, lat_c in COUNTY_LABELS:
        ax.text(lon_c, lat_c, label, fontsize=8, fontproperties=poppins_reg,
                 color="#8a877a", ha="center", va="center", zorder=6,
                 style="italic", transform=pc)

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
    if reservation_geom is not None:
        handles.append(Patch(facecolor=RESERVATION_FILL, edgecolor=RESERVATION_EDGE,
                              alpha=0.6, linewidth=1.1, linestyle=(0, (5, 3)),
                              label="Yakama Nation Reservation"))
    handles += [
        Line2D([0], [0], color=MOTORWAY_COLOR, linewidth=2.2, label="Interstate"),
        Line2D([0], [0], color=TRUNK_COLOR, linewidth=2.0, label="US / State highway"),
    ]
    leg = fig.legend(handles=handles, loc="center", frameon=False, fontsize=9,
                      prop=poppins_reg, ncol=len(handles), handletextpad=0.6,
                      columnspacing=1.5, bbox_to_anchor=(frame_center, 0.078))
    for text in leg.get_texts():
        text.set_color("#2b2a26")

    # ---- Title / caption ----
    acres = fire["acres"] or 0
    pct = fire["pct_contained"]
    pct_str = f"{pct:.0f}% contained" if pct is not None else "containment unknown"
    discovered_local = fire["discovered"].astimezone(LOCAL_TZ) if fire["discovered"] else None
    mapped_local = fire["mapped"].astimezone(LOCAL_TZ) if fire["mapped"] else None

    fig.text(0.03, 0.977, f"{fire['name']} Fire", fontsize=22,
              fontproperties=poppins_med, color="#2b2a26", ha="left", va="top")
    fig.text(0.03, 0.928, f"{acres:,.0f} acres • {pct_str} • "
                           f"{fire['county']} County, {fire['state']}",
              fontsize=12.5, fontproperties=poppins_med, color="#3a3835", ha="left", va="top")
    detail_bits = []
    if discovered_local:
        detail_bits.append(f"Discovered {discovered_local.strftime('%b %-d')}")
    if mapped_local:
        detail_bits.append(f"perimeter mapped {mapped_local.strftime('%b %-d, %-I:%M %p')} Pacific")
    if fire["jurisdiction"]:
        detail_bits.append(f"jurisdiction: {fire['jurisdiction']}")
    if fire["map_method"]:
        detail_bits.append(f"mapped via {fire['map_method']}")
    fig.text(0.03, 0.893, " • ".join(detail_bits), fontsize=10,
              fontproperties=poppins_reg, color="#5a584f", ha="left", va="top")

    fig.text(0.5, 0.014, "NIFC WFIGS Interagency Fire Perimeters, US Census (reservation, "
                          "counties), OpenStreetMap (roads) — Ingalls Weather", fontsize=9,
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

    reservation_geom = None
    if args.fire_name == DEFAULT_FIRE_NAME and args.state == DEFAULT_STATE:
        print(f"Fetching {RESERVATION_NAME!r} boundary...")
        reservation_geom = fetch_reservation(RESERVATION_NAME)

    now = datetime.now(tz=timezone.utc)
    out_path = args.out or (OUTPUT_DIR / f"{args.fire_name.lower().replace(' ', '_')}"
                                          f"_fire_{now.strftime('%Y-%m-%d')}.png")
    build_map(fire, reservation_geom, out_path)

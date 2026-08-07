import argparse
import json
import math
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
from matplotlib.patches import Patch, PathPatch
from matplotlib.lines import Line2D
from matplotlib.axes import Axes
import cartopy.crs as ccrs
from cartopy.mpl.path import shapely_to_path
from shapely.geometry import shape, box, Polygon, LineString, Point
from shapely.ops import transform as shp_transform, unary_union
import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict

# ---------- fonts ----------
FONT_DIR = "/usr/share/fonts/truetype/google-fonts/"
f_bold = fm.FontProperties(fname=FONT_DIR + "Poppins-Bold.ttf")
f_reg = fm.FontProperties(fname=FONT_DIR + "Poppins-Regular.ttf")
f_med = fm.FontProperties(fname=FONT_DIR + "Poppins-Medium.ttf")

# ---------- official NWS hazard colors ----------
NWS_COLORS = {
    "Tsunami Warning": "#FD6347", "Tornado Warning": "#FF0000",
    "Extreme Wind Warning": "#FF8C00", "Severe Thunderstorm Warning": "#FFA500",
    "Flash Flood Warning": "#8B0000", "Flash Flood Statement": "#8B0000",
    "Severe Weather Statement": "#00FFFF", "Shelter In Place Warning": "#FA8072",
    "Evacuation Immediate": "#7FFF00", "Civil Danger Warning": "#FFB6C1",
    "Nuclear Power Plant Warning": "#4B0082", "Radiological Hazard Warning": "#4B0082",
    "Hazardous Materials Warning": "#4B0082", "Fire Warning": "#A0522D",
    "Civil Emergency Message": "#FFB6C1", "Law Enforcement Warning": "#C0C0C0",
    "Storm Surge Warning": "#B524F7", "Hurricane Force Wind Warning": "#CD5C5C",
    "Hurricane Warning": "#DC143C", "Typhoon Warning": "#DC143C",
    "Special Marine Warning": "#FFA500", "Blizzard Warning": "#FF4500",
    "Snow Squall Warning": "#C71585", "Ice Storm Warning": "#8B008B",
    "Heavy Freezing Spray Warning": "#00BFFF", "Winter Storm Warning": "#FF69B4",
    "Lake Effect Snow Warning": "#008B8B", "Dust Storm Warning": "#FFE4C4",
    "Blowing Dust Warning": "#FFE4C4", "High Wind Warning": "#DAA520",
    "Tropical Storm Warning": "#B22222", "Storm Warning": "#9400D3",
    "Tsunami Advisory": "#D2691E", "Tsunami Watch": "#FF00FF",
    "Avalanche Warning": "#1E90FF", "Earthquake Warning": "#8B4513",
    "Volcano Warning": "#2F4F4F", "Ashfall Warning": "#A9A9A9",
    "Flood Warning": "#00FF00", "Coastal Flood Warning": "#228B22",
    "Lakeshore Flood Warning": "#228B22", "Ashfall Advisory": "#696969",
    "High Surf Warning": "#228B22", "Excessive Heat Warning": "#C71585",
    "Extreme Heat Warning": "#C71585",
    "Tornado Watch": "#FFFF00", "Severe Thunderstorm Watch": "#DB7093",
    "Flash Flood Watch": "#2E8B57", "Gale Warning": "#DDA0DD",
    "Flood Statement": "#00FF00", "Extreme Cold Warning": "#0000FF",
    "Freeze Warning": "#483D8B", "Red Flag Warning": "#FF1493",
    "Storm Surge Watch": "#DB7FF7", "Hurricane Watch": "#FF00FF",
    "Hurricane Force Wind Watch": "#9932CC", "Typhoon Watch": "#FF00FF",
    "Tropical Storm Watch": "#F08080", "Storm Watch": "#FFE4B5",
    "Tropical Cyclone Local Statement": "#FFE4B5", "Winter Weather Advisory": "#7B68EE",
    "Avalanche Advisory": "#CD853F", "Cold Weather Advisory": "#AFEEEE",
    "Heat Advisory": "#FF7F50", "Flood Advisory": "#00FF7F",
    "Coastal Flood Advisory": "#7CFC00", "Lakeshore Flood Advisory": "#7CFC00",
    "High Surf Advisory": "#BA55D3", "Dense Fog Advisory": "#708090",
    "Dense Smoke Advisory": "#F0E68C", "Small Craft Advisory": "#D8BFD8",
    "Brisk Wind Advisory": "#D8BFD8", "Hazardous Seas Warning": "#D8BFD8",
    "Dust Advisory": "#BDB76B", "Blowing Dust Advisory": "#BDB76B",
    "Lake Wind Advisory": "#D2B48C", "Wind Advisory": "#D2B48C",
    "Frost Advisory": "#6495ED", "Freezing Fog Advisory": "#008080",
    "Freezing Spray Advisory": "#00BFFF", "Low Water Advisory": "#A52A2A",
    "Local Area Emergency": "#C0C0C0", "Winter Storm Watch": "#4682B4",
    "Rip Current Statement": "#40E0D0", "Beach Hazards Statement": "#40E0D0",
    "Gale Watch": "#FFC0CB", "Avalanche Watch": "#F4A460",
    "Hazardous Seas Watch": "#483D8B", "Heavy Freezing Spray Watch": "#BC8F8F",
    "Flood Watch": "#2E8B57", "Coastal Flood Watch": "#66CDAA",
    "Lakeshore Flood Watch": "#66CDAA", "High Wind Watch": "#B8860B",
    "Excessive Heat Watch": "#800000", "Extreme Heat Watch": "#800000",
    "Extreme Cold Watch": "#5F9EA0",
    "Freeze Watch": "#00FFFF", "Fire Weather Watch": "#FFDEAD",
    "Extreme Fire Danger": "#E9967A", "Special Weather Statement": "#FFE4B5",
    "Marine Weather Statement": "#FFDAB9", "Air Quality Alert": "#808080",
    "Air Stagnation Advisory": "#808080", "Hazardous Weather Outlook": "#EEE8AA",
    "Hydrologic Outlook": "#90EE90", "Short Term Forecast": "#98FB98",
}
# Fire Weather Watch's official color (Navajowhite) is very pale - darken the
# edge so it reads clearly against the #e3e1da land tone at this map's scale.
EDGE_OVERRIDE = {
    "Fire Weather Watch": "#B8860B",
}

# NWS issues these as literal storm-tracking polygons, not tied to county/
# zone boundaries like every other product here -- shading them the same
# way as a zone-based hazard reads as if the whole zone is under threat,
# when the real warning is just the polygon's boundary. Drawn as an
# outlined boundary line instead of a fill; see the "polygon warnings"
# section of build_map().
POLYGON_WARNING_EVENTS = {"Severe Thunderstorm Warning", "Tornado Warning", "Flash Flood Warning"}

MAPS_DIR = "../maps"

# How far a state boundary line can sit from the land layer before it's
# treated as one of Natural Earth's offshore 3-nautical-mile maritime
# boundary lines (a coastal state's state-waters extent, e.g. Oregon/
# Washington) rather than a genuine land-touching state line -- same
# constant/technique as western-us-noaa-outlooks/build_map.py's
# load_state_lines(), ported here now that the Portland region's frame
# reaches the coast (Columbia Basin's original extent never did, so this
# artifact was never visible before there was a region that included any
# coastline).
OFFSHORE_LINE_DISTANCE_DEG = 0.02

# ---------------------------------------------------------------------------
# Region registry -- each entry is one map "product": its own extent, center
# point (for the NearsidePerspective projection), city labels, roads files,
# title, and output filename. satellite_height is shared and fixed (see
# SATELLITE_HEIGHT below) rather than set per-region, so every region is
# rendered at the same true zoom level -- add a new region by copying the
# extent math in the comment above PORTLAND's entry, not by hand-picking a
# new height.
# ---------------------------------------------------------------------------

# Degrees shown across each map -- same for every region, so "add a region"
# means "pick a center point," not "guess a matching zoom level." Columbia
# Basin's original hand-tuned extent ([-122.5, -117.0, 44.4, 48.0]) is what
# these spans and its center point were reverse-engineered from.
LON_SPAN, LAT_SPAN = 5.5, 3.6

# NearsidePerspective's actual zoom control -- shared across every region for
# the same reason as LON_SPAN/LAT_SPAN above (see satellite_height in the
# western-us-noaa-outlooks / tri-cities-7day-forecast projection setup for
# the same pattern).
SATELLITE_HEIGHT = 4_000_000


def region_extent(center_lon, center_lat, lon_span=LON_SPAN, lat_span=LAT_SPAN):
    return [
        round(center_lon - lon_span / 2, 2), round(center_lon + lon_span / 2, 2),
        round(center_lat - lat_span / 2, 2), round(center_lat + lat_span / 2, 2),
    ]


REGIONS = {
    "columbia_basin": dict(
        title="Columbia Basin",
        center_lon=-119.75, center_lat=46.2,
        roads_files=["washington_roads.geojson", "oregon_roads.geojson", "idaho_roads_north.geojson"],
        output="columbia_basin_alerts.png",
        cities=[
            ("Spokane", -117.4260, 47.6588, "left"),
            ("Seattle", -122.3321, 47.6062, "right"),
            ("Wenatchee", -120.3103, 47.4235, "right"),
            ("Tacoma", -122.4443, 47.2529, "right"),
            ("Moses Lake", -119.2781, 47.1301, "left"),
            ("Ritzville", -118.3766, 47.1289, "right"),
            ("Ellensburg", -120.5478, 46.9965, "left"),
            ("Othello", -119.1717, 46.8273, "left"),
            ("Pullman", -117.1817, 46.7298, "left"),
            ("Yakima", -120.5059, 46.6021, "right"),
            ("Packwood", -121.6733, 46.6088, "right"),
            ("Dayton", -117.9762, 46.3212, "right"),
            ("Prosser", -119.7686, 46.2532, "left"),
            ("Kennewick", -119.1372, 46.2112, "right"),
            ("Walla Walla", -118.3430, 46.0646, "right"),
            ("Goldendale", -120.8215, 45.8210, "left"),
            ("Boardman", -119.7006, 45.8393, "left"),
            ("Hermiston", -119.2895, 45.8404, "right"),
            ("Pendleton", -118.7879, 45.6721, "left"),
            ("The Dalles", -121.1787, 45.5946, "left"),
            ("La Grande", -118.0877, 45.3246, "right"),
            ("Condon", -120.1837, 45.2373, "right"),
        ],
    ),
    "portland": dict(
        title="Portland Metro",
        # Same coordinates tri-cities-7day-forecast/deploy/build_and_publish.py
        # uses for Portland, so every product that has a "Portland point"
        # refers to the same physical location.
        # Shifted ~0.35 deg west of the true Portland point (-122.60917) so
        # the bottom-left legend lands mostly over open ocean instead of on
        # top of Newport/Lincoln City -- everything else in this project
        # that shares "the Portland point" (e.g. tri-cities-7day-forecast)
        # still uses the unshifted -122.60917.
        center_lon=-122.95917, center_lat=45.59578,
        roads_files=["washington_roads.geojson", "oregon_roads.geojson"],
        output="portland_alerts.png",
        cities=[
            ("Portland", -122.6765, 45.5152, "right"),
            ("Vancouver", -122.6615, 45.6387, "right"),
            ("Hillsboro", -122.9898, 45.5229, "left"),
            ("Salem", -123.0351, 44.9429, "left"),
            ("Eugene", -123.0868, 44.0521, "left"),
            ("Corvallis", -123.2620, 44.5646, "left"),
            ("Astoria", -123.8313, 46.1879, "left"),
            ("Newport", -124.0535, 44.6365, "left"),
            ("Lincoln City", -124.0179, 44.9582, "left"),
            ("Tillamook", -123.8429, 45.4554, "left"),
            ("Aberdeen", -123.8157, 46.9754, "left"),
            ("Longview", -122.9382, 46.1382, "right"),
            ("Olympia", -122.9007, 47.0379, "left"),
            ("Tacoma", -122.4443, 47.2529, "right"),
            ("Centralia", -122.9543, 46.7162, "left"),
            ("The Dalles", -121.1787, 45.5946, "right"),
            ("Hood River", -121.5215, 45.7054, "right"),
            ("Government Camp", -121.7550, 45.3021, "below-right"),
            ("Packwood", -121.6733, 46.6088, "right"),
            ("Bend", -121.3153, 44.0582, "right"),
            ("Redmond", -121.1739, 44.2726, "right"),
        ],
    ),
    # PREVIEW ONLY -- lon_span/lat_span/satellite_height are overridden here
    # since this region is a fundamentally different (much wider) zoom than
    # Columbia Basin/Portland's shared true-zoom-level setup, not a variant
    # of it.
    "pnw_wide": dict(
        title="Pacific Northwest + Adjacent Areas",
        center_lon=-119.3, center_lat=44.9,
        lon_span=13.0, lat_span=8.8, satellite_height=22_000_000,
        legend_loc="upper right",
        roads_files=["washington_roads.geojson", "oregon_roads.geojson", "idaho_roads.geojson",
                     "nevada_roads_north.geojson", "montana_roads_west.geojson",
                     "california_roads_north.geojson", "utah_roads_northwest.geojson"],
        output="pnw_wide_alerts_PREVIEW.png",
        cities=[
            ("Seattle", -122.3321, 47.6062, "left"),
            ("Bellingham", -122.4443, 48.7519, "left"),
            ("Spokane", -117.4260, 47.6588, "below-right"),
            ("Wenatchee", -120.3103, 47.4235, "right"),
            ("Yakima", -120.5059, 46.6021, "left"),
            ("Tri-Cities", -119.1372, 46.2112, "right"),
            ("Portland", -122.6765, 45.5152, "below-left"),
            ("Eugene", -123.0868, 44.0521, "left"),
            ("Medford", -122.8756, 42.3265, "left"),
            ("Weed", -122.3861, 41.4227, "left"),
            ("Bend", -121.3153, 44.0582, "right"),
            ("Klamath Falls", -121.7817, 42.2249, "right"),
            ("John Day", -118.9490, 44.4165, "right"),
            ("Burns", -119.0541, 43.5865, "right"),
            ("Boise", -116.2023, 43.6150, "right"),
            ("Twin Falls", -114.4609, 42.5629, "right"),
            ("Lewiston", -117.0177, 46.4165, "right"),
            ("Missoula", -113.9940, 46.8721, "right"),
            ("Salmon", -113.9032, 45.1758, "right"),
        ],
    ),
}


def darken(hexcolor, factor=0.6):
    hexcolor = hexcolor.lstrip("#")
    r, g, b = (int(hexcolor[i:i+2], 16) for i in (0, 2, 4))
    r, g, b = int(r*factor), int(g*factor), int(b*factor)
    return f"#{r:02x}{g:02x}{b:02x}"


def hex_to_rgb(hexcolor):
    hexcolor = hexcolor.lstrip("#")
    return tuple(int(hexcolor[i:i+2], 16) for i in (0, 2, 4))


def trim_offshore_segments(geom, land_union, threshold):
    """Cut interior offshore-excursion vertices out of an admin-1 boundary
    line instead of an all-or-nothing whole-feature filter. Oregon's 3nm
    state-waters jog is its own separate feature (entirely offshore, so a
    whole-feature min-distance filter drops it cleanly), but Washington's
    equivalent jog is fused into the *same* LineString as its real Canada
    and Columbia River land borders -- since part of that line touches
    land, the feature's overall min distance is 0 and a whole-feature
    filter keeps the whole thing, offshore jog included. Splitting on
    per-vertex distance and keeping only the near-land runs handles both
    shapes correctly."""
    lines = geom.geoms if geom.geom_type == "MultiLineString" else [geom]
    kept = []
    for line in lines:
        run = []
        for x, y in line.coords:
            if Point(x, y).distance(land_union) <= threshold:
                run.append((x, y))
            else:
                if len(run) >= 2:
                    kept.append(LineString(run))
                run = []
        if len(run) >= 2:
            kept.append(LineString(run))
    return kept


# Longest legitimate segment length seen in admin1_boundary_lines.json's
# TIGER-derived state lines is ~1.6 degrees; countries_slim.json's country
# borders, by contrast, have several segments over-simplified down to a
# single straight run of 3 to 27+ degrees (e.g. the entire WA-to-Minnesota
# stretch of the 49th parallel collapsed to one 27.6-degree segment) --
# those don't track the real border and show up as a stray straight line
# cutting across more detailed layers once a region's extent is wide
# enough to reach them. 3 degrees sits comfortably above any real
# simplification grain seen in either file and well below the degenerate
# ones.
MAX_BORDER_SEGMENT_DEG = 3.0


def drop_long_segments(geom, max_len):
    """Split polygon/line boundary rings on any segment longer than
    max_len, dropping it -- see MAX_BORDER_SEGMENT_DEG above. Safe for any
    outline-only (facecolor="none") layer since there's no fill to
    preserve, only the traced border."""
    if geom.geom_type == "MultiPolygon":
        rings = []
        for poly in geom.geoms:
            rings.append(poly.exterior)
            rings.extend(poly.interiors)
    elif geom.geom_type == "Polygon":
        rings = [geom.exterior] + list(geom.interiors)
    elif geom.geom_type == "MultiLineString":
        rings = list(geom.geoms)
    elif geom.geom_type == "LineString":
        rings = [geom]
    else:
        return []
    kept = []
    for ring in rings:
        run = []
        for x, y in ring.coords:
            if run:
                px, py = run[-1]
                if math.hypot(x - px, y - py) > max_len:
                    if len(run) >= 2:
                        kept.append(LineString(run))
                    run = []
            run.append((x, y))
        if len(run) >= 2:
            kept.append(LineString(run))
    return kept


# Degree^2 area floor for keeping a polygon from an overlay op. The
# smallest real alert zone we've seen is ~0.006 deg^2; floating-point
# slivers from touching boundaries have measured as large as ~3e-7
# deg^2 (a ~1km-long, near-zero-width strip) and still broken cartopy's
# projection cutting, so this floor sits comfortably between the two.
MIN_POLY_AREA = 1e-4


def polygons_only(geom):
    """Drop degenerate Point/LineString/near-zero-area slivers that
    shapely's intersection and difference ops leave behind at touching
    polygon boundaries. Left in, cartopy's projection code can't cut a
    degenerate ring cleanly and falls back to covering the entire
    projection disk instead of the sliver's true (near-zero) extent --
    which is what made overlap-stripe fills bleed across the whole map."""
    if geom.geom_type == "GeometryCollection":
        parts = [g for g in geom.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
        geom = unary_union(parts) if parts else Polygon()
    if geom.geom_type not in ("Polygon", "MultiPolygon"):
        return Polygon()
    polys = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
    kept = [p for p in polys if p.area > MIN_POLY_AREA]
    if not kept:
        return Polygon()
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


def build_map(region_key, alerts_path, output_path):
    cfg = REGIONS[region_key]
    extent = region_extent(cfg["center_lon"], cfg["center_lat"],
                            cfg.get("lon_span", LON_SPAN), cfg.get("lat_span", LAT_SPAN))

    proj = ccrs.NearsidePerspective(central_longitude=cfg["center_lon"],
                                     central_latitude=cfg["center_lat"],
                                     satellite_height=cfg.get("satellite_height", SATELLITE_HEIGHT))
    pc = ccrs.PlateCarree()

    fig = plt.figure(figsize=(12, 8.3), dpi=200)
    fig.patch.set_facecolor("#f7f6f2")
    ax = fig.add_axes([0.04, 0.045, 0.92, 0.80], projection=proj)
    ax.set_facecolor("white")
    ax.set_extent(extent, crs=pc)

    # Pixel size of the map's plotted area, used later to render candy-stripe
    # fills at a consistent on-screen stripe width regardless of map extent.
    fig.canvas.draw()
    ax_bbox = ax.get_window_extent()
    ax_w_px, ax_h_px = int(ax_bbox.width), int(ax_bbox.height)

    # ---------- land ----------
    land = json.load(open(f"{MAPS_DIR}/land_slim.json"))
    geoms = [shape(f["geometry"]) for f in land["features"]]
    ax.add_geometries(geoms, crs=pc, facecolor="#e3e1da", edgecolor="none", zorder=1)

    # ---------- countries (US/Canada/Mexico border) ----------
    countries = json.load(open(f"{MAPS_DIR}/countries_slim.json"))
    target_names = {"United States of America", "Canada", "Mexico"}
    c_geoms = []
    for f in countries["features"]:
        props = f["properties"]
        name = props.get("NAME") or props.get("ADMIN") or props.get("name")
        if name in target_names:
            c_geoms.extend(drop_long_segments(shape(f["geometry"]), MAX_BORDER_SEGMENT_DEG))
    ax.add_geometries(c_geoms, crs=pc, facecolor="none", edgecolor="#9a978c",
                       linewidth=1.1, zorder=2)

    # ---------- states + lakes ----------
    # State outlines come from the dedicated admin1_boundary_lines.json (TIGER-
    # derived for the US, full state-line precision -- following rivers like
    # the WA/OR border tightly instead of states_lakes_slim.json's coarser,
    # generalized polygon edges), not from the lake/state polygon file's own
    # state boundaries. Lakes still come from states_lakes_slim.json since
    # that's the only source for them.
    admin1_lines = json.load(open(f"{MAPS_DIR}/admin1_boundary_lines.json"))
    raw_geoms = [shape(f["geometry"]) for f in admin1_lines["features"]]
    # Drop each coastal state's 3-nautical-mile offshore maritime boundary
    # (its state-waters extent), which Natural Earth includes as an
    # ordinary admin-1 boundary line running parallel to, but detached
    # from, the actual coastline -- confirmed by distance from the land
    # layer, same as western-us-noaa-outlooks. Oregon's version is its own
    # feature (entirely offshore) so a whole-feature filter drops it
    # cleanly; Washington's is fused into the same line as its real land
    # borders, so it needs the per-vertex trim in trim_offshore_segments()
    # too -- see that function's docstring.
    land_union = unary_union(geoms)
    s_geoms = []
    for g in raw_geoms:
        if g.distance(land_union) <= OFFSHORE_LINE_DISTANCE_DEG:
            s_geoms.extend(trim_offshore_segments(g, land_union, OFFSHORE_LINE_DISTANCE_DEG))

    states = json.load(open(f"{MAPS_DIR}/states_lakes_slim.json"))
    lake_geoms = []
    for f in states["features"]:
        props = f["properties"]
        featurecla = props.get("featurecla", "")
        admin = props.get("admin", "")
        if admin in ("United States of America", "Canada", "Mexico") and "Lake" in featurecla:
            lake_geoms.append(shape(f["geometry"]))
    ax.add_geometries(s_geoms, crs=pc, facecolor="none", edgecolor="#b9b6ac",
                       linewidth=0.8, zorder=3)
    ax.add_geometries(lake_geoms, crs=pc, facecolor="white", edgecolor="#b9b6ac",
                       linewidth=0.7, zorder=3)

    # ---------- counties ----------
    counties = json.load(open(f"{MAPS_DIR}/counties_wa_or_id.geojson"))
    co_geoms = [shape(f["geometry"]) for f in counties["features"]]
    ax.add_geometries(co_geoms, crs=pc, facecolor="none", edgecolor="#c7c4b8",
                       linewidth=0.5, zorder=4)

    # ---------- roads ----------
    # oregon_roads.geojson/washington_roads.geojson/idaho_roads_north.geojson
    # originally only had motorway/trunk OSM tags -- primary was added later
    # (regenerated from fresh Geofabrik OR/WA/ID extracts) specifically
    # because US-26 toward Government Camp, US-97 through Bend/Redmond, and
    # most of the Willamette Valley's highways south of Portland are tagged
    # `primary` in OSM, not `trunk` -- they were structurally absent before,
    # not just filtered out here.
    MOTORWAY = {"motorway", "motorway_link"}
    TRUNK = {"trunk", "trunk_link"}
    PRIMARY = {"primary", "primary_link"}
    MOTORWAY_COLOR = "#8FB8E0"  # pastel blue
    TRUNK_COLOR = "#F2B880"     # pastel orange
    PRIMARY_COLOR = "#E8C9A0"   # lighter/duller pastel orange -- one step down from trunk

    motorway_geoms, trunk_geoms, primary_geoms = [], [], []
    for region_file in cfg["roads_files"]:
        d = json.load(open(f"{MAPS_DIR}/{region_file}"))
        for f in d["features"]:
            hwy = f["properties"].get("highway")
            geom = shape(f["geometry"])
            if hwy in MOTORWAY:
                motorway_geoms.append(geom)
            elif hwy in TRUNK:
                trunk_geoms.append(geom)
            elif hwy in PRIMARY:
                primary_geoms.append(geom)

    ax.add_geometries(primary_geoms, crs=pc, facecolor="none", edgecolor=PRIMARY_COLOR,
                       linewidth=0.9, zorder=4.8)
    ax.add_geometries(trunk_geoms, crs=pc, facecolor="none", edgecolor=TRUNK_COLOR,
                       linewidth=1.1, zorder=5)
    ax.add_geometries(motorway_geoms, crs=pc, facecolor="none", edgecolor=MOTORWAY_COLOR,
                       linewidth=1.3, zorder=6)

    # ---------- alerts ----------
    alerts = json.load(open(alerts_path))
    extent_box = box(extent[0], extent[2], extent[1], extent[3])

    # Union every zone geometry per event type -- this both merges adjacent
    # same-event zones into one clean outline and naturally de-duplicates
    # NWS products that cover the exact same zone twice.
    event_geoms = {}
    plotted_zones = set()  # (event, zone_id)
    for a in alerts:
        event = a["event"]
        for z in a["zones"]:
            zone_key = (event, z.get("zone_id"))
            if zone_key in plotted_zones:
                continue
            plotted_zones.add(zone_key)
            event_geoms.setdefault(event, []).append(shape(z["geometry"]))
    event_geoms = {event: unary_union(geoms) for event, geoms in event_geoms.items()}

    # Only reflect an event in the title/legend if it's actually visible
    # somewhere in the current map domain -- NWS returns every active alert
    # for the queried states, some of which can sit far outside whatever
    # extent we're currently showing.
    active_event_types = [event for event, geom in event_geoms.items()
                           if geom.intersects(extent_box)]

    # Polygon-type warnings (see POLYGON_WARNING_EVENTS) are drawn as an
    # outlined boundary line, not shaded -- pull them out before the
    # shading/overlap-stripe partition logic below, which only makes sense
    # for zone-based hazards.
    outline_event_geoms = {e: g for e, g in event_geoms.items() if e in POLYGON_WARNING_EVENTS}
    shaded_event_geoms = {e: g for e, g in event_geoms.items() if e not in POLYGON_WARNING_EVENTS}

    # Split the events into a partition of disjoint regions, each tagged with
    # the set of events covering it, so overlapping alerts (e.g. a Red Flag
    # Warning inside a Heat Advisory) can be drawn as their own region instead
    # of alpha-stacking into a color that matches neither alert.
    partition = []  # list of (geom, frozenset(events))
    for event, geom in shaded_event_geoms.items():
        next_partition = []
        remaining = geom
        for cell_geom, cell_events in partition:
            overlap = polygons_only(cell_geom.intersection(remaining))
            if not overlap.is_empty:
                next_partition.append((overlap, cell_events | {event}))
            rest = polygons_only(cell_geom.difference(remaining))
            if not rest.is_empty:
                next_partition.append((rest, cell_events))
            remaining = polygons_only(remaining.difference(cell_geom))
        if not remaining.is_empty:
            next_partition.append((remaining, frozenset({event})))
        partition = next_partition

    # Merge same-tagged cells back together so each distinct combination of
    # overlapping events is drawn (and clipped) once.
    combo_geoms = defaultdict(list)
    for geom, tags in partition:
        combo_geoms[tags].append(geom)
    combo_geoms = {tags: polygons_only(unary_union(geoms))
                    for tags, geoms in combo_geoms.items()}

    OVERLAP_EDGE = "#4a4a4a"

    for tags, geom in combo_geoms.items():
        if geom.is_empty:
            continue
        if len(tags) == 1:
            event = next(iter(tags))
            fill = NWS_COLORS.get(event, "#e8a33d")
            edge = EDGE_OVERRIDE.get(event, darken(fill, 0.55))
            ax.add_geometries([geom], crs=pc, facecolor=fill, edgecolor=edge,
                               alpha=0.55, linewidth=1.2, zorder=4.5)
            ax.add_geometries([geom], crs=pc, facecolor="none", edgecolor=edge,
                               linewidth=1.2, alpha=1.0, zorder=4.6)
            continue

        # Overlap region: fill with alternating stripes, one band per
        # contributing event, clipped to the region's exact shape. Same
        # alpha as the single-event fill so overlap zones don't read darker.
        colors = [NWS_COLORS.get(e, "#e8a33d") for e in sorted(tags)]
        stripe_img = make_stripe_image(colors, ax_w_px, ax_h_px)
        proj_geom = ax.projection.project_geometry(geom, pc)
        clip_path = shapely_to_path(proj_geom)
        clip_patch = PathPatch(clip_path, transform=ax.transData)
        # GeoAxes overrides imshow to require a CRS transform; we're placing
        # this in plain axes-fraction space, so call the base Axes.imshow.
        im = Axes.imshow(ax, stripe_img, extent=(0, 1, 0, 1), transform=ax.transAxes,
                          origin="upper", interpolation="nearest", alpha=0.55, zorder=4.5)
        im.set_clip_path(clip_patch)
        ax.add_geometries([geom], crs=pc, facecolor="none", edgecolor=OVERLAP_EDGE,
                           linewidth=1.2, alpha=1.0, zorder=4.6)

    # Polygon-type warnings drawn last (highest zorder among alerts) so
    # they're never buried under the zone-based shading -- a black outline
    # behind the event's own color traces just the polygon boundary, no
    # fill, per POLYGON_WARNING_EVENTS above.
    for event, geom in outline_event_geoms.items():
        if geom.is_empty or not geom.intersects(extent_box):
            continue
        color = NWS_COLORS.get(event, "#e8a33d")
        ax.add_geometries([geom], crs=pc, facecolor="none", edgecolor="black",
                           linewidth=2.6, zorder=4.7)
        ax.add_geometries([geom], crs=pc, facecolor="none", edgecolor=color,
                           linewidth=1.4, zorder=4.8)

    # ---------- city labels ----------
    # 8-way (not just left/right) since Columbia Basin's original 2-way
    # left/right was tuned against cities spread far enough apart that a
    # fixed horizontal-only offset never collided -- Portland's much
    # tighter cluster (Portland/Vancouver/Beaverton/Hillsboro/Gresham are
    # all within a few miles of each other) needs the diagonals too: with
    # Vancouver/Hillsboro/Gresham unambiguously north/west/east, Portland
    # and Beaverton both want a southward label, and plain "below" for
    # both collides -- below-left/below-right split them apart instead of
    # landing on the same latitude.
    POS_DX = {"right": 0.13, "below-right": 0.11, "above-right": 0.11,
              "left": -0.13, "below-left": -0.11, "above-left": -0.11}
    POS_DY = {"above": 0.09, "above-left": 0.08, "above-right": 0.08,
              "below": -0.09, "below-left": -0.08, "below-right": -0.08}
    POS_HA = {"right": "left", "above-right": "left", "below-right": "left",
              "left": "right", "above-left": "right", "below-left": "right"}
    POS_VA = {"above": "bottom", "above-left": "bottom", "above-right": "bottom",
              "below": "top", "below-left": "top", "below-right": "top"}
    for name, lon, lat, pos in cfg["cities"]:
        ax.plot(lon, lat, marker="o", markersize=4, color="black",
                 transform=pc, zorder=8)
        dx, dy = POS_DX.get(pos, 0), POS_DY.get(pos, 0)
        ha, va = POS_HA.get(pos, "center"), POS_VA.get(pos, "center")
        txt = ax.text(lon + dx, lat + dy, name, transform=pc, ha=ha, va=va,
                       fontproperties=f_med, fontsize=11, color="black", zorder=9)
        txt.set_path_effects([pe.withStroke(linewidth=1.65, foreground="white", alpha=0.6)])

    # ---------- frame ----------
    ax.spines["geo"].set_edgecolor("black")
    ax.spines["geo"].set_linewidth(1.6)

    # Cartopy shrinks the axes box to preserve the projection's aspect ratio,
    # so the map frame doesn't actually sit at the nominal axes position we
    # requested. Force a draw and read back where it really landed so the
    # title/legend/attribution/logo can align to it instead of the figure edge.
    fig.canvas.draw()
    map_pos = ax.get_position()
    left_x = map_pos.x0
    right_x = map_pos.x1
    top_y = map_pos.y1
    center_x = (map_pos.x0 + map_pos.x1) / 2

    # ---------- logo (bottom-right, ~8% of map width, ~22px inset) ----------
    LOGO_PATH = "../assets/ingalls_weather_logo.png"
    if os.path.exists(LOGO_PATH):
        logo_img = plt.imread(LOGO_PATH)
        img_h, img_w = logo_img.shape[0], logo_img.shape[1]
        fig_w_in, fig_h_in = fig.get_size_inches()
        dpi = fig.get_dpi()
        inset_px = 22
        inset_x = inset_px / (fig_w_in * dpi)
        inset_y = inset_px / (fig_h_in * dpi)

        logo_width_fig = 0.08 * (map_pos.x1 - map_pos.x0)
        logo_width_in = logo_width_fig * fig_w_in
        logo_height_in = logo_width_in * (img_h / img_w)
        logo_height_fig = logo_height_in / fig_h_in

        logo_x0 = map_pos.x1 - inset_x - logo_width_fig
        logo_y0 = map_pos.y0 + inset_y
        logo_ax = fig.add_axes([logo_x0, logo_y0, logo_width_fig, logo_height_fig], zorder=20)
        logo_ax.imshow(logo_img)
        logo_ax.axis("off")
    else:
        print(f"NOTE: no logo found at {LOGO_PATH} -- skipping logo placement.")

    # ---------- title / subtitle ----------
    subtitle_y = top_y + 0.018
    title_y = subtitle_y + 0.035
    fig.text(left_x, title_y, "Active NWS Weather Alerts",
              fontproperties=f_bold, fontsize=22, color="#2b2a26")
    now_pt = datetime.now(ZoneInfo("America/Los_Angeles"))
    subtitle = f"Updated: {now_pt.strftime('%d %B %Y %H:%M')} PT"
    fig.text(left_x, subtitle_y, subtitle, fontproperties=f_reg, fontsize=12, color="#5a584f")

    # ---------- legend ----------
    legend_handles = []
    for event in active_event_types:
        fill = NWS_COLORS.get(event, "#e8a33d")
        if event in POLYGON_WARNING_EVENTS:
            # Matches the outlined-line treatment these get on the map
            # instead of a shaded fill -- a solid Patch swatch here would
            # misrepresent how the event actually looks.
            legend_handles.append(Line2D([0], [0], color=fill, linewidth=2.5, label=event))
        else:
            edge = EDGE_OVERRIDE.get(event, darken(fill, 0.55))
            legend_handles.append(Patch(facecolor=fill, edgecolor=edge, alpha=0.85, label=event))

    # Legend corner defaults to lower-left (tuned so it sits over open ocean
    # on Columbia Basin/Portland) -- pnw_wide overrides to upper-right since
    # its lower-left corner covers real cities (Redding/Eureka, CA) at this
    # much wider zoom instead of empty ocean.
    legend_loc = cfg.get("legend_loc", "lower left")
    if legend_loc == "upper right":
        legend_anchor = (right_x - 0.012, top_y - 0.012)
    else:
        legend_anchor = (left_x + 0.012, map_pos.y0 + 0.012)
    # More than 5 active alert types stops fitting comfortably at the
    # normal size -- halve the font/handle/spacing so a busy day's legend
    # still fits without spilling off the map. legend()'s own `fontsize`
    # kwarg is silently ignored whenever `prop` is also a FontProperties
    # instance (matplotlib only falls back to fontsize when prop is None),
    # so the size has to be set on a copy of the FontProperties itself.
    many_events = len(active_event_types) > 5
    legend_font = f_reg.copy()
    legend_font.set_size(5 if many_events else 10)
    leg = fig.legend(handles=legend_handles, loc=legend_loc,
                      bbox_to_anchor=legend_anchor,
                      bbox_transform=fig.transFigure,
                      frameon=True, facecolor="white", edgecolor="#d8d5cc",
                      framealpha=1.0, prop=legend_font,
                      borderpad=0.4 if many_events else 0.8,
                      labelspacing=0.25 if many_events else 0.5,
                      handlelength=1.0 if many_events else 2.0,
                      handleheight=0.35 if many_events else 0.7)
    leg.get_frame().set_linewidth(0.8)

    # ---------- attribution ----------
    fig.text(center_x, 0.02, "NWS / US Census (counties) / OpenStreetMap (roads) — Ingalls Weather",
              fontproperties=f_reg, fontsize=9, color="#5a584f", ha="center")

    plt.savefig(output_path, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    print(f"saved {output_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Render a Columbia Basin / Portland Metro NWS alerts map.")
    ap.add_argument("--region", choices=sorted(REGIONS), default="columbia_basin")
    ap.add_argument("--alerts", default="alerts_with_zones.json")
    ap.add_argument("--output", default=None,
                     help="Output PNG path (default: REGIONS[region]['output'])")
    args = ap.parse_args()
    build_map(args.region, args.alerts, args.output or REGIONS[args.region]["output"])

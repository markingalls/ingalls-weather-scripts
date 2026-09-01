import json
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
from shapely.geometry import shape, box, Polygon
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


def darken(hexcolor, factor=0.6):
    hexcolor = hexcolor.lstrip("#")
    r, g, b = (int(hexcolor[i:i+2], 16) for i in (0, 2, 4))
    r, g, b = int(r*factor), int(g*factor), int(b*factor)
    return f"#{r:02x}{g:02x}{b:02x}"


def hex_to_rgb(hexcolor):
    hexcolor = hexcolor.lstrip("#")
    return tuple(int(hexcolor[i:i+2], 16) for i in (0, 2, 4))


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


def make_stripe_image(colors, width_px, height_px, stripe_px=20, seam_px=2):
    """Diagonal candy-stripe raster alternating full-opacity bands of
    each color in `colors`, sized to cover width_px x height_px. A thin
    darkened seam is drawn at each band boundary so low-contrast color
    pairs (e.g. Air Quality Alert's gray next to a pale watch color)
    still read as distinct bands instead of blurring into a flat wash."""
    yy, xx = np.mgrid[0:height_px, 0:width_px]
    diag = xx + yy
    band = (diag // stripe_px) % len(colors)
    img = np.zeros((height_px, width_px, 3), dtype=np.uint8)
    for i, c in enumerate(colors):
        img[band == i] = hex_to_rgb(c)
    seam = (diag % stripe_px) < seam_px
    img[seam] = (img[seam].astype(float) * 0.55).astype(np.uint8)
    return img


# ---------- extent / projection ----------
# SE Texas (Houston-Galveston-Beaumont corridor) down to the adjacent
# Louisiana parishes around Lake Charles and Lafayette.
EXTENT = [-97.3, -92.0, 27.6, 31.3]
CENTER_LON, CENTER_LAT = -94.65, 29.45

proj = ccrs.NearsidePerspective(central_longitude=CENTER_LON,
                                 central_latitude=CENTER_LAT,
                                 satellite_height=4_000_000)
pc = ccrs.PlateCarree()

fig = plt.figure(figsize=(12, 8.3), dpi=200)
fig.patch.set_facecolor("#f7f6f2")
ax = fig.add_axes([0.04, 0.045, 0.92, 0.80], projection=proj)
ax.set_facecolor("white")
ax.set_extent(EXTENT, crs=pc)

# Pixel size of the map's plotted area, used later to render candy-stripe
# fills at a consistent on-screen stripe width regardless of map extent.
fig.canvas.draw()
ax_bbox = ax.get_window_extent()
AX_W_PX, AX_H_PX = int(ax_bbox.width), int(ax_bbox.height)

MAPS_DIR = "../maps"

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
        c_geoms.append(shape(f["geometry"]))
ax.add_geometries(c_geoms, crs=pc, facecolor="none", edgecolor="#9a978c",
                   linewidth=1.1, zorder=2)

# ---------- states + lakes ----------
# State outlines come from the dedicated admin1_boundary_lines.json (TIGER-
# derived for the US, full state-line precision), not from the lake/state
# polygon file's own state boundaries -- see columbia-basin-alerts-map's
# README for why. Lakes still come from states_lakes_slim.json since
# that's the only source for them.
admin1_lines = json.load(open(f"{MAPS_DIR}/admin1_boundary_lines.json"))
s_geoms = [shape(f["geometry"]) for f in admin1_lines["features"]]

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
counties = json.load(open(f"{MAPS_DIR}/counties_tx_la.geojson"))
co_geoms = [shape(f["geometry"]) for f in counties["features"]]
ax.add_geometries(co_geoms, crs=pc, facecolor="none", edgecolor="#c7c4b8",
                   linewidth=0.5, zorder=4)

# ---------- roads ----------
# Sourced from Census TIGER/Line primary roads (RTTYP: I=Interstate,
# U=US highway, S=State highway, M=named local/freeway, O=other) rather
# than OSM motorway/trunk tags -- Overpass/Geofabrik weren't reachable
# from this environment. Interstates and named freeways/tollways/beltways
# (RTTYP M is almost entirely Houston-area limited-access roads like the
# Sam Houston Tollway and Gulf Fwy) are styled as motorway; numbered US/
# state highways are styled as trunk.
MOTORWAY_RTTYP = {"I", "M"}
MOTORWAY_COLOR = "#8FB8E0"  # pastel blue
TRUNK_COLOR = "#F2B880"     # pastel orange

roads = json.load(open(f"{MAPS_DIR}/se_texas_la_primary_roads.geojson"))
motorway_geoms, trunk_geoms = [], []
for f in roads["features"]:
    rttyp = f["properties"].get("RTTYP")
    geom = shape(f["geometry"])
    if rttyp in MOTORWAY_RTTYP:
        motorway_geoms.append(geom)
    else:
        trunk_geoms.append(geom)

ax.add_geometries(trunk_geoms, crs=pc, facecolor="none", edgecolor=TRUNK_COLOR,
                   linewidth=1.1, zorder=5)
ax.add_geometries(motorway_geoms, crs=pc, facecolor="none", edgecolor=MOTORWAY_COLOR,
                   linewidth=1.3, zorder=6)

# ---------- alerts ----------
alerts = json.load(open("alerts_with_zones.json"))
extent_box = box(EXTENT[0], EXTENT[2], EXTENT[1], EXTENT[3])

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

# Split the events into a partition of disjoint regions, each tagged with
# the set of events covering it, so overlapping alerts (e.g. a Red Flag
# Warning inside a Heat Advisory) can be drawn as their own region instead
# of alpha-stacking into a color that matches neither alert.
partition = []  # list of (geom, frozenset(events))
for event, geom in event_geoms.items():
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
                           alpha=0.68, linewidth=1.2, zorder=4.5)
        ax.add_geometries([geom], crs=pc, facecolor="none", edgecolor=edge,
                           linewidth=1.2, alpha=1.0, zorder=4.6)
        continue

    # Overlap region: fill with alternating stripes, one band per
    # contributing event, clipped to the region's exact shape. Same
    # alpha as the single-event fill (0.68) so each band keeps enough
    # contrast against the basemap to read as its own color instead of
    # the pair blurring into a single tone -- most visible when Air
    # Quality Alert's gray sits next to another pale color.
    colors = [NWS_COLORS.get(e, "#e8a33d") for e in sorted(tags)]
    stripe_img = make_stripe_image(colors, AX_W_PX, AX_H_PX)
    proj_geom = ax.projection.project_geometry(geom, pc)
    clip_path = shapely_to_path(proj_geom)
    clip_patch = PathPatch(clip_path, transform=ax.transData)
    # GeoAxes overrides imshow to require a CRS transform; we're placing
    # this in plain axes-fraction space, so call the base Axes.imshow.
    im = Axes.imshow(ax, stripe_img, extent=(0, 1, 0, 1), transform=ax.transAxes,
                      origin="upper", interpolation="nearest", alpha=0.68, zorder=4.5)
    im.set_clip_path(clip_patch)
    ax.add_geometries([geom], crs=pc, facecolor="none", edgecolor=OVERLAP_EDGE,
                       linewidth=1.2, alpha=1.0, zorder=4.6)

# ---------- city labels ----------
cities = [
    ("El Campo", -96.2694, 29.1966, "left", 0),
    ("Bay City", -95.9694, 28.9836, "left", 0),
    ("College Station", -96.3344, 30.6280, "left", 0),
    ("Huntsville", -95.5508, 30.7235, "left", 0),
    ("Livingston", -94.9327, 30.7118, "right", 0),
    ("Conroe", -95.4560, 30.3119, "left", 0),
    ("Cleveland", -95.0847, 30.3413, "right", 0),
    ("Houston", -95.3698, 29.7604, "right", 0),
    ("Baytown", -94.9774, 29.7355, "right", 0),
    ("Freeport", -95.3599, 28.9541, "right", 0),
    ("Galveston", -94.7977, 29.3013, "right", 0),
    ("Texas City", -94.9027, 29.3838, "left", 0),
    ("Jasper", -94.0055, 30.9202, "left", 0),
    ("Beaumont", -94.1266, 30.0860, "left", 0),
    ("Orange", -93.7360, 30.0930, "right", 0),
    ("Port Arthur", -93.9399, 29.8850, "right", 0),
    ("Cameron", -93.3352, 29.7961, "right", 0),
    ("DeRidder", -93.2885, 30.8460, "left", 0),
    # Lake Charles and Lafayette sit close together at nearly the same
    # latitude -- stagger them vertically too, or their side-extending
    # text runs into each other across the gap.
    ("Lake Charles", -93.2174, 30.2266, "right", -0.11),
    ("Lafayette", -92.0198, 30.2241, "left", 0.11),
]
for name, lon, lat, side, dy in cities:
    ax.plot(lon, lat, marker="o", markersize=4, color="black",
             transform=pc, zorder=8)
    ha = "left" if side == "right" else "right"
    dx = 0.12 if side == "right" else -0.12
    va = "center" if dy == 0 else ("bottom" if dy > 0 else "top")
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
now_ct = datetime.now(ZoneInfo("America/Chicago"))
subtitle = f"Updated: {now_ct.strftime('%d %B %Y %H:%M')} CT"
fig.text(left_x, subtitle_y, subtitle, fontproperties=f_reg, fontsize=12, color="#5a584f")

# ---------- legend ----------
legend_handles = []
for event in active_event_types:
    fill = NWS_COLORS.get(event, "#e8a33d")
    edge = EDGE_OVERRIDE.get(event, darken(fill, 0.55))
    legend_handles.append(Patch(facecolor=fill, edgecolor=edge, alpha=0.85, label=event))

leg = fig.legend(handles=legend_handles, loc="lower left",
                  bbox_to_anchor=(left_x + 0.012, map_pos.y0 + 0.012),
                  bbox_transform=fig.transFigure,
                  frameon=True, facecolor="white", edgecolor="#d8d5cc",
                  framealpha=1.0, prop=f_reg, fontsize=10, borderpad=0.8)
leg.get_frame().set_linewidth(0.8)

# ---------- attribution ----------
fig.text(center_x, 0.02, "NWS / US Census (counties, roads) — Ingalls Weather",
          fontproperties=f_reg, fontsize=9, color="#5a584f", ha="center")


plt.savefig("se_texas_alerts.png",
            facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
print("saved")

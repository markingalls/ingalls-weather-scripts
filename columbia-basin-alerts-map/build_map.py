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


# ---------- extent / projection ----------
# Zoomed view: North Bend, WA down to Baker City, OR corridor
EXTENT = [-122.5, -117.0, 44.4, 48.0]
CENTER_LON, CENTER_LAT = -119.75, 46.2

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
states = json.load(open(f"{MAPS_DIR}/states_lakes_slim.json"))
s_geoms = []
lake_geoms = []
for f in states["features"]:
    props = f["properties"]
    featurecla = props.get("featurecla", "")
    admin = props.get("admin", "")
    if admin in ("United States of America", "Canada", "Mexico"):
        if "Lake" in featurecla:
            lake_geoms.append(shape(f["geometry"]))
        else:
            s_geoms.append(shape(f["geometry"]))
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
MOTORWAY = {"motorway", "motorway_link"}
TRUNK = {"trunk", "trunk_link"}
MOTORWAY_COLOR = "#8FB8E0"  # pastel blue
TRUNK_COLOR = "#F2B880"     # pastel orange

motorway_geoms, trunk_geoms = [], []
for region_file in ["washington_roads.geojson", "oregon_roads.geojson", "idaho_roads_north.geojson"]:
    d = json.load(open(f"{MAPS_DIR}/{region_file}"))
    for f in d["features"]:
        hwy = f["properties"].get("highway")
        geom = shape(f["geometry"])
        if hwy in MOTORWAY:
            motorway_geoms.append(geom)
        elif hwy in TRUNK:
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
                           alpha=0.55, linewidth=1.2, zorder=4.5)
        ax.add_geometries([geom], crs=pc, facecolor="none", edgecolor=edge,
                           linewidth=1.2, alpha=1.0, zorder=4.6)
        continue

    # Overlap region: fill with alternating stripes, one band per
    # contributing event, clipped to the region's exact shape. Same
    # alpha as the single-event fill so overlap zones don't read darker.
    colors = [NWS_COLORS.get(e, "#e8a33d") for e in sorted(tags)]
    stripe_img = make_stripe_image(colors, AX_W_PX, AX_H_PX)
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

# ---------- city labels ----------
cities = [
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
]
for name, lon, lat, side in cities:
    ax.plot(lon, lat, marker="o", markersize=4, color="black",
             transform=pc, zorder=8)
    ha = "left" if side == "right" else "right"
    dx = 0.12 if side == "right" else -0.12
    txt = ax.text(lon + dx, lat, name, transform=pc, ha=ha, va="center",
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
fig.text(left_x, title_y, "Columbia Basin: Active NWS Weather Alerts",
          fontproperties=f_bold, fontsize=22, color="#2b2a26")
if active_event_types:
    subtitle = ", ".join(active_event_types) + " in effect"
else:
    subtitle = "No active NWS alerts"
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
fig.text(center_x, 0.02, "NWS / US Census (counties) / OpenStreetMap (roads) \u2014 Ingalls Weather",
          fontproperties=f_reg, fontsize=9, color="#5a584f", ha="center")


plt.savefig("columbia_basin_alerts.png",
            facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
print("saved")

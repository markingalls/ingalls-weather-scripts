import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
from matplotlib.lines import Line2D
import cartopy.crs as ccrs
from shapely.geometry import shape

PACIFIC = ZoneInfo("America/Los_Angeles")

# ---------- fonts ----------
FONT_DIR = "/usr/share/fonts/truetype/google-fonts/"
f_bold = fm.FontProperties(fname=FONT_DIR + "Poppins-Bold.ttf")
f_reg = fm.FontProperties(fname=FONT_DIR + "Poppins-Regular.ttf")
f_med = fm.FontProperties(fname=FONT_DIR + "Poppins-Medium.ttf")

# ---------- quake styling ----------
LATEST_COLOR = "#E0242B"
LATEST_EDGE = "#8E1116"
PAST_COLOR = "#8a877d"
PAST_EDGE = "#55534c"


def marker_diameter(mag):
    """Marker diameter in points. Linear in magnitude (which is already a
    log scale) -- M3 ~7pt up to M6 ~37pt -- so the 1936 M6 near Walla Walla
    reads as big without swallowing everything around it."""
    return 7 + (mag - 3.0) * 10


def marker_area(mag):
    return marker_diameter(mag) ** 2  # scatter's `s` is area in pt^2


# ---------- extent / projection (Wallowa County + neighbors) ----------
# Keep in sync with LON/LAT bounds in fetch_earthquakes.py.
EXTENT = [-118.6, -116.0, 44.65, 46.3]
CENTER_LON, CENTER_LAT = -117.3, 45.475

proj = ccrs.NearsidePerspective(central_longitude=CENTER_LON,
                                 central_latitude=CENTER_LAT,
                                 satellite_height=4_000_000)
pc = ccrs.PlateCarree()

fig = plt.figure(figsize=(10, 10.6), dpi=200)
fig.patch.set_facecolor("#f7f6f2")
ax = fig.add_axes([0.05, 0.085, 0.90, 0.80], projection=proj)
ax.set_facecolor("white")
ax.set_extent(EXTENT, crs=pc)

MAPS_DIR = "../maps"
WALLOWA_FIPS = "41063"

# ---------- land ----------
land = json.load(open(f"{MAPS_DIR}/land_slim.json"))
geoms = [shape(f["geometry"]) for f in land["features"]]
ax.add_geometries(geoms, crs=pc, facecolor="#e3e1da", edgecolor="none", zorder=1)

# ---------- states + lakes ----------
admin1_lines = json.load(open(f"{MAPS_DIR}/admin1_boundary_lines.json"))
s_geoms = [shape(f["geometry"]) for f in admin1_lines["features"]]
ax.add_geometries(s_geoms, crs=pc, facecolor="none", edgecolor="#9a978c",
                   linewidth=1.1, zorder=3)

states = json.load(open(f"{MAPS_DIR}/states_lakes_slim.json"))
lake_geoms = []
for f in states["features"]:
    props = f["properties"]
    if props.get("admin", "") == "United States of America" and "Lake" in props.get("featurecla", ""):
        lake_geoms.append(shape(f["geometry"]))
ax.add_geometries(lake_geoms, crs=pc, facecolor="white", edgecolor="#b9b6ac",
                   linewidth=0.7, zorder=3)

# ---------- counties (Wallowa tinted + outlined) ----------
counties = json.load(open(f"{MAPS_DIR}/counties_wa_or_id.geojson"))
co_geoms, wallowa_geoms = [], []
for f in counties["features"]:
    g = shape(f["geometry"])
    co_geoms.append(g)
    if f["properties"].get("id") == WALLOWA_FIPS:
        wallowa_geoms.append(g)
ax.add_geometries(wallowa_geoms, crs=pc, facecolor="#d6d3c8", edgecolor="none", zorder=2)
ax.add_geometries(co_geoms, crs=pc, facecolor="none", edgecolor="#c7c4b8",
                   linewidth=0.6, zorder=4)
ax.add_geometries(wallowa_geoms, crs=pc, facecolor="none", edgecolor="#2b2a26",
                   linewidth=1.6, zorder=4.5)

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
        if hwy in MOTORWAY:
            motorway_geoms.append(shape(f["geometry"]))
        elif hwy in TRUNK:
            trunk_geoms.append(shape(f["geometry"]))

ax.add_geometries(trunk_geoms, crs=pc, facecolor="none", edgecolor=TRUNK_COLOR,
                   linewidth=1.1, zorder=5)
ax.add_geometries(motorway_geoms, crs=pc, facecolor="none", edgecolor=MOTORWAY_COLOR,
                   linewidth=1.3, zorder=6)

# ---------- city labels ----------
cities = [
    ("Walla Walla", -118.3430, 46.0646, "right"),
    ("Clarkston", -117.0482, 46.4163, "right"),
    ("Pomeroy", -117.6022, 46.4746, "right"),
    ("Pendleton", -118.7879, 45.6721, "right"),
    ("Elgin", -117.9177, 45.5649, "left"),
    ("Wallowa", -117.5288, 45.5704, "right"),
    ("Enterprise", -117.2785, 45.4263, "left"),
    ("Joseph", -117.2296, 45.3543, "right"),
    ("Imnaha", -116.8338, 45.5604, "right"),
    ("La Grande", -118.0877, 45.3246, "left"),
    ("Union", -117.8655, 45.2085, "right"),
    ("Baker City", -117.8344, 44.7749, "right"),
    ("Halfway", -117.1135, 44.8771, "left"),
    ("Riggins", -116.3154, 45.4224, "right"),
    ("Grangeville", -116.1224, 45.9266, "left"),
    ("New Meadows", -116.2843, 44.9713, "right"),
]
for name, lon, lat, side in cities:
    if not (EXTENT[0] <= lon <= EXTENT[1] and EXTENT[2] <= lat <= EXTENT[3]):
        continue
    ax.plot(lon, lat, marker="o", markersize=4, color="black",
             transform=pc, zorder=8)
    ha = "left" if side == "right" else "right"
    dx = 0.05 if side == "right" else -0.05
    txt = ax.text(lon + dx, lat, name, transform=pc, ha=ha, va="center",
                   fontproperties=f_med, fontsize=11, color="black", zorder=9)
    txt.set_path_effects([pe.withStroke(linewidth=1.65, foreground="white", alpha=0.6)])

# ---------- earthquakes ----------
data = json.load(open("earthquakes.json"))
quakes = data["quakes"]
latest = next(q for q in quakes if q["id"] == data["highlight_id"])
past = [q for q in quakes if q["id"] != latest["id"]]

# Largest first so smaller circles stay visible on top where they overlap.
past.sort(key=lambda q: -q["mag"])
ax.scatter([q["lon"] for q in past], [q["lat"] for q in past], transform=pc,
           s=[marker_area(q["mag"]) for q in past], color=PAST_COLOR, alpha=0.55,
           edgecolor=PAST_EDGE, linewidths=0.8, zorder=10)
ax.scatter([latest["lon"]], [latest["lat"]], transform=pc,
           s=[marker_area(latest["mag"])], color=LATEST_COLOR, alpha=0.9,
           edgecolor=LATEST_EDGE, linewidths=1.2, zorder=11)

latest_pt = datetime.fromisoformat(latest["time"]).astimezone(PACIFIC)
callout = (f"M{latest['mag']:.1f}  ·  {latest_pt:%b %-d, %-I:%M %p %Z}\n"
           f"{latest['place']}")
ann = ax.annotate(callout, xy=(latest["lon"], latest["lat"]), xycoords=pc._as_mpl_transform(ax),
                  xytext=(-34, -52), textcoords="offset points", ha="right", va="top", multialignment="left",
                  fontproperties=f_med, fontsize=10.5, color=LATEST_EDGE, zorder=12,
                  bbox=dict(boxstyle="round,pad=0.4", facecolor="white",
                            edgecolor=LATEST_COLOR, linewidth=1.0, alpha=0.95),
                  arrowprops=dict(arrowstyle="-", color=LATEST_EDGE, linewidth=1.0,
                                  shrinkA=0, shrinkB=marker_diameter(latest["mag"]) / 2))

# ---------- frame ----------
ax.spines["geo"].set_edgecolor("black")
ax.spines["geo"].set_linewidth(1.6)

fig.canvas.draw()
map_pos = ax.get_position()
left_x = map_pos.x0
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

    logo_width_fig = 0.10 * (map_pos.x1 - map_pos.x0)
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
first_year = datetime.fromisoformat(quakes[0]["time"]).year
subtitle_y = top_y + 0.016
title_y = subtitle_y + 0.032
fig.text(left_x, title_y, f"Wallowa County Area: M{data['min_mag']:.0f}+ Earthquakes",
          fontproperties=f_bold, fontsize=22, color="#2b2a26")
subtitle = (f"{len(quakes)} earthquakes on record, {first_year}–{latest_pt.year} "
            f"— USGS ComCat")
fig.text(left_x, subtitle_y, subtitle, fontproperties=f_reg, fontsize=12, color="#5a584f")

# ---------- legend ----------
legend_handles = [
    Line2D([0], [0], marker="o", color="none", markerfacecolor=LATEST_COLOR,
           markeredgecolor=LATEST_EDGE, markersize=marker_diameter(latest["mag"]),
           alpha=0.9, label=f"Latest (M{latest['mag']:.1f}, {latest_pt:%b %-d})"),
]
for m in (3, 4, 5, 6):
    legend_handles.append(
        Line2D([0], [0], marker="o", color="none", markerfacecolor=PAST_COLOR,
               markeredgecolor=PAST_EDGE, markersize=marker_diameter(m), alpha=0.55,
               label=f"M{m}"))
leg = fig.legend(handles=legend_handles, loc="upper center", ncol=len(legend_handles),
                  bbox_to_anchor=(center_x, map_pos.y0 - 0.012),
                  bbox_transform=fig.transFigure,
                  frameon=False, prop=f_reg, fontsize=11,
                  handlelength=3.6, handletextpad=0.3, columnspacing=1.8, borderaxespad=0)

# ---------- attribution ----------
fig.text(center_x, 0.018,
          "USGS ComCat / US Census (counties) / OpenStreetMap (roads) — Ingalls Weather",
          fontproperties=f_reg, fontsize=9, color="#5a584f", ha="center")

plt.savefig("wallowa_earthquakes.png",
            facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
print("saved")

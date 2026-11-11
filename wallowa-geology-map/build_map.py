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
from matplotlib.patches import Patch
import cartopy.crs as ccrs
from shapely.geometry import shape

PACIFIC = ZoneInfo("America/Los_Angeles")

# ---------- fonts ----------
FONT_DIR = "/usr/share/fonts/truetype/google-fonts/"
f_bold = fm.FontProperties(fname=FONT_DIR + "Poppins-Bold.ttf")
f_reg = fm.FontProperties(fname=FONT_DIR + "Poppins-Regular.ttf")
f_med = fm.FontProperties(fname=FONT_DIR + "Poppins-Medium.ttf")

# ---------- geology classes (shared color table) ----------
# Colors and legend order come from ../maps/geology_classes.json, the table
# every geology map uses, so a class looks the same in every county and
# state. Only the wording is local: LABELS rewords classes for Wallowa
# County (named terranes/batholith, tighter local ages).
import sys
sys.path.insert(0, "../maps")
from geology_sgmc import display_class, load_classes  # noqa: E402

CLASSES = load_classes()
# Oregon's SGMC map also splits Grande Ronde / Wanapum / Saddle Mountains,
# but at this county's scale only Imnaha is worth its own legend entry;
# the other formations draw in the parent Columbia River Basalt color.
SHOW_DETAIL = {"crb_imnaha"}
CLASS_COLOR = {c["key"]: c["color"] for c in CLASSES}
WATER_COLOR = CLASS_COLOR["water"]
WATER_EDGE = next(c["edge"] for c in CLASSES if c["key"] == "water")

LABELS = {
    "surficial": ("Glacial, river & landslide deposits", "Ice Age to today"),
    "cz_volcanic": ("Younger volcanic vents & ash beds", "~16–2 million years ago"),
    "crb": ("Columbia River Basalt, Grande Ronde & younger", "~16.5–6 million years ago"),
    "crb_imnaha": ("Imnaha Basalt, oldest flood basalt", "~17 million years ago"),
    "plutonic": ("Wallowa batholith granite", "Jurassic–Cretaceous, ~160–120 Ma"),
    "mz_pz_sedimentary": ("Marine sediments incl. limestone", "Wallowa terrane, Permian–Jurassic"),
    "mz_pz_volcanic": ("Island-arc volcanic rocks", "Wallowa terrane, Triassic"),
}


def legend_label(c):
    title, age = LABELS.get(c["key"], (c["label"], c.get("age")))
    return f"{title}\n({age})" if age else title


# ---------- quake styling (same as ../wallowa-earthquakes-map) ----------
LATEST_COLOR = "#E0242B"
LATEST_EDGE = "#8E1116"


def marker_diameter(mag):
    return 7 + (mag - 3.0) * 10


# ---------- extent / projection (Wallowa County + a small margin) ----------
EXTENT = [-118.03, -116.40, 44.99, 46.09]
CENTER_LON, CENTER_LAT = -117.22, 45.54

proj = ccrs.NearsidePerspective(central_longitude=CENTER_LON,
                                 central_latitude=CENTER_LAT,
                                 satellite_height=4_000_000)
pc = ccrs.PlateCarree()

# Exactly 4:5 (Instagram's tallest feed shape): 10 x 12.5 in at 216 dpi =
# 2160 x 2700 px, a clean 2x of Instagram's 1080 x 1350. Saved without
# bbox_inches="tight" so the canvas stays exactly that size; everything
# below is laid out in figure coordinates to fit inside it.
FIG_W, FIG_H, DPI = 10, 12.5, 216
fig = plt.figure(figsize=(FIG_W, FIG_H), dpi=DPI)
fig.patch.set_facecolor("#f7f6f2")
ax = fig.add_axes([0.06, 0.28, 0.88, 0.635], projection=proj)
ax.set_anchor("N")  # map hugs the title; spare height goes to the legend
ax.set_facecolor("white")
ax.set_extent(EXTENT, crs=pc)

MAPS_DIR = "../maps"
WALLOWA_FIPS = "41063"

# ---------- land ----------
land = json.load(open(f"{MAPS_DIR}/land_slim.json"))
ax.add_geometries([shape(f["geometry"]) for f in land["features"]], crs=pc,
                   facecolor="#e3e1da", edgecolor="none", zorder=1)

# ---------- geology (Wallowa County only) ----------
geo = json.load(open(f"{MAPS_DIR}/wallowa_county_geology.geojson"))
by_class = {}
for f in geo["features"]:
    key = display_class(f["properties"]["class"], CLASSES, SHOW_DETAIL)
    by_class.setdefault(key, []).append(shape(f["geometry"]))
for key, geoms in by_class.items():
    color = CLASS_COLOR[key]
    ax.add_geometries(geoms, crs=pc, facecolor=color, edgecolor=color,
                       linewidth=0.2, zorder=2)

# ---------- states + counties ----------
admin1_lines = json.load(open(f"{MAPS_DIR}/admin1_boundary_lines.json"))
ax.add_geometries([shape(f["geometry"]) for f in admin1_lines["features"]], crs=pc,
                   facecolor="none", edgecolor="#9a978c", linewidth=1.1, zorder=3)

counties = json.load(open(f"{MAPS_DIR}/counties_wa_or_id.geojson"))
co_geoms, wallowa_geoms = [], []
for f in counties["features"]:
    g = shape(f["geometry"])
    co_geoms.append(g)
    if f["properties"].get("id") == WALLOWA_FIPS:
        wallowa_geoms.append(g)
ax.add_geometries(co_geoms, crs=pc, facecolor="none", edgecolor="#b9b6ac",
                   linewidth=0.7, zorder=3)

# ---------- roads ----------
MOTORWAY = {"motorway", "motorway_link"}
TRUNK = {"trunk", "trunk_link"}
MOTORWAY_COLOR = "#8FB8E0"  # pastel blue
TRUNK_COLOR = "#F2B880"     # pastel orange
SECONDARY_COLOR = "#D9B78A"  # same as ../wallowa-earthquakes-map

motorway_geoms, trunk_geoms = [], []
for region_file in ["washington_roads.geojson", "oregon_roads.geojson", "idaho_roads_north.geojson"]:
    d = json.load(open(f"{MAPS_DIR}/{region_file}"))
    for f in d["features"]:
        hwy = f["properties"].get("highway")
        if hwy in MOTORWAY:
            motorway_geoms.append(shape(f["geometry"]))
        elif hwy in TRUNK:
            trunk_geoms.append(shape(f["geometry"]))
sec = json.load(open(f"{MAPS_DIR}/wallowa_area_secondary_roads.geojson"))
sec_geoms = [shape(f["geometry"]) for f in sec["features"]]

# All highways sit above the geology shading (zorder 2) and below the
# faults (zorder 5). Each class gets a thin white glow -- a slightly wider
# white line drawn just underneath -- so the pale highway colors stay
# readable on the tan basalt and other unit colors.
GLOW_COLOR, GLOW_EXTRA, GLOW_ALPHA = "white", 1.4, 0.85
for geoms, color, lw, z in [
    (sec_geoms, SECONDARY_COLOR, 0.9, 4.0),
    (trunk_geoms, TRUNK_COLOR, 1.3, 4.2),
    (motorway_geoms, MOTORWAY_COLOR, 1.5, 4.4),
]:
    ax.add_geometries(geoms, crs=pc, facecolor="none", edgecolor=GLOW_COLOR,
                       linewidth=lw + GLOW_EXTRA, alpha=GLOW_ALPHA, zorder=z - 0.05)
    ax.add_geometries(geoms, crs=pc, facecolor="none", edgecolor=color,
                       linewidth=lw, zorder=z)

# ---------- faults ----------
faults = json.load(open(f"{MAPS_DIR}/wallowa_county_faults.geojson"))
solid, dashed = [], []
for f in faults["features"]:
    desc = f["properties"]["descript"].lower()
    (solid if "certain" in desc else dashed).append(shape(f["geometry"]))
ax.add_geometries(solid, crs=pc, facecolor="none", edgecolor="black",
                   linewidth=1.0, zorder=5)
ax.add_geometries(dashed, crs=pc, facecolor="none", edgecolor="black",
                   linewidth=0.9, linestyle=(0, (3, 2)), zorder=5)

# ---------- county outline + Wallowa Lake ----------
ax.add_geometries(wallowa_geoms, crs=pc, facecolor="none", edgecolor="#2b2a26",
                   linewidth=2.0, zorder=6)
wl = json.load(open(f"{MAPS_DIR}/wallowa_lake.geojson"))
ax.add_geometries([shape(f["geometry"]) for f in wl["features"]], crs=pc,
                   facecolor=WATER_COLOR, edgecolor=WATER_EDGE, linewidth=0.6, zorder=3.5)  # under highways + faults

# ---------- city labels ----------
cities = [
    ("Enterprise", -117.2785, 45.4263, "right"),
    ("Joseph", -117.2296, 45.3543, "right"),
    ("Lostine", -117.4277, 45.4904, "right"),
    ("Wallowa", -117.5288, 45.5704, "right"),
    ("Imnaha", -116.8338, 45.5604, "right"),
    ("Troy", -117.4510, 45.9465, "right"),
    ("Elgin", -117.9177, 45.5649, "right"),
    ("Halfway", -117.1135, 44.8771, "right"),
]
for name, lon, lat, side in cities:
    if not (EXTENT[0] <= lon <= EXTENT[1] and EXTENT[2] <= lat <= EXTENT[3]):
        continue
    ax.plot(lon, lat, marker="o", markersize=4.5, color="black",
             markeredgecolor="white", markeredgewidth=0.8, transform=pc, zorder=8)
    ha = "left" if side == "right" else "right"
    dx = 0.035 if side == "right" else -0.035
    txt = ax.text(lon + dx, lat, name, transform=pc, ha=ha, va="center",
                   fontproperties=f_med, fontsize=11, color="black", zorder=9)
    txt.set_path_effects([pe.withStroke(linewidth=2.4, foreground="white", alpha=0.85)])

# ---------- earthquake ----------
quake = json.load(open("earthquake.json"))
quake_pt = datetime.fromisoformat(quake["time"]).astimezone(PACIFIC)
ax.scatter([quake["lon"]], [quake["lat"]], transform=pc,
           s=[marker_diameter(quake["mag"]) ** 2], color=LATEST_COLOR, alpha=0.9,
           edgecolor=LATEST_EDGE, linewidths=1.2, zorder=11)

# ---------- frame ----------
ax.spines["geo"].set_edgecolor("black")
ax.spines["geo"].set_linewidth(1.6)
ax.spines["geo"].set_zorder(100)  # frame draws over every map layer

fig.canvas.draw()
map_pos = ax.get_position()
left_x = map_pos.x0
top_y = map_pos.y1
center_x = (map_pos.x0 + map_pos.x1) / 2

# ---------- logo (bottom-right, ~10% of map width, ~22px inset) ----------
LOGO_PATH = "../assets/ingalls_weather_logo.png"
if os.path.exists(LOGO_PATH):
    logo_img = plt.imread(LOGO_PATH)
    img_h, img_w = logo_img.shape[0], logo_img.shape[1]
    fig_w_in, fig_h_in = fig.get_size_inches()
    dpi = fig.get_dpi()
    inset_x = 22 / (fig_w_in * dpi)
    inset_y = 22 / (fig_h_in * dpi)
    logo_width_fig = 0.10 * (map_pos.x1 - map_pos.x0)
    logo_height_fig = logo_width_fig * fig_w_in * (img_h / img_w) / fig_h_in
    logo_ax = fig.add_axes([map_pos.x1 - inset_x - logo_width_fig, map_pos.y0 + inset_y,
                            logo_width_fig, logo_height_fig], zorder=20)
    logo_ax.imshow(logo_img)
    logo_ax.axis("off")
else:
    print(f"NOTE: no logo found at {LOGO_PATH} -- skipping logo placement.")

# ---------- title / subtitle ----------
subtitle_y = top_y + 0.014
title_y = subtitle_y + 0.028
fig.text(left_x, title_y, "Wallowa County Geology",
          fontproperties=f_bold, fontsize=22, color="#2b2a26")
fig.text(left_x, subtitle_y,
          f"Rock units, faults, and the M{quake['mag']:.1f} earthquake of {quake_pt:%b %-d}",
          fontproperties=f_reg, fontsize=12, color="#5a584f")

# ---------- legend ----------
# Only classes that actually appear on this map, in the shared table's
# order; water is shown as "Lake" in the second legend block instead.
unit_handles = [Patch(facecolor=c["color"], edgecolor="#8a877d", linewidth=0.5,
                      label=legend_label(c))
                for c in CLASSES if c["key"] in by_class and c["key"] != "water"]
other_handles = [
    Line2D([0], [0], marker="o", color="none", markerfacecolor=LATEST_COLOR,
           markeredgecolor=LATEST_EDGE, markersize=marker_diameter(quake["mag"]),
           alpha=0.9, label=f"M{quake['mag']:.1f} earthquake, {quake_pt:%b %-d}"),
    Line2D([0], [0], color="black", linewidth=1.2, label="Fault"),
    Line2D([0], [0], color="black", linewidth=1.1, linestyle=(0, (3, 2)),
           label="Fault, approximate or concealed"),
    Line2D([0], [0], color=MOTORWAY_COLOR, linewidth=2.2, label="Freeway"),
    Line2D([0], [0], color=TRUNK_COLOR, linewidth=2.2, label="Major highway"),
    Line2D([0], [0], color=SECONDARY_COLOR, linewidth=1.2, label="State highway"),
    Patch(facecolor=WATER_COLOR, edgecolor=WATER_EDGE, linewidth=0.6, label="Lake"),
]
leg_units = fig.legend(handles=unit_handles, loc="upper left", ncol=2,
                        bbox_to_anchor=(left_x, map_pos.y0 - 0.014),
                        bbox_transform=fig.transFigure, frameon=False, prop=f_reg,
                        fontsize=9.5, labelspacing=0.45, handlelength=2.0,
                        handleheight=1.6, columnspacing=1.5, borderaxespad=0)
fig.canvas.draw()
inv = fig.transFigure.inverted()
units_bottom = inv.transform(leg_units.get_window_extent())[0][1]
leg_other = fig.legend(handles=other_handles, loc="upper left", ncol=4,
                        bbox_to_anchor=(left_x, units_bottom - 0.012),
                        bbox_transform=fig.transFigure, frameon=False, prop=f_reg,
                        fontsize=9.5, labelspacing=0.6, handlelength=2.4,
                        columnspacing=1.5, borderaxespad=0)

# ---------- attribution (bottom of the canvas) ----------
fig.text(center_x, 0.012,
          "USGS State Geologic Map Compilation (Walker & MacLeod 1991) / USGS ComCat / "
          "US Census / OpenStreetMap — Ingalls Weather",
          fontproperties=f_reg, fontsize=8.5, color="#5a584f", ha="center")

fig.canvas.draw()
other_bottom = inv.transform(leg_other.get_window_extent())[0][1]
if other_bottom < 0.03:
    print(f"WARNING: legend runs into the attribution (bottom at {other_bottom:.3f})")

plt.savefig("wallowa_geology.png", facecolor=fig.get_facecolor(), dpi=DPI)
print("saved")

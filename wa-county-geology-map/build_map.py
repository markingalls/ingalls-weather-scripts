"""
Renders a 4:5 (2160 x 2700 px, Instagram-ready) geologic map of one
Washington county from the files fetch_geology.py wrote:

    python3 build_map.py --county Adams      ->  adams_geology.png

Colors come from the shared table in ../maps/geology_classes.json, so a
rock class looks the same here as on any other county's map (and on
../wallowa-geology-map). DNR's 1:100,000 map splits the Columbia River
Basalt into formations and separates loess from Ice Age flood deposits, so
by default every detail class is shown; --no-detail draws them in their
parent class's color instead.
"""
import argparse
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import cartopy.crs as ccrs
import numpy as np
from shapely.geometry import shape

MAPS_DIR = "../maps"
sys.path.insert(0, MAPS_DIR)
from geology_sgmc import display_class, load_classes  # noqa: E402
from fetch_geology import county_shape, slug  # noqa: E402

# ---------- fonts ----------
FONT_DIR = "/usr/share/fonts/truetype/google-fonts/"
f_bold = fm.FontProperties(fname=FONT_DIR + "Poppins-Bold.ttf")
f_reg = fm.FontProperties(fname=FONT_DIR + "Poppins-Regular.ttf")
f_med = fm.FontProperties(fname=FONT_DIR + "Poppins-Medium.ttf")

# ---------- shared styling (same as ../wallowa-geology-map) ----------
MOTORWAY_COLOR = "#8FB8E0"
TRUNK_COLOR = "#F2B880"
SECONDARY_COLOR = "#D9B78A"
GLOW_EXTRA, GLOW_ALPHA = 1.4, 0.85
MOTORWAY = {"motorway", "motorway_link"}
TRUNK = {"trunk", "trunk_link"}

ap = argparse.ArgumentParser(description=__doc__,
                             formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--county", required=True)
ap.add_argument("--no-detail", action="store_true",
                help="draw detail classes (CRB formations, loess, flood deposits) "
                     "in their parent class's color")
args = ap.parse_args()
name = slug(args.county)
title_name = args.county.strip().title()

CLASSES = load_classes()
BY_KEY = {c["key"]: c for c in CLASSES}
SHOW_DETAIL = set() if args.no_detail else {c["key"] for c in CLASSES if c.get("parent")}

geo = json.load(open(f"data/{name}_geology.geojson"))
faults = json.load(open(f"data/{name}_faults.geojson"))
roads2 = json.load(open(f"data/{name}_roads.geojson"))
places = json.load(open(f"data/{name}_places.geojson"))
county = county_shape(args.county)

by_class = {}
for f in geo["features"]:
    k = display_class(f["properties"]["class"], CLASSES, SHOW_DETAIL)
    by_class.setdefault(k, []).append(shape(f["geometry"]))

# ---------- figure: exactly 4:5 ----------
FIG_W, FIG_H, DPI = 10, 12.5, 216
fig = plt.figure(figsize=(FIG_W, FIG_H), dpi=DPI)
fig.patch.set_facecolor("#f7f6f2")
LEFT, WIDTH = 0.06, 0.88
MAP_TOP = 0.915

# ---------- legends first (bottom-up), so the map can take what's left ----------
unit_handles = [Patch(facecolor=c["color"], edgecolor="#8a877d", linewidth=0.5,
                      label=f"{c['label']}\n({c['age']})" if c.get("age") else c["label"])
                for c in CLASSES if c["key"] in by_class and c["key"] != "water"]
has_solid = any(not f["properties"]["concealed"] for f in faults["features"])
has_dashed = any(f["properties"]["concealed"] for f in faults["features"])
other_handles = []
if has_solid:
    other_handles.append(Line2D([0], [0], color="black", linewidth=1.2, label="Fault"))
if has_dashed:
    other_handles.append(Line2D([0], [0], color="black", linewidth=1.1, linestyle=(0, (3, 2)),
                                label="Fault, concealed"))
other_handles += [
    Line2D([0], [0], color=MOTORWAY_COLOR, linewidth=2.2, label="Freeway"),
    Line2D([0], [0], color=TRUNK_COLOR, linewidth=2.2, label="Major highway"),
    Line2D([0], [0], color=SECONDARY_COLOR, linewidth=1.2, label="State highway"),
]
if "water" in by_class:
    other_handles.append(Patch(facecolor=BY_KEY["water"]["color"], edgecolor=BY_KEY["water"]["edge"],
                               linewidth=0.6, label="Lake / river"))

inv = fig.transFigure.inverted()
leg_other = fig.legend(handles=other_handles, loc="lower left", ncol=4,
                       bbox_to_anchor=(LEFT, 0.04), bbox_transform=fig.transFigure,
                       frameon=False, prop=f_reg, fontsize=9.5, labelspacing=0.6,
                       handlelength=2.4, columnspacing=1.5, borderaxespad=0)
fig.canvas.draw()
other_top = inv.transform(leg_other.get_window_extent())[1][1]
leg_units = fig.legend(handles=unit_handles, loc="lower left", ncol=2,
                       bbox_to_anchor=(LEFT, other_top + 0.015), bbox_transform=fig.transFigure,
                       frameon=False, prop=f_reg, fontsize=9.5, labelspacing=0.45,
                       handlelength=2.0, handleheight=1.6, columnspacing=1.5, borderaxespad=0)
fig.canvas.draw()
legend_top = inv.transform(leg_units.get_window_extent())[1][1]

# ---------- map box and extent: county + margin, stretched to fill the box ----------
map_bottom = legend_top + 0.022
box_w_in = WIDTH * FIG_W
box_h_in = (MAP_TOP - map_bottom) * FIG_H
x0, y0, x1, y1 = county.bounds
cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
coslat = np.cos(np.radians(cy))
half_w, half_h = (x1 - x0) / 2 * 1.06, (y1 - y0) / 2 * 1.06
target = box_w_in / box_h_in  # width/height of the box, in ground terms
if (half_w * coslat) / half_h > target:
    half_h = half_w * coslat / target       # wide county: add context N/S
else:
    half_w = half_h * target / coslat       # tall county: add context E/W
EXTENT = [cx - half_w, cx + half_w, cy - half_h, cy + half_h]

proj = ccrs.NearsidePerspective(central_longitude=cx, central_latitude=cy,
                                satellite_height=4_000_000)
pc = ccrs.PlateCarree()
ax = fig.add_axes([LEFT, map_bottom, WIDTH, MAP_TOP - map_bottom], projection=proj)
ax.set_anchor("N")
ax.set_facecolor("white")
ax.set_extent(EXTENT, crs=pc)

# ---------- land ----------
land = json.load(open(f"{MAPS_DIR}/land_slim.json"))
ax.add_geometries([shape(f["geometry"]) for f in land["features"]], crs=pc,
                  facecolor="#e3e1da", edgecolor="none", zorder=1)

# ---------- geology (county only) ----------
for key, geoms in by_class.items():
    if key == "water":
        continue  # drawn later, above other lines' base but under highways/faults
    ax.add_geometries(geoms, crs=pc, facecolor=BY_KEY[key]["color"],
                      edgecolor=BY_KEY[key]["color"], linewidth=0.2, zorder=2)

# ---------- states + counties ----------
admin1_lines = json.load(open(f"{MAPS_DIR}/admin1_boundary_lines.json"))
ax.add_geometries([shape(f["geometry"]) for f in admin1_lines["features"]], crs=pc,
                  facecolor="none", edgecolor="#9a978c", linewidth=1.1, zorder=3)
counties = json.load(open(f"{MAPS_DIR}/counties_wa_or_id.geojson"))
ax.add_geometries([shape(f["geometry"]) for f in counties["features"]], crs=pc,
                  facecolor="none", edgecolor="#b9b6ac", linewidth=0.7, zorder=3)

if "water" in by_class:
    ax.add_geometries(by_class["water"], crs=pc, facecolor=BY_KEY["water"]["color"],
                      edgecolor=BY_KEY["water"]["edge"], linewidth=0.5, zorder=3.5)

# ---------- highways: above geology, below faults, thin white glow ----------
motorway_geoms, trunk_geoms = [], []
d = json.load(open(f"{MAPS_DIR}/washington_roads.geojson"))
for f in d["features"]:
    hwy = f["properties"].get("highway")
    if hwy in MOTORWAY:
        motorway_geoms.append(shape(f["geometry"]))
    elif hwy in TRUNK:
        trunk_geoms.append(shape(f["geometry"]))
sec_geoms = [shape(f["geometry"]) for f in roads2["features"]]
for geoms, color, lw, z in [(sec_geoms, SECONDARY_COLOR, 0.9, 4.0),
                            (trunk_geoms, TRUNK_COLOR, 1.3, 4.2),
                            (motorway_geoms, MOTORWAY_COLOR, 1.5, 4.4)]:
    ax.add_geometries(geoms, crs=pc, facecolor="none", edgecolor="white",
                      linewidth=lw + GLOW_EXTRA, alpha=GLOW_ALPHA, zorder=z - 0.05)
    ax.add_geometries(geoms, crs=pc, facecolor="none", edgecolor=color, linewidth=lw, zorder=z)

# ---------- faults ----------
solid = [shape(f["geometry"]) for f in faults["features"] if not f["properties"]["concealed"]]
dashed = [shape(f["geometry"]) for f in faults["features"] if f["properties"]["concealed"]]
ax.add_geometries(solid, crs=pc, facecolor="none", edgecolor="black", linewidth=1.0, zorder=5)
ax.add_geometries(dashed, crs=pc, facecolor="none", edgecolor="black", linewidth=0.9,
                  linestyle=(0, (3, 2)), zorder=5)

# ---------- county outline ----------
ax.add_geometries([county], crs=pc, facecolor="none", edgecolor="#2b2a26",
                  linewidth=2.0, zorder=6)

# ---------- city labels (incorporated places, label to the right) ----------
for f in places["features"]:
    lon, lat = f["geometry"]["coordinates"]
    ax.plot(lon, lat, marker="o", markersize=4.5, color="black", markeredgecolor="white",
            markeredgewidth=0.8, transform=pc, zorder=8)
    txt = ax.text(lon + 0.012 * (EXTENT[1] - EXTENT[0]), lat, f["properties"]["name"],
                  transform=pc, ha="left", va="center", fontproperties=f_med,
                  fontsize=11, color="black", zorder=9)
    txt.set_path_effects([pe.withStroke(linewidth=2.4, foreground="white", alpha=0.85)])

# ---------- frame (above everything) ----------
ax.spines["geo"].set_edgecolor("black")
ax.spines["geo"].set_linewidth(1.6)
ax.spines["geo"].set_zorder(100)

fig.canvas.draw()
map_pos = ax.get_position()

# ---------- logo ----------
LOGO_PATH = "../assets/ingalls_weather_logo.png"
if os.path.exists(LOGO_PATH):
    logo_img = plt.imread(LOGO_PATH)
    img_h, img_w = logo_img.shape[:2]
    inset_x, inset_y = 22 / (FIG_W * DPI), 22 / (FIG_H * DPI)
    logo_w = 0.10 * (map_pos.x1 - map_pos.x0)
    logo_h = logo_w * FIG_W * (img_h / img_w) / FIG_H
    logo_ax = fig.add_axes([map_pos.x1 - inset_x - logo_w, map_pos.y0 + inset_y,
                            logo_w, logo_h], zorder=20)
    logo_ax.imshow(logo_img)
    logo_ax.axis("off")

# ---------- title / subtitle ----------
subtitle_y = map_pos.y1 + 0.014
fig.text(map_pos.x0, subtitle_y + 0.028, f"{title_name} County Geology",
         fontproperties=f_bold, fontsize=22, color="#2b2a26")
fig.text(map_pos.x0, subtitle_y, "Rock units and faults",
         fontproperties=f_reg, fontsize=12, color="#5a584f")

# ---------- attribution ----------
fig.text((map_pos.x0 + map_pos.x1) / 2, 0.012,
         "Washington DNR 1:100,000 Geologic Map / US Census / OpenStreetMap — Ingalls Weather",
         fontproperties=f_reg, fontsize=8.5, color="#5a584f", ha="center")

out = f"{name}_geology.png"
plt.savefig(out, facecolor=fig.get_facecolor(), dpi=DPI)
print(f"saved {out}")

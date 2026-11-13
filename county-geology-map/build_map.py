"""
Renders a 4:5 (2160 x 2700 px, Instagram-ready) geologic map of one
Washington or Oregon county from the files fetch_geology.py wrote:

    python3 build_map.py --state WA --county Adams   ->  wa_adams_geology.png
    python3 build_map.py --state OR --county Baker   ->  or_baker_geology.png

Colors come from the shared table in ../maps/geology_classes.json, so a
rock class looks the same here as on any other county's map (and on
../wallowa-geology-map). Both WA DNR's and DOGAMI's maps split the Columbia
River Basalt into formations and separate loess from Ice Age flood
deposits, so by default every detail class is shown; --no-detail draws them in their
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
from matplotlib.legend_handler import HandlerBase
from matplotlib.patches import FancyArrowPatch, Patch
import cartopy.crs as ccrs
import geopandas as gpd
import numpy as np
from shapely.geometry import LineString, shape
from shapely.ops import unary_union

MAPS_DIR = "../maps"
sys.path.insert(0, MAPS_DIR)
from geology_sgmc import display_class, load_classes  # noqa: E402
from geology_labels import county_labels  # noqa: E402
from fetch_geology import STATE_INFO, cached, clean_polygon, data_name  # noqa: E402

CB_COUNTIES = "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_county_500k.zip"

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

ap = argparse.ArgumentParser(description=__doc__,
                             formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--state", required=True, type=str.upper, choices=sorted(STATE_INFO))
ap.add_argument("--county", required=True)
ap.add_argument("--also-label", action="append", default=[], metavar="CITY",
                help='label an incorporated city outside the county that falls on the map, '
                     'e.g. --also-label "Moses Lake" (repeatable)')
ap.add_argument("--out", help="output PNG path (default <state>_<county>_geology.png)")
ap.add_argument("--logo-corner", choices=["bottom-right", "top-right", "top-left", "bottom-left"],
                default="bottom-right",
                help="where the logo sits inside the map frame (move it off the county)")
ap.add_argument("--no-detail", action="store_true",
                help="draw detail classes (CRB formations, loess, flood deposits) "
                     "in their parent class's color")
args = ap.parse_args()
name = data_name(args.state, args.county)
state_name = STATE_INFO[args.state][1]
title_name = args.county.strip().title()

CLASSES = load_classes()
BY_KEY = {c["key"]: c for c in CLASSES}
SHOW_DETAIL = set() if args.no_detail else {c["key"] for c in CLASSES if c.get("parent")}

geo = json.load(open(f"data/{name}_geology.geojson"))
faults = json.load(open(f"data/{name}_faults.geojson"))
folds = json.load(open(f"data/{name}_folds.geojson"))
roads2 = json.load(open(f"data/{name}_roads.geojson"))
water_ctx = json.load(open(f"data/{name}_water.geojson"))
places = json.load(open(f"data/{name}_places.geojson"))
_cf = {f["properties"].get("role", "land"): clean_polygon(shape(f["geometry"]))
       for f in json.load(open(f"data/{name}_county.geojson"))["features"]}
county = _cf.get("outline", _cf["land"])  # shoreline-following outline (see fetch_geology)
near_counties = json.load(open(f"data/{name}_counties.geojson"))["features"]

by_class = {}
for f in geo["features"]:
    k = display_class(f["properties"]["class"], CLASSES, SHOW_DETAIL)
    by_class.setdefault(k, []).append(clean_polygon(shape(f["geometry"])))  # see fetch_geology

# ---------- figure: exactly 4:5 ----------
FIG_W, FIG_H, DPI = 10, 12.5, 216
fig = plt.figure(figsize=(FIG_W, FIG_H), dpi=DPI)
fig.patch.set_facecolor("#f7f6f2")
LEFT, WIDTH = 0.06, 0.88
MAP_TOP = 0.935

# ---------- legends first (bottom-up), so the map can take what's left ----------
# Legend wording is local (names + age range from this county's data, see
# ../maps/geology_labels.py); colors stay the shared ones.
LOCAL = county_labels(geo["features"], args.state, args.county.strip().title(), CLASSES)


def unit_label(c):
    if c["key"] in LOCAL:
        return LOCAL[c["key"]]
    return f"{c['label']}\n({c['age']})" if c.get("age") else c["label"]


unit_handles = [Patch(facecolor=c["color"], edgecolor="#8a877d", linewidth=0.5,
                      label=unit_label(c))
                for c in CLASSES if c["key"] in by_class and c["key"] != "water"]
has_solid = any(not f["properties"]["concealed"] for f in faults["features"])
has_dashed = any(f["properties"]["concealed"] for f in faults["features"])
other_handles = []
if has_solid:
    other_handles.append(Line2D([0], [0], color="black", linewidth=1.2, label="Fault"))
if has_dashed:
    other_handles.append(Line2D([0], [0], color="black", linewidth=1.1, linestyle=(0, (3, 2)),
                                label="Fault, concealed"))
FOLD_COLOR = "#6B3FA0"  # purple: reads on every unit color, distinct from black faults


class FoldHandle:
    def __init__(self, kind):
        self.kind = kind


class FoldHandler(HandlerBase):
    """Legend swatch: a horizontal fold axis with the map's perpendicular
    arrow pair at its center (out = anticline, in = syncline)."""
    def create_artists(self, legend, orig, x0, y0, width, height, fontsize, trans):
        cy, cx, arm = y0 + height / 2, x0 + width / 2, height * 0.95
        arts = [Line2D([x0, x0 + width], [cy, cy], color=FOLD_COLOR, linewidth=1.2,
                       transform=trans)]
        for side in (1, -1):
            tip, base = (cy + side * arm, cy) if orig.kind == "anticline" else (cy + side * 0.15 * arm, cy + side * arm)
            arts.append(FancyArrowPatch((cx, base), (cx, tip), arrowstyle="-|>,head_length=3,head_width=2",
                                        color=FOLD_COLOR, linewidth=1.0, shrinkA=0, shrinkB=0,
                                        transform=trans))
        return arts


fold_types = {f["properties"]["type"] for f in folds["features"]}
fold_handles, fold_labels = [], []
for kind in ("anticline", "syncline"):
    if kind in fold_types:
        other_handles.append(FoldHandle(kind))
other_handles += [
    Line2D([0], [0], color=MOTORWAY_COLOR, linewidth=2.2, label="Freeway"),
    Line2D([0], [0], color=TRUNK_COLOR, linewidth=2.2, label="Major highway"),
    Line2D([0], [0], color=SECONDARY_COLOR, linewidth=1.2, label="State highway"),
]
if "water" in by_class or water_ctx["features"]:
    other_handles.append(Patch(facecolor=BY_KEY["water"]["color"], edgecolor=BY_KEY["water"]["edge"],
                               linewidth=0.6, label="Water"))

inv = fig.transFigure.inverted()
other_labels = [h.kind.title() if isinstance(h, FoldHandle) else h.get_label()
                for h in other_handles]

# Legend layouts, roomiest first: (font size, unit columns, key columns).
# Both blocks are centered under the map. The first layout that leaves the
# map at least MIN_MAP_FRAC of the canvas height and fits the width wins;
# counties with many rock classes get a smaller, wider legend.
LEGEND_LAYOUTS = [(9.5, 2, 4), (9, 2, 4), (8.5, 2, 5), (8.5, 3, 5), (8, 3, 5),
                  (7.5, 3, 5), (7, 3, 6), (6.5, 3, 6)]
MIN_MAP_FRAC = 0.56
MAX_LEGEND_W = 0.96


def place_legends(font, unit_cols, key_cols):
    # matplotlib ignores `fontsize` when `prop` is given, so size a copy.
    prop = f_reg.copy()
    prop.set_size(font)
    leg_o = fig.legend(other_handles, other_labels, loc="lower center", ncol=key_cols,
                       handler_map={FoldHandle: FoldHandler()},
                       bbox_to_anchor=(0.5, 0.04), bbox_transform=fig.transFigure,
                       frameon=False, prop=prop, labelspacing=0.9,
                       handlelength=2.4, columnspacing=1.5, borderaxespad=0)
    fig.canvas.draw()
    o_box = inv.transform(leg_o.get_window_extent())
    leg_u = fig.legend(handles=unit_handles, loc="lower center", ncol=unit_cols,
                       bbox_to_anchor=(0.5, o_box[1][1] + 0.015), bbox_transform=fig.transFigure,
                       frameon=False, prop=prop, labelspacing=0.45,
                       handlelength=2.0, handleheight=1.6, columnspacing=1.5, borderaxespad=0)
    fig.canvas.draw()
    u_box = inv.transform(leg_u.get_window_extent())
    width = max(o_box[1][0] - o_box[0][0], u_box[1][0] - u_box[0][0])
    return leg_o, leg_u, u_box[1][1], width


for font, unit_cols, key_cols in LEGEND_LAYOUTS:
    leg_other, leg_units, legend_top, legend_w = place_legends(font, unit_cols, key_cols)
    if MAP_TOP - (legend_top + 0.022) >= MIN_MAP_FRAC and legend_w <= MAX_LEGEND_W:
        break
    leg_other.remove()
    leg_units.remove()
else:
    leg_other, leg_units, legend_top, legend_w = place_legends(font, unit_cols, key_cols)

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
# Ocean/Sound show through as water: the map background is the water
# color; land is Natural Earth (for Canada) plus the full-res TIGER
# counties around the county, with TIGER water (incl. the ocean within
# 3 nmi, Puget Sound, big rivers) drawn back on top.
ax.set_facecolor(BY_KEY["water"]["color"])
ax.set_extent(EXTENT, crs=pc)
LAND_COLOR = "#e3e1da"

# ---------- land ----------
land = json.load(open(f"{MAPS_DIR}/land_slim.json"))
ax.add_geometries([shape(f["geometry"]) for f in land["features"]], crs=pc,
                  facecolor=LAND_COLOR, edgecolor="none", zorder=1)
# Neighboring land from Census's shoreline-clipped cartographic counties
# (1:500k): the legal TIGER counties run 3 nmi out to sea, and where the
# TIGER ocean polygon doesn't cover all of that band it showed as a gray
# strip offshore (Jefferson, Grays Harbor, Pacific...).
_cb = gpd.read_file(cached(CB_COUNTIES),
                    bbox=(EXTENT[0] - 0.2, EXTENT[2] - 0.2, EXTENT[1] + 0.2, EXTENT[3] + 0.2))
ax.add_geometries([clean_polygon(g) for g in _cb.to_crs(4326).geometry], crs=pc,
                  facecolor=LAND_COLOR, edgecolor="none", zorder=1.05)

# ---------- geology (county only) ----------
for key, geoms in by_class.items():
    if key == "water":
        continue  # drawn later, above other lines' base but under highways/faults
    ax.add_geometries(geoms, crs=pc, facecolor=BY_KEY[key]["color"],
                      edgecolor=BY_KEY[key]["color"], linewidth=0.2, zorder=2)

# ---------- states + counties ----------
# Full-resolution TIGER boundaries (fetch_geology.py), so the county
# outline and state lines follow the Snake/Columbia rather than cutting
# corners. State lines = each state's dissolved counties' outline.
# Lines are clipped to (shoreline) land, so the legal 3-nmi offshore and
# mid-river boundaries don't draw stray lines across open water.
_land_mask = unary_union([clean_polygon(g) for g in _cb.to_crs(4326).geometry]).buffer(0.003)
_county_lines = [shape(f["geometry"]).boundary.intersection(_land_mask) for f in near_counties]
ax.add_geometries([g for g in _county_lines if not g.is_empty], crs=pc,
                  facecolor="none", edgecolor="#b9b6ac", linewidth=0.7, zorder=3)
by_state = {}
for f in near_counties:
    by_state.setdefault(f["properties"]["state"], []).append(shape(f["geometry"]).buffer(0))
_state_lines = [unary_union(g).boundary.intersection(_land_mask) for g in by_state.values()]
ax.add_geometries([g for g in _state_lines if not g.is_empty], crs=pc,
                  facecolor="none", edgecolor="#9a978c", linewidth=1.1, zorder=3.05)

# Big lakes/reservoirs/rivers around the county (TIGER) for context --
# e.g. Moses Lake and Potholes Reservoir next to Adams County.
# Big water (ocean, Sound, estuaries > 20 km^2) gets no edge line: its
# outer edge is the 3-nmi county limit, which would draw a stray line
# offshore. Smaller lakes/rivers keep a thin edge so they read.
_water = [clean_polygon(shape(f["geometry"])) for f in water_ctx["features"]]
_big = [g for g in _water if g.area > 0.002]
ax.add_geometries(_big, crs=pc, facecolor=BY_KEY["water"]["color"], edgecolor="none", zorder=3.4)
ax.add_geometries([g for g in _water if g.area <= 0.002], crs=pc,
                  facecolor=BY_KEY["water"]["color"], edgecolor=BY_KEY["water"]["edge"],
                  linewidth=0.5, zorder=3.4)
if "water" in by_class:
    ax.add_geometries(by_class["water"], crs=pc, facecolor=BY_KEY["water"]["color"],
                      edgecolor=BY_KEY["water"]["edge"], linewidth=0.5, zorder=3.5)

# ---------- highways: above geology, below faults, thin white glow ----------
# Classes were set by fetch_geology.classify_roads: TIGER primary roads
# (any limited-access freeway, Interstate or not) refined by the repo's
# OSM extract where it has data; US routes = major; the rest = state.
motorway_geoms, trunk_geoms, sec_geoms = [], [], []
for f in roads2["features"]:
    cls = f["properties"]["class"]
    (motorway_geoms if cls == "freeway" else trunk_geoms if cls == "major" else sec_geoms).append(
        shape(f["geometry"]))
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

# ---------- folds: purple axis line (dashed where concealed/approximate),
# with the standard symbol at its midpoint -- arrows pointing away from
# the axis for an anticline, toward it for a syncline ----------
def fold_symbol(line, kind):
    xy = proj.transform_points(pc, *np.asarray(line.coords).T)[:, :2]
    seg = np.diff(xy, axis=0)
    seglen = np.hypot(*seg.T)
    if seglen.sum() == 0:
        return
    i = int(np.searchsorted(np.cumsum(seglen), seglen.sum() / 2))
    t = seg[i] / seglen[i]
    mid = xy[i] + t * (seglen.sum() / 2 - (np.cumsum(seglen)[i] - seglen[i]))
    normal = np.array([-t[1], t[0]])
    arm = 0.011 * (ax.get_xlim()[1] - ax.get_xlim()[0])
    for side in (1, -1):
        tip, base = mid + side * normal * arm, mid
        if kind == "syncline":
            tip, base = base + side * normal * 0.15 * arm, mid + side * normal * arm
        ax.annotate("", xy=tip, xytext=base, xycoords="data",
                    arrowprops=dict(arrowstyle="-|>,head_length=0.35,head_width=0.2",
                                    color=FOLD_COLOR, linewidth=1.0, shrinkA=0, shrinkB=0),
                    zorder=5.6)


for f in folds["features"]:
    g = shape(f["geometry"])
    ax.add_geometries([g], crs=pc, facecolor="none", edgecolor=FOLD_COLOR, linewidth=1.0,
                      linestyle=(0, (3, 2)) if f["properties"]["concealed"] else "solid",
                      zorder=5.5)
    for part in getattr(g, "geoms", [g]):
        if part.length > 0.03:  # skip slivers left by clipping at the county line
            fold_symbol(part, f["properties"]["type"])

# ---------- county outline ----------
# The county's land (shoreline, not the 3-nmi/mid-river legal line);
# exterior rings only, so lakes cut out of it don't get a black outline.
# Fragments under 0.2% of the county (islets in reservoirs) are skipped --
# outlined, they read as stray city dots; real islands are far bigger.
parts = list(getattr(county, "geoms", [county]))
outline = [LineString(p.exterior.coords) for p in parts if p.area > 0.002 * county.area]
ax.add_geometries(outline, crs=pc, facecolor="none", edgecolor="#2b2a26",
                  linewidth=2.0, zorder=6)

# ---------- city labels ----------
# Incorporated places in the county, biggest (by land area) first, then a
# few notable nearby cities outside it (>= NEARBY_MIN_KM2) for context, plus
# any --also-label. Each label tries right/left/above/below its dot and is
# dropped if it would overlap another label or dot, the logo corner, or the
# frame -- so dense counties stay readable.
NEARBY_MIN_KM2, MAX_IN_COUNTY, MAX_NEARBY = 15, 18, 4
also = {n.lower() for n in args.also_label}
missing = also - {f["properties"]["name"].lower() for f in places["features"]}
if missing:
    raise SystemExit(f"--also-label: no incorporated place on this map named {sorted(missing)}")


def in_view(f):
    lon, lat = f["geometry"]["coordinates"]
    return EXTENT[0] < lon < EXTENT[1] and EXTENT[2] < lat < EXTENT[3]


by_size = sorted((f for f in places["features"] if in_view(f)),
                 key=lambda f: -f["properties"].get("aland_km2", 0))
forced = [f for f in by_size if f["properties"]["name"].lower() in also]
inside = [f for f in by_size if f["properties"]["in_county"] and f not in forced][:MAX_IN_COUNTY]
nearby = [f for f in by_size if not f["properties"]["in_county"] and f not in forced
          and f["properties"].get("aland_km2", 0) >= NEARBY_MIN_KM2][:MAX_NEARBY]

fig.canvas.draw()
renderer = fig.canvas.get_renderer()
ax_box = ax.get_window_extent(renderer)
_zw = 0.16 * ax_box.width
_lx0 = ax_box.x1 - _zw if args.logo_corner.endswith("right") else ax_box.x0
_ly0 = ax_box.y1 - _zw if args.logo_corner.startswith("top") else ax_box.y0
logo_zone = (_lx0, _ly0, _lx0 + _zw, _ly0 + _zw)
taken = [logo_zone]
dx_deg = 0.012 * (EXTENT[1] - EXTENT[0])
dy_deg = 0.022 * (EXTENT[3] - EXTENT[2])


def overlaps(b1, b2, pad=3):
    return not (b1[2] + pad < b2[0] or b2[2] + pad < b1[0] or b1[3] + pad < b2[1] or b2[3] + pad < b1[1])


for f in forced + inside + nearby:
    lon, lat = f["geometry"]["coordinates"]
    dot_xy = ax.transData.transform(proj.transform_point(lon, lat, pc))
    dot = (dot_xy[0] - 4, dot_xy[1] - 4, dot_xy[0] + 4, dot_xy[1] + 4)
    if any(overlaps(dot, t, 0) for t in taken):
        continue
    for ddx, ddy, ha, va in [(dx_deg, 0, "left", "center"), (-dx_deg, 0, "right", "center"),
                             (0, dy_deg, "center", "bottom"), (0, -dy_deg, "center", "top")]:
        txt = ax.text(lon + ddx, lat + ddy, f["properties"]["name"], transform=pc, ha=ha, va=va,
                      fontproperties=f_med, fontsize=11, color="black", zorder=9)
        bb = txt.get_window_extent(renderer)
        box = (bb.x0, bb.y0, bb.x1, bb.y1)
        inside_frame = (box[0] > ax_box.x0 + 4 and box[2] < ax_box.x1 - 4 and
                        box[1] > ax_box.y0 + 4 and box[3] < ax_box.y1 - 4)
        if inside_frame and not any(overlaps(box, t) for t in taken) and not overlaps(box, dot):
            txt.set_path_effects([pe.withStroke(linewidth=2.4, foreground="white", alpha=0.85)])
            ax.plot(lon, lat, marker="o", markersize=4.5, color="black", markeredgecolor="white",
                    markeredgewidth=0.8, transform=pc, zorder=8)
            taken += [box, dot]
            break
        txt.remove()

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
    logo_x = (map_pos.x1 - inset_x - logo_w if args.logo_corner.endswith("right")
              else map_pos.x0 + inset_x)
    logo_y = (map_pos.y1 - inset_y - logo_h if args.logo_corner.startswith("top")
              else map_pos.y0 + inset_y)
    logo_ax = fig.add_axes([logo_x, logo_y, logo_w, logo_h], zorder=20)
    logo_ax.imshow(logo_img)
    logo_ax.axis("off")

# ---------- title (single line) ----------
fig.text(map_pos.x0, map_pos.y1 + 0.018, f"{title_name} Co., {state_name} Geologic Map",
         fontproperties=f_bold, fontsize=22, color="#2b2a26")

# ---------- attribution ----------
sources = {f["properties"].get("source", "100k") for f in geo["features"]}
if "ogdc7" in sources:
    dnr_credit = "DOGAMI Oregon Geologic Data Compilation (OGDC-7)"
else:
    dnr_credit = {frozenset({"100k"}): "Washington DNR 1:100,000 Geologic Map",
                  frozenset({"250k"}): "Washington DNR 1:250,000 Geologic Map"}.get(
        frozenset(sources), "Washington DNR 1:100,000 & 1:250,000 Geologic Maps")
fig.text((map_pos.x0 + map_pos.x1) / 2, 0.012,
         f"{dnr_credit} / US Census — Ingalls Weather",
         fontproperties=f_reg, fontsize=8.5, color="#5a584f", ha="center")

out = args.out or f"{name}_geology.png"
os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
plt.savefig(out, facecolor=fig.get_facecolor(), dpi=DPI)
print(f"saved {out}")

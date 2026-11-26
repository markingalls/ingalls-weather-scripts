import argparse
import json
import os
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
import cartopy.crs as ccrs
from shapely.geometry import shape, Point
from shapely.ops import unary_union, nearest_points

# ---------- fonts ----------
FONT_DIR = "/usr/share/fonts/truetype/google-fonts/"
f_bold = fm.FontProperties(fname=FONT_DIR + "Poppins-Bold.ttf")
f_reg = fm.FontProperties(fname=FONT_DIR + "Poppins-Regular.ttf")
f_med = fm.FontProperties(fname=FONT_DIR + "Poppins-Medium.ttf")

PT = ZoneInfo("America/Los_Angeles")

# ---------- warning colors ----------
# Official NWS Tornado Warning red for the highlighted (most recent) day;
# earlier warnings get a muted version of the same hue so they read as
# history behind it rather than competing with it.
HIGHLIGHT_FILL = "#FF0000"
HIGHLIGHT_EDGE = "#8B0000"
PAST_FILL = "#E8837A"
PAST_EDGE = "#9E3B32"

# Per-day label positions (lon, lat, horizontal alignment), keyed by local
# (PT) date. Several Grays Harbor days stack on top of each other, so the
# labels sit in open land nearby and a thin leader line runs to the nearest
# edge of that day's polygons. Any day not listed here gets a label just
# east of its polygons.
LABEL_POS = {
    "2014-10-11": (-122.25, 46.92, "left"),
    "2020-01-21": (-123.45, 47.30, "left"),
    "2020-10-10": (-123.95, 47.72, "left"),
    "2021-03-19": (-123.95, 47.98, "left"),
    "2021-11-09": (-122.95, 47.90, "right"),
    "2024-11-20": (-123.55, 46.72, "left"),
    "2026-11-26": (-121.62, 47.78, "left"),
}

# ---------- extent / projection ----------
# Western Washington / Puget Sound: wide enough to hold every SEW tornado
# warning on record (coast at Clallam/Grays Harbor east to the Cascade
# foothills in King County). Shape roughly matches the lightning map's
# axes box so cartopy doesn't leave big gutters.
EXTENT = [-125.2, -121.0, 46.6, 48.3]
CENTER_LON, CENTER_LAT = -123.1, 47.45

ap = argparse.ArgumentParser()
ap.add_argument("--file", default="tornado_warnings.json")
ap.add_argument("--out", default="puget_sound_tornado_warnings.png")
args = ap.parse_args()

proj = ccrs.NearsidePerspective(central_longitude=CENTER_LON,
                                 central_latitude=CENTER_LAT,
                                 satellite_height=4_000_000)
pc = ccrs.PlateCarree()

fig = plt.figure(figsize=(12, 8.3), dpi=200)
fig.patch.set_facecolor("#f7f6f2")
ax = fig.add_axes([0.04, 0.045, 0.92, 0.80], projection=proj)
ax.set_facecolor("white")
ax.set_extent(EXTENT, crs=pc)

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
# western_wa_us101.geojson patches US-101 around the Olympic Peninsula and
# Grays Harbor coast, which washington_roads.geojson is missing. Overlapping
# segments are just drawn twice in the same style.
for region_file in ["washington_roads.geojson", "western_wa_us101.geojson"]:
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

# ---------- tornado warnings ----------
data = json.load(open(args.file))
warnings = data["warnings"]
for w in warnings:
    w["issue_pt"] = datetime.fromisoformat(w["issue"].replace("Z", "+00:00")).astimezone(PT)
    w["day"] = w["issue_pt"].strftime("%Y-%m-%d")

# Highlight the most recent warning day (today, when there's an active
# event); everything earlier is drawn as history underneath it.
highlight_day = max(w["day"] for w in warnings)

by_day = defaultdict(list)
for w in warnings:
    by_day[w["day"]].append(w)

for day in sorted(by_day):
    is_hl = day == highlight_day
    for w in by_day[day]:
        geom = shape(w["geometry"])
        if is_hl:
            # White halo under a dark-red edge so the highlighted polygon
            # pops against both the basemap and any older polygons.
            ax.add_geometries([geom], crs=pc, facecolor="none", edgecolor="white",
                               linewidth=4.5, zorder=7.0)
            ax.add_geometries([geom], crs=pc, facecolor=HIGHLIGHT_FILL,
                               edgecolor="none", alpha=0.72, zorder=7.1)
            ax.add_geometries([geom], crs=pc, facecolor="none",
                               edgecolor=HIGHLIGHT_EDGE, linewidth=1.8, zorder=7.2)
        else:
            ax.add_geometries([geom], crs=pc, facecolor=PAST_FILL,
                               edgecolor="none", alpha=0.55, zorder=6.5)
            ax.add_geometries([geom], crs=pc, facecolor="none",
                               edgecolor=PAST_EDGE, linewidth=1.0, zorder=6.6)

# ---------- per-day labels ----------
data_xform = pc._as_mpl_transform(ax)
for day, ws in sorted(by_day.items()):
    is_hl = day == highlight_day
    union = unary_union([shape(w["geometry"]) for w in ws])
    if day in LABEL_POS:
        lx, ly, ha = LABEL_POS[day]
    else:
        b = union.bounds
        lx, ly, ha = b[2] + 0.15, union.centroid.y, "left"
    target = nearest_points(union.boundary, Point(lx, ly))[0]
    n = len(ws)
    date_str = ws[0]["issue_pt"].strftime("%b %-d, %Y")
    label = date_str if n == 1 else f"{date_str} ({n})"
    color = HIGHLIGHT_EDGE if is_hl else "#5e231d"
    halo = [pe.withStroke(linewidth=2.5, foreground="white", alpha=0.85)]
    line_halo = [pe.withStroke(linewidth=2.6, foreground="white", alpha=0.85)]
    arrowprops = dict(arrowstyle="-", color=color,
                      linewidth=1.3 if is_hl else 0.9, shrinkA=3, shrinkB=0)

    # Sub-label under the highlighted day so it's clear the warning isn't
    # still in effect when the map is shared after the fact. When present,
    # the leader line hangs off the sub-label instead of the date so it
    # doesn't cut through it.
    expired = False
    if is_hl:
        last_expire = max(datetime.fromisoformat(w["expire"].replace("Z", "+00:00"))
                          for w in ws)
        expired = datetime.now(PT) > last_expire

    txt = ax.annotate(label, xy=(target.x, target.y), xytext=(lx, ly),
                       xycoords=data_xform, textcoords=data_xform,
                       ha=ha, va="center",
                       fontproperties=f_bold if is_hl else f_med,
                       fontsize=13 if is_hl else 10.5, color=color, zorder=10,
                       arrowprops=None if expired else arrowprops)
    txt.set_path_effects(halo)
    if not expired:
        txt.arrow_patch.set_path_effects(line_halo)
        continue

    # Place the sub-label 17pt below the date, in display space, then
    # convert back to the axes' data coords so annotate can draw the
    # leader from it to the polygon.
    fig.canvas.draw()
    disp = data_xform.transform((lx, ly))
    sub_xy = data_xform.inverted().transform((disp[0], disp[1] - 17 * fig.dpi / 72))
    sub = ax.annotate("(now expired)", xy=(target.x, target.y), xytext=sub_xy,
                       xycoords=data_xform, textcoords=data_xform,
                       ha=ha, va="center", fontproperties=f_med,
                       fontsize=10.5, color=color, zorder=10,
                       arrowprops=arrowprops)
    sub.set_path_effects(halo)
    sub.arrow_patch.set_path_effects(line_halo)

# ---------- city labels ----------
cities = [
    ("Seattle", -122.3321, 47.6062, "right"),
    ("Tacoma", -122.4443, 47.2529, "right"),
    ("Everett", -122.2021, 47.9790, "right"),
    ("Bellingham", -122.4787, 48.7519, "right"),
    ("Olympia", -122.9007, 47.0379, "left"),
    ("Bremerton", -122.6326, 47.5673, "left"),
    ("Port Angeles", -123.4307, 48.1181, "right"),
    ("Forks", -124.3855, 47.9504, "right"),
    ("Aberdeen", -123.8157, 46.9754, "right"),
    ("Ocean Shores", -124.1568, 46.9737, "left"),
    ("Shelton", -123.1007, 47.2151, "right"),
    ("Port Townsend", -122.7604, 48.1170, "right"),
    ("North Bend", -121.7868, 47.4957, "right"),
]
for name, lon, lat, side in cities:
    if not (EXTENT[0] < lon < EXTENT[1] and EXTENT[2] < lat < EXTENT[3]):
        continue
    ax.plot(lon, lat, marker="o", markersize=4, color="black",
             transform=pc, zorder=8)
    ha = "left" if side == "right" else "right"
    dx = 0.06 if side == "right" else -0.06
    txt = ax.text(lon + dx, lat, name, transform=pc, ha=ha, va="center",
                   fontproperties=f_med, fontsize=11, color="black", zorder=9)
    txt.set_path_effects([pe.withStroke(linewidth=1.65, foreground="white", alpha=0.6)])

# ---------- frame ----------
ax.spines["geo"].set_edgecolor("black")
ax.spines["geo"].set_linewidth(1.6)

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
n_total = len(warnings)

subtitle_y = top_y + 0.018
title_y = subtitle_y + 0.035
fig.text(left_x, title_y, "Every NWS Seattle Tornado Warning Polygon",
          fontproperties=f_bold, fontsize=22, color="#2b2a26")
subtitle = f"All {n_total} storm-based warnings since polygons began in Oct 2007"
fig.text(left_x, subtitle_y, subtitle, fontproperties=f_reg, fontsize=12, color="#5a584f")

# ---------- attribution ----------
fig.text(center_x, 0.02,
          "NWS warnings via Iowa Environmental Mesonet / US Census (counties) / "
          "OpenStreetMap (roads) — Ingalls Weather",
          fontproperties=f_reg, fontsize=9, color="#5a584f", ha="center")

plt.savefig(args.out, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
print(f"saved {args.out}")

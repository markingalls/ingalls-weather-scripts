import json
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
from matplotlib.lines import Line2D
import cartopy.crs as ccrs
from shapely.geometry import shape
from datetime import datetime, timezone

# ---------- fonts ----------
FONT_DIR = "/usr/share/fonts/truetype/google-fonts/"
f_bold = fm.FontProperties(fname=FONT_DIR + "Poppins-Bold.ttf")
f_reg = fm.FontProperties(fname=FONT_DIR + "Poppins-Regular.ttf")
f_med = fm.FontProperties(fname=FONT_DIR + "Poppins-Medium.ttf")

# ---------- recency bands ----------
# (max_age_hours, label, color) -- newest first. Colors follow the common
# lightning-tracker convention: hot/bright for very recent, fading to pale
# for older strikes, drawn oldest-first so recent strikes sit on top.
AGE_BANDS = [
    (1, "Last hour", "#FF1E56"),
    (6, "1-6 hours ago", "#FF8C00"),
    (24, "6-24 hours ago", "#FFD84D"),
]


def band_for_age(age_hours):
    for max_age, label, color in AGE_BANDS:
        if age_hours <= max_age:
            return label, color
    return AGE_BANDS[-1][1], AGE_BANDS[-1][2]


# ---------- extent / projection (same domain as ../columbia-basin-alerts-map) ----------
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

# ---------- lightning flashes ----------
data = json.load(open("lightning_last24h.json"))
flashes = data["flashes"]
window_end = datetime.fromisoformat(data["window_end"])

# Bucket by age band, then plot oldest band first so more recent strikes
# (drawn last) sit visually on top of older ones where they overlap.
buckets = {label: {"lons": [], "lats": []} for _, label, _ in AGE_BANDS}
for flash in flashes:
    flash_time = datetime.fromisoformat(flash["time"])
    age_hours = (window_end - flash_time).total_seconds() / 3600.0
    label, _ = band_for_age(age_hours)
    buckets[label]["lons"].append(flash["lon"])
    buckets[label]["lats"].append(flash["lat"])

for max_age, label, color in reversed(AGE_BANDS):
    lons = buckets[label]["lons"]
    lats = buckets[label]["lats"]
    if not lons:
        continue
    ax.scatter(lons, lats, transform=pc, s=10, color=color, alpha=0.65,
               edgecolor="none", linewidths=0, zorder=7)

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
fig.text(left_x, title_y, "Columbia Basin: GOES-18 GLM Lightning (Last 24 Hours)",
          fontproperties=f_bold, fontsize=22, color="#2b2a26")
subtitle = (f"{len(flashes):,} flashes detected — "
            f"{window_end.strftime('%b %d %H:%M UTC')} lookback")
fig.text(left_x, subtitle_y, subtitle, fontproperties=f_reg, fontsize=12, color="#5a584f")

# ---------- legend ----------
legend_handles = [
    Line2D([0], [0], marker="o", color="none", markerfacecolor=color,
           markeredgecolor="none", markersize=9, alpha=0.85, label=label)
    for _, label, color in AGE_BANDS
]
leg = fig.legend(handles=legend_handles, loc="lower left",
                  bbox_to_anchor=(left_x + 0.012, map_pos.y0 + 0.012),
                  bbox_transform=fig.transFigure,
                  frameon=True, facecolor="white", edgecolor="#d8d5cc",
                  framealpha=1.0, prop=f_reg, fontsize=10, borderpad=0.8)
leg.get_frame().set_linewidth(0.8)

# ---------- attribution ----------
fig.text(center_x, 0.02,
          "NOAA GOES-18 GLM / US Census (counties) / OpenStreetMap (roads) — Ingalls Weather",
          fontproperties=f_reg, fontsize=9, color="#5a584f", ha="center")


plt.savefig("columbia_basin_lightning.png",
            facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
print("saved")

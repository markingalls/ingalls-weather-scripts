import argparse
import json
import math
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
from matplotlib.lines import Line2D
import cartopy.crs as ccrs
from shapely.geometry import shape, LineString, Point
from shapely.ops import unary_union
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
    (1, "Last hour", "#8B2FC9"),
    (6, "1-6 hours ago", "#FF1E56"),
    (24, "6-24 hours ago", "#FF8C00"),
]


def band_for_age(age_hours):
    for max_age, label, color in AGE_BANDS:
        if age_hours <= max_age:
            return label, color
    return AGE_BANDS[-1][1], AGE_BANDS[-1][2]


# Absolute, derived from this file's own location -- not the process's
# cwd at invocation time. A relative path here breaks under cron (which
# starts with cwd set to the crontab user's home directory, not this
# project's directory) even though it works fine for a manual run after
# `cd`-ing into the project directory -- see columbia-basin-alerts-map/
# build_map.py, where this was first found and fixed, for the full
# writeup.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MAPS_DIR = os.path.join(SCRIPT_DIR, "..", "maps")

# Degrees shown across each map -- same for every "true zoom" region, so
# adding one means picking a center point, not guessing a matching zoom
# level by eye. A region can override lon_span/lat_span/satellite_height
# for a fundamentally different (e.g. much wider) zoom -- see "pnw" below.
LON_SPAN, LAT_SPAN = 5.5, 3.6
SATELLITE_HEIGHT = 4_000_000


def region_extent(center_lon, center_lat, lon_span=LON_SPAN, lat_span=LAT_SPAN):
    return [
        round(center_lon - lon_span / 2, 2), round(center_lon + lon_span / 2, 2),
        round(center_lat - lat_span / 2, 2), round(center_lat + lat_span / 2, 2),
    ]


# Longest legitimate segment length seen in admin1_boundary_lines.json's
# TIGER-derived state lines is ~1.6 degrees; countries_slim.json's country
# borders have several segments over-simplified down to a single straight
# run several degrees long (worst case: the entire WA-to-Minnesota stretch
# of the 49th parallel collapsed to one 27.6-degree segment) that cuts
# across the more detailed admin1 line underneath once a region's extent
# is wide enough to see it -- see columbia-basin-alerts-map/build_map.py,
# where this was first found and fixed, for the full writeup.
MAX_BORDER_SEGMENT_DEG = 3.0

# Natural Earth's admin1_boundary_lines.json includes each coastal state's
# offshore 3-nautical-mile maritime boundary as an ordinary admin-1 line --
# same fix as columbia-basin-alerts-map/build_map.py.
OFFSHORE_LINE_DISTANCE_DEG = 0.02


def drop_long_segments(geom, max_len):
    """Split polygon/line boundary rings on any segment longer than
    max_len, dropping it. Safe for any outline-only (facecolor="none")
    layer since there's no fill to preserve, only the traced border."""
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


def trim_offshore_segments(geom, land_union, threshold):
    """Cut interior offshore-excursion vertices out of an admin-1 boundary
    line instead of an all-or-nothing whole-feature filter -- see
    columbia-basin-alerts-map/build_map.py for the full writeup (Oregon's
    3nm jog is its own feature and drops cleanly; Washington's is fused
    into the same line as its real land borders and needs this)."""
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


REGIONS = {
    "columbia_basin": dict(
        center_lon=-119.75, center_lat=46.2,
        roads_files=["washington_roads.geojson", "oregon_roads.geojson", "idaho_roads_north.geojson"],
        output="columbia_basin_lightning.png",
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
        # Same coordinates tri-cities-7day-forecast/deploy/build_and_publish.py
        # and columbia-basin-alerts-map use for Portland.
        center_lon=-122.60917, center_lat=45.59578,
        roads_files=["washington_roads.geojson", "oregon_roads.geojson"],
        output="portland_lightning.png",
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
            ("Government Camp", -121.7550, 45.3021, "right"),
            ("Packwood", -121.6733, 46.6088, "right"),
            ("Bend", -121.3153, 44.0582, "right"),
            ("Redmond", -121.1739, 44.2726, "right"),
        ],
    ),
    # lon_span/lat_span/satellite_height are overridden here since this
    # region is a fundamentally different (much wider) zoom than Columbia
    # Basin/Portland/BC Interior's shared true-zoom-level setup, not a
    # variant of it -- same extent as columbia-basin-alerts-map's
    # "pnw_wide" region so a domain looks the same across products.
    "pnw": dict(
        center_lon=-119.3, center_lat=44.9,
        lon_span=13.0, lat_span=8.8, satellite_height=22_000_000,
        legend_loc="upper right",
        roads_files=["washington_roads.geojson", "oregon_roads.geojson", "idaho_roads.geojson",
                     "nevada_roads_north.geojson", "montana_roads_west.geojson",
                     "california_roads_north.geojson", "utah_roads_northwest.geojson"],
        output="pnw_lightning.png",
        cities=[
            ("Seattle", -122.3321, 47.6062, "left"),
            ("Bellingham", -122.4443, 48.7519, "left"),
            ("Spokane", -117.4260, 47.6588, "left"),
            ("Wenatchee", -120.3103, 47.4235, "right"),
            ("Yakima", -120.5059, 46.6021, "left"),
            ("Tri-Cities", -119.1372, 46.2112, "right"),
            ("Portland", -122.6765, 45.5152, "right"),
            ("Astoria", -123.8313, 46.1879, "left"),
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
    # Wider than the true-zoom span (not as wide as "pnw") -- covers the
    # Southern Interior (Kamloops/Kelowna/Vernon/Penticton), Prince
    # George, the southwest corridor (Hope, Whistler), and the Yellowhead
    # Pass area just across the Alberta border (Jasper, Banff, Nordegg).
    # lat_span=5.2 and satellite_height=9_000_000 are chosen independently
    # (5.2 for Prince George's latitude, 9_000_000 so that span doesn't
    # clip at the frame edges) and are NOT to be changed just because a
    # storm extends past the frame -- that's expected for any bounded
    # regional map, not a bug. lon_span=8.87 is NOT an independent choice
    # picked by eye, though -- it's lat_span converted to real ground km
    # (5.2 * 111.32) times Columbia Basin's true-zoom width:height ratio
    # in km ((5.5 * cos(46.2deg)) / 3.6), converted back to degrees at
    # this region's own latitude (dividing by 111.32 * cos(51.71deg)).
    # Picking lon_span by eye in raw degrees (as earlier revisions of this
    # region did) produces a box whose real-world aspect ratio doesn't
    # match the other true-zoom regions, since a degree of longitude
    # covers less ground the farther north you go -- that mismatch, not
    # the zoom level or the fetch, was the actual source of the
    # "hard cutoff" complaints. `timezone` (America/Vancouver, not
    # America/Los_Angeles) is used for this region's day/time labels --
    # numerically identical to Pacific Time for any date since 2007
    # (Canada's DST rules matched the US that year), so this is a
    # correctness/clarity fix, not a behavior change today.
    "bc_interior": dict(
        center_lon=-119.68, center_lat=51.71,
        lon_span=8.87, lat_span=5.2, satellite_height=9_000_000,
        timezone="America/Vancouver",
        roads_files=["british_columbia_roads.geojson", "alberta_roads_west.geojson"],
        output="bc_interior_lightning.png",
        cities=[
            ("Prince George", -122.7497, 53.9171, "left"),
            ("Quesnel", -122.4930, 53.0027, "left"),
            ("Wells", -121.5670, 53.1073, "right"),
            ("Williams Lake", -122.1417, 52.1417, "left"),
            ("100 Mile House", -121.2980, 51.6410, "left"),
            ("Cache Creek", -121.3200, 50.8085, "left"),
            ("Kamloops", -120.3273, 50.6745, "below"),
            ("Kelowna", -119.4960, 49.8880, "right"),
            ("Vernon", -119.2720, 50.2670, "right"),
            ("Penticton", -119.5937, 49.4991, "right"),
            ("Merritt", -120.7862, 50.1163, "left"),
            ("Salmon Arm", -119.2838, 50.7001, "right"),
            ("Revelstoke", -118.1957, 50.9981, "right"),
            ("Blue River", -119.2907, 52.1319, "right"),
            ("Jasper", -118.0708, 52.8734, "left"),
            ("Hope", -121.4416, 49.3821, "right"),
            ("Whistler", -122.9574, 50.1163, "right"),
            ("Banff", -115.5708, 51.1784, "right"),
            ("Nordegg", -116.0500, 52.4667, "right"),
        ],
    ),
}


def build_map(region_key, lightning_path, output_path):
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
    admin1_lines = json.load(open(f"{MAPS_DIR}/admin1_boundary_lines.json"))
    raw_geoms = [shape(f["geometry"]) for f in admin1_lines["features"]]
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

    # ---------- counties (WA/OR/ID only -- no-op elsewhere, not a bug) ----------
    counties = json.load(open(f"{MAPS_DIR}/counties_wa_or_id.geojson"))
    co_geoms = [shape(f["geometry"]) for f in counties["features"]]
    ax.add_geometries(co_geoms, crs=pc, facecolor="none", edgecolor="#c7c4b8",
                       linewidth=0.5, zorder=4)

    # ---------- roads ----------
    MOTORWAY = {"motorway", "motorway_link"}
    TRUNK = {"trunk", "trunk_link"}
    PRIMARY = {"primary", "primary_link"}
    MOTORWAY_COLOR = "#8FB8E0"  # pastel blue
    TRUNK_COLOR = "#F2B880"     # pastel orange
    PRIMARY_COLOR = "#E8C9A0"   # lighter/duller pastel orange

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

    # ---------- lightning flashes ----------
    data = json.load(open(lightning_path))
    flashes = data["flashes"]
    window_end = datetime.fromisoformat(data["window_end"])
    extent_box_lons = (extent[0], extent[1])
    extent_box_lats = (extent[2], extent[3])

    # Bucket by age band, then plot oldest band first so more recent
    # strikes (drawn last) sit visually on top of older ones where they
    # overlap. Flashes are filtered to this region's own extent here --
    # the fetch step pulls one shared domain-spanning box, and individual
    # regions crop tighter than that shared box.
    buckets = {label: {"lons": [], "lats": []} for _, label, _ in AGE_BANDS}
    for flash in flashes:
        lon, lat = flash["lon"], flash["lat"]
        if not (extent_box_lons[0] <= lon <= extent_box_lons[1] and
                extent_box_lats[0] <= lat <= extent_box_lats[1]):
            continue
        flash_time = datetime.fromisoformat(flash["time"])
        age_hours = (window_end - flash_time).total_seconds() / 3600.0
        label, _ = band_for_age(age_hours)
        buckets[label]["lons"].append(lon)
        buckets[label]["lats"].append(lat)

    total_in_region = sum(len(b["lons"]) for b in buckets.values())

    for max_age, label, color in reversed(AGE_BANDS):
        lons = buckets[label]["lons"]
        lats = buckets[label]["lats"]
        if not lons:
            continue
        ax.scatter(lons, lats, transform=pc, s=10, color=color, alpha=0.65,
                   edgecolor="none", linewidths=0, zorder=7)

    # ---------- city labels ----------
    # 8-way (not just left/right) -- see columbia-basin-alerts-map/
    # build_map.py, where this was first built out, for the full writeup.
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

    fig.canvas.draw()
    map_pos = ax.get_position()
    left_x = map_pos.x0
    right_x = map_pos.x1
    top_y = map_pos.y1
    center_x = (map_pos.x0 + map_pos.x1) / 2

    # ---------- logo (bottom-right, ~8% of map width, ~22px inset) ----------
    LOGO_PATH = os.path.join(SCRIPT_DIR, "..", "assets", "ingalls_weather_logo.png")
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
    fig.text(left_x, title_y, "Lightning (Last 24 Hours)",
              fontproperties=f_bold, fontsize=22, color="#2b2a26")
    subtitle = (f"{total_in_region:,} flashes detected — GOES-18 GLM, "
                f"{window_end.strftime('%b %d %H:%M UTC')} lookback")
    fig.text(left_x, subtitle_y, subtitle, fontproperties=f_reg, fontsize=12, color="#5a584f")

    # ---------- legend ----------
    legend_handles = [
        Line2D([0], [0], marker="o", color="none", markerfacecolor=color,
               markeredgecolor="none", markersize=9, alpha=0.85, label=label)
        for _, label, color in AGE_BANDS
    ]
    legend_loc = cfg.get("legend_loc", "lower left")
    if legend_loc == "upper right":
        legend_anchor = (right_x - 0.012, top_y - 0.012)
    else:
        legend_anchor = (left_x + 0.012, map_pos.y0 + 0.012)
    leg = fig.legend(handles=legend_handles, loc=legend_loc,
                      bbox_to_anchor=legend_anchor,
                      bbox_transform=fig.transFigure,
                      frameon=True, facecolor="white", edgecolor="#d8d5cc",
                      framealpha=1.0, prop=f_reg, fontsize=10, borderpad=0.8)
    leg.get_frame().set_linewidth(0.8)

    # ---------- attribution ----------
    fig.text(center_x, 0.02,
              "NOAA GOES-18 GLM / US Census (counties) / OpenStreetMap (roads) — Ingalls Weather",
              fontproperties=f_reg, fontsize=9, color="#5a584f", ha="center")

    plt.savefig(output_path, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    print(f"saved {output_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Render a lightning (last 24 hours) map for one region.")
    ap.add_argument("--region", choices=sorted(REGIONS), default="columbia_basin")
    ap.add_argument("--lightning", default="lightning_last24h.json")
    ap.add_argument("--output", default=None,
                     help="Output PNG path (default: REGIONS[region]['output'])")
    args = ap.parse_args()
    build_map(args.region, args.lightning, args.output or REGIONS[args.region]["output"])

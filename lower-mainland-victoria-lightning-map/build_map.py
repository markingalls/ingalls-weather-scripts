"""
Lower Mainland / Victoria GLM Lightning Map -- one-off builder
Ingalls Weather

Styled map zoomed to Whistler (N), Hope (E), Port Renfrew (W), and
Everett (S) -- covering Metro Vancouver, the Fraser Valley, southern
Vancouver Island, and the northwest Puget Sound corridor: GLM flash
detections for a single full calendar day (Pacific time), sourced from
GOES-18. Reads output/lightning_<date>.json (written by
fetch_lightning.py) and writes output/lower_mainland_victoria_lightning_
<date>.png.

USAGE
-----
    python3 fetch_lightning.py                # yesterday, Pacific time
    python3 build_map.py                      # renders yesterday's fetch
    python3 build_map.py --date 2026-08-22
"""
import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
from matplotlib.lines import Line2D
import cartopy.crs as ccrs
from shapely.geometry import shape

THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parent
MAPS_DIR = REPO_ROOT / "maps"
ASSETS_DIR = REPO_ROOT / "assets"
OUTPUT_DIR = THIS_DIR / "output"

PACIFIC = ZoneInfo("America/Los_Angeles")

# ---------- fonts ----------
FONT_DIR = "/usr/share/fonts/truetype/google-fonts/"
f_bold = fm.FontProperties(fname=FONT_DIR + "Poppins-Bold.ttf")
f_reg = fm.FontProperties(fname=FONT_DIR + "Poppins-Regular.ttf")
f_med = fm.FontProperties(fname=FONT_DIR + "Poppins-Medium.ttf")

# A full archived day has no meaningful "how recent" axis the way a live
# nowcast does (every flash on the map is equally "that day"), so this is
# a single style, matching ../columbia-basin-lightning-daily-map/ (the
# canonical daily-archive lightning map posted to the website) rather than
# the age-banded style used by the rolling-lookback lightning maps.
FLASH_COLOR = "#8B2FC9"
FLASH_LABEL = "Lightning flash"


# ---------- extent / projection ----------
# Whistler (N), Hope (E), Port Renfrew (W), Everett (S), padded 0.2 deg so
# none of the four sit right at the frame edge.
LON_MIN, LON_MAX = -124.6204, -121.2412
LAT_MIN, LAT_MAX = 47.7790, 50.3163

# FIG_WIDTH_IN chosen (given AXES_RECT below) so the axes box's pixel
# aspect ratio matches the domain's lon/lat degree-span ratio (~1.33);
# otherwise cartopy shrinks one dimension to preserve the projection's
# aspect and leaves empty gutters (see ../dew-point-storm-map/build_map.py).
FIG_WIDTH_IN, FIG_HEIGHT_IN = 10.2, 8.8
AXES_RECT = [0.04, 0.045, 0.92, 0.80]  # [left, bottom, width, height], figure fraction

# PlateCarree, not NearsidePerspective (used by ../columbia-basin-lightning-
# map/) -- NearsidePerspective fits the axes to a rectangle bounding the
# *projected*, curved shape of the requested lon/lat box, which at this
# domain's tighter, more elongated shape left visible blank corners; see
# the note in ../dew-point-storm-map/build_map.py for the same tradeoff.
pc = ccrs.PlateCarree()
proj = pc


def load_geoms(path, filter_fn=None):
    data = json.load(open(path))
    feats = data["features"] if filter_fn is None else [f for f in data["features"] if filter_fn(f)]
    return [shape(f["geometry"]) for f in feats]


def build_map(date, data_path, output_path):
    data = json.load(open(data_path))
    flashes = data["flashes"]
    window_start = datetime.fromisoformat(data["window_start"]).astimezone(PACIFIC)
    window_end = datetime.fromisoformat(data["window_end"]).astimezone(PACIFIC)

    fig = plt.figure(figsize=(FIG_WIDTH_IN, FIG_HEIGHT_IN), dpi=200)
    fig.patch.set_facecolor("#f7f6f2")
    ax = fig.add_axes(AXES_RECT, projection=proj)
    ax.set_facecolor("white")
    ax.set_extent([LON_MIN, LON_MAX, LAT_MIN, LAT_MAX], crs=pc)

    # ---------- land ----------
    # Full-resolution Natural Earth 10m land + minor islands, clipped to
    # this domain and checked in locally -- ../maps/land_slim.json is
    # simplified for continental-scale maps and reads visibly blocky at
    # this tight a zoom (Gulf Islands, Howe Sound, the Fraser mouth).
    land_geoms = load_geoms(THIS_DIR / "coastline_10m.geojson")
    ax.add_geometries(land_geoms, crs=pc, facecolor="#e3e1da", edgecolor="none", zorder=1)

    # ---------- countries (US/Canada border) ----------
    # admin0_boundary_lines.json, not ../maps/countries_slim.json's polygon
    # edges -- a dedicated boundary-line layer (land border only, no
    # coastline duplication) renders a cleaner line than tracing a
    # simplified country polygon's outline; see ../dew-point-storm-map/
    # build_map.py for the same choice.
    c_geoms = load_geoms(MAPS_DIR / "admin0_boundary_lines.json")
    ax.add_geometries(c_geoms, crs=pc, facecolor="none", edgecolor="#9a978c",
                       linewidth=1.1, zorder=2)

    # ---------- lakes ----------
    # No admin1_boundary_lines.json layer here -- the only state/province
    # boundary this domain touches is WA's own northern edge, which *is*
    # the international border already drawn above, so adding it back on
    # top (Natural Earth's admin1 lines don't distinguish "shares this
    # segment with an admin0 border" from a true internal state line) drew
    # a visible double line right along the border.
    lake_geoms = load_geoms(
        MAPS_DIR / "states_lakes_slim.json",
        lambda f: f["properties"].get("admin", "") in ("United States of America", "Canada")
        and "Lake" in f["properties"].get("featurecla", ""))
    ax.add_geometries(lake_geoms, crs=pc, facecolor="white", edgecolor="#b9b6ac",
                       linewidth=0.7, zorder=3)

    # ---------- roads (WA + BC -- ../maps/bc_roads.geojson is this map's
    # own OSM motorway/trunk pull for the Canadian side, in the same
    # style/schema as the shared washington_roads.geojson) ----------
    MOTORWAY = {"motorway", "motorway_link"}
    TRUNK = {"trunk", "trunk_link"}
    MOTORWAY_COLOR = "#8FB8E0"  # pastel blue
    TRUNK_COLOR = "#F2B880"     # pastel orange

    motorway_geoms, trunk_geoms = [], []
    for roads_file in ("washington_roads.geojson", "bc_roads.geojson"):
        d = json.load(open(MAPS_DIR / roads_file))
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
    lons = [f["lon"] for f in flashes]
    lats = [f["lat"] for f in flashes]
    ax.scatter(lons, lats, transform=pc, s=10, color=FLASH_COLOR, alpha=0.55,
               edgecolor="none", linewidths=0, zorder=7)

    # ---------- city labels ----------
    cities = [
        ("Whistler", -122.9574, 50.1163, "right"),
        ("Squamish", -123.1558, 49.7016, "right"),
        ("Sechelt", -123.7556, 49.4742, "left"),
        ("Vancouver", -123.1207, 49.2827, "left"),
        ("Coquitlam", -122.7932, 49.2838, "right"),
        ("Surrey", -122.8490, 49.1913, "right"),
        ("Abbotsford", -122.3045, 49.0504, "right"),
        ("Chilliwack", -121.9514, 49.1579, "right"),
        ("Hope", -121.4412, 49.3820, "left"),
        ("Nanaimo", -123.9401, 49.1659, "left"),
        ("Duncan", -123.7079, 48.7787, "left"),
        ("Victoria", -123.3656, 48.4284, "right"),
        ("Sooke", -123.7275, 48.3742, "right"),
        ("Port Renfrew", -124.4204, 48.5541, "right"),
        ("Port Angeles", -123.4307, 48.1181, "right"),
        ("Oak Harbor", -122.6401, 48.2934, "left"),
        ("Bellingham", -122.4787, 48.7519, "right"),
        ("Everett", -122.2021, 47.9790, "right"),
    ]
    LABEL_DX = 0.035
    for name, lon, lat, side in cities:
        ax.plot(lon, lat, marker="o", markersize=4, color="black",
                 transform=pc, zorder=8)
        ha = "left" if side == "right" else "right"
        dx = LABEL_DX if side == "right" else -LABEL_DX
        txt = ax.text(lon + dx, lat, name, transform=pc, ha=ha, va="center",
                       fontproperties=f_med, fontsize=11, color="black", zorder=9)
        txt.set_path_effects([pe.withStroke(linewidth=1.65, foreground="white", alpha=0.6)])

    # ---------- frame ----------
    ax.spines["geo"].set_edgecolor("black")
    ax.spines["geo"].set_linewidth(1.6)

    fig.canvas.draw()
    map_pos = ax.get_position()
    left_x = map_pos.x0
    top_y = map_pos.y1
    center_x = (map_pos.x0 + map_pos.x1) / 2

    # ---------- logo (bottom-right, ~8% of map width, ~22px inset) ----------
    LOGO_PATH = ASSETS_DIR / "ingalls_weather_logo.png"
    if LOGO_PATH.exists():
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
    fig.text(left_x, title_y,
              f"Lower Mainland & Victoria: Lightning ({window_start.strftime('%b %d, %Y')})",
              fontproperties=f_bold, fontsize=22, color="#2b2a26")
    subtitle = f"{len(flashes):,} flashes detected — GOES-18 GLM ({window_start.strftime('%Z')})"
    fig.text(left_x, subtitle_y, subtitle, fontproperties=f_reg, fontsize=12, color="#5a584f")

    # ---------- legend ----------
    legend_handles = [
        Line2D([0], [0], marker="o", color="none", markerfacecolor=FLASH_COLOR,
               markeredgecolor="none", markersize=9, alpha=0.85, label=FLASH_LABEL),
    ]
    leg = fig.legend(handles=legend_handles, loc="lower left",
                      bbox_to_anchor=(left_x + 0.012, map_pos.y0 + 0.012),
                      bbox_transform=fig.transFigure,
                      frameon=True, facecolor="white", edgecolor="#d8d5cc",
                      framealpha=1.0, prop=f_reg, fontsize=10, borderpad=0.8)
    leg.get_frame().set_linewidth(0.8)

    # ---------- attribution ----------
    fig.text(center_x, 0.02,
              "NOAA GOES-18 GLM / OpenStreetMap (roads) — Ingalls Weather",
              fontproperties=f_reg, fontsize=9, color="#5a584f", ha="center")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, facecolor=fig.get_facecolor(), bbox_inches="tight", pad_inches=0.15)
    print(f"Saved {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, default=None,
                         help="Calendar day to render, Pacific time, as 'YYYY-MM-DD'. "
                              "Defaults to yesterday.")
    args = parser.parse_args()

    if args.date:
        date = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        from datetime import timedelta
        date = (datetime.now(PACIFIC) - timedelta(days=1)).date()

    data_path = OUTPUT_DIR / f"lightning_{date.isoformat()}.json"
    if not data_path.exists():
        raise SystemExit(f"No data file at {data_path} -- run fetch_lightning.py "
                          f"--date {date.isoformat()} first.")
    output_path = OUTPUT_DIR / f"lower_mainland_victoria_lightning_{date.isoformat()}.png"
    build_map(date, data_path, output_path)

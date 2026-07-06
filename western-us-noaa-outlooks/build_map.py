"""
Western U.S. NOAA Outlooks — map builder
Ingalls Weather

Currently supports: CPC Day 8-14 Extreme Heat outlooks (both the
probabilistic "Slight/Moderate/High Risk" KML and the categorical
single "Extreme Heat" KML). Auto-detects which one you've handed it.

USAGE
-----
1. Grab the current KML from CPC yourself (this data is not fetchable
   live by an automated pipeline — CPC does not offer a stable feed,
   so this must be a manual download each time):
     - Probabilistic (preferred): https://www.cpc.ncep.noaa.gov/products/predictions/threats/excess_heat_prob_D8_14.kml
     - Categorical (fallback):    https://www.cpc.ncep.noaa.gov/products/predictions/threats/temp_D8_14.kml
2. Drop the downloaded file in western-us-noaa-outlooks/data/
3. Run:
     python build_map.py --kml data/excess_heat_prob_D8_14.kml
   (or just `python build_map.py` if the filename matches DEFAULT_KML below)
4. Output PNG lands in western-us-noaa-outlooks/output/

REQUIRES (already checked into /maps at repo root, shared across all
Ingalls Weather map projects):
    land_slim.json, countries_slim.json, states_lakes_slim.json
  Sourced from raw.githubusercontent.com/martynafford/natural-earth-geojson
  (10m), clipped down to North America.

Logo is read from /assets/ingalls_weather_logo.png at repo root.
"""

import argparse
import json
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
from matplotlib.patches import Patch
import numpy as np

import cartopy.crs as ccrs
from shapely.geometry import shape, Polygon as ShPolygon, MultiPolygon as ShMultiPolygon
from PIL import Image

# ---------------------------------------------------------------------------
# Paths (relative to this script's location: western-us-noaa-outlooks/)
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
MAPS_DIR = REPO_ROOT / "maps"
ASSETS_DIR = REPO_ROOT / "assets"
THIS_DIR = Path(__file__).resolve().parent
DATA_DIR = THIS_DIR / "data"
OUTPUT_DIR = THIS_DIR / "output"

LAND_FILE = MAPS_DIR / "land_slim.json"
COUNTRIES_FILE = MAPS_DIR / "countries_slim.json"
STATES_LAKES_FILE = MAPS_DIR / "states_lakes_slim.json"
LOGO_FILE = ASSETS_DIR / "ingalls_weather_logo.png"

TARGET_COUNTRIES = {"United States of America", "Canada", "Mexico"}

DEFAULT_KML = DATA_DIR / "excess_heat_prob_D8_14.kml"
OUTPUT_FILE = OUTPUT_DIR / "western_us_extreme_heat_hazard.png"

POPPINS_REG_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf"
POPPINS_MED_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf"

# ---------------------------------------------------------------------------
# Map domain (western US) — do not change this when adding new cities;
# cities right at the edge often still render fine thanks to the curved
# projection. Only change this if you deliberately want a wider/narrower map.
# ---------------------------------------------------------------------------
LON_MIN, LON_MAX = -128.5, -98.0
LAT_MIN, LAT_MAX = 28.0, 51.5
CENTER_LON, CENTER_LAT = -113.5, 39.5

# ---------------------------------------------------------------------------
# City labels: (name, lon, lat, label position: "left" | "right" | "above" | "below")
# ---------------------------------------------------------------------------
CITIES = [
    ("Seattle", -122.33, 47.61, "left"),
    ("Portland", -122.68, 45.52, "left"),
    ("Bend", -121.31, 44.06, "left"),
    ("Sacramento", -121.49, 38.58, "right"),
    ("San Francisco", -122.42, 37.77, "left"),
    ("Los Angeles", -118.24, 34.05, "right"),
    ("San Diego", -117.16, 32.72, "left"),
    ("Las Vegas", -115.14, 36.17, "right"),
    ("Phoenix", -112.07, 33.45, "right"),
    ("Salt Lake City", -111.89, 40.76, "right"),
    ("Boise", -116.20, 43.62, "left"),
    ("Idaho Falls", -112.03, 43.49, "right"),
    ("Denver", -104.99, 39.74, "right"),
    ("Cheyenne", -104.82, 41.14, "right"),
    ("Billings", -108.50, 45.78, "right"),
    ("Rapid City", -103.23, 44.08, "right"),
    ("Bismarck", -100.78, 46.81, "right"),
    ("Albuquerque", -106.65, 35.08, "right"),
    ("El Paso", -106.49, 31.76, "right"),
    ("Spokane", -117.43, 47.66, "right"),
    ("Tri-Cities", -119.28, 46.26, "right"),
    ("Warroad", -95.31, 48.91, "left"),
]

# ---------------------------------------------------------------------------
# Known CPC hazard categories -> style. Covers both the probabilistic
# (Slight/Moderate/High) and categorical (single "Extreme Heat") products.
# Only whichever of these are actually present in the KML get drawn/legended.
# ---------------------------------------------------------------------------
STYLE_MAP = {
    "Slight Risk of Extreme Heat":   {"color": "#f2a341", "alpha": 0.55, "z": 3, "label": "Slight Risk"},
    "Moderate Risk of Extreme Heat": {"color": "#d1382b", "alpha": 0.60, "z": 4, "label": "Moderate Risk"},
    "High Risk of Extreme Heat":     {"color": "#9c1f4a", "alpha": 0.65, "z": 5, "label": "High Risk"},
    "Extreme Heat":                  {"color": "#d1382b", "alpha": 0.60, "z": 4, "label": "Extreme Heat"},
}
# Draw/legend order, least to most severe
CATEGORY_ORDER = [
    "Slight Risk of Extreme Heat",
    "Moderate Risk of Extreme Heat",
    "High Risk of Extreme Heat",
    "Extreme Heat",
]


def parse_kml(path):
    """Pull placemark name + polygon rings + Start_Date/End_Date out of a
    CPC hazards KML (handles both the probabilistic and categorical exports)."""
    txt = Path(path).read_text(errors="ignore")
    placemarks = re.findall(r"<Placemark.*?</Placemark>", txt, re.S)
    results = []
    for pm in placemarks:
        name = re.search(r"<[nN]ame>(.*?)</[nN]ame>", pm, re.S).group(1).strip()
        coord_blocks = re.findall(r"<coordinates>(.*?)</coordinates>", pm, re.S)
        rings = []
        for block in coord_blocks:
            pts = [(float(lon), float(lat))
                   for lon, lat, _ in (triplet.split(",") for triplet in block.strip().split())]
            rings.append(pts)
        start = re.search(r"Start_Date</td>\s*<td>([\d/]+)</td>", pm)
        end = re.search(r"End_Date</td>\s*<td>([\d/]+)</td>", pm)
        results.append({
            "name": name,
            "rings": rings,
            "start_date": start.group(1) if start else None,
            "end_date": end.group(1) if end else None,
        })
    return results


def format_date_range(features):
    """Build a 'valid Jul 13-19, 2026' style string from the earliest
    start date and latest end date found across all placemarks."""
    from datetime import datetime
    starts, ends = [], []
    for f in features:
        if f["start_date"]:
            starts.append(datetime.strptime(f["start_date"], "%m/%d/%Y"))
        if f["end_date"]:
            ends.append(datetime.strptime(f["end_date"], "%m/%d/%Y"))
    if not starts or not ends:
        return "valid date range unavailable"
    s, e = min(starts), max(ends)
    if s.month == e.month:
        return f"valid {s.strftime('%b')} {s.day}–{e.day}, {e.year}"
    return f"valid {s.strftime('%b %d')}–{e.strftime('%b %d')}, {e.year}"


def load_land():
    with open(LAND_FILE) as f:
        data = json.load(f)
    return [shape(feat["geometry"]) for feat in data["features"] if feat.get("geometry")]


def load_countries():
    with open(COUNTRIES_FILE) as f:
        data = json.load(f)
    geoms = []
    for feat in data["features"]:
        props = feat["properties"]
        name = props.get("NAME") or props.get("ADMIN") or props.get("name")
        if name in TARGET_COUNTRIES:
            geoms.append(shape(feat["geometry"]))
    return geoms


def load_states_and_lakes():
    with open(STATES_LAKES_FILE) as f:
        data = json.load(f)
    state_geoms, lake_geoms = [], []
    for feat in data["features"]:
        props = feat["properties"]
        featurecla = props.get("featurecla", "")
        if "Lake" in featurecla:
            lake_geoms.append(shape(feat["geometry"]))
        elif props.get("admin") in TARGET_COUNTRIES:
            state_geoms.append(shape(feat["geometry"]))
    return state_geoms, lake_geoms


def build_map(kml_path, output_path):
    poppins_reg = fm.FontProperties(fname=POPPINS_REG_PATH)
    poppins_semibold = fm.FontProperties(fname=POPPINS_MED_PATH)

    heat_features = parse_kml(kml_path)
    if not heat_features:
        sys.exit(f"No placemarks found in {kml_path} — is this the right KML?")
    date_str = format_date_range(heat_features)
    present_categories = [f["name"] for f in heat_features]
    print(f"Parsed categories: {present_categories}")
    print(f"Date range: {date_str}")

    print("Loading basemap layers...")
    land_geoms = load_land()
    country_geoms = load_countries()
    state_geoms, lake_geoms = load_states_and_lakes()

    proj = ccrs.NearsidePerspective(central_longitude=CENTER_LON, central_latitude=CENTER_LAT,
                                     satellite_height=4_000_000)
    pc = ccrs.PlateCarree()

    fig = plt.figure(figsize=(10, 8.9), dpi=200)
    fig.patch.set_facecolor("#f7f6f2")

    ax = fig.add_axes([0.035, 0.045, 0.93, 0.855], projection=proj)
    ax.set_extent([LON_MIN, LON_MAX, LAT_MIN, LAT_MAX], crs=pc)
    ax.patch.set_facecolor("white")

    ax.add_geometries(land_geoms, crs=pc, facecolor="#e3e1da", edgecolor="none", linewidth=0, zorder=1)
    ax.add_geometries(state_geoms, crs=pc, facecolor="none", edgecolor="#b9b6ac", linewidth=0.7, zorder=2)
    ax.add_geometries(lake_geoms, crs=pc, facecolor="white", edgecolor="#b9b6ac", linewidth=0.7, zorder=2.2)
    ax.add_geometries(country_geoms, crs=pc, facecolor="none", edgecolor="#9a978c", linewidth=1.1, zorder=2.5)

    # Heat hazard polygons
    for feat in heat_features:
        sty = STYLE_MAP.get(feat["name"])
        if sty is None:
            print(f"WARNING: unrecognized category '{feat['name']}', skipping. Add it to STYLE_MAP.")
            continue
        polys = [ShPolygon(ring) for ring in feat["rings"]]
        geom = polys[0] if len(polys) == 1 else ShMultiPolygon(polys)
        ax.add_geometries([geom], crs=pc, facecolor=sty["color"], edgecolor=sty["color"],
                           linewidth=1.2, alpha=sty["alpha"], zorder=sty["z"])

    # City labels
    for name, lon, lat, pos in CITIES:
        ax.plot(lon, lat, marker="o", markersize=5.0, color="#3b3a35", zorder=6,
                mec="white", mew=0.7, transform=pc)
        dx = 0.3 if pos == "right" else (-0.3 if pos == "left" else 0)
        dy = 0.38 if pos == "above" else (-0.52 if pos == "below" else 0)
        ha = "left" if pos == "right" else ("right" if pos == "left" else "center")
        va = "bottom" if pos == "above" else ("top" if pos == "below" else "center")
        txt = ax.text(lon + dx, lat + dy, name, fontsize=14.01, fontproperties=poppins_semibold,
                       color="#2b2a26", ha=ha, va=va, zorder=7, transform=pc)
        txt.set_path_effects([pe.withStroke(linewidth=1.65, foreground=(1, 1, 1, 0.6))])

    ax.spines['geo'].set_edgecolor('black')
    ax.spines['geo'].set_linewidth(1.6)

    # Legend — only for categories actually present, in severity order
    ordered_present = [c for c in CATEGORY_ORDER if c in present_categories]
    handles = [Patch(facecolor=STYLE_MAP[n]["color"], edgecolor=STYLE_MAP[n]["color"],
                      alpha=STYLE_MAP[n]["alpha"], label=STYLE_MAP[n]["label"])
               for n in reversed(ordered_present)]  # most severe first in legend
    leg = fig.legend(handles=handles, loc="lower left", frameon=False, fontsize=11,
                      prop=poppins_reg, handlelength=1.4, handleheight=1.4, borderpad=0.3,
                      bbox_to_anchor=(0.14, 0.065))
    for text in leg.get_texts():
        text.set_color("#2b2a26")

    # Title & subtitle above the map
    fig.text(0.03, 0.975, "Western U.S. Extreme Heat Hazard", fontsize=22,
              fontproperties=poppins_reg, color="#2b2a26", ha="left", va="top")
    fig.text(0.03, 0.935, f"NWS Climate Prediction Center — Day 8–14 Outlook, {date_str}",
              fontsize=12, fontproperties=poppins_reg, color="#5a584f", ha="left", va="top")

    # Attribution
    fig.text(0.5, 0.012, "NOAA / CPC — Ingalls Weather", fontsize=9,
              fontproperties=poppins_reg, color="#8a887e", ha="center", va="bottom")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, facecolor=fig.get_facecolor(), dpi=200)
    plt.close(fig)
    print(f"Saved base map to {output_path}")

    # ---- Composite logo, bottom-right, snug inside the frame ----
    if LOGO_FILE.exists():
        base = Image.open(output_path).convert("RGB")
        bw, bh = base.size
        # Locate the black map frame so the logo sits just inside it
        arr = np.array(base)
        y = bh // 2
        black_cols = [x for x in range(bw) if arr[y, x][0] < 40 and arr[y, x][1] < 40 and arr[y, x][2] < 40]
        x = bw // 2
        black_rows = [yy for yy in range(bh) if arr[yy, x][0] < 40 and arr[yy, x][1] < 40 and arr[yy, x][2] < 40]
        frame_right = max(black_cols) if black_cols else bw - 20
        frame_bottom = max(black_rows) if black_rows else bh - 20

        logo = Image.open(LOGO_FILE).convert("RGB")
        target_w = int(bw * 0.08)
        scale = target_w / logo.width
        target_h = int(logo.height * scale)
        logo_resized = logo.resize((target_w, target_h), Image.LANCZOS)

        inset = 22
        pos = (frame_right - inset - target_w, frame_bottom - inset - target_h)
        base.paste(logo_resized, pos)
        base.save(output_path)
        print(f"Composited logo at {pos}")
    else:
        print(f"NOTE: logo not found at {LOGO_FILE}, skipping (map saved without logo).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the Western U.S. Extreme Heat Hazard map.")
    parser.add_argument("--kml", type=Path, default=DEFAULT_KML,
                         help="Path to the CPC Day 8-14 heat KML (probabilistic or categorical).")
    parser.add_argument("--out", type=Path, default=OUTPUT_FILE,
                         help="Output PNG path.")
    args = parser.parse_args()

    if not args.kml.exists():
        sys.exit(
            f"KML not found at {args.kml}\n\n"
            "Download the current file from CPC and place it there:\n"
            "  Probabilistic: https://www.cpc.ncep.noaa.gov/products/predictions/threats/excess_heat_prob_D8_14.kml\n"
            "  Categorical:   https://www.cpc.ncep.noaa.gov/products/predictions/threats/temp_D8_14.kml\n"
            "(CPC does not offer a live-fetchable feed for this product, so this is a manual step each run.)"
        )
    build_map(args.kml, args.out)

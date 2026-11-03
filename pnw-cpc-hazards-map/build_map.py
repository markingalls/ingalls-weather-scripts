"""
Pacific Northwest CPC Day 8-14 Hazards Map -- map builder
Ingalls Weather

Same domain as ../wildcad-fires-map/ and ../dew-point-storm-map/ (Prince
George BC to Winnemucca NV, Bella Coola BC to Yellowstone WY), plotting
three of the NWS Climate Prediction Center's Day 8-14 probabilistic hazard
outlooks on one map, layered (z-order, top to bottom) as:

  Top     Heavy Snow           Moderate + High Risk: solid fill
                               Slight Risk: hatched (no fill)
  Middle  Heavy Precipitation  Slight / Moderate / High Risk: solid fill
  Bottom  High Winds           Slight Risk: outline only
                               Moderate Risk: hatched

Fills are translucent so a lower layer stays readable underneath a higher
one (e.g. a wind hatch under a rain fill), and the two hatched layers lean
opposite directions (snow "\\\\", wind "//") so they're still tellable
apart where they overlap.

The legend below the map follows the same top-to-bottom order, one row per
hazard. Each category's label carries its own valid dates -- CPC routinely
gives individual risk areas a shorter window than the full Day 8-14 period
(e.g. a High Risk for days 8-10 only, inside a Slight Risk for 8-14).

DATA SOURCES
------------
CPC publishes a stable, non-dated "latest" KML per hazard:
    https://www.cpc.ncep.noaa.gov/products/predictions/threats/snow_prob_D8_14.kml
    https://www.cpc.ncep.noaa.gov/products/predictions/threats/prcp_prob_D8_14.kml
    https://www.cpc.ncep.noaa.gov/products/predictions/threats/wind_prob_D8_14.kml
(the same family as the heat outlook in ../western-us-noaa-outlooks/). Each
Placemark is named e.g. "Moderate Risk of Heavy Snow", with Start_Date /
End_Date (MM/DD/YYYY) in its description table. The same category can
appear in more than one Placemark (separate areas, sometimes with
different dates); those are unioned per category for drawing and their
date ranges merged for the legend. The hazards outlook is CONUS-only, so
nothing is ever drawn over BC/Alberta.

CPC's 8-14 day hazards KMLs carry no Polygon holes today, but
parse_hazard_kml() honors <innerBoundaryIs> anyway rather than filling
holes in, should a future issuance draw, say, a Slight Risk ring around
a Moderate Risk.

USAGE
-----
    python3 build_map.py
    python3 build_map.py --data-dir data/     # render from saved KMLs, no fetch

Every live run saves the three fetched KMLs into data/ so --data-dir can
re-render without re-fetching.

REQUIRES (already checked into /maps at repo root, shared across all
Ingalls Weather map projects): land_slim.json, states_lakes_slim.json,
admin0_boundary_lines.json. Logo is read from /assets/ingalls_weather_logo.png.
"""

import argparse
import json
import re
import sys
from datetime import datetime
from html import unescape
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
from matplotlib.patches import Patch
from matplotlib.transforms import offset_copy
import numpy as np
import requests

import cartopy.crs as ccrs
import shapely
from shapely.geometry import shape, box, Polygon as ShPolygon
from shapely.ops import unary_union
from PIL import Image

# ---------------------------------------------------------------------------
# Paths (relative to this script's location: pnw-cpc-hazards-map/)
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
MAPS_DIR = REPO_ROOT / "maps"
ASSETS_DIR = REPO_ROOT / "assets"
THIS_DIR = Path(__file__).resolve().parent
DATA_DIR = THIS_DIR / "data"
OUTPUT_DIR = THIS_DIR / "output"

LAND_FILE = MAPS_DIR / "land_slim.json"
STATES_LAKES_FILE = MAPS_DIR / "states_lakes_slim.json"
ADMIN0_LINES_FILE = MAPS_DIR / "admin0_boundary_lines.json"
LOGO_FILE = ASSETS_DIR / "ingalls_weather_logo.png"

TARGET_COUNTRIES = {"United States of America", "Canada"}

POPPINS_REG_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf"
POPPINS_MED_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf"

# ---------------------------------------------------------------------------
# Figure geometry / map domain -- same LON/LAT domain, figure size, and
# axes box as ../wildcad-fires-map/build_map.py, so the PNW products read
# as a matched set: three compact legend rows below the frame, title block
# above it.
# ---------------------------------------------------------------------------
FIG_WIDTH_IN, FIG_HEIGHT_IN = 8.4, 8.5
FIG_DPI = 200
AXES_RECT = [0.03, 0.149, 0.94, 0.716]
MAP_FRAME_INSET_PX = 22

LON_MIN, LON_MAX = -128.2, -108.8
LAT_MIN, LAT_MAX = 39.7, 55.2

# CPC's outlooks are nationwide; anything entirely outside this (slightly
# padded) box is dropped so it doesn't pad out the legend.
MAP_BBOX = box(LON_MIN - 1, LAT_MIN - 1, LON_MAX + 1, LAT_MAX + 1)

CITIES = [
    ("Bella Coola", -126.7659, 52.3728, "right"),
    ("Wells", -121.5589, 53.1058, "right"),
    ("Vancouver", -123.1207, 49.2827, "left"),
    ("Victoria", -123.3656, 48.4284, "left"),
    ("Kelowna", -119.4960, 49.8880, "right"),
    ("Kamloops", -120.3273, 50.6745, "right"),
    ("Prince George", -122.7497, 53.9171, "right"),
    ("Cranbrook", -115.7697, 49.5097, "right"),
    ("Williams Lake", -122.1417, 52.1417, "left"),
    ("Seattle", -122.3321, 47.6062, "left"),
    ("Spokane", -117.4260, 47.6588, "left"),
    ("Tri-Cities", -119.2781, 46.2565, "right"),
    ("Portland", -122.6784, 45.5152, "left"),
    ("Bend", -121.3153, 44.0582, "left"),
    ("Eugene", -123.0868, 44.0521, "left"),
    ("Medford", -122.8756, 42.3265, "left"),
    ("Redding", -122.3917, 40.5865, "left"),
    ("Burns", -119.0541, 43.5866, "right"),
    ("Boise", -116.2023, 43.6150, "left"),
    ("Twin Falls", -114.4609, 42.5629, "left"),
    ("Idaho Falls", -112.0362, 43.4917, "right"),
    ("Winnemucca", -117.7357, 40.9730, "left"),
    ("Salt Lake City", -111.8910, 40.7608, "right"),
    ("Bozeman", -111.0429, 45.6770, "right"),
    ("Missoula", -113.9940, 46.8721, "left"),
    ("Great Falls", -111.3008, 47.5053, "right"),
    ("Calgary", -114.0719, 51.0447, "right"),
    ("Red Deer", -113.8112, 52.2681, "right"),
    ("Edmonton", -113.4938, 53.5461, "right"),
    ("Lethbridge", -112.8418, 49.6935, "right"),
]

# ---------------------------------------------------------------------------
# Hazard layers, listed TOP to BOTTOM (draw order is the reverse). Each
# category's "mode" is one of:
#   fill     translucent solid fill + same-color edge
#   hatch    hatch lines + same-color edge, no fill
#   outline  edge only
# Colors follow CPC's own convention per hazard (blues/purple for snow,
# greens for precipitation, browns for wind), deepening with risk level.
# ---------------------------------------------------------------------------
CPC_THREATS_BASE = "https://www.cpc.ncep.noaa.gov/products/predictions/threats"

HAZARDS = [
    dict(
        key="snow",
        title="Heavy Snow",
        url=f"{CPC_THREATS_BASE}/snow_prob_D8_14.kml",
        name_suffix="Risk of Heavy Snow",
        categories={
            "Slight":   dict(mode="hatch", color="#3d6fd1", hatch="\\\\\\\\", alpha=1.0),
            "Moderate": dict(mode="fill",  color="#3d6fd1", alpha=0.72),
            "High":     dict(mode="fill",  color="#6a3aa6", alpha=0.78),
        },
    ),
    dict(
        key="prcp",
        title="Heavy Precip",
        url=f"{CPC_THREATS_BASE}/prcp_prob_D8_14.kml",
        name_suffix="Risk of Heavy Precipitation",
        categories={
            "Slight":   dict(mode="fill", color="#98d18f", alpha=0.55),
            "Moderate": dict(mode="fill", color="#3f9a4e", alpha=0.58),
            "High":     dict(mode="fill", color="#1c5e33", alpha=0.62),
        },
    ),
    dict(
        key="wind",
        title="High Winds",
        url=f"{CPC_THREATS_BASE}/wind_prob_D8_14.kml",
        name_suffix="Risk of High Winds",
        categories={
            "Slight":   dict(mode="outline", color="#8b5a2b", alpha=1.0),
            "Moderate": dict(mode="hatch",   color="#8b5a2b", hatch="////", alpha=1.0),
            # CPC hasn't issued a High Risk of High Winds in recent memory,
            # but style it in case -- denser hatch, darker brown.
            "High":     dict(mode="hatch",   color="#5a3412", hatch="//////", alpha=1.0),
        },
    ),
]
RISK_ORDER = ["Slight", "Moderate", "High"]

HAZARD_EDGE_WIDTH = 1.2
# How close (deg) an outline-only category's edge can sit to the US/Canada
# border and still get trimmed as "drawn along the border" -- see
# draw_hazard(). CPC's border clip doesn't vertex-match Natural Earth's
# line exactly, so this needs a little slack.
BORDER_TRIM_BUFFER_DEG = 0.08
OUTLINE_WIDTH = 1.8
plt.rcParams["hatch.linewidth"] = 1.0

# Layer z-order bases (each hazard's categories stack a little above its
# base, Slight lowest). Basemap sits at 1-2.5, cities at 10+.
LAYER_ZORDER = {"wind": 3, "prcp": 4, "snow": 5}


# ---------------------------------------------------------------------------
# KML parsing
# ---------------------------------------------------------------------------

def _parse_coords(block):
    pts = []
    for triplet in block.split():
        parts = triplet.split(",")
        if len(parts) >= 2:
            pts.append((float(parts[0]), float(parts[1])))
    return pts


def _parse_polygons(placemark_xml):
    """Each <Polygon> -> shapely Polygon, honoring <innerBoundaryIs> holes."""
    polys = []
    for poly_xml in re.findall(r"<Polygon[ >].*?</Polygon>", placemark_xml, re.S):
        outer = re.search(r"<outerBoundaryIs>.*?<coordinates>(.*?)</coordinates>", poly_xml, re.S)
        if not outer:
            continue
        shell = _parse_coords(outer.group(1))
        if len(shell) < 3:
            continue
        holes = [_parse_coords(h) for h in
                 re.findall(r"<innerBoundaryIs>.*?<coordinates>(.*?)</coordinates>", poly_xml, re.S)]
        poly = ShPolygon(shell, [h for h in holes if len(h) >= 3])
        if not poly.is_valid:
            poly = shapely.make_valid(poly)
        polys.append(poly)
    return polys


def parse_hazard_kml(text, hazard):
    """Returns {risk: {"geom": shapely geom, "start": dt|None, "end": dt|None}}
    for each risk level present inside the map frame."""
    out = {}
    for pm in re.findall(r"<Placemark[ >].*?</Placemark>", text, re.S):
        m = re.search(r"<name>(.*?)</name>", pm, re.S)
        name = unescape(m.group(1)).strip() if m else ""
        fields = {k.strip(): unescape(v).strip()
                  for k, v in re.findall(r"<td>([^<]+)</td>\s*<td[^>]*>([^<]*)</td>", pm)}
        name = name or fields.get("Label", "")
        risk = name.split(" ", 1)[0] if name.endswith(hazard["name_suffix"]) else None
        if risk not in hazard["categories"]:
            if name:
                print(f"WARNING: unrecognized {hazard['title']} category '{name}', skipping.")
            continue
        polys = [p for p in _parse_polygons(pm) if p.intersects(MAP_BBOX)]
        if not polys:
            continue  # this placemark's area is elsewhere in CONUS
        entry = out.setdefault(risk, {"geoms": [], "starts": [], "ends": []})
        entry["geoms"].extend(polys)
        for key, bucket in (("Start_Date", "starts"), ("End_Date", "ends")):
            try:
                entry[bucket].append(datetime.strptime(fields.get(key, ""), "%m/%d/%Y"))
            except ValueError:
                pass
    return {
        risk: {
            "geom": unary_union(e["geoms"]),
            "start": min(e["starts"]) if e["starts"] else None,
            "end": max(e["ends"]) if e["ends"] else None,
        }
        for risk, e in out.items()
    }


def all_placemark_dates(text):
    """Every Start/End date in a KML, frame or not -- for the subtitle's
    overall outlook period."""
    starts = [datetime.strptime(s, "%m/%d/%Y")
              for s in re.findall(r"<td>Start_Date</td>\s*<td[^>]*>(\d+/\d+/\d{4})</td>", text)]
    ends = [datetime.strptime(s, "%m/%d/%Y")
            for s in re.findall(r"<td>End_Date</td>\s*<td[^>]*>(\d+/\d+/\d{4})</td>", text)]
    return starts, ends


def format_range(s, e, with_year=True):
    if s is None or e is None:
        return "dates n/a"
    if s == e:
        out = f"{s.strftime('%b')} {s.day}"
    elif s.month == e.month:
        out = f"{s.strftime('%b')} {s.day}–{e.day}"
    else:
        out = f"{s.strftime('%b')} {s.day}–{e.strftime('%b')} {e.day}"
    return f"{out}, {e.year}" if with_year else out


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def fetch_kmls(data_dir):
    """Returns {hazard key: KML text}. Live fetch unless data_dir is given;
    a live fetch also saves each KML to DATA_DIR for later --data-dir use."""
    texts = {}
    for hz in HAZARDS:
        fname = hz["url"].rsplit("/", 1)[1]
        if data_dir:
            path = Path(data_dir) / fname
            if not path.exists():
                sys.exit(f"--data-dir: {path} not found.")
            print(f"Using local file: {path}")
            texts[hz["key"]] = path.read_text(encoding="utf-8", errors="ignore")
            continue
        print(f"Fetching {hz['url']} ...")
        try:
            resp = requests.get(hz["url"], timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            sys.exit(f"Could not fetch {hz['url']}: {e}")
        texts[hz["key"]] = resp.content.decode("utf-8", errors="ignore")
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        (DATA_DIR / fname).write_text(texts[hz["key"]], encoding="utf-8")
    return texts


# ---------------------------------------------------------------------------
# Basemap
# ---------------------------------------------------------------------------

def load_land():
    with open(LAND_FILE) as f:
        data = json.load(f)
    return [shape(feat["geometry"]) for feat in data["features"] if feat.get("geometry")]


def load_states():
    with open(STATES_LAKES_FILE) as f:
        data = json.load(f)
    return [shape(feat["geometry"]) for feat in data["features"]
            if "Lake" not in feat["properties"].get("featurecla", "")
            and feat["properties"].get("admin") in TARGET_COUNTRIES]


def load_boundary_lines(path):
    with open(path) as f:
        data = json.load(f)
    return [shape(feat["geometry"]) for feat in data["features"]]


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

def draw_hazard(ax, pc, hz, areas, border_buffer):
    """Draw one hazard's categories, Slight lowest. Fill/hatch areas have
    any higher category's area cut out first, so e.g. the snow Slight
    hatch doesn't run underneath (and muddy) the Moderate fill it
    surrounds; outlines keep their full shape so the boundary reads as one
    clean line.

    Outline-only categories also have any stretch of their boundary lying
    along the US/Canada border removed (border_buffer): CPC's polygons are
    clipped at the border, and an outline-only category has no fill to show
    which side it's on, so a stroke there just reads as a recolored
    international border rather than a hazard edge."""
    base_z = LAYER_ZORDER[hz["key"]]
    present = [r for r in RISK_ORDER if r in areas]
    for i, risk in enumerate(present):
        sty = hz["categories"][risk]
        geom = areas[risk]["geom"]
        higher = [areas[r]["geom"] for r in present[i + 1:]]
        if sty["mode"] != "outline" and higher:
            geom = geom.difference(unary_union(higher))
        if geom.is_empty:
            continue
        z = base_z + 0.1 * i
        if sty["mode"] == "fill":
            ax.add_geometries([geom], crs=pc, facecolor=sty["color"], edgecolor=sty["color"],
                               linewidth=HAZARD_EDGE_WIDTH, alpha=sty["alpha"], zorder=z)
        elif sty["mode"] == "hatch":
            ax.add_geometries([geom], crs=pc, facecolor="none", edgecolor=sty["color"],
                               hatch=sty["hatch"], linewidth=HAZARD_EDGE_WIDTH, zorder=z)
        else:  # outline
            edge = geom.boundary.difference(border_buffer)
            if not edge.is_empty:
                ax.add_geometries([edge], crs=pc, facecolor="none", edgecolor=sty["color"],
                                   linewidth=OUTLINE_WIDTH, zorder=z)


def legend_handle(sty, label):
    if sty["mode"] == "fill":
        return Patch(facecolor=sty["color"], edgecolor=sty["color"], alpha=sty["alpha"], label=label)
    if sty["mode"] == "hatch":
        return Patch(facecolor="white", edgecolor=sty["color"], hatch=sty["hatch"],
                     linewidth=HAZARD_EDGE_WIDTH, label=label)
    return Patch(facecolor="white", edgecolor=sty["color"], linewidth=OUTLINE_WIDTH, label=label)


def build_map(texts, output_path):
    poppins_reg = fm.FontProperties(fname=POPPINS_REG_PATH)
    poppins_semibold = fm.FontProperties(fname=POPPINS_MED_PATH)

    areas_by_hazard = {}
    all_starts, all_ends = [], []
    for hz in HAZARDS:
        areas_by_hazard[hz["key"]] = parse_hazard_kml(texts[hz["key"]], hz)
        s, e = all_placemark_dates(texts[hz["key"]])
        all_starts += s
        all_ends += e
        summary = ", ".join(f"{r} ({format_range(a['start'], a['end'], False)})"
                            for r, a in areas_by_hazard[hz["key"]].items()) or "none in frame"
        print(f"{hz['title']}: {summary}")
    period = (format_range(min(all_starts), max(all_ends))
              if all_starts and all_ends else "valid dates unavailable")

    print("Loading basemap layers...")
    land_geoms = load_land()
    state_geoms = load_states()
    admin0_lines = load_boundary_lines(ADMIN0_LINES_FILE)

    pc = ccrs.PlateCarree()
    fig = plt.figure(figsize=(FIG_WIDTH_IN, FIG_HEIGHT_IN), dpi=FIG_DPI)
    fig.patch.set_facecolor("#f7f6f2")

    ax = fig.add_axes(AXES_RECT, projection=pc)
    ax.set_extent([LON_MIN, LON_MAX, LAT_MIN, LAT_MAX], crs=pc)
    ax.patch.set_facecolor("#bfe1ef")  # pastel ocean, as in wildcad-fires-map

    ax.add_geometries(land_geoms, crs=pc, facecolor="#e3e1da", edgecolor="#4a6b7a", linewidth=0.8, zorder=1)
    ax.add_geometries(state_geoms, crs=pc, facecolor="none", edgecolor="#8a8578", linewidth=0.8, zorder=2)
    ax.add_geometries(admin0_lines, crs=pc, facecolor="none", edgecolor="#3a2f21", linewidth=1.1, zorder=2.5)

    border_buffer = unary_union(admin0_lines).buffer(BORDER_TRIM_BUFFER_DEG)
    # Bottom layer first, so the top layer (snow) draws last.
    for hz in reversed(HAZARDS):
        draw_hazard(ax, pc, hz, areas_by_hazard[hz["key"]], border_buffer)

    geodetic_transform = pc._as_mpl_transform(ax)
    city_stroke = [pe.withStroke(linewidth=1.5, foreground=(1, 1, 1, 0.85))]
    for name, lon_c, lat_c, pos in CITIES:
        if not (LON_MIN <= lon_c <= LON_MAX and LAT_MIN <= lat_c <= LAT_MAX):
            continue
        ax.plot(lon_c, lat_c, marker="o", markersize=3.6, color="#3a3835", zorder=10,
                mec="white", mew=0.6, transform=pc)
        dx_pt = 6 if pos == "right" else -6
        ha = "left" if pos == "right" else "right"
        name_transform = offset_copy(geodetic_transform, fig=fig, x=dx_pt, y=0, units="points")
        txt = ax.text(lon_c, lat_c, name, fontsize=8.25, fontproperties=poppins_semibold,
                       color="#3a3835", ha=ha, va="center", zorder=11, transform=name_transform)
        txt.set_path_effects(city_stroke)

    ax.spines['geo'].set_edgecolor('black')
    ax.spines['geo'].set_linewidth(1.6)

    # Legend -- below the map, one row per hazard in the same top-to-bottom
    # order as the map's layering. Row label in a fixed left column; risk
    # swatches (with each category's own valid dates) after it. Only
    # categories present in the frame are listed.
    fig.canvas.draw()
    frame_px = ax.get_window_extent()
    fig_w_px = FIG_WIDTH_IN * FIG_DPI
    frame_left = frame_px.x0 / fig_w_px
    label_x = frame_left + 0.005
    swatch_x = frame_left + 0.135
    row_ys = [0.124, 0.092, 0.060]
    for hz, y in zip(HAZARDS, row_ys):
        fig.text(label_x, y, hz["title"], fontsize=9.5, fontproperties=poppins_semibold,
                 color="#2b2a26", ha="left", va="center")
        areas = areas_by_hazard[hz["key"]]
        handles = [legend_handle(hz["categories"][r],
                                 f"{r} ({format_range(areas[r]['start'], areas[r]['end'], False)})")
                   for r in RISK_ORDER if r in areas]
        if not handles:
            fig.text(swatch_x, y, "No risk areas in the region", fontsize=8.75, fontproperties=poppins_reg,
                     color="#8a887e", ha="left", va="center")
            continue
        leg = fig.legend(handles=handles, loc="center left", frameon=False, prop=poppins_reg,
                          ncol=len(handles), handlelength=2.0, handleheight=1.1, handletextpad=0.6,
                          columnspacing=1.6, borderpad=0, borderaxespad=0,
                          bbox_to_anchor=(swatch_x, y))
        for text in leg.get_texts():
            text.set_color("#2b2a26")
            text.set_fontsize(8.75)

    # Title & subtitle above the map
    fig.text(0.03, 0.977, "Pacific Northwest 8–14 Day Hazards", fontsize=19,
              fontproperties=poppins_reg, color="#2b2a26", ha="left", va="top")
    fig.text(0.03, 0.940, "NWS Climate Prediction Center — Heavy Snow, Heavy Precipitation, High Winds",
              fontsize=11.5, fontproperties=poppins_semibold, color="#3a3835", ha="left", va="top")
    fig.text(0.03, 0.909, f"Valid {period} • U.S. only",
              fontsize=10.5, fontproperties=poppins_reg, color="#5a584f", ha="left", va="top")

    fig.text(0.5, 0.014, "NOAA / CPC — Ingalls Weather", fontsize=9,
              fontproperties=poppins_reg, color="#8a887e", ha="center", va="bottom")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, facecolor=fig.get_facecolor(), dpi=FIG_DPI)
    plt.close(fig)
    print(f"Saved base map to {output_path}")

    # ---- Composite logo, bottom-left, snug inside the frame (open Pacific
    # off northern California -- never under a hazard area) ----
    if LOGO_FILE.exists():
        base = Image.open(output_path).convert("RGB")
        bw, bh = base.size
        arr = np.array(base)
        y = bh // 2
        black_cols = [x for x in range(bw) if arr[y, x][0] < 40 and arr[y, x][1] < 40 and arr[y, x][2] < 40]
        x = bw // 2
        black_rows = [yy for yy in range(bh) if arr[yy, x][0] < 40 and arr[yy, x][1] < 40 and arr[yy, x][2] < 40]
        frame_left_px = min(black_cols) if black_cols else 20
        frame_bottom_px = max(black_rows) if black_rows else bh - 20

        logo = Image.open(LOGO_FILE).convert("RGB")
        target_w = int(bw * 0.08)
        target_h = int(logo.height * target_w / logo.width)
        logo_resized = logo.resize((target_w, target_h), Image.LANCZOS)

        pos = (frame_left_px + MAP_FRAME_INSET_PX, frame_bottom_px - MAP_FRAME_INSET_PX - target_h)
        base.paste(logo_resized, pos)
        base.save(output_path)
        print(f"Composited logo at {pos}")
    else:
        print(f"NOTE: logo not found at {LOGO_FILE}, skipping (map saved without logo).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build an Ingalls Weather Pacific Northwest CPC Day 8-14 hazards map.")
    parser.add_argument("--data-dir", type=Path, default=None,
                         help="Render from snow/prcp/wind_prob_D8_14.kml saved in this directory "
                              "instead of fetching live (every live run saves them to data/).")
    parser.add_argument("--out", type=Path, default=None,
                         help="Output PNG path (default: output/pnw_cpc_hazards_<start date>.png).")
    args = parser.parse_args()

    texts = fetch_kmls(args.data_dir)
    if args.out:
        out_path = args.out
    else:
        starts = [s for t in texts.values() for s in all_placemark_dates(t)[0]]
        stamp = min(starts).strftime("%Y-%m-%d") if starts else datetime.now().strftime("%Y-%m-%d")
        out_path = OUTPUT_DIR / f"pnw_cpc_hazards_{stamp}.png"
    build_map(texts, out_path)

"""
Western U.S. NOAA Outlooks — map builder
Ingalls Weather

Renders any of several NOAA outlook products over the same Western U.S.
frame/style. Pick one with --product:

    heat_d8_14    CPC Day 8-14 Extreme Heat outlook (probabilistic,
                  falls back to categorical if unavailable)
    temp_6_10     CPC 6-10 Day Temperature Outlook
    precip_6_10   CPC 6-10 Day Precipitation Outlook
    temp_8_14     CPC 8-14 Day Temperature Outlook
    precip_8_14   CPC 8-14 Day Precipitation Outlook
    temp_wk34     CPC Week 3-4 Temperature Outlook
    precip_wk34   CPC Week 3-4 Precipitation Outlook
    spc_fire      SPC Day 1 Fire Weather Outlook
    spc_severe    SPC Day 1 Categorical (Severe Weather) Outlook
    wpc_precip    WPC Day 1 Excessive Rainfall Outlook

USAGE
-----
    python build_map.py --product temp_8_14

Each product's current KML/KMZ is fetched live over HTTPS (all of the
sources above publish a stable, non-dated "latest" URL — see PRODUCTS
below). Output PNG lands in western-us-noaa-outlooks/output/.

To render from a KML/KMZ you already have on disk instead of fetching
(useful for testing, or if a source is temporarily down), pass
--file path/to/thing.kml.

REQUIRES (already checked into /maps at repo root, shared across all
Ingalls Weather map projects):
    land_slim.json, countries_slim.json, states_lakes_slim.json
  Sourced from raw.githubusercontent.com/martynafford/natural-earth-geojson
  (10m), clipped down to North America.

Logo is read from /assets/ingalls_weather_logo.png at repo root.
"""

import argparse
import io
import json
import re
import sys
import zipfile
from datetime import datetime
from html import unescape
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
import matplotlib.colors as mcolors
from matplotlib.patches import Patch
import numpy as np
import requests

import cartopy.crs as ccrs
from shapely.geometry import shape, box, Polygon as ShPolygon, MultiPolygon as ShMultiPolygon
from shapely.ops import unary_union
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
STATES_LAKES_FILE = MAPS_DIR / "states_lakes_slim.json"
LOGO_FILE = ASSETS_DIR / "ingalls_weather_logo.png"

TARGET_COUNTRIES = {"United States of America", "Canada", "Mexico"}

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

# National products (CPC temp/precip, SPC, WPC) carry shading well outside
# this frame; padded slightly beyond the visible extent so edge-clipped
# polygons still count as "present" for the legend.
MAP_BBOX = box(LON_MIN - 3, LAT_MIN - 3, LON_MAX + 3, LAT_MAX + 3)

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
# KML parsing — NOAA centers export two different flavors of KML. Each
# product below picks whichever of these two matches its source:
#
#   parse_kml_named          Placemark has a <name> (sometimes blank, in
#                             which case we fall back to the "KML Label"
#                             field in its description table) plus an
#                             optional label/value description table.
#                             Covers CPC's heat/temp/precip outlooks and
#                             WPC's Excessive Rainfall Outlook.
#
#   parse_kml_extended_data  Placemark has no <name>; category + styling
#                             live in ExtendedData, as either
#                             <Data name="X"><value>Y</value></Data> or
#                             schema-based <SimpleData name="X">Y</SimpleData>.
#                             Covers SPC's fire weather + categorical
#                             severe outlooks.
# ---------------------------------------------------------------------------

def _parse_rings(placemark_xml):
    rings = []
    for block in re.findall(r"<coordinates>(.*?)</coordinates>", placemark_xml, re.S):
        pts = []
        for triplet in block.split():
            parts = triplet.split(",")
            if len(parts) < 2:
                continue
            pts.append((float(parts[0]), float(parts[1])))
        if len(pts) >= 3:
            rings.append(pts)
    return rings


def parse_kml_named(text):
    placemarks = re.findall(r"<Placemark[ >].*?</Placemark>", text, re.S)
    results = []
    for pm in placemarks:
        m = re.search(r"<name>(.*?)</name>", pm, re.S)
        name = unescape(m.group(1)).strip() if m else ""
        fields = {k.strip(): unescape(v).strip()
                  for k, v in re.findall(r"<td>([^<]+)</td>\s*<td[^>]*>([^<]*)</td>", pm)}
        if not name:
            name = fields.get("KML Label", "")
        rings = _parse_rings(pm)
        if not rings or not name:
            continue
        results.append({"name": name, "fields": fields, "rings": rings})
    return results


def parse_kml_extended_data(text):
    placemarks = re.findall(r"<Placemark[ >].*?</Placemark>", text, re.S)
    results = []
    for pm in placemarks:
        fields = {}
        for k, v in re.findall(r'<Data name="([^"]+)"><value>(.*?)</value></Data>', pm, re.S):
            fields[k] = unescape(v).strip()
        for k, v in re.findall(r'<SimpleData name="([^"]+)">(.*?)</SimpleData>', pm, re.S):
            fields[k] = unescape(v).strip()
        rings = _parse_rings(pm)
        if not rings or "LABEL" not in fields:
            continue
        results.append({"fields": fields, "rings": rings})
    return results


# ---------------------------------------------------------------------------
# Date formatting per source
# ---------------------------------------------------------------------------

def _format_range(s, e):
    if s.month == e.month:
        return f"valid {s.strftime('%b')} {s.day}–{e.day}, {e.year}"
    return f"valid {s.strftime('%b %d')}–{e.strftime('%b %d')}, {e.year}"


def date_from_fields(start_key, end_key):
    """CPC's date fields land in each placemark's description table, just
    under a different label per product line ("Start_Date" for the heat
    outlook, "Start Date" for the temp/precip outlooks)."""
    def fn(placemarks, fetched_at):
        starts, ends = [], []
        for pm in placemarks:
            f = pm["fields"]
            if f.get(start_key):
                starts.append(datetime.strptime(f[start_key], "%m/%d/%Y"))
            if f.get(end_key):
                ends.append(datetime.strptime(f[end_key], "%m/%d/%Y"))
        if not starts or not ends:
            return "valid date range unavailable"
        return _format_range(min(starts), max(ends))
    return fn


def date_from_valid_expire_iso(placemarks, fetched_at):
    valids, expires = [], []
    for pm in placemarks:
        f = pm["fields"]
        if f.get("VALID_ISO"):
            valids.append(datetime.fromisoformat(f["VALID_ISO"]))
        if f.get("EXPIRE_ISO"):
            expires.append(datetime.fromisoformat(f["EXPIRE_ISO"]))
    if not valids or not expires:
        return "valid period unavailable"
    v, e = min(valids), max(expires)
    return f"valid {v.strftime('%b %d, %H')}Z–{e.strftime('%b %d, %H')}Z"


def date_from_fetch_time(placemarks, fetched_at):
    """WPC's Excessive Rainfall Outlook KML carries no embedded date --
    fall back to today (the outlook is always for the current cycle)."""
    return f"issued {datetime.now().strftime('%b %d, %Y')}"


# ---------------------------------------------------------------------------
# Styling per source. Each style function takes a parsed placemark and
# returns None (skip / unrecognized) or a dict with:
#   color, alpha, order_key (severity, for zorder + legend ordering), label
# ---------------------------------------------------------------------------

NORMAL_COLOR = "#b2b2b2"

HEAT_STYLE_MAP = {
    "Slight Risk of Extreme Heat":   {"color": "#f2a341", "alpha": 0.55, "order_key": 1, "label": "Slight Risk"},
    "Moderate Risk of Extreme Heat": {"color": "#d1382b", "alpha": 0.60, "order_key": 2, "label": "Moderate Risk"},
    "High Risk of Extreme Heat":     {"color": "#9c1f4a", "alpha": 0.65, "order_key": 3, "label": "High Risk"},
    "Extreme Heat":                  {"color": "#d1382b", "alpha": 0.60, "order_key": 2, "label": "Extreme Heat"},
}


def heat_style(pm):
    sty = HEAT_STYLE_MAP.get(pm["name"])
    if sty is None:
        print(f"WARNING: unrecognized heat category '{pm['name']}', skipping. Add it to HEAT_STYLE_MAP.")
        return None
    return dict(sty)


# CPC temperature/precipitation outlooks are a continuous probability (33-90%)
# rather than a handful of fixed categories, so instead of hand-picking a
# swatch per tier we sample a colormap by probability. Below/Above use
# different colormaps per variable (temp: blue/red: dry precip: brown, wet
# precip: green), matching CPC's own outlook color convention.
TEMP_CMAP = {"Above": matplotlib.colormaps["YlOrRd"], "Below": matplotlib.colormaps["Blues"]}
PRECIP_CMAP = {"Above": matplotlib.colormaps["Greens"], "Below": matplotlib.colormaps["YlOrBr"]}


def _prob_ramp_color(cmap, probability):
    t = 0.30 + 0.60 * max(0.0, min(1.0, (probability - 33.0) / (90.0 - 33.0)))
    return mcolors.to_hex(cmap(t))


def cpc_prob_style(cmap_by_direction):
    def style(pm):
        fields = pm["fields"]
        category = fields.get("Category", "").strip()
        try:
            probability = float(fields.get("Probability", 0))
        except ValueError:
            probability = 0.0
        if category in ("Normal", "EC", ""):
            label = "Equal Chances" if category == "EC" else "Near Normal"
            return {"color": NORMAL_COLOR, "alpha": 0.55, "order_key": 0, "label": label}
        if category not in ("Above", "Below"):
            print(f"WARNING: unrecognized outlook category '{category}', skipping.")
            return None
        color = _prob_ramp_color(cmap_by_direction[category], probability)
        order_key = probability if category == "Above" else -probability
        label = f"{probability:.0f}% {category} Normal"
        return {"color": color, "alpha": 0.68, "order_key": order_key, "label": label}
    return style


SPC_FIRE_STYLE = {
    "ELEV": {"color": "#e0b04a", "alpha": 0.60, "order_key": 1, "label": "Elevated"},
    "CRIT": {"color": "#dd7a2e", "alpha": 0.62, "order_key": 2, "label": "Critical"},
    "EXTM": {"color": "#c13a2b", "alpha": 0.65, "order_key": 3, "label": "Extreme"},
    # Dry thunderstorm risk is a separate hazard axis (lightning without
    # rain), not a more severe fire-weather-index tier -- distinct hue.
    "IDRT": {"color": "#6a4c93", "alpha": 0.45, "order_key": 4, "label": "Isolated Dry Thunderstorms"},
}

SPC_SEVERE_STYLE = {
    "TSTM": {"color": "#8fc48f", "alpha": 0.55, "order_key": 1, "label": "General Thunder"},
    "MRGL": {"color": "#3f8f4f", "alpha": 0.58, "order_key": 2, "label": "Marginal"},
    "SLGT": {"color": "#e8c84b", "alpha": 0.62, "order_key": 3, "label": "Slight"},
    "ENH":  {"color": "#e2872f", "alpha": 0.64, "order_key": 4, "label": "Enhanced"},
    "MDT":  {"color": "#c23b2b", "alpha": 0.66, "order_key": 5, "label": "Moderate"},
    "HIGH": {"color": "#b23b9c", "alpha": 0.68, "order_key": 6, "label": "High"},
}


def spc_style(style_map, warning_label):
    def style(pm):
        code = pm["fields"].get("LABEL", "")
        sty = style_map.get(code)
        if sty is None:
            print(f"WARNING: unrecognized {warning_label} category '{code}', skipping.")
            return None
        return dict(sty)
    return style


WPC_ERO_STYLE = [
    ("Marginal", {"color": "#6fae6f", "alpha": 0.58}),
    ("Slight",   {"color": "#e0c84b", "alpha": 0.62}),
    ("Moderate", {"color": "#d9622f", "alpha": 0.65}),
    ("High",     {"color": "#a83b9c", "alpha": 0.68}),
]


def wpc_ero_style(pm):
    name = pm["name"]
    for i, (key, sty) in enumerate(WPC_ERO_STYLE):
        if name.startswith(key):
            return {**sty, "order_key": i + 1, "label": name}
    print(f"WARNING: unrecognized excessive rainfall category '{name}', skipping.")
    return None


# ---------------------------------------------------------------------------
# Product registry
# ---------------------------------------------------------------------------

PRODUCTS = {
    "heat_d8_14": dict(
        title="Western U.S. Extreme Heat Hazard",
        subtitle_prefix="NWS Climate Prediction Center — Day 8–14 Outlook",
        agency="CPC",
        urls=[
            "https://www.cpc.ncep.noaa.gov/products/predictions/threats/excess_heat_prob_D8_14.kml",
            "https://www.cpc.ncep.noaa.gov/products/predictions/threats/temp_D8_14.kml",
        ],
        parser=parse_kml_named,
        style=heat_style,
        date=date_from_fields("Start_Date", "End_Date"),
        output="western_us_extreme_heat_hazard.png",
    ),
    "temp_6_10": dict(
        title="Western U.S. 6–10 Day Temperature Outlook",
        subtitle_prefix="NWS Climate Prediction Center — 6–10 Day Outlook",
        agency="CPC",
        urls=["https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/610temp_latest.kmz"],
        parser=parse_kml_named,
        style=cpc_prob_style(TEMP_CMAP),
        date=date_from_fields("Start Date", "End Date"),
        output="western_us_temp_6_10.png",
    ),
    "precip_6_10": dict(
        title="Western U.S. 6–10 Day Precipitation Outlook",
        subtitle_prefix="NWS Climate Prediction Center — 6–10 Day Outlook",
        agency="CPC",
        urls=["https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/610prcp_latest.kmz"],
        parser=parse_kml_named,
        style=cpc_prob_style(PRECIP_CMAP),
        date=date_from_fields("Start Date", "End Date"),
        output="western_us_precip_6_10.png",
    ),
    "temp_8_14": dict(
        title="Western U.S. 8–14 Day Temperature Outlook",
        subtitle_prefix="NWS Climate Prediction Center — 8–14 Day Outlook",
        agency="CPC",
        urls=["https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/814temp_latest.kmz"],
        parser=parse_kml_named,
        style=cpc_prob_style(TEMP_CMAP),
        date=date_from_fields("Start Date", "End Date"),
        output="western_us_temp_8_14.png",
    ),
    "precip_8_14": dict(
        title="Western U.S. 8–14 Day Precipitation Outlook",
        subtitle_prefix="NWS Climate Prediction Center — 8–14 Day Outlook",
        agency="CPC",
        urls=["https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/814prcp_latest.kmz"],
        parser=parse_kml_named,
        style=cpc_prob_style(PRECIP_CMAP),
        date=date_from_fields("Start Date", "End Date"),
        output="western_us_precip_8_14.png",
    ),
    "temp_wk34": dict(
        title="Western U.S. Week 3–4 Temperature Outlook",
        subtitle_prefix="NWS Climate Prediction Center — Week 3–4 Outlook",
        agency="CPC",
        urls=["https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/wk34temp_latest.kmz"],
        parser=parse_kml_named,
        style=cpc_prob_style(TEMP_CMAP),
        date=date_from_fields("Start Date", "End Date"),
        output="western_us_temp_wk34.png",
    ),
    "precip_wk34": dict(
        title="Western U.S. Week 3–4 Precipitation Outlook",
        subtitle_prefix="NWS Climate Prediction Center — Week 3–4 Outlook",
        agency="CPC",
        urls=["https://ftp.cpc.ncep.noaa.gov/GIS/us_tempprcpfcst/wk34prcp_latest.kmz"],
        parser=parse_kml_named,
        style=cpc_prob_style(PRECIP_CMAP),
        date=date_from_fields("Start Date", "End Date"),
        output="western_us_precip_wk34.png",
    ),
    "spc_fire": dict(
        title="Western U.S. Fire Weather Outlook",
        subtitle_prefix="NWS Storm Prediction Center — Day 1 Outlook",
        agency="SPC",
        urls=["https://www.spc.noaa.gov/products/fire_wx/day1fireotlk.kmz"],
        parser=parse_kml_extended_data,
        style=spc_style(SPC_FIRE_STYLE, "fire outlook"),
        date=date_from_valid_expire_iso,
        output="western_us_spc_fire.png",
    ),
    "spc_severe": dict(
        title="Western U.S. Severe Weather Outlook",
        subtitle_prefix="NWS Storm Prediction Center — Day 1 Categorical Outlook",
        agency="SPC",
        urls=["https://www.spc.noaa.gov/products/outlook/day1otlk_cat.kmz"],
        parser=parse_kml_extended_data,
        style=spc_style(SPC_SEVERE_STYLE, "severe outlook"),
        date=date_from_valid_expire_iso,
        output="western_us_spc_severe.png",
    ),
    "wpc_precip": dict(
        title="Western U.S. Excessive Rainfall Outlook",
        subtitle_prefix="NWS Weather Prediction Center — Day 1 Outlook",
        agency="WPC",
        urls=["https://www.wpc.ncep.noaa.gov/kml/ero/Day_1_Excessive_Rainfall_Outlook.kmz"],
        parser=parse_kml_named,
        style=wpc_ero_style,
        date=date_from_fetch_time,
        output="western_us_wpc_precip.png",
    ),
}


def fetch_source(cfg, override_path):
    """Returns (kml_text, fetched_at_header_or_None)."""
    if override_path:
        print(f"Using local file: {override_path}")
        raw = Path(override_path).read_bytes()
        fetched_at = None
    else:
        raw, fetched_at, last_err = None, None, None
        for url in cfg["urls"]:
            try:
                print(f"Fetching {url} ...")
                resp = requests.get(url, timeout=30)
                resp.raise_for_status()
                raw = resp.content
                fetched_at = resp.headers.get("Last-Modified")
                break
            except requests.RequestException as e:
                last_err = e
                print(f"  failed: {e}")
        if raw is None:
            sys.exit(
                "Could not fetch data from any source:\n  " + "\n  ".join(cfg["urls"]) +
                f"\nLast error: {last_err}"
            )
    if raw[:2] == b"PK":  # zip (kmz)
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            kml_name = next(n for n in zf.namelist() if n.lower().endswith(".kml"))
            text = zf.read(kml_name).decode("utf-8", errors="ignore")
    else:
        text = raw.decode("utf-8", errors="ignore")
    return text, fetched_at


def load_land():
    with open(LAND_FILE) as f:
        data = json.load(f)
    return [shape(feat["geometry"]) for feat in data["features"] if feat.get("geometry")]


def load_states_lakes_and_countries():
    """State/province + lake geometries, plus a country outline per
    TARGET_COUNTRIES dissolved from those same state/province polygons
    (rather than a separately-sourced country layer) so the international
    border lines up exactly with the state/province borders drawn on top
    of it -- two independently-simplified datasets of the same border
    otherwise drift apart and leave a visible seam."""
    with open(STATES_LAKES_FILE) as f:
        data = json.load(f)
    state_geoms, lake_geoms = [], []
    by_country = {c: [] for c in TARGET_COUNTRIES}
    for feat in data["features"]:
        props = feat["properties"]
        featurecla = props.get("featurecla", "")
        if "Lake" in featurecla:
            lake_geoms.append(shape(feat["geometry"]))
            continue
        admin = props.get("admin")
        if admin in TARGET_COUNTRIES:
            geom = shape(feat["geometry"])
            state_geoms.append(geom)
            by_country[admin].append(geom)
    country_geoms = [unary_union(geoms) for geoms in by_country.values() if geoms]
    return state_geoms, lake_geoms, country_geoms


def build_map(product_key, output_path, override_path=None):
    cfg = PRODUCTS[product_key]
    poppins_reg = fm.FontProperties(fname=POPPINS_REG_PATH)
    poppins_semibold = fm.FontProperties(fname=POPPINS_MED_PATH)

    text, fetched_at = fetch_source(cfg, override_path)
    placemarks = cfg["parser"](text)
    if not placemarks:
        sys.exit(f"No placemarks found for '{product_key}' — is the source format as expected?")

    styled = []
    for pm in placemarks:
        sty = cfg["style"](pm)
        if sty is None:
            continue
        polys = [ShPolygon(ring) for ring in pm["rings"]]
        geom = polys[0] if len(polys) == 1 else ShMultiPolygon(polys)
        if not geom.intersects(MAP_BBOX):
            continue  # outside the Western US frame -- drop so it doesn't pad out the legend
        styled.append({**sty, "geom": geom})
    if not styled:
        sys.exit(f"No recognized categories found for '{product_key}' within the map frame.")
    styled.sort(key=lambda d: d["order_key"])

    date_str = cfg["date"](placemarks, fetched_at)
    print(f"Parsed {len(styled)} shaded areas across {len(set(d['label'] for d in styled))} categories. {date_str}")

    print("Loading basemap layers...")
    land_geoms = load_land()
    state_geoms, lake_geoms, country_geoms = load_states_lakes_and_countries()

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

    # Outlook polygons, least to most severe so more severe areas draw on top
    # where categories overlap.
    for i, item in enumerate(styled):
        ax.add_geometries([item["geom"]], crs=pc, facecolor=item["color"], edgecolor=item["color"],
                           linewidth=1.2, alpha=item["alpha"], zorder=3 + i)

    # City labels
    for name, lon, lat, pos in CITIES:
        ax.plot(lon, lat, marker="o", markersize=5.0, color="#3b3a35", zorder=100,
                mec="white", mew=0.7, transform=pc)
        dx = 0.3 if pos == "right" else (-0.3 if pos == "left" else 0)
        dy = 0.38 if pos == "above" else (-0.52 if pos == "below" else 0)
        ha = "left" if pos == "right" else ("right" if pos == "left" else "center")
        va = "bottom" if pos == "above" else ("top" if pos == "below" else "center")
        txt = ax.text(lon + dx, lat + dy, name, fontsize=14.01, fontproperties=poppins_semibold,
                       color="#2b2a26", ha=ha, va=va, zorder=101, transform=pc)
        txt.set_path_effects([pe.withStroke(linewidth=1.65, foreground=(1, 1, 1, 0.6))])

    ax.spines['geo'].set_edgecolor('black')
    ax.spines['geo'].set_linewidth(1.6)

    # Legend — one swatch per distinct label actually present, most severe first
    legend_by_label = {}
    for item in styled:
        legend_by_label.setdefault(item["label"], item)
    ordered = sorted(legend_by_label.values(), key=lambda d: d["order_key"], reverse=True)
    handles = [Patch(facecolor=d["color"], edgecolor=d["color"], alpha=d["alpha"], label=d["label"])
               for d in ordered]
    leg = fig.legend(handles=handles, loc="lower left", frameon=True, fontsize=8.25,
                      prop=poppins_reg, handlelength=1.05, handleheight=1.05, borderpad=0.3,
                      facecolor="white", framealpha=0.7, edgecolor="none",
                      bbox_to_anchor=(0.045, 0.055))
    for text in leg.get_texts():
        text.set_color("#2b2a26")

    # Title & subtitle above the map
    fig.text(0.03, 0.975, cfg["title"], fontsize=22,
              fontproperties=poppins_reg, color="#2b2a26", ha="left", va="top")
    fig.text(0.03, 0.935, f"{cfg['subtitle_prefix']}, {date_str}",
              fontsize=12, fontproperties=poppins_reg, color="#5a584f", ha="left", va="top")

    # Attribution
    fig.text(0.5, 0.012, f"NOAA / {cfg['agency']} — Ingalls Weather", fontsize=9,
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
    parser = argparse.ArgumentParser(description="Build an Ingalls Weather Western U.S. NOAA outlook map.")
    parser.add_argument("--product", choices=sorted(PRODUCTS), default="heat_d8_14",
                         help="Which outlook to render (default: heat_d8_14). See module docstring for the list.")
    parser.add_argument("--file", type=Path, default=None,
                         help="Render from a local KML/KMZ instead of fetching the current one live.")
    parser.add_argument("--out", type=Path, default=None,
                         help="Output PNG path (default: output/<product's default filename>).")
    args = parser.parse_args()

    if args.file and not args.file.exists():
        sys.exit(f"--file {args.file} not found.")

    out_path = args.out or (OUTPUT_DIR / PRODUCTS[args.product]["output"])
    build_map(args.product, out_path, override_path=args.file)

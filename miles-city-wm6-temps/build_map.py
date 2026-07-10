"""
Miles City WM-6 3km High Temps -- map builder
Ingalls Weather

One-off styled map of WindBorne WeatherMesh-6 3km high (daily max) 2m
temperatures over eastern Montana / the western Dakotas, centered on Miles
City, MT, framed from a little west of Helena to a little east of Bismarck.

"High" for a given date is the max hourly 2m temperature between 8am and
8pm local time (America/Denver) -- the daytime window that reliably
contains the daily peak without fetching all 24 hourly grids.

USAGE
-----
    python build_map.py --date 2026-07-12

Requires WB_API_KEY (a WindBorne API token, see
https://app.windbornesystems.com/api_tokens) in the environment to fetch
live gridded forecast data. To render from a previously-saved grid instead
(useful for testing, or to avoid re-fetching ~1 GB of hourly grids), pass
--file path/to/snapshot.npz -- see fetch_daily_high() for the npz layout.

REQUIRES (already checked into /maps at repo root, shared across all
Ingalls Weather map projects):
    states_lakes_slim.json
  Sourced from raw.githubusercontent.com/martynafford/natural-earth-geojson
  (10m), clipped down to North America.

Logo is read from /assets/ingalls_weather_logo.png at repo root.
"""

import argparse
import io
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
from matplotlib.colors import Normalize
from matplotlib.cm import ScalarMappable
import numpy as np
import requests
import jwt
import zarr

import cartopy.crs as ccrs
from shapely.geometry import shape
from shapely.ops import unary_union
from PIL import Image

# ---------------------------------------------------------------------------
# Paths (relative to this script's location: miles-city-wm6-temps/)
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
MAPS_DIR = REPO_ROOT / "maps"
ASSETS_DIR = REPO_ROOT / "assets"
THIS_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = THIS_DIR / "output"

STATES_LAKES_FILE = MAPS_DIR / "states_lakes_slim.json"
LOGO_FILE = ASSETS_DIR / "ingalls_weather_logo.png"

TARGET_COUNTRIES = {"United States of America", "Canada"}

POPPINS_REG_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf"
POPPINS_MED_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf"

# ---------------------------------------------------------------------------
# WindBorne API
# ---------------------------------------------------------------------------
WB_BASE = "https://api.windbornesystems.com/forecasts/v1/wm-6-3km"
LOCAL_TZ = ZoneInfo("America/Denver")
DAY_START_HOUR, DAY_END_HOUR = 8, 20  # local daytime window used for the daily high

# ---------------------------------------------------------------------------
# Figure geometry -- shared by the colorbar (bottom-left) and the logo
# (bottom-right) so both sit the same distance from the map frame's corner.
# ---------------------------------------------------------------------------
FIG_WIDTH_IN, FIG_HEIGHT_IN = 10, 8.9
FIG_DPI = 200
AXES_RECT = [0.035, 0.045, 0.93, 0.855]  # [left, bottom, width, height], figure fraction
MAP_FRAME_INSET_PX = 22

# ---------------------------------------------------------------------------
# Map domain -- centered on Miles City, MT; framed a little west of Helena
# to a little east of Bismarck.
# ---------------------------------------------------------------------------
LON_MIN, LON_MAX = -113.3, -99.3
LAT_MIN, LAT_MAX = 42.7, 50.2
CENTER_LON, CENTER_LAT = -105.8404, 46.4083  # Miles City, MT

CITIES = [
    ("Helena", -112.03, 46.59, "left"),
    ("Great Falls", -111.28, 47.50, "above"),
    ("Bozeman", -111.04, 45.68, "below"),
    ("Sheridan", -106.96, 44.80, "below"),
    ("Billings", -108.50, 45.78, "left"),
    ("Miles City", -105.84, 46.41, "above"),
    ("Glendive", -104.71, 47.11, "right"),
    ("Sidney", -104.16, 47.72, "right"),
    ("Williston", -103.62, 48.15, "left"),
    ("Dickinson", -102.79, 46.88, "below"),
    ("Minot", -101.30, 48.23, "right"),
    ("Bismarck", -100.78, 46.81, "right"),
    ("Rapid City", -103.23, 44.08, "left"),
    ("Pierre", -100.35, 44.37, "below"),
]


def sign_jwt(api_key):
    return jwt.encode({"iat": int(time.time())}, api_key, algorithm="HS256")


def wb_get(path, api_key, **params):
    token = sign_jwt(api_key)
    resp = requests.get(f"{WB_BASE}/{path}", headers={"Authorization": f"Bearer {token}"},
                         params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def local_daytime_valid_times(date):
    """UTC valid times for each local hour in [DAY_START_HOUR, DAY_END_HOUR] on `date`."""
    times = []
    for h in range(DAY_START_HOUR, DAY_END_HOUR + 1):
        local_dt = datetime(date.year, date.month, date.day, h, tzinfo=LOCAL_TZ)
        times.append(local_dt.astimezone(ZoneInfo("UTC")))
    return times


def fetch_daily_high(date, api_key):
    """Fetch hourly temperature_2m grids spanning the local daytime window on
    `date`, crop to the map bbox, and reduce to a max (the daily high).
    Returns (lat_2d, lon_2d, temp_k_2d)."""
    run_info = wb_get("run_information", api_key)
    forecast_zero = datetime.fromisoformat(run_info["forecast_zero"].replace("Z", "+00:00"))
    init_time = run_info["initialization_time"]
    available_hours = {a["forecast_hour"] for a in run_info["available"]}

    valid_times = local_daytime_valid_times(date)
    lat = lon = None
    max_temp_k = None
    r0 = r1 = c0 = c1 = None

    for valid_time in valid_times:
        forecast_hour = round((valid_time - forecast_zero).total_seconds() / 3600)
        if forecast_hour not in available_hours:
            sys.exit(f"Forecast hour {forecast_hour} (valid {valid_time.isoformat()}) "
                      f"is not yet available from run {init_time}. wm-6-3km's horizon "
                      f"may not reach the requested date yet -- try again closer to it.")
        url_info = wb_get("gridded", api_key, variable="all", domain="conus", format="zarr",
                           as_url="true", initialization_time=init_time,
                           forecast_hour=forecast_hour, time=valid_time.strftime("%Y-%m-%dT%H:%M:%SZ"))
        print(f"Fetching forecast hour {forecast_hour} (valid {valid_time.isoformat()}) ...")
        resp = requests.get(url_info["url"], timeout=60)
        resp.raise_for_status()
        store = zarr.storage.ZipStore(io.BytesIO(resp.content), mode="r")
        g = zarr.open(store, mode="r")
        if lat is None:
            lat = g["latitude"][:]
            lon = g["longitude"][:]
            # Pad the crop beyond the plotted extent -- the source grid is
            # curvilinear (rotated relative to lat/lon), so a tight crop can
            # leave slivers of missing data at the corners of the map frame.
            pad = 0.6
            mask = ((lon >= LON_MIN - pad) & (lon <= LON_MAX + pad) &
                    (lat >= LAT_MIN - pad) & (lat <= LAT_MAX + pad))
            rows = np.where(mask.any(axis=1))[0]
            cols = np.where(mask.any(axis=0))[0]
            r0, r1 = rows.min(), rows.max() + 1
            c0, c1 = cols.min(), cols.max() + 1
            lat, lon = lat[r0:r1, c0:c1], lon[r0:r1, c0:c1]
            max_temp_k = np.full(lat.shape, -np.inf, dtype=np.float32)
        max_temp_k = np.maximum(max_temp_k, g["temperature_2m"][r0:r1, c0:c1])
        store.close()

    return lat, lon, max_temp_k


def load_states_lakes_and_countries():
    with open(STATES_LAKES_FILE) as f:
        data = json.load(f)
    state_geoms, lake_geoms = [], []
    by_country = {c: [] for c in TARGET_COUNTRIES}
    for feat in data["features"]:
        props = feat["properties"]
        if "Lake" in props.get("featurecla", ""):
            lake_geoms.append(shape(feat["geometry"]))
            continue
        admin = props.get("admin")
        if admin in TARGET_COUNTRIES:
            geom = shape(feat["geometry"])
            state_geoms.append(geom)
            by_country[admin].append(geom)
    country_geoms = [unary_union(geoms) for geoms in by_country.values() if geoms]
    return state_geoms, lake_geoms, country_geoms


def build_map(date, output_path, override_path=None):
    poppins_reg = fm.FontProperties(fname=POPPINS_REG_PATH)
    poppins_semibold = fm.FontProperties(fname=POPPINS_MED_PATH)

    if override_path:
        print(f"Using local snapshot: {override_path}")
        npz = np.load(override_path)
        lat, lon, temp_k = npz["lat"], npz["lon"], npz["temp_k"]
    else:
        api_key = os.environ.get("WB_API_KEY")
        if not api_key:
            sys.exit("WB_API_KEY not set -- get a token at "
                      "https://app.windbornesystems.com/api_tokens, or pass --file "
                      "to render from a saved snapshot instead.")
        lat, lon, temp_k = fetch_daily_high(date, api_key)

    temp_f = (temp_k - 273.15) * 9 / 5 + 32
    print(f"Daily high range: {temp_f.min():.0f}F - {temp_f.max():.0f}F")

    print("Loading basemap layers...")
    state_geoms, lake_geoms, country_geoms = load_states_lakes_and_countries()

    proj = ccrs.NearsidePerspective(central_longitude=CENTER_LON, central_latitude=CENTER_LAT,
                                     satellite_height=4_000_000)
    pc = ccrs.PlateCarree()

    fig = plt.figure(figsize=(FIG_WIDTH_IN, FIG_HEIGHT_IN), dpi=FIG_DPI)
    fig.patch.set_facecolor("#f7f6f2")

    ax = fig.add_axes(AXES_RECT, projection=proj)
    ax.set_extent([LON_MIN, LON_MAX, LAT_MIN, LAT_MAX], crs=pc)
    ax.patch.set_facecolor("white")

    # Temperature field -- sequential single-hue (warm) ramp, light to dark,
    # scaled to the actual range present so the map uses its full contrast.
    vmin = 5 * np.floor(temp_f.min() / 5)
    vmax = 5 * np.ceil(temp_f.max() / 5)
    ax.pcolormesh(lon, lat, temp_f, transform=pc, cmap="YlOrRd",
                  vmin=vmin, vmax=vmax, shading="auto", zorder=1, alpha=0.92)

    ax.add_geometries(state_geoms, crs=pc, facecolor="none", edgecolor="#5a4632", linewidth=0.8, zorder=2)
    ax.add_geometries(lake_geoms, crs=pc, facecolor="#dce7ef", edgecolor="#5a4632", linewidth=0.7, zorder=2.2)
    ax.add_geometries(country_geoms, crs=pc, facecolor="none", edgecolor="#3a2f21", linewidth=1.1, zorder=2.5)

    # City labels
    for name, lon_c, lat_c, pos in CITIES:
        is_center = name == "Miles City"
        ax.plot(lon_c, lat_c, marker=("*" if is_center else "o"),
                markersize=(13 if is_center else 5.5), color="#2b2a26", zorder=100,
                mec="white", mew=0.8, transform=pc)
        dx = 0.28 if pos == "right" else (-0.28 if pos == "left" else 0)
        dy = 0.30 if pos == "above" else (-0.42 if pos == "below" else 0)
        ha = "left" if pos == "right" else ("right" if pos == "left" else "center")
        va = "bottom" if pos == "above" else ("top" if pos == "below" else "center")
        txt = ax.text(lon_c + dx, lat_c + dy, name,
                       fontsize=15.5 if is_center else 13, fontproperties=poppins_semibold,
                       color="#2b2a26", ha=ha, va=va, zorder=101, transform=pc)
        txt.set_path_effects([pe.withStroke(linewidth=1.8, foreground=(1, 1, 1, 0.75))])

    ax.spines['geo'].set_edgecolor('black')
    ax.spines['geo'].set_linewidth(1.6)

    # Colorbar -- anchored the same MAP_FRAME_INSET_PX from the axes frame's
    # lower-left corner as the logo sits from the frame's lower-right corner.
    fig.canvas.draw()
    frame_px = ax.get_window_extent()
    cbar_left = (frame_px.x0 + MAP_FRAME_INSET_PX) / (FIG_WIDTH_IN * FIG_DPI)
    cbar_bottom = (frame_px.y0 + MAP_FRAME_INSET_PX) / (FIG_HEIGHT_IN * FIG_DPI)
    cbar_width, cbar_height = 0.30, 0.022

    bg_ax = fig.add_axes([cbar_left - 0.012, cbar_bottom - 0.028, cbar_width + 0.024, cbar_height + 0.05],
                          zorder=150)
    bg_ax.set_facecolor("white")
    bg_ax.patch.set_alpha(0.7)
    bg_ax.set_xticks([])
    bg_ax.set_yticks([])
    for spine in bg_ax.spines.values():
        spine.set_visible(False)

    cax = fig.add_axes([cbar_left, cbar_bottom, cbar_width, cbar_height], zorder=151)
    sm = ScalarMappable(norm=Normalize(vmin=vmin, vmax=vmax), cmap="YlOrRd")
    cb = fig.colorbar(sm, cax=cax, orientation="horizontal")
    cb.outline.set_linewidth(0.6)
    cb.outline.set_edgecolor("#8a887e")
    cb.set_ticks(np.arange(vmin, vmax + 1, 10))
    cb.ax.tick_params(labelsize=8.5, color="#8a887e", labelcolor="#2b2a26")
    for label in cb.ax.get_xticklabels():
        label.set_fontproperties(poppins_reg)
    cax.text(0.5, 2.6, "High Temperature (°F)", transform=cax.transAxes, fontsize=8.5,
              fontproperties=poppins_reg, color="#2b2a26", ha="center", va="bottom")

    # Title & subtitle above the map
    date_str = date.strftime("%A, %B %-d, %Y")
    fig.text(0.03, 0.975, f"Miles City Area — {date.strftime('%A')} High Temperatures", fontsize=22,
              fontproperties=poppins_reg, color="#2b2a26", ha="left", va="top")
    fig.text(0.03, 0.935, f"WindBorne WeatherMesh-6 (3 km) — {date_str}, Mountain Time",
              fontsize=12, fontproperties=poppins_reg, color="#5a584f", ha="left", va="top")

    # Attribution
    fig.text(0.5, 0.012, "WindBorne WeatherMesh-6 — Ingalls Weather", fontsize=9,
              fontproperties=poppins_reg, color="#8a887e", ha="center", va="bottom")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, facecolor=fig.get_facecolor(), dpi=200)
    plt.close(fig)
    print(f"Saved base map to {output_path}")

    # ---- Composite logo, bottom-right, snug inside the frame ----
    if LOGO_FILE.exists():
        base = Image.open(output_path).convert("RGB")
        bw, bh = base.size
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

        pos = (frame_right - MAP_FRAME_INSET_PX - target_w, frame_bottom - MAP_FRAME_INSET_PX - target_h)
        base.paste(logo_resized, pos)
        base.save(output_path)
        print(f"Composited logo at {pos}")
    else:
        print(f"NOTE: logo not found at {LOGO_FILE}, skipping (map saved without logo).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build an Ingalls Weather Miles City WM-6 3km high-temp map.")
    parser.add_argument("--date", type=str, default=None,
                         help="Target date, YYYY-MM-DD (default: the coming Sunday).")
    parser.add_argument("--file", type=Path, default=None,
                         help="Render from a local saved grid (.npz with lat/lon/temp_k) "
                              "instead of fetching live.")
    parser.add_argument("--out", type=Path, default=None,
                         help="Output PNG path (default: output/miles_city_wm6_highs_<date>.png).")
    args = parser.parse_args()

    if args.file and not args.file.exists():
        sys.exit(f"--file {args.file} not found.")

    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        today = datetime.now(LOCAL_TZ).date()
        days_ahead = (6 - today.weekday()) % 7 or 7  # next Sunday, weekday(): Mon=0..Sun=6
        target_date = today + timedelta(days=days_ahead)

    out_path = args.out or (OUTPUT_DIR / f"miles_city_wm6_highs_{target_date.isoformat()}.png")
    build_map(target_date, out_path, override_path=args.file)

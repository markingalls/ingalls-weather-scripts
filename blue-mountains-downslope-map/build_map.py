"""
Blue Mountains Downslope Wind Map -- RTMA temperature + wind streamlines
Ingalls Weather

Styled map of the latest NOAA RTMA (Real-Time Mesoscale Analysis, 2.5 km)
2m temperature over the Tri-Cities / Walla Walla / Umatilla Basin, with
10m wind streamlines and Blue Mountains terrain contours drawn on top --
built to show downslope (downsloping/foehn-type) flow off the Blues
mixing warmer air down into Pendleton and Hermiston while the Tri-Cities
and Walla Walla stay stuck in the basin cold pool.

Temperature uses the same fixed Kelvin-to-RGB color table as
../columbia-basin-temps/build_map.py (TEMP_COLOR_TABLE), so a given shade
means the same absolute temperature here as on every other Ingalls Weather
temperature map.

USAGE
-----
    python build_map.py                              # latest available RTMA hour
    python build_map.py --time "2026-11-18 15:00"    # a specific analysis hour (UTC)
    python build_map.py --title "Downslope Winds Off the Blues"

No API key needed -- Herbie pulls RTMA's GRIB2 from NOAA's AWS Open Data
bucket (noaa-rtma-pds) via byte-range requests, so only the TMP/WIND/WDIR/
HGT records are downloaded.

Wind is built from RTMA's WIND (speed) + WDIR (true-north meteorological
direction) records, not UGRD/VGRD: RTMA's U/V are grid-relative to its
Lambert conformal grid (rotated ~10 deg here vs true north), whereas WDIR
is earth-relative.

Shared basemap data in /maps and the logo in /assets at repo root, same as
../columbia-basin-temps/.
"""

import argparse
import json
import sys
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

warnings.filterwarnings("ignore", message="In a future version of xarray.*compat", category=FutureWarning)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
from matplotlib.colors import Normalize, LinearSegmentedColormap
from matplotlib.transforms import offset_copy
import numpy as np
from scipy.interpolate import griddata
from scipy.ndimage import gaussian_filter
from herbie import Herbie

import cartopy.crs as ccrs
from shapely.geometry import shape
from PIL import Image

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
MAPS_DIR = REPO_ROOT / "maps"
ASSETS_DIR = REPO_ROOT / "assets"
THIS_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = THIS_DIR / "output"

ADMIN1_LINES_FILE = MAPS_DIR / "admin1_boundary_lines.json"
ROAD_FILES = ["washington_roads.geojson", "oregon_roads.geojson"]
LOGO_FILE = ASSETS_DIR / "ingalls_weather_logo.png"

MOTORWAY_TYPES = {"motorway", "motorway_link"}
TRUNK_TYPES = {"trunk", "trunk_link"}
MOTORWAY_COLOR = "#8FB8E0"  # pastel blue
TRUNK_COLOR = "#F2B880"     # pastel orange

POPPINS_REG_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf"
POPPINS_MED_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf"

LOCAL_TZ = ZoneInfo("America/Los_Angeles")

# ---------------------------------------------------------------------------
# Figure geometry -- same canvas/layout as ../columbia-basin-temps/.
# ---------------------------------------------------------------------------
FIG_WIDTH_IN, FIG_HEIGHT_IN = 10, 8.9
FIG_DPI = 200
AXES_RECT = [0.035, 0.15, 0.93, 0.75]
MAP_FRAME_INSET_PX = 22

# ---------------------------------------------------------------------------
# Map domain -- zoomed in on the Tri-Cities, Walla Walla Valley, Umatilla
# Basin, and the northern Blue Mountains rising to the east/southeast.
# ---------------------------------------------------------------------------
LON_MIN, LON_MAX = -120.15, -117.35
LAT_MIN, LAT_MAX = 45.05, 46.65
CENTER_LON, CENTER_LAT = (LON_MIN + LON_MAX) / 2, (LAT_MIN + LAT_MAX) / 2

FETCH_PAD_DEG = 0.6
RESAMPLE_PAD_DEG = 0.3
RESAMPLE_NX, RESAMPLE_NY = 520, 400   # ~0.5 km -- finer than RTMA's 2.5 km
RESAMPLE_LON_MIN, RESAMPLE_LON_MAX = LON_MIN - RESAMPLE_PAD_DEG, LON_MAX + RESAMPLE_PAD_DEG
RESAMPLE_LAT_MIN, RESAMPLE_LAT_MAX = LAT_MIN - RESAMPLE_PAD_DEG, LAT_MAX + RESAMPLE_PAD_DEG

# Streamlines are computed on a coarser regular grid (RTMA's wind field is
# noisy at full res) after light smoothing, so they read as flow, not static.
STREAM_NX, STREAM_NY = 140, 100
STREAM_SMOOTH_SIGMA = 1.2  # in STREAM grid cells
STREAM_DENSITY = (1.35, 1.05)
# Streamlines are only drawn where the (smoothed) wind is at least this
# fast -- calm/light-and-variable areas (e.g. the cold pool) stay clean.
STREAM_MIN_MPH = 3.0

# Terrain contours (ft) to show where the Blue Mountains rise.
TERRAIN_CONTOURS_FT = [2000, 3000, 4000, 5000, 6000]

CITIES = [
    ("Richland", -119.2845, 46.2856, "left"),
    ("Pasco", -119.1006, 46.2396, "right"),
    ("Kennewick", -119.1372, 46.2112, "left"),
    ("Walla Walla", -118.3430, 46.0646, "right"),
    ("Dayton", -117.9762, 46.3212, "right"),
    ("Milton-Freewater", -118.3880, 45.9326, "right"),
    ("Umatilla", -119.3411, 45.9174, "left"),
    ("Hermiston", -119.2895, 45.8404, "right"),
    ("Boardman", -119.7006, 45.8393, "left"),
    ("Pendleton", -118.7879, 45.6721, "right"),
    ("Heppner", -119.5528, 45.3554, "right"),
    ("Meacham", -118.4220, 45.5110, "right"),
    ("La Grande", -118.0877, 45.3246, "right"),
    ("Prosser", -119.7686, 46.2532, "left"),
]

# ---------------------------------------------------------------------------
# Preferred Ingalls Weather temperature color table -- identical to
# TEMP_COLOR_TABLE in ../columbia-basin-temps/build_map.py. Fixed (K, RGB)
# control points, never rescaled per map.
# ---------------------------------------------------------------------------
TEMP_COLOR_TABLE = [
    (205.53962824635747, [20, 1, 11]),
    (220.54105933801642, [72, 2, 42]),
    (223.30970412365585, [114, 5, 69]),
    (226.07834890929527, [156, 7, 95]),
    (228.8469936949347, [190, 31, 133]),
    (231.61563848057412, [216, 33, 184]),
    (234.38428326621354, [224, 94, 226]),
    (237.15292805185297, [208, 143, 208]),
    (239.9215728374924, [198, 174, 206]),
    (242.71111221757047, [177, 149, 200]),
    (245.48274194527255, [153, 122, 186]),
    (248.25437167297463, [120, 90, 160]),
    (251.02600140067673, [95, 67, 136]),
    (253.7976311283788, [75, 44, 128]),
    (256.5692608560809, [52, 34, 130]),
    (259.2740222360249, [44, 54, 150]),
    (262.11252031148507, [62, 73, 174]),
    (264.88415003918715, [79, 90, 198]),
    (267.13811875987665, [90, 128, 206]),
    (269.1251668409579, [100, 165, 214]),
    (271.1122149220392, [94, 194, 212]),
    (273.0992630031204, [40, 142, 160]),
    (275.0863110842017, [24, 105, 120]),
    (279.0604072463642, [28, 108, 79]),
    (283.03450340852675, [39, 132, 85]),
    (286.97216346781227, [60, 150, 83]),
    (289.741977590991, [112, 172, 91]),
    (292.5117917141697, [159, 190, 91]),
    (295.2816058373485, [208, 200, 84]),
    (298.0514199605272, [204, 172, 70]),
    (300.8212340837059, [212, 146, 61]),
    (303.5910482068847, [218, 121, 35]),
    (306.3608623300634, [208, 90, 31]),
    (309.13067645324213, [216, 59, 32]),
    (311.9004905764209, [182, 32, 7]),
    (314.6703046995996, [142, 36, 19]),
    (317.44011882277835, [102, 23, 10]),
    (320.20993294595706, [142, 15, 54]),
    (322.9797470691358, [194, 50, 94]),
    (325.74956119231456, [216, 120, 149]),
    (332.71070543555834, [204, 16, 171]),
]
TEMP_KMIN = TEMP_COLOR_TABLE[0][0]
TEMP_KMAX = TEMP_COLOR_TABLE[-1][0]


def build_temp_colormap():
    span = TEMP_KMAX - TEMP_KMIN
    stops = [((k - TEMP_KMIN) / span, [c / 255 for c in rgb]) for k, rgb in TEMP_COLOR_TABLE]
    return LinearSegmentedColormap.from_list("ingalls_temp", stops, N=256)


def f_to_k(f):
    return (f - 32) * 5 / 9 + 273.15


def k_to_f(k):
    return (k - 273.15) * 9 / 5 + 32


def f_to_c(f):
    return (f - 32) * 5 / 9


def c_to_f(c):
    return c * 9 / 5 + 32


# ---------------------------------------------------------------------------
# RTMA fetch
# ---------------------------------------------------------------------------
RTMA_SEARCH = ":(TMP:2 m above ground|WIND:10 m above ground|WDIR:10 m above ground|HGT:surface):"


def select_rtma_hour(requested=None):
    """Most recent hourly RTMA analysis posted to AWS (or the requested one)."""
    if requested:
        H = Herbie(requested, model="rtma", product="anl", verbose=False)
        if H.grib is None:
            sys.exit(f"RTMA analysis for {requested:%Y-%m-%d %H}z not found on AWS.")
        return requested
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0, tzinfo=None)
    for lookback in range(6):
        candidate = now - timedelta(hours=lookback)
        if Herbie(candidate, model="rtma", product="anl", verbose=False).grib is not None:
            return candidate
    sys.exit("Could not find a recent RTMA analysis on AWS.")


def fetch_rtma(valid):
    """Returns cropped (lat, lon, temp_k, u_ms, v_ms, hgt_m) on RTMA's native
    2.5 km grid. u/v are earth-relative, derived from WIND + WDIR."""
    print(f"Fetching RTMA {valid:%Y-%m-%d %H}z ...")
    ds = Herbie(valid, model="rtma", product="anl", verbose=False).xarray(RTMA_SEARCH)
    if isinstance(ds, list):
        import xarray as xr
        ds = xr.merge(ds, compat="override")
    lat_full = ds.latitude.values
    lon_full = np.where(ds.longitude.values > 180, ds.longitude.values - 360, ds.longitude.values)
    mask = ((lon_full >= LON_MIN - FETCH_PAD_DEG) & (lon_full <= LON_MAX + FETCH_PAD_DEG) &
            (lat_full >= LAT_MIN - FETCH_PAD_DEG) & (lat_full <= LAT_MAX + FETCH_PAD_DEG))
    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    sl = (slice(rows.min(), rows.max() + 1), slice(cols.min(), cols.max() + 1))
    speed = ds["si10"].values[sl]
    wdir = np.radians(ds["wdir10"].values[sl])
    u = -speed * np.sin(wdir)   # meteorological "from" direction -> toward-vector
    v = -speed * np.cos(wdir)
    return lat_full[sl], lon_full[sl], ds["t2m"].values[sl], u, v, ds["orog"].values[sl]


def resample(lat, lon, values, nx, ny):
    reg_lon = np.linspace(RESAMPLE_LON_MIN, RESAMPLE_LON_MAX, nx)
    reg_lat = np.linspace(RESAMPLE_LAT_MIN, RESAMPLE_LAT_MAX, ny)
    glon, glat = np.meshgrid(reg_lon, reg_lat)
    points = np.column_stack([lon.ravel(), lat.ravel()])
    out = griddata(points, values.ravel(), (glon, glat), method="linear")
    nan = np.isnan(out)
    if nan.any():
        out[nan] = griddata(points, values.ravel(), (glon[nan], glat[nan]), method="nearest")
    return reg_lon, reg_lat, out


def sample_native(lat, lon, values, lon_pt, lat_pt):
    """Nearest native RTMA grid point to a city -- no interpolation."""
    d = (lat - lat_pt) ** 2 + ((lon - lon_pt) * np.cos(np.radians(lat_pt))) ** 2
    return values[np.unravel_index(d.argmin(), d.shape)]


def compass(deg):
    pts = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return pts[int((deg % 360) / 22.5 + 0.5) % 16]


# ---------------------------------------------------------------------------
# Basemap
# ---------------------------------------------------------------------------
def load_boundary_lines(path):
    with open(path) as f:
        data = json.load(f)
    return [shape(feat["geometry"]) for feat in data["features"]]


def load_roads():
    motorway_geoms, trunk_geoms = [], []
    for region_file in ROAD_FILES:
        with open(MAPS_DIR / region_file) as f:
            data = json.load(f)
        for feat in data["features"]:
            hwy = feat["properties"].get("highway")
            if hwy in MOTORWAY_TYPES:
                motorway_geoms.append(shape(feat["geometry"]))
            elif hwy in TRUNK_TYPES:
                trunk_geoms.append(shape(feat["geometry"]))
    return motorway_geoms, trunk_geoms


def build_map(valid, title, output_path):
    poppins_reg = fm.FontProperties(fname=POPPINS_REG_PATH)
    poppins_semibold = fm.FontProperties(fname=POPPINS_MED_PATH)

    lat, lon, temp_k_native, u_native, v_native, hgt_native = fetch_rtma(valid)

    print("Resampling onto regular grids...")
    _, _, temp_k = resample(lat, lon, temp_k_native, RESAMPLE_NX, RESAMPLE_NY)
    t_lon, t_lat, hgt_ft = resample(lat, lon, hgt_native * 3.28084, RESAMPLE_NX, RESAMPLE_NY)
    s_lon, s_lat, u = resample(lat, lon, u_native, STREAM_NX, STREAM_NY)
    _, _, v = resample(lat, lon, v_native, STREAM_NX, STREAM_NY)
    u = gaussian_filter(u, STREAM_SMOOTH_SIGMA)
    v = gaussian_filter(v, STREAM_SMOOTH_SIGMA)
    speed_mph = np.hypot(u, v) * 2.23694

    in_view = ((lon >= LON_MIN) & (lon <= LON_MAX) & (lat >= LAT_MIN) & (lat <= LAT_MAX))
    visible_f = k_to_f(temp_k_native[in_view])
    print(f"Visible range: {visible_f.min():.0f}F - {visible_f.max():.0f}F")

    print("City readout (nearest RTMA grid point):")
    city_vals = {}
    for name, lon_c, lat_c, _ in CITIES:
        tf = k_to_f(sample_native(lat, lon, temp_k_native, lon_c, lat_c))
        uu = sample_native(lat, lon, u_native, lon_c, lat_c)
        vv = sample_native(lat, lon, v_native, lon_c, lat_c)
        spd = np.hypot(uu, vv) * 2.23694
        frm = (np.degrees(np.arctan2(-uu, -vv)) + 360) % 360
        elev = sample_native(lat, lon, hgt_native, lon_c, lat_c) * 3.28084
        city_vals[name] = tf
        print(f"  {name:17s} {tf:5.1f}F  {compass(frm):>3s} {spd:4.1f} mph  ({elev:,.0f} ft)")

    print("Loading basemap layers...")
    admin1_lines = load_boundary_lines(ADMIN1_LINES_FILE)
    motorway_geoms, trunk_geoms = load_roads()

    proj = ccrs.NearsidePerspective(central_longitude=CENTER_LON, central_latitude=CENTER_LAT,
                                     satellite_height=4_000_000)
    pc = ccrs.PlateCarree()

    fig = plt.figure(figsize=(FIG_WIDTH_IN, FIG_HEIGHT_IN), dpi=FIG_DPI)
    fig.patch.set_facecolor("#f7f6f2")
    ax = fig.add_axes(AXES_RECT, projection=proj)
    ax.set_extent([LON_MIN, LON_MAX, LAT_MIN, LAT_MAX], crs=pc)
    ax.patch.set_facecolor("white")

    # Temperature -- fixed Kelvin color table, imshow (see columbia-basin-temps
    # README for why imshow + a padded resample grid rather than pcolormesh).
    temp_cmap = build_temp_colormap()
    temp_norm = Normalize(vmin=TEMP_KMIN, vmax=TEMP_KMAX)
    ax.imshow(temp_k, transform=pc, cmap=temp_cmap, norm=temp_norm, origin="lower",
              extent=[RESAMPLE_LON_MIN, RESAMPLE_LON_MAX, RESAMPLE_LAT_MIN, RESAMPLE_LAT_MAX],
              interpolation="bilinear", zorder=1)

    # Terrain contours -- thin, translucent, so the Blues read as relief
    # without fighting the temperature colors.
    ax.contour(t_lon, t_lat, gaussian_filter(hgt_ft, 2), levels=TERRAIN_CONTOURS_FT, transform=pc,
               colors=[(0.12, 0.10, 0.08, 0.38)], linewidths=0.55, zorder=1.4)

    ax.add_geometries(admin1_lines, crs=pc, facecolor="none", edgecolor="#5a4632", linewidth=0.9, zorder=2)
    ax.add_geometries(trunk_geoms, crs=pc, facecolor="none", edgecolor=TRUNK_COLOR, linewidth=1.1, zorder=2.6)
    ax.add_geometries(motorway_geoms, crs=pc, facecolor="none", edgecolor=MOTORWAY_COLOR, linewidth=1.3, zorder=2.7)

    # Wind streamlines. Cartopy treats PlateCarree vectors as d(lon), d(lat)
    # rates, so the eastward component is scaled by 1/cos(lat) to keep true
    # compass direction once projected. Line width scales with speed.
    s_lon2d, s_lat2d = np.meshgrid(s_lon, s_lat)
    lw = 0.45 + 1.6 * np.clip(speed_mph / 18, 0, 1)
    # NaN out light-wind cells: matplotlib's streamplot treats non-finite
    # vectors as masked, so a streamline stops where it enters one.
    calm = speed_mph < STREAM_MIN_MPH
    u_plot = np.where(calm, np.nan, u / np.cos(np.radians(s_lat2d)))
    v_plot = np.where(calm, np.nan, v)
    strm = ax.streamplot(s_lon2d, s_lat2d, u_plot, v_plot, transform=pc,
                         density=STREAM_DENSITY, color=(1, 1, 1, 0.9), linewidth=lw,
                         arrowsize=1.0, arrowstyle="-|>", minlength=0.15, maxlength=3.0, zorder=3)
    halo = [pe.withStroke(linewidth=2.2, foreground=(0, 0, 0, 0.35))]
    strm.lines.set_path_effects(halo)

    # City labels
    geodetic_transform = pc._as_mpl_transform(ax)
    stroke = [pe.withStroke(linewidth=1.5, foreground=(0, 0, 0, 0.8))]
    for name, lon_c, lat_c, pos in CITIES:
        ax.plot(lon_c, lat_c, marker="o", markersize=5.0, color="white", zorder=100,
                mec="black", mew=0.8, transform=pc)
        dx_pt = 6 if pos == "right" else -6
        ha = "left" if pos == "right" else "right"
        t1 = ax.text(lon_c, lat_c, name, fontsize=9.75, fontproperties=poppins_semibold, color="white",
                     ha=ha, va="center", zorder=101,
                     transform=offset_copy(geodetic_transform, fig=fig, x=dx_pt, y=0, units="points"))
        t1.set_path_effects(stroke)
        t2 = ax.text(lon_c, lat_c, f"{city_vals[name]:.0f}°F", fontsize=9.75, fontproperties=poppins_semibold,
                     color="white", ha=ha, va="top", zorder=101,
                     transform=offset_copy(geodetic_transform, fig=fig, x=dx_pt, y=-4, units="points"))
        t2.set_path_effects(stroke)

    ax.spines['geo'].set_edgecolor('black')
    ax.spines['geo'].set_linewidth(1.6)

    # Colorbar -- same construction as columbia-basin-temps.
    fig.canvas.draw()
    frame_px = ax.get_window_extent()
    frame_left = frame_px.x0 / (FIG_WIDTH_IN * FIG_DPI)
    frame_right = frame_px.x1 / (FIG_WIDTH_IN * FIG_DPI)
    cbar_width, cbar_height = (frame_right - frame_left) * 0.55, 0.022
    cbar_left = (frame_left + frame_right) / 2 - cbar_width / 2
    vmin_disp = 5 * np.floor(visible_f.min() / 5)
    vmax_disp = 5 * np.ceil(visible_f.max() / 5)
    gradient_k = f_to_k(np.linspace(vmin_disp, vmax_disp, 256)).reshape(1, -1)
    cax = fig.add_axes([cbar_left, 0.085, cbar_width, cbar_height])
    cax.imshow(gradient_k, aspect="auto", cmap=temp_cmap, norm=temp_norm, extent=[vmin_disp, vmax_disp, 0, 1])
    cax.set_yticks([])
    for spine in cax.spines.values():
        spine.set_edgecolor("#8a887e")
        spine.set_linewidth(0.6)
    step = 5 if vmax_disp - vmin_disp <= 40 else 10
    f_ticks = [f for f in range(-100, 151, step) if vmin_disp <= f <= vmax_disp]
    cax.set_xticks(f_ticks)
    cax.set_xticklabels([f"{f}°F" for f in f_ticks])
    cax.tick_params(labelsize=8.5, color="#8a887e", labelcolor="#2b2a26")
    for label in cax.get_xticklabels():
        label.set_fontproperties(poppins_reg)
    cax_c = cax.secondary_xaxis("top", functions=(f_to_c, c_to_f))
    c_lo, c_hi = f_to_c(vmin_disp), f_to_c(vmax_disp)
    cax_c.set_xticks([c for c in range(-50, 61, 5 if c_hi - c_lo > 12 else 2) if c_lo <= c <= c_hi])
    cax_c.xaxis.set_major_formatter(lambda c, _: f"{c:.0f}°C")
    cax_c.tick_params(labelsize=8.5, color="#8a887e", labelcolor="#2b2a26")
    for label in cax_c.get_xticklabels():
        label.set_fontproperties(poppins_reg)

    # Title / subtitle
    valid_local = valid.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ)
    h12 = valid_local.hour % 12 or 12
    ampm = "am" if valid_local.hour < 12 else "pm"
    when = f"{valid_local:%A} {h12}{ampm} {valid_local.tzname()}"
    fig.text(0.03, 0.975, title, fontsize=22, fontproperties=poppins_reg, color="#2b2a26", ha="left", va="top")
    fig.text(0.03, 0.935, f"NOAA RTMA 2.5 km • Temperature & 10 m wind streamlines • {when}",
             fontsize=12, fontproperties=poppins_reg, color="#5a584f", ha="left", va="top")
    fig.text(0.5, 0.012, "NOAA RTMA 2.5 km analysis — terrain contours every 1,000 ft — Ingalls Weather",
             fontsize=9, fontproperties=poppins_reg, color="#8a887e", ha="center", va="bottom")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, facecolor=fig.get_facecolor(), dpi=FIG_DPI)
    plt.close(fig)
    print(f"Saved base map to {output_path}")

    # Logo, bottom-right inside the frame (same approach as columbia-basin-temps).
    if LOGO_FILE.exists():
        base = Image.open(output_path).convert("RGB")
        bw, bh = base.size
        arr = np.array(base)
        y = bh // 2
        black_cols = [x for x in range(bw) if (arr[y, x] < 40).all()]
        x = bw // 2
        black_rows = [yy for yy in range(bh) if (arr[yy, x] < 40).all()]
        fr = max(black_cols) if black_cols else bw - 20
        fb = max(black_rows) if black_rows else bh - 20
        logo = Image.open(LOGO_FILE).convert("RGB")
        target_w = int(bw * 0.08)
        target_h = int(logo.height * target_w / logo.width)
        base.paste(logo.resize((target_w, target_h), Image.LANCZOS),
                   (fr - MAP_FRAME_INSET_PX - target_w, fb - MAP_FRAME_INSET_PX - target_h))
        base.save(output_path)
    else:
        print(f"NOTE: logo not found at {LOGO_FILE}, skipping.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RTMA temperature + wind streamline map, Blue Mountains downslope.")
    parser.add_argument("--time", type=str, default=None,
                        help='RTMA analysis hour, UTC, "YYYY-MM-DD HH:00" (default: latest available).')
    parser.add_argument("--title", type=str, default="Downslope Winds Warm Pendleton & Hermiston",
                        help="Map title.")
    parser.add_argument("--out", type=Path, default=None, help="Output PNG path.")
    args = parser.parse_args()

    requested = datetime.strptime(args.time, "%Y-%m-%d %H:%M") if args.time else None
    valid = select_rtma_hour(requested)
    out = args.out or OUTPUT_DIR / f"blue_mountains_downslope_rtma_{valid:%Y%m%d_%H}z.png"
    build_map(valid, args.title, out)

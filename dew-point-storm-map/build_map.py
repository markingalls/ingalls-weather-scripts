"""
BC / WA / OR / ID Dew Point Depression + Thunderstorm Map -- one-off builder
Ingalls Weather

Styled map covering British Columbia, Washington, Oregon, and Idaho:
  - Shading: today's maximum dew point depression (2m temperature minus 2m
    dewpoint), sampled across the local day from ECMWF IFS.
  - Outline: a dashed red contour around where ECMWF IFS's own fields flag
    likely thunderstorms today.

ECMWF's free Open Data distribution (what Herbie pulls IFS from) has no
single "thunderstorm" field -- no lightning/thunder flag (ECMWF's own
"Instantaneous total lightning flash density" parameter, litoti, exists
only in the paid MARS archive, not Open Data -- checked directly against
today's oper/enfo/aifs index files, no lit* param in any of them). The
outline is therefore a proxy: a grid cell is flagged for any 3-hourly
window today where most-unstable CAPE (mucape) reaches
MUCAPE_THRESHOLD_JKG, i.e. the airmass is unstable enough to support
convection. The threshold is tuned low (150 J/kg by default) for the
Pacific Northwest/BC interior's generally modest summertime instability,
not Great Plains-scale severe setups -- and since this is CAPE alone (no
precipitation check), it flags convective *potential*, not confirmation
that a storm actually fired. Treat the outline as "where ECMWF's fields
are consistent with thunderstorms," not an official convective outlook.

USAGE
-----
    python build_map.py                        # today, BC/WA/OR/ID
    python build_map.py --date 2026-07-16
    python build_map.py --file snapshot.npz     # render from a saved fetch

REQUIRES (already checked into /maps at repo root, shared across all
Ingalls Weather map projects):
    land_slim.json, states_lakes_slim.json, admin1_boundary_lines.json,
    admin0_boundary_lines.json
  Sourced from raw.githubusercontent.com/martynafford/natural-earth-geojson
  (10m), already clipped to US/Canada/Mexico -- includes British Columbia.

Logo is read from /assets/ingalls_weather_logo.png at repo root.
"""

import argparse
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
from matplotlib.lines import Line2D
from matplotlib.transforms import offset_copy
import numpy as np
from scipy.interpolate import griddata
from scipy.ndimage import gaussian_filter
from herbie import Herbie

import cartopy.crs as ccrs
import json
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

LAND_FILE = MAPS_DIR / "land_slim.json"
STATES_LAKES_FILE = MAPS_DIR / "states_lakes_slim.json"
ADMIN0_LINES_FILE = MAPS_DIR / "admin0_boundary_lines.json"
LOGO_FILE = ASSETS_DIR / "ingalls_weather_logo.png"

TARGET_COUNTRIES = {"United States of America", "Canada"}

POPPINS_REG_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf"
POPPINS_MED_PATH = "/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf"

LOCAL_TZ = ZoneInfo("America/Los_Angeles")

# ---------------------------------------------------------------------------
# Figure geometry
# ---------------------------------------------------------------------------
FIG_WIDTH_IN, FIG_HEIGHT_IN = 11.0, 9.0
FIG_DPI = 200
AXES_RECT = [0.03, 0.14, 0.94, 0.73]  # [left, bottom, width, height], figure fraction
MAP_FRAME_INSET_PX = 22

# ---------------------------------------------------------------------------
# Map domain -- bounding box of BC + WA + OR + ID, padded slightly.
# ---------------------------------------------------------------------------
LON_MIN, LON_MAX = -140.0, -110.5
LAT_MIN, LAT_MAX = 41.5, 60.5
CENTER_LON, CENTER_LAT = -123.5, 51.3

FETCH_PAD_DEG = 2.0
RESAMPLE_NX, RESAMPLE_NY = 460, 560
RESAMPLE_PAD_DEG = 1.5
RESAMPLE_LON_MIN, RESAMPLE_LON_MAX = LON_MIN - RESAMPLE_PAD_DEG, LON_MAX + RESAMPLE_PAD_DEG
RESAMPLE_LAT_MIN, RESAMPLE_LAT_MAX = LAT_MIN - RESAMPLE_PAD_DEG, LAT_MAX + RESAMPLE_PAD_DEG

# ---------------------------------------------------------------------------
# ECMWF IFS (Open Data, via Herbie) -- 0.25 deg, 3-hourly steps.
# ---------------------------------------------------------------------------
STEP_HOURS = 3

# Thunderstorm proxy threshold (see module docstring).
MUCAPE_THRESHOLD_JKG = 150.0

CITIES = [
    ("Vancouver", -123.1207, 49.2827, "left"),
    ("Victoria", -123.3656, 48.4284, "left"),
    ("Kelowna", -119.4960, 49.8880, "right"),
    ("Kamloops", -120.3273, 50.6745, "right"),
    ("Prince George", -122.7497, 53.9171, "right"),
    ("Nelson", -117.2948, 49.4928, "right"),
    ("Cranbrook", -115.7697, 49.5097, "right"),
    ("Williams Lake", -122.1417, 52.1417, "left"),
    ("Whistler", -122.9574, 50.1163, "left"),
    ("Seattle", -122.3321, 47.6062, "left"),
    ("Spokane", -117.4260, 47.6588, "left"),
    ("Tacoma", -122.4443, 47.2529, "left"),
    ("Wenatchee", -120.3103, 47.4235, "right"),
    ("Yakima", -120.5059, 46.6021, "right"),
    ("Walla Walla", -118.3430, 46.0646, "right"),
    ("Portland", -122.6784, 45.5152, "left"),
    ("Bend", -121.3153, 44.0582, "left"),
    ("Eugene", -123.0868, 44.0521, "left"),
    ("Medford", -122.8756, 42.3265, "left"),
    ("Pendleton", -118.7879, 45.6721, "right"),
    ("Boise", -116.2023, 43.6150, "left"),
    ("Coeur d'Alene", -116.7805, 47.6777, "right"),
    ("Lewiston", -117.0177, 46.4165, "right"),
    ("Twin Falls", -114.4609, 42.5629, "left"),
]

# ---------------------------------------------------------------------------
# Dew point depression color table -- fixed Fahrenheit-to-RGB control points
# (not rescaled per map), running from near-saturated (blue/teal) through
# green/yellow (comfortable) to orange/red/maroon (very dry -- the fire-
# weather-relevant end of the scale).
# ---------------------------------------------------------------------------
DPD_COLOR_TABLE_F = [
    (0,   [8, 48, 107]),
    (5,   [33, 102, 172]),
    (10,  [67, 147, 195]),
    (15,  [146, 197, 222]),
    (20,  [199, 233, 192]),
    (25,  [161, 217, 155]),
    (30,  [116, 196, 118]),
    (35,  [255, 255, 191]),
    (40,  [254, 217, 118]),
    (45,  [254, 178, 76]),
    (50,  [253, 141, 60]),
    (55,  [252, 78, 42]),
    (60,  [227, 26, 28]),
    (70,  [177, 0, 38]),
    (80,  [128, 0, 38]),
    (100, [73, 0, 46]),
]
DPD_FMIN = DPD_COLOR_TABLE_F[0][0]
DPD_FMAX = DPD_COLOR_TABLE_F[-1][0]


def build_dpd_colormap():
    span = DPD_FMAX - DPD_FMIN
    stops = [((f - DPD_FMIN) / span, [c / 255 for c in rgb]) for f, rgb in DPD_COLOR_TABLE_F]
    return LinearSegmentedColormap.from_list("ingalls_dpd", stops, N=256)


def k_diff_to_f(dk):
    """Convert a temperature *difference* (Kelvin/Celsius) to Fahrenheit --
    no +32 offset, since a delta scales directly by 9/5."""
    return dk * 9 / 5


# ---------------------------------------------------------------------------
# ECMWF IFS run selection / step snapping (same approach as
# ../columbia-basin-temps/build_map.py's fetch_ecmwf helpers).
# ---------------------------------------------------------------------------
def local_window_valid_times(date, start_hour, end_hour):
    times = []
    for h in range(start_hour, end_hour + 1):
        local_dt = datetime(date.year, date.month, date.day, h, tzinfo=LOCAL_TZ)
        times.append(local_dt.astimezone(ZoneInfo("UTC")))
    return times


def select_ecmwf_run(valid_times):
    now = datetime.now(timezone.utc)
    latest_cycle = now.replace(hour=(now.hour // 6) * 6, minute=0, second=0, microsecond=0)
    for lookback_cycles in range(40):
        candidate = latest_cycle - timedelta(hours=6 * lookback_cycles)
        fxxs = [round((vt - candidate).total_seconds() / 3600) for vt in valid_times]
        if min(fxxs) < 0:
            continue
        test_fxx = int(round(min(fxxs) / STEP_HOURS) * STEP_HOURS)
        if Herbie(candidate.replace(tzinfo=None), model="ifs", product="oper", fxx=test_fxx, verbose=False).grib is not None:
            return candidate
    sys.exit("Could not find an ECMWF IFS run covering the requested date.")


def snap_fxx_list(valid_times, run_init):
    fxxs = set()
    for vt in valid_times:
        raw_hours = (vt - run_init).total_seconds() / 3600
        fxxs.add(max(int(round(raw_hours / STEP_HOURS)) * STEP_HOURS, 0))
    return sorted(fxxs)


def fetch_day(date):
    """Fetch ECMWF IFS 2t/2d/mucape across today's local-hour steps,
    cropped to the map bbox. Returns (lat_2d, lon_2d, dpd_k_max_2d,
    storm_mask_2d, run_init)."""
    valid_times = local_window_valid_times(date, 0, 23)
    run_init = select_ecmwf_run(valid_times)
    fxxs = snap_fxx_list(valid_times, run_init)

    lat = lon = None
    dpd_max_k = None
    storm_mask = None

    for fxx in fxxs:
        print(f"Fetching ECMWF IFS {run_init:%Y-%m-%d %H}z F{fxx:03d} (2t, 2d, mucape) ...")
        H = Herbie(run_init.replace(tzinfo=None), model="ifs", product="oper", fxx=fxx, verbose=False)
        # Anchored on colons -- Herbie's plain-substring search would also
        # match e.g. "mx2t3"/"mn2t3" against "2t", or return multiple
        # messages at fxx=0.
        ds_t = H.xarray(":2t:")
        ds_d = H.xarray(":2d:")
        ds_cape = H.xarray(":mucape:")

        if lat is None:
            lat_1d, lon_1d = ds_t.latitude.values, ds_t.longitude.values
            lon_1d = np.where(lon_1d > 180, lon_1d - 360, lon_1d)
            lat_idx = np.where((lat_1d >= LAT_MIN - FETCH_PAD_DEG) & (lat_1d <= LAT_MAX + FETCH_PAD_DEG))[0]
            lon_idx = np.where((lon_1d >= LON_MIN - FETCH_PAD_DEG) & (lon_1d <= LON_MAX + FETCH_PAD_DEG))[0]
            lon, lat = np.meshgrid(lon_1d[lon_idx], lat_1d[lat_idx])
            dpd_max_k = np.full(lat.shape, -np.inf, dtype=np.float32)
            storm_mask = np.zeros(lat.shape, dtype=bool)

        t2m = ds_t["t2m"].values[np.ix_(lat_idx, lon_idx)]
        d2m = ds_d["d2m"].values[np.ix_(lat_idx, lon_idx)]
        mucape = ds_cape["mucape"].values[np.ix_(lat_idx, lon_idx)]

        dpd_max_k = np.maximum(dpd_max_k, t2m - d2m)
        storm_mask |= mucape >= MUCAPE_THRESHOLD_JKG

    return lat, lon, dpd_max_k, storm_mask, run_init


def resample_to_regular_grid(lat, lon, values, method="linear"):
    reg_lon = np.linspace(RESAMPLE_LON_MIN, RESAMPLE_LON_MAX, RESAMPLE_NX)
    reg_lat = np.linspace(RESAMPLE_LAT_MIN, RESAMPLE_LAT_MAX, RESAMPLE_NY)
    reg_lon_grid, reg_lat_grid = np.meshgrid(reg_lon, reg_lat)
    points = np.column_stack([np.ravel(lon), np.ravel(lat)])
    regridded = griddata(points, np.ravel(values), (reg_lon_grid, reg_lat_grid), method=method)
    nan_mask = np.isnan(regridded)
    if nan_mask.any():
        regridded[nan_mask] = griddata(points, np.ravel(values),
                                        (reg_lon_grid[nan_mask], reg_lat_grid[nan_mask]), method="nearest")
    return regridded


# ---------------------------------------------------------------------------
# Basemap layers
# ---------------------------------------------------------------------------
def load_land():
    with open(LAND_FILE) as f:
        data = json.load(f)
    return [shape(feat["geometry"]) for feat in data["features"] if feat.get("geometry")]


def load_states_lakes():
    with open(STATES_LAKES_FILE) as f:
        data = json.load(f)
    state_geoms, lake_geoms = [], []
    for feat in data["features"]:
        props = feat["properties"]
        if "Lake" in props.get("featurecla", ""):
            lake_geoms.append(shape(feat["geometry"]))
        elif props.get("admin") in TARGET_COUNTRIES:
            state_geoms.append(shape(feat["geometry"]))
    return state_geoms, lake_geoms


def load_boundary_lines(path):
    with open(path) as f:
        data = json.load(f)
    return [shape(feat["geometry"]) for feat in data["features"]]


def build_map(date, output_path, override_path=None):
    poppins_reg = fm.FontProperties(fname=POPPINS_REG_PATH)
    poppins_semibold = fm.FontProperties(fname=POPPINS_MED_PATH)

    if override_path:
        print(f"Using local snapshot: {override_path}")
        npz = np.load(override_path)
        lat, lon, dpd_max_k, storm_mask = npz["lat"], npz["lon"], npz["dpd_max_k"], npz["storm_mask"]
        run_init = datetime.fromisoformat(str(npz["run_init"]))
    else:
        lat, lon, dpd_max_k, storm_mask, run_init = fetch_day(date)
        np.savez(OUTPUT_DIR / f"snapshot_{date.isoformat()}.npz", lat=lat, lon=lon,
                 dpd_max_k=dpd_max_k, storm_mask=storm_mask, run_init=run_init.isoformat())

    print("Resampling onto a regular grid...")
    dpd_max_k = resample_to_regular_grid(lat, lon, dpd_max_k, method="linear")
    storm_mask_f = resample_to_regular_grid(lat, lon, storm_mask.astype(np.float32), method="linear")

    dpd_f = k_diff_to_f(dpd_max_k)
    lon_frac0 = (LON_MIN - RESAMPLE_LON_MIN) / (RESAMPLE_LON_MAX - RESAMPLE_LON_MIN)
    lon_frac1 = (LON_MAX - RESAMPLE_LON_MIN) / (RESAMPLE_LON_MAX - RESAMPLE_LON_MIN)
    lat_frac0 = (LAT_MIN - RESAMPLE_LAT_MIN) / (RESAMPLE_LAT_MAX - RESAMPLE_LAT_MIN)
    lat_frac1 = (LAT_MAX - RESAMPLE_LAT_MIN) / (RESAMPLE_LAT_MAX - RESAMPLE_LAT_MIN)
    visible = dpd_f[round(lat_frac0 * RESAMPLE_NY):round(lat_frac1 * RESAMPLE_NY),
                     round(lon_frac0 * RESAMPLE_NX):round(lon_frac1 * RESAMPLE_NX)]
    print(f"Max dew point depression range: {visible.min():.0f}F - {visible.max():.0f}F")
    print(f"Thunderstorm-signal grid cells: {(storm_mask_f >= 0.5).sum()} of {storm_mask_f.size}")

    print("Loading basemap layers...")
    land_geoms = load_land()
    state_geoms, lake_geoms = load_states_lakes()
    admin0_lines = load_boundary_lines(ADMIN0_LINES_FILE)

    # PlateCarree (not NearsidePerspective, used by the other scripts in
    # this repo) -- this domain is unusually tall north-south (BC down to
    # OR/ID). Both NearsidePerspective and Lambert Conformal fit the axes to
    # a rectangle bounding the *projected* (curved) shape of the requested
    # lon/lat box; on a box this tall, that bounding rectangle's corners
    # fall outside the box itself, leaving a real gap no amount of data
    # padding fixes (confirmed by testing plain PlateCarree, which has no
    # such gap, against the same data). PlateCarree does compress east-west
    # distance somewhat near the domain's north end (~60N) versus its south
    # end, a standard, acceptable tradeoff for a wide-latitude-range map.
    pc = ccrs.PlateCarree()
    proj = pc

    fig = plt.figure(figsize=(FIG_WIDTH_IN, FIG_HEIGHT_IN), dpi=FIG_DPI)
    fig.patch.set_facecolor("#f7f6f2")

    ax = fig.add_axes(AXES_RECT, projection=proj)
    ax.set_extent([LON_MIN, LON_MAX, LAT_MIN, LAT_MAX], crs=pc)
    ax.patch.set_facecolor("white")

    # Shaded with pcolormesh (not imshow, used by the other scripts in this
    # repo): imshow warps a raster into the map projection by inverse-
    # projecting each screen pixel back to lon/lat and sampling the source
    # array, which can leave gaps unfilled if the source raster doesn't
    # extend far enough past the plotted extent. pcolormesh instead forward-
    # projects each source grid cell directly, so there's no inverse-lookup
    # to miss regardless of how much the raster is padded.
    dpd_cmap = build_dpd_colormap()
    dpd_norm = Normalize(vmin=DPD_FMIN, vmax=DPD_FMAX)
    dpd_k_norm = Normalize(vmin=DPD_FMIN * 5 / 9, vmax=DPD_FMAX * 5 / 9)
    reg_lon = np.linspace(RESAMPLE_LON_MIN, RESAMPLE_LON_MAX, RESAMPLE_NX)
    reg_lat = np.linspace(RESAMPLE_LAT_MIN, RESAMPLE_LAT_MAX, RESAMPLE_NY)
    ax.pcolormesh(reg_lon, reg_lat, dpd_max_k, transform=pc, cmap=dpd_cmap, norm=dpd_k_norm,
                  shading="gouraud", zorder=1)

    ax.add_geometries(land_geoms, crs=pc, facecolor="none", edgecolor="#4a6b7a", linewidth=0.8, zorder=1.5)
    ax.add_geometries(state_geoms, crs=pc, facecolor="none", edgecolor="#5a4632", linewidth=0.8, zorder=2)
    ax.add_geometries(lake_geoms, crs=pc, facecolor="white", edgecolor="#5a4632", linewidth=0.6, zorder=2.1)
    ax.add_geometries(admin0_lines, crs=pc, facecolor="none", edgecolor="#3a2f21", linewidth=1.1, zorder=2.5)

    # Thunderstorm-signal outline -- smoothed lightly so the contour reads as
    # a clean boundary rather than the raw grid's stair-steps, then drawn as
    # a dashed red line around the >=0.5 (i.e. "flagged") region.
    storm_smooth = gaussian_filter(storm_mask_f, sigma=1.4)
    if storm_smooth.max() >= 0.5:
        ax.contour(reg_lon, reg_lat, storm_smooth, levels=[0.5], colors="#e6231e",
                    linewidths=1.8, linestyles="dashed", transform=pc, zorder=3)
    else:
        print("No grid cells cleared the thunderstorm-signal threshold today -- no outline drawn.")

    geodetic_transform = pc._as_mpl_transform(ax)
    stroke = [pe.withStroke(linewidth=1.5, foreground=(0, 0, 0, 0.75))]
    for name, lon_c, lat_c, pos in CITIES:
        if not (LON_MIN <= lon_c <= LON_MAX and LAT_MIN <= lat_c <= LAT_MAX):
            continue
        ax.plot(lon_c, lat_c, marker="o", markersize=4.6, color="white", zorder=100,
                mec="black", mew=0.7, transform=pc)
        dx_pt = 6 if pos == "right" else -6
        ha = "left" if pos == "right" else "right"
        name_transform = offset_copy(geodetic_transform, fig=fig, x=dx_pt, y=0, units="points")
        txt = ax.text(lon_c, lat_c, name, fontsize=9.25, fontproperties=poppins_semibold,
                       color="white", ha=ha, va="center", zorder=101, transform=name_transform)
        txt.set_path_effects(stroke)

    ax.spines['geo'].set_edgecolor('black')
    ax.spines['geo'].set_linewidth(1.6)

    # Colorbar -- below the map, centered on the rendered map frame.
    fig.canvas.draw()
    frame_px = ax.get_window_extent()
    frame_left = frame_px.x0 / (FIG_WIDTH_IN * FIG_DPI)
    frame_right = frame_px.x1 / (FIG_WIDTH_IN * FIG_DPI)
    cbar_width, cbar_height = (frame_right - frame_left) * 0.55, 0.018
    cbar_left = (frame_left + frame_right) / 2 - cbar_width / 2
    cbar_bottom = 0.075

    vmin_disp = 5 * np.floor(max(visible.min(), DPD_FMIN) / 5)
    vmax_disp = 5 * np.ceil(min(visible.max(), DPD_FMAX) / 5)
    gradient_f = np.linspace(vmin_disp, vmax_disp, 256).reshape(1, -1)

    cax = fig.add_axes([cbar_left, cbar_bottom, cbar_width, cbar_height])
    cax.imshow(gradient_f, aspect="auto", cmap=dpd_cmap, norm=dpd_norm,
               extent=[vmin_disp, vmax_disp, 0, 1])
    cax.set_yticks([])
    for spine in cax.spines.values():
        spine.set_edgecolor("#8a887e")
        spine.set_linewidth(0.6)

    f_ticks = [f for f in range(0, 101, 10) if vmin_disp <= f <= vmax_disp]
    cax.set_xticks(f_ticks)
    cax.set_xticklabels([f"{f}°F" for f in f_ticks])
    cax.tick_params(labelsize=8.5, color="#8a887e", labelcolor="#2b2a26")
    for label in cax.get_xticklabels():
        label.set_fontproperties(poppins_reg)

    # Legend entry for the thunderstorm-signal outline -- a thin unboxed
    # strip in the gap between the map frame and the colorbar.
    storm_handle = Line2D([0], [0], color="#e6231e", linestyle="--", linewidth=1.8,
                           label=f"ECMWF thunderstorm signal (MUCAPE ≥ {MUCAPE_THRESHOLD_JKG:.0f} J/kg)")
    legend_y = (AXES_RECT[1] + cbar_bottom + cbar_height) / 2
    leg = fig.legend(handles=[storm_handle], loc="center", frameon=False, fontsize=8.75,
                      prop=poppins_reg, handlelength=2.4,
                      bbox_to_anchor=(0.5, legend_y))
    for text in leg.get_texts():
        text.set_color("#2b2a26")

    # Title & subtitle above the map
    fig.text(0.03, 0.978, f"{date.strftime('%A, %B %-d')} — Max Dew Point Depression", fontsize=19,
              fontproperties=poppins_reg, color="#2b2a26", ha="left", va="top")
    fig.text(0.03, 0.943, "British Columbia • Washington • Oregon • Idaho", fontsize=12.5,
              fontproperties=poppins_semibold, color="#3a3835", ha="left", va="top")
    fig.text(0.03, 0.914, f"ECMWF IFS 0.25° • Init {run_init.strftime('%Y-%m-%d %H')}z",
              fontsize=10.5, fontproperties=poppins_reg, color="#5a584f", ha="left", va="top")

    fig.text(0.5, 0.012, "ECMWF IFS — Ingalls Weather", fontsize=9,
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
        description="Build an Ingalls Weather BC/WA/OR/ID dew point depression + thunderstorm map.")
    parser.add_argument("--date", type=str, default=None,
                         help="Target date, YYYY-MM-DD, local (Pacific) time (default: today).")
    parser.add_argument("--file", type=Path, default=None,
                         help="Render from a local saved snapshot (.npz) instead of fetching live.")
    parser.add_argument("--out", type=Path, default=None,
                         help="Output PNG path (default: output/dew_point_storm_map_<date>.png).")
    args = parser.parse_args()

    if args.file and not args.file.exists():
        sys.exit(f"--file {args.file} not found.")

    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        target_date = datetime.now(LOCAL_TZ).date()

    out_path = args.out or (OUTPUT_DIR / f"dew_point_storm_map_{target_date.isoformat()}.png")
    build_map(target_date, out_path, override_path=args.file)

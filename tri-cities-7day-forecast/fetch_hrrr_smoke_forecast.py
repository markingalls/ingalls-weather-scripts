"""
Fetches NOAA HRRR's vertically-integrated smoke forecast (VIS -- the
"COLMD" GRIB field, column-integrated smoke mass density) for a point,
hourly out to 48 hours, and writes hrrr_smoke_forecast.json. Used by
build_graphic.py, May-Oct only (wildfire smoke season), to override a
day's condition icon with a smoke icon when HRRR is forecasting a
significant daytime smoke plume.

COLMD comes back from NOAA in kg/m^2 (raw GRIB2 SI units) and is converted
to mg/m^2 here to match how NOAA's own smoke guidance is normally quoted.

Fetched via Herbie (https://herbie.readthedocs.io), which pulls each grib
message directly from NOAA's own free HRRR distribution (AWS Open Data /
NOMADS) -- no API key needed, and only the COLMD record is downloaded from
each hourly file (byte-range subsetting), not the whole ~500MB grib. Same
access pattern as columbia-basin-temps/build_map.py's fetch_hrrr().
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
from herbie import Herbie

# Default point: KPSC (Tri-Cities Airport, Pasco, WA)
DEFAULT_LAT = 46.2647
DEFAULT_LON = -119.1189

MAX_FORECAST_HOUR = 48
KG_PER_M2_TO_MG_PER_M2 = 1_000_000


def select_hrrr_run():
    """Most recent synoptic-hour HRRR init (00/06/12/18z UTC) with data
    available -- only those cycles run out to 48h (others only reach 18h),
    and this feature needs the full 48h horizon."""
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    now -= timedelta(hours=now.hour % 6)
    for lookback_cycles in range(12):
        candidate = now - timedelta(hours=6 * lookback_cycles)
        if Herbie(candidate.replace(tzinfo=None), model="hrrr", product="sfc", fxx=1, verbose=False).grib is not None:
            return candidate
    sys.exit("Could not find a recent synoptic-hour HRRR run on NOAA's servers.")


def nearest_point_value(ds, lat, lon):
    lon_360 = lon % 360
    lat2d, lon2d = ds["latitude"].values, ds["longitude"].values
    dist2 = (lat2d - lat) ** 2 + (lon2d - lon_360) ** 2
    iy, ix = np.unravel_index(np.argmin(dist2), dist2.shape)
    return float(ds["unknown"].values[iy, ix])


def fetch(lat, lon):
    run_init = select_hrrr_run()

    hourly = []
    for fxx in range(1, MAX_FORECAST_HOUR + 1):
        ds = Herbie(run_init.replace(tzinfo=None), model="hrrr", product="sfc",
                    fxx=fxx, verbose=False).xarray(":COLMD:entire atmosphere")
        vis_kg_m2 = nearest_point_value(ds, lat, lon)
        valid_time = run_init + timedelta(hours=fxx)
        hourly.append({
            "valid_time": valid_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "vis_smoke_mg_m2": vis_kg_m2 * KG_PER_M2_TO_MG_PER_M2,
        })

    return {
        "run_init": run_init.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lat": lat,
        "lon": lon,
        "hourly": hourly,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lat", type=float, default=DEFAULT_LAT)
    ap.add_argument("--lon", type=float, default=DEFAULT_LON)
    ap.add_argument("--output", default="hrrr_smoke_forecast.json")
    args = ap.parse_args()

    data = fetch(args.lat, args.lon)

    with open(args.output, "w") as f:
        json.dump(data, f)

    print(f"Saved {args.output}: {len(data['hourly'])} hourly steps from HRRR "
          f"{data['run_init']} run, at {args.lat},{args.lon}")

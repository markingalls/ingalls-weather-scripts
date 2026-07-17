"""
Fetches NOAA HRRR smoke for one or more points, across a full 00/06/12/18z
HRRR cycle (the only cycles that run out to 48h -- the other hourly cycles
stop at 18h), and writes smoke.json. Run this before build_chart.py any
time you want the chart to reflect the latest run.

Pulls both smoke fields HRRR publishes, so a single fetch covers every
build_chart.py --variable/--units combination:
  - near_surface_smoke      MASSDEN @ 8 m above ground, kg/m^3 -> ug/m3
  - vertically_integrated_smoke   COLMD @ entire atmosphere, kg/m^2 -> ug/m2

No API key needed -- pulls HRRR's own free GRIB2 distribution directly
(NOAA's AWS Open Data bucket, falling back to NOMADS) via Herbie, one
byte-range subset request per field per forecast hour.
"""
import argparse
import json
import sys
import warnings
from datetime import datetime, timedelta, timezone

warnings.filterwarnings("ignore", message="In a future version of xarray.*compat", category=FutureWarning)

import numpy as np
from herbie import Herbie

# search string -> (variable key, output units, kg -> output-unit multiplier)
FIELDS = {
    "MASSDEN:8 m above ground": ("near_surface_smoke", "ug/m3", 1e9),
    "COLMD:entire atmosphere": ("vertically_integrated_smoke", "ug/m2", 1e9),
}
MAX_FORECAST_HOUR = 48

# Default points
DEFAULT_LOCATIONS = [
    {"label": "Kennewick, WA", "lat": 46.2087, "lon": -119.1361},
    {"label": "Hermiston, OR", "lat": 45.8404, "lon": -119.2895},
]


def select_latest_48h_run():
    """Most recent HRRR init at a synoptic hour (00/06/12/18z) that has
    completed processing all the way out to F48 on NOAA's servers."""
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    now -= timedelta(hours=now.hour % 6)
    for lookback_cycles in range(20):
        candidate = now - timedelta(hours=6 * lookback_cycles)
        H = Herbie(candidate.replace(tzinfo=None), model="hrrr", product="sfc",
                   fxx=MAX_FORECAST_HOUR, verbose=False)
        if H.grib is not None:
            return candidate
    sys.exit("Could not find a complete HRRR 00/06/12/18z run (through F48) on NOAA's servers.")


def nearest_index(lat_grid, lon_grid, lat_pt, lon_pt):
    d2 = (lat_grid - lat_pt) ** 2 + (lon_grid - lon_pt) ** 2
    return np.unravel_index(np.argmin(d2), d2.shape)


def fetch(locations, run_init):
    times = []
    variables = {var_key: {"units": units, "series": {loc["label"]: [] for loc in locations}}
                 for var_key, units, _ in FIELDS.values()}
    indices = None

    for fxx in range(0, MAX_FORECAST_HOUR + 1):
        valid_time = run_init + timedelta(hours=fxx)
        times.append(valid_time.strftime("%Y-%m-%dT%H:%M:%SZ"))

        for search, (var_key, units, scale) in FIELDS.items():
            print(f"Fetching HRRR {run_init:%Y-%m-%d %H}z F{fxx:02d} -- {var_key} ...")
            ds = Herbie(run_init.replace(tzinfo=None), model="hrrr", product="sfc",
                        fxx=fxx, verbose=False).xarray(search)

            if indices is None:
                lat_grid = ds.latitude.values
                lon_grid = np.where(ds.longitude.values > 180, ds.longitude.values - 360, ds.longitude.values)
                indices = {loc["label"]: nearest_index(lat_grid, lon_grid, loc["lat"], loc["lon"])
                           for loc in locations}

            values = ds["unknown"].values
            for loc in locations:
                variables[var_key]["series"][loc["label"]].append(
                    float(values[indices[loc["label"]]]) * scale)

    return times, variables


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--locations", default=None,
                     help="JSON string overriding the default locations, e.g. "
                          '\'[{"label":"Kennewick, WA","lat":46.2087,"lon":-119.1361}]\'')
    ap.add_argument("--output", default="smoke.json")
    args = ap.parse_args()

    locations = json.loads(args.locations) if args.locations else DEFAULT_LOCATIONS

    run_init = select_latest_48h_run()
    print(f"Using HRRR {run_init:%Y-%m-%d %H}z (most recent complete 48h run)")

    times, variables = fetch(locations, run_init)

    data = {
        "initialization_time": run_init.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "locations": locations,
        "times": times,
        "variables": variables,
    }
    with open(args.output, "w") as f:
        json.dump(data, f)

    print(f"Saved {args.output}: {len(times)} timesteps x {len(variables)} variable(s) "
          f"for {len(locations)} location(s) (init {data['initialization_time']})")

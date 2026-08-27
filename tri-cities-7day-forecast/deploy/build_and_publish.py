#!/usr/bin/env python3
"""
Cron entry point for the droplet deployment. Runs the full fetch + build
pipeline for each location in LOCATIONS and overwrites each published PNG
in place. One location failing (e.g. a fetch source hiccup) doesn't stop
the others from publishing -- each is fetched, built, and published
independently within the same run.

Scheduled at fixed times matching the proven GitHub Actions offsets --
07:15, 12:30, 19:15, 00:30 UTC (see deploy/crontab.example) -- rather than
polling for a new ECMWF run, because the pipeline pulls from four sources
(NWS, WindBorne MetaMesh, Open-Meteo, Open-Meteo ensemble) and those fixed
offsets were tuned to land safely after all four have absorbed a given
ECMWF cycle. A trigger based on any single source's own availability (e.g.
WindBorne's ecmwf-det initialization_times) risks firing before the other
three have caught up, rendering a graphic that mixes a fresh source with a
stale one.

An flock-based lock means an overlapping cron tick (e.g. a slow run still
in progress when the next scheduled tick fires) skips instead of running
a second pass concurrently.
"""
import fcntl
import os
import subprocess
import sys
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # tri-cities-7day-forecast/
STATE_DIR = os.path.join(BASE_DIR, "state")
LOCK_FILE = os.path.join(STATE_DIR, "run.lock")
LOG_FILE = os.path.join(STATE_DIR, "build.log")
PYTHON = os.path.join(BASE_DIR, "venv", "bin", "python3")

# Where nginx serves static files from -- see deploy/nginx-images.conf.
WEB_ROOT = "/var/www/images"

# Each location's own coordinates drive every fetch script (fetch_forecast.py
# resolves NWS's own gridpoint/icons from lat/lon; Open-Meteo and the ECMWF
# ensemble are lat/lon-native; HRRR smoke likewise). MetaMesh's station
# queries need the full 4-letter, K-prefixed ICAO id (matching Tri-Cities'
# working "kpsc") -- WindBorne's public /point_forecast/stations catalog
# lists CONUS entries under a misleading 3-letter form ("pdx", not "kpdx")
# that silently returns an empty forecast if queried directly; confirmed
# against the live API that both "kpdx" and "khri" work as station queries
# even though neither 3-letter/short form does, and KHRI isn't listed in
# that catalog under any form at all despite resolving correctly.
LOCATIONS = [
    {
        "label": "Tri-Cities, WA",
        "lat": 46.2647,
        "lon": -119.1189,
        "metamesh_station": "kpsc",
        "output_name": "tricities_forecast.png",
    },
    {
        "label": "Hermiston, OR",
        "lat": 45.82583,
        "lon": -119.26111,
        "metamesh_station": "khri",
        "output_name": "hermiston_forecast.png",
    },
    {
        "label": "Portland, OR",
        "lat": 45.59578,
        "lon": -122.60917,
        "metamesh_station": "kpdx",
        "output_name": "portland_forecast.png",
    },
    {
        "label": "Eugene, OR",
        "lat": 44.1247,
        "lon": -123.2206,
        "metamesh_station": "keug",
        "output_name": "eugene_forecast.png",
    },
    {
        "label": "Seattle, WA",
        "lat": 47.4489,
        "lon": -122.3089,
        "metamesh_station": "ksea",
        "output_name": "seattle_forecast.png",
    },
]


def log(msg):
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def build_location(loc, env):
    lat, lon = loc["lat"], loc["lon"]

    subprocess.run([PYTHON, "fetch_forecast.py", "--lat", str(lat), "--lon", str(lon),
                     "--label", loc["label"]], cwd=BASE_DIR, check=True, env=env)

    metamesh_args = [PYTHON, "fetch_metamesh_forecast.py"]
    if loc["metamesh_station"]:
        metamesh_args += ["--station", loc["metamesh_station"]]
    else:
        metamesh_args += ["--lat", str(lat), "--lon", str(lon)]
    subprocess.run(metamesh_args, cwd=BASE_DIR, check=True, env=env)

    subprocess.run([PYTHON, "fetch_openmeteo_forecast.py", "--lat", str(lat), "--lon", str(lon)],
                    cwd=BASE_DIR, check=True, env=env)
    subprocess.run([PYTHON, "fetch_ecmwf_ensemble_forecast.py", "--lat", str(lat), "--lon", str(lon)],
                    cwd=BASE_DIR, check=True, env=env)

    # HRRR smoke is a decorative overlay (build_graphic.py already renders
    # fine without it -- see its `if os.path.exists(args.hrrr_smoke_forecast)`
    # check), not a hard prerequisite like the four sources above, so its
    # failure shouldn't take down the whole graphic the way theirs would.
    month = datetime.now(timezone.utc).month
    if 5 <= month <= 10:
        smoke_path = os.path.join(BASE_DIR, "hrrr_smoke_forecast.json")
        try:
            subprocess.run([PYTHON, "fetch_hrrr_smoke_forecast.py", "--lat", str(lat), "--lon", str(lon)],
                            cwd=BASE_DIR, check=True, env=env)
        except subprocess.CalledProcessError as e:
            log(f"{loc['label']}: HRRR smoke fetch FAILED ({e}) -- rendering without a smoke overlay.")
            # The fetch script writes its output only on success, so a
            # failure here can only mean this file (if present at all) is
            # left over from a previous successful run -- remove it rather
            # than silently reusing a possibly days-stale smoke forecast.
            if os.path.exists(smoke_path):
                os.remove(smoke_path)
    else:
        log(f"{loc['label']}: outside smoke season (May-Oct), skipping HRRR smoke fetch.")

    # Render to a temp file in the same directory, then atomically replace
    # the published file so nginx never serves a half-written PNG. The temp
    # name has to keep a .png suffix -- matplotlib's savefig picks its
    # output format from the file extension, not from an actual PNG being
    # requested, so e.g. a ".tmp" suffix fails with "Format 'tmp' is not
    # supported" instead of writing a PNG under a temp name.
    final_path = os.path.join(WEB_ROOT, loc["output_name"])
    tmp_path = os.path.join(WEB_ROOT, f".tmp_{loc['output_name']}")
    subprocess.run([PYTHON, "build_graphic.py", "--output", tmp_path], cwd=BASE_DIR, check=True, env=env)
    os.replace(tmp_path, final_path)


def main():
    os.makedirs(STATE_DIR, exist_ok=True)
    lock_fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("Previous run still in progress -- skipping this tick.")
        return 0

    try:
        log("Starting scheduled build.")
        env = os.environ.copy()
        failures = 0
        for loc in LOCATIONS:
            try:
                build_location(loc, env)
                log(f"{loc['label']}: succeeded -- {WEB_ROOT}/{loc['output_name']} updated.")
            except subprocess.CalledProcessError as e:
                failures += 1
                log(f"{loc['label']}: FAILED ({e}) -- leaving its previous published image in place.")
        return 1 if failures else 0
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    sys.exit(main())

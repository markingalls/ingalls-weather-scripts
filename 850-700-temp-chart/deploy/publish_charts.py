#!/usr/bin/env python3
"""
Cron entry point for the droplet deployment. For each location in
LOCATIONS: fetches the current WM-6 ensemble forecast, builds the chart
against that location's cached climatology (see seed_climatology.py --
climatology is a static 1991-2020 normal, not refetched every cycle), and
atomically publishes the PNG. One location failing (e.g. a WindBorne API
hiccup) doesn't stop the others -- each is fetched, built, and published
independently within the same run, same pattern as
tri-cities-7day-forecast/deploy/build_and_publish.py.

Scheduled hourly (see deploy/crontab.example) to match WM-6's own update
cadence. Unlike the SPC/IEM buffer in western-us-noaa-outlooks, WM-6's
per-hour availability lag hasn't been empirically checked against a live
cycle boundary -- the cron offset is a reasonable default (10 min past the
hour), worth confirming against a few real days of state/publish.log
before assuming it's exactly right.

An flock-based lock means an overlapping cron tick (e.g. a slow run still
in progress when the next scheduled tick fires) skips instead of running a
second pass concurrently.
"""
import fcntl
import os
import subprocess
import sys
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 850-700-temp-chart/
STATE_DIR = os.path.join(BASE_DIR, "state")
CLIMATOLOGY_DIR = os.path.join(BASE_DIR, "deploy", "climatology")
LOCK_FILE = os.path.join(STATE_DIR, "run.lock")
LOG_FILE = os.path.join(STATE_DIR, "publish.log")
PYTHON = os.path.join(BASE_DIR, "venv", "bin", "python3")

# Where nginx serves static files from -- see
# ../../tri-cities-7day-forecast/deploy/nginx-images.conf, reused as-is for
# this project too (same images.ingallswx.com folder).
WEB_ROOT = "/var/www/images"

PRESSURE_LEVEL = 850

# Tri-Cities/Hermiston/Portland coordinates match
# tri-cities-7day-forecast/deploy/build_and_publish.py's LOCATIONS exactly,
# so both products refer to the same physical point per city. The other six
# are airport (or, for Bend, town-center) coordinates picked fresh for this
# product -- no prior precedent elsewhere in the repo.
LOCATIONS = [
    {"slug": "tricities", "station": "KPSC", "label": "Pasco, WA", "lat": 46.2647, "lon": -119.1189},
    {"slug": "hermiston", "station": "KHRI", "label": "Hermiston, OR", "lat": 45.82583, "lon": -119.26111},
    {"slug": "portland", "station": "KPDX", "label": "Portland, OR", "lat": 45.59578, "lon": -122.60917},
    {"slug": "seattle", "station": "KSEA", "label": "Seattle, WA", "lat": 47.4502, "lon": -122.3088},
    {"slug": "spokane", "station": "KGEG", "label": "Spokane, WA", "lat": 47.6199, "lon": -117.5339},
    {"slug": "eugene", "station": "KEUG", "label": "Eugene, OR", "lat": 44.1246, "lon": -123.2120},
    {"slug": "bellingham", "station": "KBLI", "label": "Bellingham, WA", "lat": 48.7928, "lon": -122.5375},
    {"slug": "bend", "station": "Bend", "label": "Bend, OR", "lat": 44.0582, "lon": -121.3153},
    {"slug": "princegeorge", "station": "CYXS", "label": "Prince George, BC", "lat": 53.8894, "lon": -122.6786},
]


def log(msg):
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def publish_location(loc, env):
    forecast_path = os.path.join(BASE_DIR, "forecast.json")
    climatology_path = os.path.join(CLIMATOLOGY_DIR, f"{loc['slug']}.json")
    if not os.path.exists(climatology_path):
        raise RuntimeError(
            f"No cached climatology for '{loc['slug']}' at {climatology_path} -- "
            f"run deploy/seed_climatology.py first."
        )

    subprocess.run(
        [PYTHON, "fetch_forecast.py", "--lat", str(loc["lat"]), "--lon", str(loc["lon"]),
         "--station", loc["station"], "--label", loc["label"], "--level", str(PRESSURE_LEVEL),
         "--output", forecast_path],
        cwd=BASE_DIR, check=True, env=env,
    )

    # Same atomic-rename pattern as the Tri-Cities deploy: render to a temp
    # file with a real .png suffix (matplotlib's savefig needs that to pick
    # the right format), then replace so nginx never serves a half-written
    # file mid-save.
    output_name = f"850mb_{loc['slug']}.png"
    final_path = os.path.join(WEB_ROOT, output_name)
    tmp_path = os.path.join(WEB_ROOT, f".tmp_{output_name}")
    subprocess.run(
        [PYTHON, "build_chart.py", "--forecast", forecast_path, "--climatology", climatology_path,
         "--output", tmp_path],
        cwd=BASE_DIR, check=True, env=env,
    )
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
                publish_location(loc, env)
                log(f"{loc['label']}: succeeded -- 850mb_{loc['slug']}.png updated.")
            except (subprocess.CalledProcessError, RuntimeError) as e:
                failures += 1
                log(f"{loc['label']}: FAILED ({e}) -- leaving its previous published image in place.")
        return 1 if failures else 0
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    sys.exit(main())

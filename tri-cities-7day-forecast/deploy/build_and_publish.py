#!/usr/bin/env python3
"""
Cron entry point for the droplet deployment. Runs the full fetch + build
pipeline and overwrites the published PNG in place.

Scheduled at fixed times matching the proven GitHub Actions offsets --
07:15, 12:30, 19:15, 00:30 UTC (see deploy/crontab.example) -- rather than
polling for a new ECMWF run, because the pipeline pulls from four sources
(NWS, WindBorne MetaMesh, Open-Meteo, Open-Meteo ensemble) and those fixed
offsets were tuned to land safely after all four have absorbed a given
ECMWF cycle. A trigger based on any single source's own availability (e.g.
WindBorne's ecmwf-det initialization_times) risks firing before the other
three have caught up, rendering a graphic that mixes a fresh source with a
stale one.

An flock-based lock means an overlapping cron tick (e.g. a slow build
still running when the next scheduled tick fires) skips instead of
running a second build concurrently.
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
OUTPUT_NAME = "tricities_forecast.png"

FETCH_SCRIPTS = [
    "fetch_forecast.py",
    "fetch_metamesh_forecast.py",
    "fetch_openmeteo_forecast.py",
    "fetch_ecmwf_ensemble_forecast.py",
]


def log(msg):
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def build():
    env = os.environ.copy()
    for script in FETCH_SCRIPTS:
        subprocess.run([PYTHON, script], cwd=BASE_DIR, check=True, env=env)

    month = datetime.now(timezone.utc).month
    if 5 <= month <= 10:
        subprocess.run([PYTHON, "fetch_hrrr_smoke_forecast.py"], cwd=BASE_DIR, check=True, env=env)
    else:
        log("Outside smoke season (May-Oct), skipping HRRR smoke fetch.")

    # Render to a temp file in the same directory, then atomically replace
    # the published file so nginx never serves a half-written PNG.
    final_path = os.path.join(WEB_ROOT, OUTPUT_NAME)
    tmp_path = final_path + ".tmp"
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
        try:
            build()
        except subprocess.CalledProcessError as e:
            log(f"Build FAILED: {e}")
            return 1

        log(f"Build succeeded -- {WEB_ROOT}/{OUTPUT_NAME} updated.")
        return 0
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    sys.exit(main())

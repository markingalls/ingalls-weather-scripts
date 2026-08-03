#!/usr/bin/env python3
"""
Hourly cron guard for the droplet deployment. Checks WindBorne's
ecmwf-det/initialization_times endpoint (the raw ECMWF deterministic cycle,
00/06/12/18Z) for the latest completed run. If it's the same run this
script already built for, exits immediately. If it's new, runs the full
fetch + build pipeline and overwrites the published PNG in place.

An flock-based lock means an overlapping cron tick (e.g. a slow build still
running when the next hourly tick fires) skips instead of running a second
build concurrently.

Requires WB_API_KEY in the environment (see ../.env.example).
"""
import fcntl
import os
import subprocess
import sys
from datetime import datetime, timezone

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # tri-cities-7day-forecast/
STATE_DIR = os.path.join(BASE_DIR, "state")
STATE_FILE = os.path.join(STATE_DIR, "last_ecmwf_run.txt")
LOCK_FILE = os.path.join(STATE_DIR, "run.lock")
LOG_FILE = os.path.join(STATE_DIR, "guard.log")
PYTHON = os.path.join(BASE_DIR, "venv", "bin", "python3")

# Where nginx serves static files from -- see deploy/nginx-images.conf.
WEB_ROOT = "/var/www/images"
OUTPUT_NAME = "tricities_forecast.png"

INIT_TIMES_URL = "https://api.windbornesystems.com/forecasts/v1/ecmwf-det/initialization_times"

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


def latest_ecmwf_run():
    api_key = os.environ["WB_API_KEY"]
    r = requests.get(INIT_TIMES_URL, headers={"Authorization": f"Bearer {api_key}"}, timeout=30)
    r.raise_for_status()
    return r.json()["latest"]


def last_seen_run():
    if os.path.exists(STATE_FILE):
        return open(STATE_FILE).read().strip()
    return None


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
        try:
            latest = latest_ecmwf_run()
        except Exception as e:
            log(f"Could not reach WindBorne initialization_times endpoint: {e}")
            return 1

        if latest == last_seen_run():
            return 0  # no-op, stay quiet

        log(f"New ECMWF run detected: {latest} (previous: {last_seen_run()})")
        try:
            build()
        except subprocess.CalledProcessError as e:
            log(f"Build FAILED ({e}) -- state not updated, will retry next hour.")
            return 1

        with open(STATE_FILE, "w") as f:
            f.write(latest)
        log(f"Build succeeded -- {WEB_ROOT}/{OUTPUT_NAME} updated for run {latest}.")
        return 0
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    sys.exit(main())

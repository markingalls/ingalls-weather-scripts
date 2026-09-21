#!/usr/bin/env python3
"""
Cron entry point for the droplet deployment. Fetches and publishes every
pair in deploy/pairs.py -- one <slug>_gradient_forecast.png per pair --
in a single run under one lock, same one-lock-many-outputs pattern as
hrrr-smoke-chart/deploy/publish_smoke.py and this project's own
publish_gradient.py: one pair's fetch failing doesn't stop the others.

Each pair gets its own intermediate combined obs+forecast JSON
(gradient_forecast_<slug>.json) so concurrent pairs within the same run
never write over each other.

Scheduled hourly (see deploy/crontab.example) -- MetaMesh reruns on its
own schedule under an hour, but the forecast itself doesn't move fast
enough to justify the observed-only chart's 15-minute cadence, and this
avoids spending WB_API_KEY's request quota faster than needed across
every pair in deploy/pairs.py.

An flock-based lock means an overlapping cron tick (e.g. a slow run still
in progress when the next scheduled tick fires) skips instead of running
a second pass concurrently -- same pattern as every other cron entry
point in this repo (see columbia-basin-alerts-map/deploy/publish_alerts.py).
Uses its own lock file (state/forecast_run.lock), separate from
publish_gradient.py's own state/run.lock, so a slow run of one never
blocks the other.
"""
import fcntl
import os
import subprocess
import sys
from datetime import datetime, timezone

DEPLOY_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(DEPLOY_DIR)  # pressure-gradient-chart/
STATE_DIR = os.path.join(BASE_DIR, "state")
LOCK_FILE = os.path.join(STATE_DIR, "forecast_run.lock")
LOG_FILE = os.path.join(STATE_DIR, "publish.log")
PYTHON = os.path.join(BASE_DIR, "venv", "bin", "python3")

# Where nginx serves static files from -- see
# ../../tri-cities-7day-forecast/deploy/nginx-images.conf, reused as-is.
WEB_ROOT = "/var/www/images"

sys.path.insert(0, BASE_DIR)
sys.path.insert(0, DEPLOY_DIR)
import build_forecast_chart  # noqa: E402
from pairs import PAIRS  # noqa: E402


def log(msg):
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def publish_pair(station_a, station_b, slug):
    obs_path = os.path.join(BASE_DIR, f"gradient_forecast_{slug}.json")
    subprocess.run([PYTHON, "fetch_metamesh_gradient.py",
                     "--station-a", station_a, "--station-b", station_b,
                     "--output", obs_path],
                    cwd=BASE_DIR, check=True)

    output_name = f"{slug}_gradient_forecast.png"
    final_path = os.path.join(WEB_ROOT, output_name)
    tmp_path = os.path.join(WEB_ROOT, f".tmp_{output_name}")
    build_forecast_chart.build_forecast_chart(obs_path, tmp_path)
    os.replace(tmp_path, final_path)
    return output_name


def main():
    os.makedirs(STATE_DIR, exist_ok=True)
    lock_fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("Previous forecast run still in progress -- skipping this tick.")
        return 0

    try:
        log(f"Starting scheduled forecast build ({len(PAIRS)} pairs).")
        failures = 0
        for station_a, station_b, slug in PAIRS:
            pair_label = f"{station_a}-{station_b}"
            try:
                output_name = publish_pair(station_a, station_b, slug)
                log(f"{pair_label}: succeeded -- {output_name} updated.")
            except subprocess.CalledProcessError as e:
                failures += 1
                log(f"{pair_label}: fetch_metamesh_gradient.py FAILED ({e}) -- skipping this pair.")
            except Exception as e:
                failures += 1
                log(f"{pair_label}: build FAILED ({e}) -- leaving its previous published image in place.")
        return 1 if failures else 0
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    sys.exit(main())

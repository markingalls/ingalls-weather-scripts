#!/usr/bin/env python3
"""
Cron entry point for the droplet deployment. Fetches and publishes every
pair in deploy/pairs.py -- one <slug>_gradient.png per pair -- in a
single run under one lock, same one-lock-many-outputs pattern as
hrrr-smoke-chart/deploy/publish_smoke.py: one pair's fetch failing
doesn't stop the others, and it's still one cron entry regardless of how
many pairs pairs.py lists.

Each pair gets its own intermediate obs JSON (gradient_obs_<slug>.json)
so concurrent pairs within the same run never write over each other.

Scheduled every 15 minutes (see deploy/crontab.example) -- both stations
in any pair actually update roughly every 5 minutes, but the gradient
itself moves slowly enough that a 15-minute republish cadence doesn't
lose anything a viewer would notice.

An flock-based lock means an overlapping cron tick (e.g. a slow run still
in progress when the next scheduled tick fires) skips instead of running
a second pass concurrently -- same pattern as every other cron entry
point in this repo (see columbia-basin-alerts-map/deploy/publish_alerts.py).
"""
import fcntl
import os
import subprocess
import sys
from datetime import datetime, timezone

DEPLOY_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(DEPLOY_DIR)  # pressure-gradient-chart/
STATE_DIR = os.path.join(BASE_DIR, "state")
LOCK_FILE = os.path.join(STATE_DIR, "run.lock")
LOG_FILE = os.path.join(STATE_DIR, "publish.log")
PYTHON = os.path.join(BASE_DIR, "venv", "bin", "python3")

# Where nginx serves static files from -- see
# ../../tri-cities-7day-forecast/deploy/nginx-images.conf, reused as-is.
WEB_ROOT = "/var/www/images"

sys.path.insert(0, BASE_DIR)
sys.path.insert(0, DEPLOY_DIR)
import build_chart  # noqa: E402
from pairs import PAIRS  # noqa: E402


def log(msg):
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def publish_pair(station_a, station_b, slug):
    obs_path = os.path.join(BASE_DIR, f"gradient_obs_{slug}.json")
    subprocess.run([PYTHON, "fetch_gradient.py",
                     "--station-a", station_a, "--station-b", station_b,
                     "--output", obs_path],
                    cwd=BASE_DIR, check=True)

    output_name = f"{slug}_gradient.png"
    # Same atomic-rename pattern as every other published image in this
    # repo: render to a temp file with a real .png suffix (matplotlib's
    # savefig needs that to pick the right format), then replace so nginx
    # never serves a half-written file mid-save.
    final_path = os.path.join(WEB_ROOT, output_name)
    tmp_path = os.path.join(WEB_ROOT, f".tmp_{output_name}")
    build_chart.build_chart(obs_path, tmp_path)
    os.replace(tmp_path, final_path)
    return output_name


def main():
    os.makedirs(STATE_DIR, exist_ok=True)
    lock_fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("Previous run still in progress -- skipping this tick.")
        return 0

    try:
        log(f"Starting scheduled build ({len(PAIRS)} pairs).")
        failures = 0
        for station_a, station_b, slug in PAIRS:
            pair_label = f"{station_a}-{station_b}"
            try:
                output_name = publish_pair(station_a, station_b, slug)
                log(f"{pair_label}: succeeded -- {output_name} updated.")
            except subprocess.CalledProcessError as e:
                failures += 1
                log(f"{pair_label}: fetch_gradient.py FAILED ({e}) -- skipping, no fresh data.")
            except Exception as e:
                failures += 1
                log(f"{pair_label}: build FAILED ({e}) -- leaving its previous published image in place.")
        return 1 if failures else 0
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    sys.exit(main())

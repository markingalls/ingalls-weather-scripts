#!/usr/bin/env python3
"""
Cron entry point for the droplet deployment. Fetches the last 24 hours of
GLM lightning once (every region pulls from the same domain-spanning
fetch -- no need to fetch twice), then renders and atomically publishes
each region in build_map.REGIONS. One region failing doesn't stop the
others, same pattern as every other publish script in this repo.

Scheduled every 10 minutes (see deploy/crontab.example) -- lightning has
no fixed issuance schedule to align to, so like columbia-basin-alerts-map
this is just a reasonable polling interval, not a cycle time.

An flock-based lock means an overlapping cron tick (e.g. a slow run still
in progress when the next scheduled tick fires) skips instead of running
a second pass concurrently.
"""
import fcntl
import os
import subprocess
import sys
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # columbia-basin-lightning-map/
STATE_DIR = os.path.join(BASE_DIR, "state")
LOCK_FILE = os.path.join(STATE_DIR, "run.lock")
LOG_FILE = os.path.join(STATE_DIR, "publish.log")
PYTHON = os.path.join(BASE_DIR, "venv", "bin", "python3")

# Where nginx serves static files from -- see
# ../../tri-cities-7day-forecast/deploy/nginx-images.conf, reused as-is.
WEB_ROOT = "/var/www/images"

sys.path.insert(0, BASE_DIR)
import build_map  # noqa: E402


def log(msg):
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def publish_region(region_key, lightning_path):
    output_name = build_map.REGIONS[region_key]["output"]
    final_path = os.path.join(WEB_ROOT, output_name)
    # Same atomic-rename pattern as every other published image in this
    # repo: render to a temp file with a real .png suffix (matplotlib's
    # savefig needs that to pick the right format), then replace so nginx
    # never serves a half-written file mid-save.
    tmp_path = os.path.join(WEB_ROOT, f".tmp_{output_name}")
    build_map.build_map(region_key, lightning_path, tmp_path)
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
        lightning_path = os.path.join(BASE_DIR, "lightning_last24h.json")
        subprocess.run([PYTHON, "fetch_lightning.py"], cwd=BASE_DIR, check=True)

        failures = 0
        for region_key in build_map.REGIONS:
            try:
                publish_region(region_key, lightning_path)
                log(f"{region_key}: succeeded -- {build_map.REGIONS[region_key]['output']} updated.")
            except Exception as e:
                failures += 1
                log(f"{region_key}: FAILED ({e}) -- leaving its previous published image in place.")
        return 1 if failures else 0
    except subprocess.CalledProcessError as e:
        log(f"fetch_lightning.py FAILED ({e}) -- skipping this tick entirely, no region has fresh data.")
        return 1
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    sys.exit(main())

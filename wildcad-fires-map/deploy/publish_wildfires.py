#!/usr/bin/env python3
"""
Cron entry point for the droplet deployment. Fetches every active wildfire
once, then renders and atomically publishes both products from that single
fetch: the standard map (every active fire) and the companion "what's new"
map (only fires first reported within the last NEW_FIRE_HOURS -- see
build_map.py). One product failing doesn't stop the other, same pattern as
every other publish script in this repo.

Scheduled every 3 hours at :59 (see deploy/crontab.example) -- both
products share this cadence so a viewer comparing them is never looking at
two different fetches.

An flock-based lock means an overlapping cron tick (e.g. a slow run still
in progress when the next scheduled tick fires) skips instead of running
a second pass concurrently.
"""
import fcntl
import os
import sys
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # wildcad-fires-map/
STATE_DIR = os.path.join(BASE_DIR, "state")
LOCK_FILE = os.path.join(STATE_DIR, "run.lock")
LOG_FILE = os.path.join(STATE_DIR, "publish.log")

# Matches build_map.py's own CLI default -- see its docstring (STALE_CONTAINED_DAYS).
LOOKBACK_DAYS = 90

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


def publish(fires, fetched_at, output_name, new_only):
    final_path = os.path.join(WEB_ROOT, output_name)
    # Same atomic-rename pattern as every other published image in this
    # repo: render to a temp file with a real .png suffix (matplotlib's
    # savefig needs that to pick the right format), then replace so nginx
    # never serves a half-written file mid-save.
    tmp_path = os.path.join(WEB_ROOT, f".tmp_{output_name}")
    build_map.build_map(fires, fetched_at, tmp_path, new_only=new_only)
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
        fires, fetched_at = build_map.fetch_all_fires(LOOKBACK_DAYS)

        failures = 0
        for output_name, new_only, label in [
            ("wildcad_fires.png", False, "standard"),
            ("wildcad_new_fires.png", True, "new-only"),
        ]:
            try:
                publish(fires, fetched_at, output_name, new_only)
                log(f"{label}: succeeded -- {output_name} updated.")
            except Exception as e:
                failures += 1
                log(f"{label}: FAILED ({e}) -- leaving its previous published image in place.")
        return 1 if failures else 0
    except Exception as e:
        log(f"Fetch FAILED ({e}) -- skipping this tick entirely, neither product has fresh data.")
        return 1
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    sys.exit(main())

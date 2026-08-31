#!/usr/bin/env python3
"""
Cron entry point for the droplet deployment. Fetches the latest Tempest
sea-level-pressure observations, then renders and atomically publishes
hermiston_pressure.png with the day's high/low marked.

A failed Tempest fetch is fatal -- there's no fallback source for a
personal station's own observations, so this tick publishes nothing and
leaves the previous image in place.

Scheduled every 5 minutes (see deploy/crontab.example), same cadence and
reasoning as tempest-temp-chart/deploy/publish_tempest.py.

An flock-based lock means an overlapping cron tick (e.g. a slow run still
in progress when the next scheduled tick fires) skips instead of running
a second pass concurrently.
"""
import fcntl
import os
import subprocess
import sys
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # tempest-pressure-chart/
STATE_DIR = os.path.join(BASE_DIR, "state")
LOCK_FILE = os.path.join(STATE_DIR, "run.lock")
LOG_FILE = os.path.join(STATE_DIR, "publish.log")
PYTHON = os.path.join(BASE_DIR, "venv", "bin", "python3")

OUTPUT_NAME = "hermiston_pressure.png"

# Where nginx serves static files from -- see
# ../../tri-cities-7day-forecast/deploy/nginx-images.conf, reused as-is.
WEB_ROOT = "/var/www/images"

sys.path.insert(0, BASE_DIR)
import build_chart  # noqa: E402


def log(msg):
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


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
        obs_path = os.path.join(BASE_DIR, "tempest_pressure_obs.json")

        subprocess.run([PYTHON, "fetch_tempest.py"], cwd=BASE_DIR, check=True, env=env)

        # Same atomic-rename pattern as every other published image in
        # this repo: render to a temp file with a real .png suffix
        # (matplotlib's savefig needs that to pick the right format), then
        # replace so nginx never serves a half-written file mid-save.
        final_path = os.path.join(WEB_ROOT, OUTPUT_NAME)
        tmp_path = os.path.join(WEB_ROOT, f".tmp_{OUTPUT_NAME}")
        build_chart.build_chart(obs_path, tmp_path)
        os.replace(tmp_path, final_path)
        log(f"succeeded -- {OUTPUT_NAME} updated.")
        return 0
    except subprocess.CalledProcessError as e:
        log(f"fetch_tempest.py FAILED ({e}) -- skipping this tick entirely, no fresh Tempest data.")
        return 1
    except Exception as e:
        log(f"Build FAILED ({e}) -- leaving previous published image in place.")
        return 1
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    sys.exit(main())

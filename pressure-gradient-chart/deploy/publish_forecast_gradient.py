#!/usr/bin/env python3
"""
Cron entry point for the droplet deployment. Fetches the past day's
observed PDX/HRI gradient plus the next 5 days from WindBorne MetaMesh,
then renders and atomically publishes pdx_hri_gradient_forecast.png.

A failed fetch is fatal -- there's no fallback source for either segment,
so this tick publishes nothing and leaves the previous image in place.

Scheduled hourly (see deploy/crontab.example) -- MetaMesh reruns on its
own schedule under an hour, but the forecast itself doesn't change fast
enough to justify the observed-only chart's 15-minute cadence, and this
avoids spending WB_API_KEY's request quota faster than needed.

An flock-based lock means an overlapping cron tick (e.g. a slow run still
in progress when the next scheduled tick fires) skips instead of running a
second pass concurrently -- same pattern as every other cron entry point
in this repo (see columbia-basin-alerts-map/deploy/publish_alerts.py).
"""
import fcntl
import os
import subprocess
import sys
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # pressure-gradient-chart/
STATE_DIR = os.path.join(BASE_DIR, "state")
LOCK_FILE = os.path.join(STATE_DIR, "forecast_run.lock")
LOG_FILE = os.path.join(STATE_DIR, "publish.log")
PYTHON = os.path.join(BASE_DIR, "venv", "bin", "python3")

OUTPUT_NAME = "pdx_hri_gradient_forecast.png"

# Where nginx serves static files from -- see
# ../../tri-cities-7day-forecast/deploy/nginx-images.conf, reused as-is.
WEB_ROOT = "/var/www/images"

sys.path.insert(0, BASE_DIR)
import build_forecast_chart  # noqa: E402


def log(msg):
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def main():
    os.makedirs(STATE_DIR, exist_ok=True)
    # A separate lock file from publish_gradient.py's own run.lock -- the
    # two publish scripts fetch/render independently and shouldn't block
    # each other just because both happen to be mid-run at once.
    lock_fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("Previous forecast run still in progress -- skipping this tick.")
        return 0

    try:
        log("Starting scheduled forecast build.")
        env = os.environ.copy()
        obs_path = os.path.join(BASE_DIR, "gradient_forecast.json")

        subprocess.run([PYTHON, "fetch_metamesh_gradient.py"], cwd=BASE_DIR, check=True, env=env)

        final_path = os.path.join(WEB_ROOT, OUTPUT_NAME)
        tmp_path = os.path.join(WEB_ROOT, f".tmp_{OUTPUT_NAME}")
        build_forecast_chart.build_forecast_chart(obs_path, tmp_path)
        os.replace(tmp_path, final_path)
        log(f"succeeded -- {OUTPUT_NAME} updated.")
        return 0
    except subprocess.CalledProcessError as e:
        log(f"fetch_metamesh_gradient.py FAILED ({e}) -- skipping this tick entirely.")
        return 1
    except Exception as e:
        log(f"Build FAILED ({e}) -- leaving previous published image in place.")
        return 1
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    sys.exit(main())

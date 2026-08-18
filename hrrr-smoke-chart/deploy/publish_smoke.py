#!/usr/bin/env python3
"""
Cron entry point for the droplet deployment. Fetches the latest complete
HRRR 00/06/12/18z cycle once (every region's 5 cities in one pass -- see
fetch_smoke.py's DEFAULT_LOCATIONS), then renders and atomically publishes
all 6 charts from that single fetch: 3 regions (Columbia Basin, Willamette
Valley, Puget Sound) x 2 variables (near-surface, vertically integrated).
One chart failing doesn't stop the others, same pattern as every other
publish script in this repo.

Scheduled every 6 hours, ~2h05m past each synoptic cycle's init time (see
deploy/crontab.example for exact times) -- verified directly against
AWS's HRRR bucket that every cycle's F48 GRIB2 posts consistently at
~1h44-47m after init, so this leaves a ~20min cushion past that observed
posting time. fetch_smoke.py's own select_latest_48h_run() looks back
through cycles for one it can actually fetch in full, so an occasional
late-posting run just means this tick picks up the previous
(already-complete) cycle instead of failing outright -- self-correcting
on the next tick, which is what makes this tight a buffer an acceptable
trade for fresher charts rather than a real reliability risk.

An flock-based lock means an overlapping cron tick (e.g. a slow run still
in progress when the next scheduled tick fires) skips instead of running
a second pass concurrently.
"""
import fcntl
import os
import sys
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # hrrr-smoke-chart/
STATE_DIR = os.path.join(BASE_DIR, "state")
LOCK_FILE = os.path.join(STATE_DIR, "run.lock")
LOG_FILE = os.path.join(STATE_DIR, "publish.log")

# Both charts are always raw units (not AQI) for this deployment -- see
# ../README.md for why (matches NOAA's own field names/units directly,
# and keeps Vertically Integrated Smoke -- always raw, no AQI equivalent
# -- and Near-Surface Smoke on the same footing as a pair).
UNITS = "raw"

# Where nginx serves static files from -- see
# ../../tri-cities-7day-forecast/deploy/nginx-images.conf, reused as-is.
WEB_ROOT = "/var/www/images"

sys.path.insert(0, BASE_DIR)
import fetch_smoke  # noqa: E402
import build_chart  # noqa: E402


def log(msg):
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def publish(data, region, variable, output_name):
    final_path = os.path.join(WEB_ROOT, output_name)
    # Same atomic-rename pattern as every other published image in this
    # repo: render to a temp file with a real .png suffix (matplotlib's
    # savefig needs that to pick the right format), then replace so nginx
    # never serves a half-written file mid-save.
    tmp_path = os.path.join(WEB_ROOT, f".tmp_{output_name}")
    build_chart.build_chart(data, region, variable, UNITS, tmp_path)
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
        run_init = fetch_smoke.select_latest_48h_run()
        log(f"Using HRRR {run_init:%Y-%m-%d %H}z (most recent complete 48h run).")
        times, variables = fetch_smoke.fetch(fetch_smoke.DEFAULT_LOCATIONS, run_init)
        data = {
            "initialization_time": run_init.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "locations": fetch_smoke.DEFAULT_LOCATIONS,
            "times": times,
            "variables": variables,
        }

        failures = 0
        for region_key, region_cfg in fetch_smoke.REGIONS.items():
            for var_key, var_meta in build_chart.VARIABLES.items():
                output_name = f"hrrr_{region_key}_{var_key}_smoke.png"
                try:
                    publish(data, region_key, var_key, output_name)
                    log(f"{region_cfg['title']} / {var_meta['title']}: succeeded -- {output_name} updated.")
                except Exception as e:
                    failures += 1
                    log(f"{region_cfg['title']} / {var_meta['title']}: FAILED ({e}) "
                        f"-- leaving its previous published image in place.")
        return 1 if failures else 0
    except Exception as e:
        log(f"Fetch FAILED ({e}) -- skipping this tick entirely, no chart has fresh data.")
        return 1
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
One-off recovery for the 5-day lightning archive after publish_daily.py
has missed days (e.g. the fetch was getting OOM-killed). Instead of the
normal "shift day1-4 down, render a new day1" rotation -- which would just
push stale images into day2-5 under the wrong slots -- this re-renders
each slot from scratch for its correct Pacific date:

    day N = today (PT) minus N days

then records today's PT date in state/last_rotation_date.txt so the next
hourly publish_daily.py tick is a no-op and normal rotation resumes
after midnight PT. Takes the same lock as publish_daily.py, so it never
overlaps a cron run.

Memory: this parent process deliberately never imports build_map (cartopy
plus its per-region basemap caches). The fetch and every region's render
each run in their own short-lived subprocess, so memory is returned to
the OS after each step -- doing the renders in-process got the backfill
OOM-killed on the 2 GiB droplet.

Usage (on the droplet, from columbia-basin-lightning-daily-map/):
    venv/bin/python3 deploy/backfill_daily.py              # days 5..1
    venv/bin/python3 deploy/backfill_daily.py --days 4 3 2 1
"""
import argparse
import fcntl
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")

# Keep in sync with publish_daily.py.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # columbia-basin-lightning-daily-map/
STATE_DIR = os.path.join(BASE_DIR, "state")
LOCK_FILE = os.path.join(STATE_DIR, "run.lock")
LOG_FILE = os.path.join(STATE_DIR, "publish.log")
LAST_ROTATION_FILE = os.path.join(STATE_DIR, "last_rotation_date.txt")
PYTHON = os.path.join(BASE_DIR, "venv", "bin", "python3")
WEB_ROOT = "/var/www/images"


def log(msg):
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def region_bases():
    """{region_key: output_base}, read in a throwaway subprocess so this
    process never loads build_map/cartopy itself."""
    code = ("import build_map\n"
            "for k, c in build_map.REGIONS.items(): print(k, c['output_base'])")
    out = subprocess.run([PYTHON, "-c", code], cwd=BASE_DIR, check=True,
                         capture_output=True, text=True).stdout
    return dict(line.split() for line in out.strip().splitlines())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, nargs="+", default=[5, 4, 3, 2, 1],
                    choices=[1, 2, 3, 4, 5],
                    help="Archive slots to rebuild (default: 5 4 3 2 1).")
    args = ap.parse_args()

    os.makedirs(STATE_DIR, exist_ok=True)
    lock_fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("publish_daily.py is running right now -- try again in a few minutes.")
        return 1

    try:
        today_pt = datetime.now(PACIFIC).date()
        lightning_path = os.path.join(BASE_DIR, "lightning_daily.json")
        bases = region_bases()
        failures = 0
        for day_n in sorted(set(args.days), reverse=True):
            pt_date = today_pt - timedelta(days=day_n)
            log(f"Backfill: day{day_n} = {pt_date.isoformat()} PT")
            try:
                subprocess.run(
                    [PYTHON, "fetch_lightning.py", "--pt-date", pt_date.isoformat()],
                    cwd=BASE_DIR, check=True,
                )
            except subprocess.CalledProcessError as e:
                failures += 1
                log(f"Backfill day{day_n}: fetch FAILED ({e}) -- slot left as it was.")
                continue
            for region_key, output_base in bases.items():
                final_path = os.path.join(WEB_ROOT, f"{output_base}_day{day_n}.png")
                tmp_path = os.path.join(WEB_ROOT, f".tmp_{output_base}_day{day_n}.png")
                try:
                    subprocess.run(
                        [PYTHON, "build_map.py", "--region", region_key,
                         "--lightning", lightning_path, "--output", tmp_path],
                        cwd=BASE_DIR, check=True,
                    )
                    os.replace(tmp_path, final_path)
                    log(f"Backfill day{day_n} {region_key}: succeeded.")
                except (subprocess.CalledProcessError, OSError) as e:
                    failures += 1
                    log(f"Backfill day{day_n} {region_key}: FAILED ({e}).")
        with open(LAST_ROTATION_FILE, "w") as f:
            f.write(today_pt.isoformat())
        log(f"Backfill done with {failures} failure(s); marked {today_pt.isoformat()} PT as rotated.")
        return 1 if failures else 0
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    sys.exit(main())

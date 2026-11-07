#!/usr/bin/env python3
"""
One-off recovery for the 5-day lightning archive after publish_daily.py
has missed days (e.g. the fetch was getting OOM-killed). Instead of the
normal "shift day1-4 down, render a new day1" rotation -- which would just
push stale images into day2-5 under the wrong slots -- this re-renders
every slot from scratch for its correct Pacific date:

    day N = today (PT) minus N days, for N = 5 down to 1

then records today's PT date in state/last_rotation_date.txt so the next
hourly publish_daily.py tick is a no-op and normal rotation resumes
tomorrow. Takes the same lock as publish_daily.py, so it never overlaps a
cron run.

Usage (on the droplet):
    venv/bin/python3 deploy/backfill_daily.py
"""
import fcntl
import os
import subprocess
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import publish_daily as pd  # noqa: E402


def publish_slot(region_key, lightning_path, day_n):
    output_base = pd.build_map.REGIONS[region_key]["output_base"]
    final_path = os.path.join(pd.WEB_ROOT, f"{output_base}_day{day_n}.png")
    tmp_path = os.path.join(pd.WEB_ROOT, f".tmp_{output_base}_day{day_n}.png")
    pd.build_map.build_map(region_key, lightning_path, tmp_path)
    os.replace(tmp_path, final_path)


def main():
    os.makedirs(pd.STATE_DIR, exist_ok=True)
    lock_fd = open(pd.LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("publish_daily.py is running right now -- try again in a few minutes.")
        return 1

    try:
        today_pt = datetime.now(pd.PACIFIC).date()
        lightning_path = os.path.join(pd.BASE_DIR, "lightning_daily.json")
        failures = 0
        for day_n in range(5, 0, -1):
            pt_date = today_pt - timedelta(days=day_n)
            pd.log(f"Backfill: day{day_n} = {pt_date.isoformat()} PT")
            try:
                subprocess.run(
                    [pd.PYTHON, "fetch_lightning.py", "--pt-date", pt_date.isoformat()],
                    cwd=pd.BASE_DIR, check=True,
                )
            except subprocess.CalledProcessError as e:
                failures += 1
                pd.log(f"Backfill day{day_n}: fetch FAILED ({e}) -- slot left as it was.")
                continue
            for region_key in pd.build_map.REGIONS:
                try:
                    publish_slot(region_key, lightning_path, day_n)
                    pd.log(f"Backfill day{day_n} {region_key}: succeeded.")
                except Exception as e:
                    failures += 1
                    pd.log(f"Backfill day{day_n} {region_key}: FAILED ({e}).")
        pd.mark_rotated(today_pt.isoformat())
        pd.log(f"Backfill done with {failures} failure(s); marked {today_pt.isoformat()} PT as rotated.")
        return 1 if failures else 0
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    sys.exit(main())

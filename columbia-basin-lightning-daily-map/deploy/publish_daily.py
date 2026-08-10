#!/usr/bin/env python3
"""
Cron entry point for the droplet deployment. Maintains a 5-day rolling
archive (Day-1 = yesterday ... Day-5 = 5 days ago) per region, published
as <output_base>_day{1..5}.png.

Meant to run shortly after midnight Pacific time -- but rather than
relying on a precisely-tuned UTC cron minute (which would need a DST-
aware offset to stay "shortly after midnight PT" year-round), this script
is idempotent per Pacific calendar date: it records the PT date it last
rotated for in state/last_rotation_date.txt, and no-ops if today's PT
date has already been handled. deploy/crontab.example runs this hourly,
so the exact minute doesn't matter -- whichever hourly tick is first to
run after midnight PT does the day's rotation, and every other tick that
day is a fast no-op.

Rotation, per region, run BEFORE fetching new data:
    for i in 5, 4, 3, 2:
        if <output_base>_day{i-1}.png exists:
            rename it to <output_base>_day{i}.png (overwriting, which is
            exactly how the old Day-5 gets dropped)
Processing i from 5 down to 2 (not the other order) matters -- it moves
the oldest slot first, before that slot's would-be source has itself been
overwritten by an earlier step. After the loop, the day1 slot is free.
On a first run (no files exist yet), every "if exists" check is false, so
the loop is a no-op and only day1 gets created -- no special-casing
needed for "first run only pulls yesterday".

Fetches once (every region reads the same domain-spanning
lightning_daily.json -- see fetch_lightning.py), then renders and
atomically publishes each region's fresh Day-1 image independently, same
one-failure-doesn't-block-others pattern as every other publish script in
this repo.

An flock-based lock means an overlapping cron tick (e.g. a slow run still
in progress when the next scheduled tick fires) skips instead of running
a second pass concurrently.
"""
import fcntl
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # columbia-basin-lightning-daily-map/
STATE_DIR = os.path.join(BASE_DIR, "state")
LOCK_FILE = os.path.join(STATE_DIR, "run.lock")
LOG_FILE = os.path.join(STATE_DIR, "publish.log")
LAST_ROTATION_FILE = os.path.join(STATE_DIR, "last_rotation_date.txt")
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


def already_rotated_today(today_pt_str):
    if not os.path.exists(LAST_ROTATION_FILE):
        return False
    with open(LAST_ROTATION_FILE) as f:
        return f.read().strip() == today_pt_str


def mark_rotated(today_pt_str):
    with open(LAST_ROTATION_FILE, "w") as f:
        f.write(today_pt_str)


def rotate_region(output_base):
    """Shift day{1..4} -> day{2..5}, dropping the old day5. See module
    docstring for why this must process i descending from 5."""
    for i in range(5, 1, -1):
        src = os.path.join(WEB_ROOT, f"{output_base}_day{i - 1}.png")
        dst = os.path.join(WEB_ROOT, f"{output_base}_day{i}.png")
        if os.path.exists(src):
            os.replace(src, dst)


def publish_region_day1(region_key, lightning_path):
    output_base = build_map.REGIONS[region_key]["output_base"]
    final_path = os.path.join(WEB_ROOT, f"{output_base}_day1.png")
    # Same atomic-rename pattern as every other published image in this
    # repo: render to a temp file, then replace so nginx never serves a
    # half-written file mid-save.
    tmp_path = os.path.join(WEB_ROOT, f".tmp_{output_base}_day1.png")
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
        now_pt = datetime.now(PACIFIC)
        today_pt_str = now_pt.date().isoformat()
        if already_rotated_today(today_pt_str):
            log(f"Already rotated for {today_pt_str} PT -- nothing to do this tick.")
            return 0

        yesterday_pt = (now_pt - timedelta(days=1)).date()
        log(f"Starting daily rotation for {yesterday_pt.isoformat()} PT (today is {today_pt_str} PT).")

        lightning_path = os.path.join(BASE_DIR, "lightning_daily.json")
        subprocess.run(
            [PYTHON, "fetch_lightning.py", "--pt-date", yesterday_pt.isoformat()],
            cwd=BASE_DIR, check=True,
        )

        failures = 0
        for region_key, cfg in build_map.REGIONS.items():
            try:
                rotate_region(cfg["output_base"])
                publish_region_day1(region_key, lightning_path)
                log(f"{region_key}: succeeded -- {cfg['output_base']}_day1.png updated, "
                    f"day2-5 rotated.")
            except Exception as e:
                failures += 1
                log(f"{region_key}: FAILED ({e}) -- day1-5 left as they were.")

        # Mark the date as handled even if some regions failed -- a
        # region failure is retried by fixing the underlying problem and
        # re-running manually, not by hammering the same PT date every
        # hour for the rest of the day (which would re-rotate on every
        # subsequent tick, corrupting the 5-day window).
        mark_rotated(today_pt_str)
        return 1 if failures else 0
    except subprocess.CalledProcessError as e:
        log(f"fetch_lightning.py FAILED ({e}) -- skipping rotation entirely, no region touched.")
        return 1
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    sys.exit(main())

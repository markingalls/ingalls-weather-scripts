#!/usr/bin/env python3
"""
Cron entry point for the droplet deployment. Maintains a 5-day rolling
archive of complete, past days (Day-1 = yesterday ... Day-5 = 5 days ago),
published as hermiston_temp_day{1..5}.png -- a look-back companion to the
always-current hermiston_temp.png publish_tempest.py maintains every 5
minutes.

Same rotation/idempotency logic as
columbia-basin-lightning-daily-map/deploy/publish_daily.py's nightly
refresh, just for one station instead of several regions:

Meant to run shortly after midnight Pacific time -- but rather than
relying on a precisely-tuned UTC cron minute (which would need a DST-
aware offset to stay "shortly after midnight PT" year-round), this script
is idempotent per Pacific calendar date: it records the PT date it last
rotated for in state/last_rotation_date.txt, and no-ops if today's PT
date has already been handled. deploy/crontab.example runs this hourly
(at :10 past, so the tick that lands right after midnight PT publishes
within 10 minutes of it -- see that file's comment for why :10-past-the-
hour, specifically, stays aligned to :10 PT year-round despite DST), so
the exact tick doesn't matter for correctness -- whichever one is first
to run after midnight PT does the day's rotation, and every other tick
that day is a fast no-op.

Rotation, run BEFORE fetching new data:
    for i in 5, 4, 3, 2:
        if hermiston_temp_day{i-1}.png exists:
            rename it to hermiston_temp_day{i}.png (overwriting, which is
            exactly how the old Day-5 gets dropped)
Processing i from 5 down to 2 (not the other order) matters -- it moves
the oldest slot first, before that slot's would-be source has itself been
overwritten by an earlier step. After the loop, the day1 slot is free. On
a first run (no files exist yet), every "if exists" check is false, so
the loop is a no-op and only day1 gets created -- the archive fills in
naturally over the first 5 days after this is deployed, no special-
casing needed (same as lightning-daily; see build_lookback_charts.py if
an immediate full backfill is wanted instead of waiting).

Renders with --no-current-conditions (day1 is a complete, past day, not
still in progress -- there's no "current" reading to highlight) and both
extremes marked (a full day's low/high are already known, unlike
today's still-in-progress chart where marking them is opt-in).

Fetches into tempest_obs_daily.json, deliberately not the plain
tempest_obs.json publish_tempest.py's own every-5-minutes tick reads and
writes -- these two cron jobs run independently (separate lock files) and
could tick concurrently, so sharing one file would risk one script
reading the other's half-written data. Same reasoning for pointing
--forecast at a path that's never written (a past day has no forecast to
extend the axis with -- fetch_forecast.py only ever pulls today's).

An flock-based lock (state/daily_run.lock, distinct from publish_tempest.py's
state/run.lock) means an overlapping cron tick (e.g. a slow run still in
progress when the next scheduled tick fires) skips instead of running a
second pass concurrently -- and doesn't contend with publish_tempest.py's
own every-5-minutes lock either.
"""
import fcntl
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# Hardcoded rather than read from the station's own /stations timezone
# (which fetch_tempest.py does use) -- this script has to know "today" in
# order to decide whether to run at all, before any API call, and the
# single station this project has ever pointed at is Pacific-time (same
# assumption build_chart.py's own "...  PT" subtitle text already makes).
PACIFIC = ZoneInfo("America/Los_Angeles")

N_DAYS = 5
OUTPUT_BASE = "hermiston_temp"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # tempest-temp-chart/
STATE_DIR = os.path.join(BASE_DIR, "state")
LOCK_FILE = os.path.join(STATE_DIR, "daily_run.lock")
LOG_FILE = os.path.join(STATE_DIR, "publish.log")
LAST_ROTATION_FILE = os.path.join(STATE_DIR, "last_rotation_date.txt")
PYTHON = os.path.join(BASE_DIR, "venv", "bin", "python3")

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


def already_rotated_today(today_pt_str):
    if not os.path.exists(LAST_ROTATION_FILE):
        return False
    with open(LAST_ROTATION_FILE) as f:
        return f.read().strip() == today_pt_str


def mark_rotated(today_pt_str):
    with open(LAST_ROTATION_FILE, "w") as f:
        f.write(today_pt_str)


def rotate():
    """Shift day{1..4} -> day{2..5}, dropping the old day5. See module
    docstring for why this must process i descending from 5."""
    for i in range(N_DAYS, 1, -1):
        src = os.path.join(WEB_ROOT, f"{OUTPUT_BASE}_day{i - 1}.png")
        dst = os.path.join(WEB_ROOT, f"{OUTPUT_BASE}_day{i}.png")
        if os.path.exists(src):
            os.replace(src, dst)


def publish_day1(obs_path, forecast_path):
    final_path = os.path.join(WEB_ROOT, f"{OUTPUT_BASE}_day1.png")
    # Same atomic-rename pattern as every other published image in this
    # repo: render to a temp file, then replace so nginx never serves a
    # half-written file mid-save.
    tmp_path = os.path.join(WEB_ROOT, f".tmp_{OUTPUT_BASE}_day1.png")
    build_chart.build_chart(obs_path, forecast_path, tmp_path,
                             mark_low=True, mark_high=True, no_current_conditions=True)
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

        obs_path = os.path.join(BASE_DIR, "tempest_obs_daily.json")
        missing_forecast_path = os.path.join(BASE_DIR, "forecast_daily_unused.json")

        subprocess.run([PYTHON, "fetch_tempest.py", "--date", yesterday_pt.isoformat(),
                         "--output", obs_path], cwd=BASE_DIR, check=True)

        try:
            rotate()
            publish_day1(obs_path, missing_forecast_path)
            log(f"succeeded -- {OUTPUT_BASE}_day1.png updated, day2-5 rotated.")
        except Exception as e:
            # Marked rotated below regardless -- a render failure needs a
            # human fix, not hourly retry-hammering of the same PT date
            # for the rest of the day (same reasoning as lightning-daily's
            # per-region failure handling).
            log(f"FAILED ({e}) -- day1-5 left as they were.")

        mark_rotated(today_pt_str)
        return 0
    except subprocess.CalledProcessError as e:
        log(f"fetch_tempest.py FAILED ({e}) -- skipping rotation entirely, nothing touched. "
            f"Not marked rotated, so the next hourly tick retries.")
        return 1
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Cron entry point for western-us-noaa-outlooks on the droplet. Fetches,
builds, and publishes one or more NOAA outlook products by calling into
build_map.py's PRODUCTS registry directly.

Usage: publish_outlooks.py --products spc_severe,spc_wind_day1,spc_hail_day1

Each invocation is meant to be one NOAA issuance-time "tier" -- see
deploy/crontab.example, where different product groups are scheduled at
different times matching when NOAA actually issues each one, rather than
a single blind fixed interval for everything. Products within a tier are
built and published independently -- one failing (e.g. a source hiccup)
doesn't stop the others in the same invocation.

An flock-based lock is shared across ALL tiers (not just the invoking
one) rather than one lock per tier: cartopy/matplotlib rendering is
memory-hungry, and this droplet is memory-constrained, so it's safer to
serialize every outlook build against every other one than to risk two
tiers' rendering processes stacking up in memory at once. Individual
builds are fast (a small KML fetch + render, not a large GRIB download),
so an actual collision serializing two tiers should be rare in practice.
"""
import argparse
import fcntl
import os
import sys
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # western-us-noaa-outlooks/
sys.path.insert(0, BASE_DIR)
import build_map  # noqa: E402

STATE_DIR = os.path.join(BASE_DIR, "state")
LOCK_FILE = os.path.join(STATE_DIR, "run.lock")
LOG_FILE = os.path.join(STATE_DIR, "publish.log")

# Where nginx serves static files from -- see ../../tri-cities-7day-forecast/deploy/nginx-images.conf,
# reused as-is for this project too (same images.ingallswx.com folder).
WEB_ROOT = "/var/www/images"


def log(msg):
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def publish_one(product):
    output_name = build_map.PRODUCTS[product]["output"]
    final_path = os.path.join(WEB_ROOT, output_name)
    # Same atomic-rename pattern as the Tri-Cities deploy: render to a temp
    # file with a real .png suffix (matplotlib's savefig needs that to pick
    # the right format), then replace so nginx never serves a half-written
    # file mid-save.
    tmp_path = os.path.join(WEB_ROOT, f".tmp_{output_name}")
    build_map.build_map(product, tmp_path)
    os.replace(tmp_path, final_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--products", required=True,
                     help="Comma-separated PRODUCTS keys from build_map.py")
    args = ap.parse_args()
    products = args.products.split(",")

    os.makedirs(STATE_DIR, exist_ok=True)
    lock_fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log(f"Previous run still in progress -- skipping this tick ({args.products}).")
        return 0

    try:
        failures = 0
        for product in products:
            try:
                publish_one(product)
                log(f"{product}: succeeded -- {build_map.PRODUCTS[product]['output']} updated.")
            except (SystemExit, Exception) as e:
                # build_map.py raises SystemExit on a real fetch/parse
                # failure -- caught here (not just Exception) so one
                # product's fetch error doesn't kill the whole process
                # before the remaining products in this tier get a turn.
                failures += 1
                log(f"{product}: FAILED ({e}) -- leaving its previous published image in place.")
        return 1 if failures else 0
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    sys.exit(main())

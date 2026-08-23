"""
One-off puller of GOES-18 (GOES-West) GLM flash-level lightning
detections over the Lower Mainland / Victoria domain (Whistler N, Hope E,
Port Renfrew W, Everett S), for a single full calendar day (Pacific time).
Writes output/lightning_<date>.json.

Source: NOAA's public "noaa-goes18" bucket on AWS Open Data
(GLM-L2-LCFA product), read anonymously -- no API key or AWS account
needed. GLM-L2-LCFA files are produced every 20 seconds (~4,320/day);
flash centroid lat/lon/energy are already provided in each file, so no
satellite-projection math is needed.
"""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import boto3
import netCDF4
import numpy as np
from botocore import UNSIGNED
from botocore.config import Config

PACIFIC = ZoneInfo("America/Los_Angeles")
THIS_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = THIS_DIR / "output"

BUCKET = "noaa-goes18"  # GOES-18 is the current operational GOES-West satellite
PRODUCT = "GLM-L2-LCFA"

# Domain: Whistler (N), Hope (E), Port Renfrew (W), Everett (S), padded
# 0.5 degrees so flashes right at the map edge aren't dropped pre-plot
# (same padding convention as ../columbia-basin-lightning-map).
BBOX_PAD = 0.5
LON_MIN, LON_MAX = -124.4204 - BBOX_PAD, -121.4412 + BBOX_PAD
LAT_MIN, LAT_MAX = 47.9790 - BBOX_PAD, 50.1163 + BBOX_PAD


def hour_prefixes(start, end):
    """Yield (prefix, hour_start, hour_end) for each UTC hour bucket the
    [start, end) window touches -- GLM files are laid out under
    GLM-L2-LCFA/{year}/{day-of-year}/{hour}/ on S3."""
    cur = start.replace(minute=0, second=0, microsecond=0)
    while cur < end:
        doy = cur.timetuple().tm_yday
        prefix = f"{PRODUCT}/{cur.year}/{doy:03d}/{cur.hour:02d}/"
        yield prefix, cur, cur + timedelta(hours=1)
        cur += timedelta(hours=1)


def parse_start_time(key):
    # ..._sYYYYDDDHHMMSSs_e...  (s = scan start, DDD = day-of-year, last
    # digit of SSSs is tenths of a second)
    token = key.split("_s")[1][:14]
    dt = datetime.strptime(token[:13], "%Y%j%H%M%S")
    return dt.replace(tzinfo=timezone.utc)


def list_keys_in_window(s3, start, end):
    keys = []
    for prefix, _, _ in hour_prefixes(start, end):
        continuation = None
        while True:
            kwargs = {"Bucket": BUCKET, "Prefix": prefix}
            if continuation:
                kwargs["ContinuationToken"] = continuation
            resp = s3.list_objects_v2(**kwargs)
            for obj in resp.get("Contents", []):
                key = obj["Key"]
                if start <= parse_start_time(key) < end:
                    keys.append(key)
            if resp.get("IsTruncated"):
                continuation = resp["NextContinuationToken"]
            else:
                break
    return keys


def download(s3, key):
    return s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()


def extract_flashes(key, blob):
    ds = netCDF4.Dataset("inmem", memory=blob)
    try:
        lat = ds.variables["flash_lat"][:]
        lon = ds.variables["flash_lon"][:]
        energy = ds.variables["flash_energy"][:]  # Joules, auto-scaled
    finally:
        ds.close()
    file_time = parse_start_time(key)
    mask = (lon >= LON_MIN) & (lon <= LON_MAX) & (lat >= LAT_MIN) & (lat <= LAT_MAX)
    records = []
    for la, lo, en in zip(lat[mask], lon[mask], energy[mask]):
        records.append({
            "lat": float(la),
            "lon": float(lo),
            "energy_j": float(en) if en is not np.ma.masked else None,
            "time": file_time.isoformat(),
        })
    return records


def fetch_window(start, end):
    s3 = boto3.client("s3", config=Config(signature_version=UNSIGNED, max_pool_connections=32))

    keys = list_keys_in_window(s3, start, end)
    print(f"Found {len(keys)} GLM-L2-LCFA files between {start.isoformat()} and {end.isoformat()}")

    with ThreadPoolExecutor(max_workers=24) as ex:
        blobs = list(ex.map(lambda k: download(s3, k), keys))

    # netCDF4/HDF5 isn't thread-safe -- parse sequentially after the
    # concurrent (I/O-bound) download pass above.
    records = []
    for key, blob in zip(keys, blobs):
        records.extend(extract_flashes(key, blob))

    return records


def parse_date_pt(value):
    """Accepts 'YYYY-MM-DD' (Pacific time). Defaults to yesterday (Pacific)
    if not given."""
    if value is None:
        return (datetime.now(PACIFIC) - timedelta(days=1)).date()
    return datetime.strptime(value, "%Y-%m-%d").date()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, default=None,
                         help="Calendar day to fetch, Pacific time, as 'YYYY-MM-DD'. "
                              "Defaults to yesterday.")
    args = parser.parse_args()

    date = parse_date_pt(args.date)
    start_pt = datetime(date.year, date.month, date.day, tzinfo=PACIFIC)
    start = start_pt.astimezone(timezone.utc)
    end = start + timedelta(hours=24)

    records = fetch_window(start, end)
    print(f"Flashes within the Lower Mainland / Victoria domain: {len(records)}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"lightning_{date.isoformat()}.json"
    out = {
        "date_pt": date.isoformat(),
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "satellite": "GOES-18 (GOES-West)",
        "product": PRODUCT,
        "flashes": records,
    }
    json.dump(out, open(out_path, "w"))
    print(f"Saved {out_path}")

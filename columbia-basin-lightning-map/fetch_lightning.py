"""
Pulls the last 24 hours of GOES-18 (GOES-West) GLM flash-level lightning
detections over the Columbia Basin and writes lightning_last24h.json. Run
this before build_map.py any time you want the map to reflect right-now
conditions instead of a stale snapshot.

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
from zoneinfo import ZoneInfo

import boto3
import netCDF4
import numpy as np
from botocore import UNSIGNED
from botocore.config import Config

PACIFIC = ZoneInfo("America/Los_Angeles")

BUCKET = "noaa-goes18"  # GOES-18 is the current operational GOES-West satellite
PRODUCT = "GLM-L2-LCFA"
LOOKBACK_HOURS = 24

# Same domain as ../columbia-basin-alerts-map and ../columbia-basin-temps,
# padded a bit so flashes right at the map edge aren't dropped pre-plot.
BBOX_PAD = 0.5
LON_MIN, LON_MAX = -122.5 - BBOX_PAD, -117.0 + BBOX_PAD
LAT_MIN, LAT_MAX = 44.4 - BBOX_PAD, 48.0 + BBOX_PAD


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


def fetch_last_24h(end=None):
    s3 = boto3.client("s3", config=Config(signature_version=UNSIGNED, max_pool_connections=32))
    if end is None:
        end = datetime.now(timezone.utc)
    start = end - timedelta(hours=LOOKBACK_HOURS)

    keys = list_keys_in_window(s3, start, end)
    print(f"Found {len(keys)} GLM-L2-LCFA files between {start.isoformat()} and {end.isoformat()}")

    with ThreadPoolExecutor(max_workers=24) as ex:
        blobs = list(ex.map(lambda k: download(s3, k), keys))

    # netCDF4/HDF5 isn't thread-safe -- parse sequentially after the
    # concurrent (I/O-bound) download pass above.
    records = []
    for key, blob in zip(keys, blobs):
        records.extend(extract_flashes(key, blob))

    return records, start, end


def parse_end_pt(value):
    """Accepts 'HH:MM' (assumed to be today, Pacific time) or
    'YYYY-MM-DD HH:MM' (Pacific time)."""
    try:
        naive = datetime.strptime(value, "%Y-%m-%d %H:%M")
    except ValueError:
        today_pt = datetime.now(PACIFIC).date()
        naive = datetime.combine(today_pt, datetime.strptime(value, "%H:%M").time())
    return naive.replace(tzinfo=PACIFIC)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--end-pt",
                         help="End of the 24-hour lookback window, Pacific time -- "
                              "'HH:MM' (today) or 'YYYY-MM-DD HH:MM'. Defaults to now.")
    args = parser.parse_args()

    end = parse_end_pt(args.end_pt).astimezone(timezone.utc) if args.end_pt else None
    records, start, end = fetch_last_24h(end=end)
    print(f"Flashes within the Columbia Basin domain: {len(records)}")
    out = {
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "satellite": "GOES-18 (GOES-West)",
        "product": PRODUCT,
        "flashes": records,
    }
    json.dump(out, open("lightning_last24h.json", "w"))
    print("Saved lightning_last24h.json")

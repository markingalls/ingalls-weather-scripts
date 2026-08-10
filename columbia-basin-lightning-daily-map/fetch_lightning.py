"""
Pulls a full Pacific-time calendar day of GOES-18 (GOES-West) GLM
flash-level lightning detections over a domain spanning all four regions
in build_map.py's REGIONS (Columbia Basin, Portland, Pacific NW, BC
Interior) and writes lightning_daily.json. Defaults to yesterday (PT) --
see deploy/publish_daily.py for how this fits into the 5-day rotating
archive. Companion to ../columbia-basin-lightning-map (24h) and
../columbia-basin-lightning-realtime-map (2h); see the 24h project's
fetch_lightning.py for the fuller write-up of the GLM data source itself.

Source: NOAA's public "noaa-goes18" bucket on AWS Open Data
(GLM-L2-LCFA product), read anonymously -- no API key or AWS account
needed.
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

# Union of all four REGIONS extents in build_map.py (columbia_basin,
# portland, pnw, bc_interior), padded a bit so flashes right at any
# region's map edge aren't dropped pre-plot. See ../columbia-basin-
# lightning-map/fetch_lightning.py for how these bounds were derived.
BBOX_PAD = 0.5
LON_MIN, LON_MAX = -125.8 - BBOX_PAD, -112.8 + BBOX_PAD
LAT_MIN, LAT_MAX = 40.5 - BBOX_PAD, 52.47 + BBOX_PAD


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


def fetch_pt_day(pt_date):
    """pt_date: a date object -- the Pacific-time calendar day to fetch,
    midnight to midnight. Returns (records, start_utc, end_utc, pt_date)."""
    start_pt = datetime.combine(pt_date, datetime.min.time(), tzinfo=PACIFIC)
    end_pt = start_pt + timedelta(days=1)
    start = start_pt.astimezone(timezone.utc)
    end = end_pt.astimezone(timezone.utc)

    s3 = boto3.client("s3", config=Config(signature_version=UNSIGNED, max_pool_connections=32))
    keys = list_keys_in_window(s3, start, end)
    print(f"Found {len(keys)} GLM-L2-LCFA files for {pt_date.isoformat()} PT "
          f"({start.isoformat()} to {end.isoformat()} UTC)")

    with ThreadPoolExecutor(max_workers=24) as ex:
        blobs = list(ex.map(lambda k: download(s3, k), keys))

    # netCDF4/HDF5 isn't thread-safe -- parse sequentially after the
    # concurrent (I/O-bound) download pass above.
    records = []
    for key, blob in zip(keys, blobs):
        records.extend(extract_flashes(key, blob))

    return records, start, end


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pt-date",
                         help="Pacific-time calendar day to fetch, YYYY-MM-DD. "
                              "Defaults to yesterday (PT).")
    args = parser.parse_args()

    if args.pt_date:
        pt_date = datetime.strptime(args.pt_date, "%Y-%m-%d").date()
    else:
        pt_date = (datetime.now(PACIFIC) - timedelta(days=1)).date()

    records, start, end = fetch_pt_day(pt_date)
    print(f"Flashes within the combined domain: {len(records)}")
    out = {
        "pt_date": pt_date.isoformat(),
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "satellite": "GOES-18 (GOES-West)",
        "product": PRODUCT,
        "flashes": records,
    }
    json.dump(out, open("lightning_daily.json", "w"))
    print("Saved lightning_daily.json")

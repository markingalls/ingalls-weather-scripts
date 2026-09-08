"""
Fetches a station-based "average first fall freeze" climatology for the
Pacific Northwest + southern/central BC domain from NOAA's GHCN-Daily
archive and writes climatology.json: for every qualifying station, the
1991-2020 average day each year's daily minimum temperature first drops
to <=32F (0C) after July 1.

GHCN-Daily (not ACIS, used by ../tri-cities-temp-chart/) is the source
here because it's the one daily-observation archive that actually crosses
the US/Canada border in one consistent feed -- ACIS's station coverage
into BC is thin/uncertain, but GHCN-Daily ingests Environment and Climate
Change Canada's own station reports alongside NOAA's, so the same query
against the same backend picks up both sides of the domain (confirmed by
inspecting the returned station IDs: US* and CA* prefixes both come back
from the same request).

No API key required -- station discovery is GHCN-Daily's own published
station/inventory metadata files, and the daily readings come from NCEI's
public Access Data Service (the same backend xmACIS itself sits behind,
just addressed by GHCN ID here instead of ACIS's "sid" aliases).

USAGE
-----
    python fetch_climatology.py                    # full PNW+BC domain
    python fetch_climatology.py --min-years 25      # stricter completeness
    python fetch_climatology.py --output data.json

METHODOLOGY
-----------
- Domain: same bounding box as ../dew-point-storm-map/'s BC/WA/OR/ID (+
  slivers of NV/MT/WY) map -- see LON_MIN/MAX, LAT_MIN/MAX below.
- Station discovery: ghcnd-stations.txt + ghcnd-inventory.txt (both
  published at fixed URLs, no key), filtered to stations inside the
  domain bbox whose TMIN inventory range plausibly overlaps 1991-2020
  (firstyear <= 1995 and lastyear >= 2018 -- a loose prefilter; the real
  completeness check happens after fetching each station's actual daily
  values, since the inventory's firstyear/lastyear only bounds a
  station's record, it doesn't guarantee no gaps within it).
- Daily TMIN is pulled from NCEI's Access Data Service
  (dataset=daily-summaries), batched GHCN_BATCH_SIZE station IDs per
  request (confirmed via manual testing that comma-separated station IDs
  in one request work and the service returns each station's own rows,
  not a cross-product) rather than one request per station, to keep the
  total request count and runtime reasonable across ~1,000+ candidate
  stations in this domain. The service's date range is a single
  continuous span, so requesting exactly "July-December only, every
  year" isn't expressible in one call -- this fetches the full
  1991-07-01..2020-12-31 continuous range (pulling in each year's
  Jan-Jun too, discarded client-side) rather than one request per year,
  trading roughly 2x bandwidth for far fewer HTTP requests.
- Per station, per year: the first date on or after July 1 whose TMIN
  reading is <=32F, expressed as an offset in days from that year's
  July 1 (0-183) rather than an absolute day-of-year, specifically to
  sidestep the leap-year day-of-year misalignment (Dec 31 is day 366 in
  a leap year, 365 otherwise) that would otherwise skew an average taken
  across leap and non-leap years.
- A station is kept only if at least MIN_YEARS_DEFAULT of the 30 years
  produced a qualifying freeze date (some low-elevation/coastal stations
  may not freeze at all some years, and any station can have data gaps).
  Both the mean and median day-offset are recorded; build_map.py plots
  the mean.
"""
import argparse
import csv
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import requests

STATIONS_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/ghcnd-stations.txt"
INVENTORY_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/ghcnd-inventory.txt"
DATA_URL = "https://www.ncei.noaa.gov/access/services/data/v1"

# Same domain as ../dew-point-storm-map/build_map.py's BC/WA/OR/ID (+
# slivers of NV/MT/WY) map.
LON_MIN, LON_MAX = -128.2, -108.8
LAT_MIN, LAT_MAX = 39.7, 55.2

START_YEAR, END_YEAR = 1991, 2020
FREEZE_THRESHOLD_F = 32.0

# Loose prefilter on GHCN's own inventory firstyear/lastyear (see module
# docstring) -- real completeness is checked against actual fetched days.
INVENTORY_FIRSTYEAR_MAX = 1995
INVENTORY_LASTYEAR_MIN = 2018

# A station needs a qualifying freeze date in at least this many of the
# 30 candidate years to be kept.
MIN_YEARS_DEFAULT = 20

GHCN_BATCH_SIZE = 50
MAX_WORKERS = 4
REQUEST_TIMEOUT_S = 120
MAX_RETRIES = 3

HEADERS = {"User-Agent": "ingalls-weather-scripts/pnw-first-freeze-map (contact: weather.ingalls@gmail.com)"}


def fetch_text(url):
    r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT_S)
    r.raise_for_status()
    return r.text


def load_candidate_stations():
    """Stations inside the domain bbox with a TMIN inventory span that
    plausibly overlaps 1991-2020. Returns {id: {lat, lon, elev_m, name}}."""
    print("Fetching GHCN-Daily station list...")
    stations = {}
    for line in fetch_text(STATIONS_URL).splitlines():
        if not line.strip():
            continue
        sid = line[0:11].strip()
        lat = float(line[12:20])
        lon = float(line[21:30])
        if LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX:
            stations[sid] = {
                "lat": lat,
                "lon": lon,
                "elev_m": float(line[31:37]),
                "name": line[41:71].strip(),
            }

    print(f"  {len(stations)} station(s) inside the domain bbox.")
    print("Fetching GHCN-Daily inventory (filtering to TMIN coverage of 1991-2020)...")
    candidates = {}
    for line in fetch_text(INVENTORY_URL).splitlines():
        if not line.strip():
            continue
        sid = line[0:11].strip()
        if sid not in stations or sid in candidates:
            continue
        if line[31:35].strip() != "TMIN":
            continue
        firstyear, lastyear = int(line[36:40]), int(line[41:45])
        if firstyear <= INVENTORY_FIRSTYEAR_MAX and lastyear >= INVENTORY_LASTYEAR_MIN:
            candidates[sid] = stations[sid]

    print(f"  {len(candidates)} candidate station(s) with plausible TMIN coverage.")
    return candidates


def fetch_batch_tmin(station_ids):
    """TMIN readings (whole degrees F, per units=standard) for one batch
    of station IDs, restricted to July-December of each candidate year.
    Returns {station_id: {year: [(offset_days, tmin_f), ...]}}."""
    params = {
        "dataset": "daily-summaries",
        "stations": ",".join(station_ids),
        "startDate": f"{START_YEAR}-07-01",
        "endDate": f"{END_YEAR}-12-31",
        "dataTypes": "TMIN",
        "format": "csv",
        "includeStationName": "false",
        "includeStationLocation": "false",
        "includeAttributes": "false",
        "units": "standard",
    }
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(DATA_URL, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT_S)
            r.raise_for_status()
            break
        except requests.RequestException as e:
            last_err = e
            time.sleep(2 * attempt)
    else:
        print(f"  WARNING: batch of {len(station_ids)} station(s) failed after {MAX_RETRIES} attempts: {last_err}")
        return {}

    out = {}
    reader = csv.DictReader(io.StringIO(r.text))
    for row in reader:
        tmin_raw = (row.get("TMIN") or "").strip()
        if not tmin_raw:
            continue
        d = date.fromisoformat(row["DATE"])
        if d.month < 7:
            continue  # outside the July-December window (see module docstring)
        offset = (d - date(d.year, 7, 1)).days
        out.setdefault(row["STATION"], {}).setdefault(d.year, []).append((offset, int(tmin_raw)))
    return out


def first_freeze_offsets(year_readings):
    """{year: [(offset, tmin_f), ...]} -> {year: first_freeze_offset_days}
    for years whose readings include a qualifying <=32F crossing."""
    result = {}
    for year, readings in year_readings.items():
        readings.sort()
        for offset, tmin_f in readings:
            if tmin_f <= FREEZE_THRESHOLD_F:
                result[year] = offset
                break
    return result


def offset_to_date_label(offset_days):
    """Mean offset (float, days since July 1) -> a 'Mon D' label, anchored
    on a non-leap reference year (irrelevant here since July-Dec never
    crosses Feb 29)."""
    d = date(2001, 7, 1) + timedelta(days=round(offset_days))
    return d.strftime("%b %-d")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-years", type=int, default=MIN_YEARS_DEFAULT,
                     help=f"Minimum qualifying years of {END_YEAR - START_YEAR + 1} required to keep a station "
                          f"(default: {MIN_YEARS_DEFAULT}).")
    ap.add_argument("--output", default="climatology.json")
    args = ap.parse_args()

    candidates = load_candidate_stations()
    candidate_ids = list(candidates)
    batches = [candidate_ids[i:i + GHCN_BATCH_SIZE] for i in range(0, len(candidate_ids), GHCN_BATCH_SIZE)]

    print(f"Fetching {START_YEAR}-07-01..{END_YEAR}-12-31 TMIN for {len(candidate_ids)} station(s) "
          f"in {len(batches)} batch(es) of up to {GHCN_BATCH_SIZE}...")
    raw = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(fetch_batch_tmin, batch): i for i, batch in enumerate(batches)}
        done = 0
        for fut in as_completed(futures):
            raw.update(fut.result())
            done += 1
            print(f"  batch {done}/{len(batches)} done ({len(raw)} station(s) with data so far)")

    stations_out = []
    dropped_thin = 0
    for sid, meta in candidates.items():
        year_readings = raw.get(sid)
        if not year_readings:
            dropped_thin += 1
            continue
        offsets = first_freeze_offsets(year_readings)
        if len(offsets) < args.min_years:
            dropped_thin += 1
            continue
        values = sorted(offsets.values())
        n = len(values)
        mean_offset = sum(values) / n
        median_offset = values[n // 2] if n % 2 else (values[n // 2 - 1] + values[n // 2]) / 2
        stations_out.append({
            "id": sid,
            "name": meta["name"],
            "lat": meta["lat"],
            "lon": meta["lon"],
            "elev_m": meta["elev_m"],
            "n_years": n,
            "mean_offset_days": round(mean_offset, 2),
            "median_offset_days": round(median_offset, 2),
            "mean_date": offset_to_date_label(mean_offset),
        })

    out = {
        "source": "NOAA GHCN-Daily, element TMIN (element data via NCEI Access Data Service)",
        "domain": {"lon_min": LON_MIN, "lon_max": LON_MAX, "lat_min": LAT_MIN, "lat_max": LAT_MAX},
        "period": f"{START_YEAR}-{END_YEAR}",
        "freeze_threshold_f": FREEZE_THRESHOLD_F,
        "min_years_required": args.min_years,
        "offset_reference": "days since July 1 of that year",
        "n_candidate_stations": len(candidates),
        "n_stations_kept": len(stations_out),
        "stations": stations_out,
    }
    with open(args.output, "w") as f:
        json.dump(out, f, indent=2)

    print(f"Saved {args.output}: {len(stations_out)} station(s) kept "
          f"({dropped_thin} dropped for <{args.min_years} qualifying years or no data) "
          f"of {len(candidates)} candidates.")
    if stations_out:
        earliest = min(stations_out, key=lambda s: s["mean_offset_days"])
        latest = max(stations_out, key=lambda s: s["mean_offset_days"])
        print(f"  Earliest average first freeze: {earliest['name']} ({earliest['id']}) -- {earliest['mean_date']}")
        print(f"  Latest average first freeze:   {latest['name']} ({latest['id']}) -- {latest['mean_date']}")

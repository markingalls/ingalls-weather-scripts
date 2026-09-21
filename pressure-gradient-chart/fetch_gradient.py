"""
Fetches the last N local calendar days' (default 3) near-real-time
observations for two NWS ASOS/AWOS stations and writes gradient_obs.json:
a single time series of station_a_pressure_mb - station_b_pressure_mb (the
"gradient"), paired with each station's own reading at that time.

Source: api.weather.gov's per-station /observations feed. This is NOT the
once-an-hour METAR text product -- NWS/FAA ASOS sites also transmit
"special" observations whenever conditions change, and api.weather.gov
folds all of those in, so a busy station like KPDX or KHRI actually updates
every ~5 minutes, not on a fixed synoptic schedule. No API key needed, just
a User-Agent identifying the requester. Paginates via the feed's own
`pagination.next` cursor -- a 3-day window is ~850 observations per
station, comfortably past the endpoint's 500-per-request cap.

Uses each observation's own `barometricPressure` field directly, with no
further elevation-based reduction (see Notes in README.md): despite its
name, api.weather.gov's `barometricPressure` is already an altimeter-
setting-equivalent, near-sea-level value, not a station's raw absolute
pressure -- confirmed against real METAR text for both KPDX and KHRI,
where `barometricPressure` lands within a few tenths of a mb of that same
observation's own altimeter (`A////`) and, where present, its `SLP///`
remark. Applying tempest-pressure-chart's own station-elevation barometric
formula on top of this (as an earlier version of this script did) double-
counts the elevation correction NWS already applied -- for KHRI (196 m
elevation) that inflated its reading by ~24 mb, turning a real ~3 mb
gradient into a fictitious ~20 mb one.

Defaults to KPDX (Portland Intl) minus KHRI (Hermiston Muni) -- the first
pair this project is built around. Pass --station-a/--station-b (bare
3-letter or full ICAO, e.g. "PDX" or "KPDX") to point it at a different
pair once more gradients are added.
"""
import argparse
import bisect
import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

BASE_URL = "https://api.weather.gov"
HEADERS = {"User-Agent": "(ingallswx.com, contact@ingallswx.com)"}

# A NWS station observation more than this far from its counterpart isn't
# treated as a matching pair -- the two stations' report times don't line
# up exactly (KPDX might land on :55/:00/:05, KHRI on :53/:58/:03), so
# nearest-neighbor matching needs some slack, but too much would pair up
# readings that are stale relative to each other.
MATCH_TOLERANCE = timedelta(minutes=4)

# The endpoint's own hard cap -- larger values are rejected outright, not
# just clamped -- so a multi-day window has to page via pagination.next
# rather than requesting a bigger page.
PAGE_LIMIT = 500


def normalize_station_id(station_id):
    station_id = station_id.strip().upper()
    return station_id if len(station_id) == 4 else f"K{station_id}"


def fetch_station_name(station_id):
    r = requests.get(f"{BASE_URL}/stations/{station_id}", headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()["properties"]["name"]


def fetch_observations(station_id, start_utc, end_utc):
    """Yields every observation feature in [start_utc, end_utc), following
    pagination.next as needed. The feed returns pages newest-first, so
    paging stops as soon as a page's oldest observation reaches start_utc
    -- there's nothing older left in the requested window."""
    url = f"{BASE_URL}/stations/{station_id}/observations"
    params = {"start": start_utc.isoformat(), "end": end_utc.isoformat(), "limit": PAGE_LIMIT}
    while url:
        r = requests.get(url, headers=HEADERS, params=params, timeout=30)
        r.raise_for_status()
        payload = r.json()
        features = payload["features"]
        yield from features
        oldest = datetime.fromisoformat(features[-1]["properties"]["timestamp"]) if features else None
        url = (payload.get("pagination") or {}).get("next")
        params = None  # the cursor URL already encodes start/end/limit
        if oldest is not None and oldest <= start_utc:
            break


def pressure_series(station_id, start_utc, end_utc):
    """Returns a time-ascending list of (epoch_seconds, pressure_mb) for
    one station, skipping any observation missing barometricPressure.
    Explicitly re-filters to [start_utc, end_utc) -- a paginated cursor
    page (see fetch_observations) doesn't carry the original start bound,
    so its last page can run a little past it."""
    series = []
    for feature in fetch_observations(station_id, start_utc, end_utc):
        props = feature["properties"]
        pressure_pa = (props.get("barometricPressure") or {}).get("value")
        if pressure_pa is None:
            continue
        ts = datetime.fromisoformat(props["timestamp"])
        if not (start_utc <= ts < end_utc):
            continue
        series.append((ts.timestamp(), pressure_pa / 100.0))
    series.sort(key=lambda row: row[0])
    return series


def merge_gradient(series_a, series_b, tolerance):
    """For each of series_a's own observation times (the coarser/master
    timeline -- both stations report on similar cadences, so either could
    serve as master, but a fixed choice keeps this deterministic), finds
    the nearest series_b sample within tolerance and pairs them. Drops any
    series_a time with no close-enough series_b match rather than
    interpolating across a real gap at one station."""
    times_b = [row[0] for row in series_b]
    merged = []
    for epoch_a, pressure_a in series_a:
        i = bisect.bisect_left(times_b, epoch_a)
        candidates = [j for j in (i - 1, i) if 0 <= j < len(times_b)]
        if not candidates:
            continue
        best_j = min(candidates, key=lambda j: abs(times_b[j] - epoch_a))
        if abs(times_b[best_j] - epoch_a) > tolerance.total_seconds():
            continue
        merged.append((epoch_a, pressure_a, series_b[best_j][1]))
    return merged


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--station-a", default="KPDX",
                     help="Bare 3-letter or full ICAO id, e.g. PDX or KPDX (default: KPDX)")
    ap.add_argument("--station-b", default="KHRI",
                     help="Bare 3-letter or full ICAO id, e.g. HRI or KHRI (default: KHRI)")
    ap.add_argument("--label-a", default="PDX")
    ap.add_argument("--label-b", default="HRI")
    ap.add_argument("--timezone", default="America/Los_Angeles",
                     help="Local timezone both stations are treated as sharing (default: America/Los_Angeles)")
    ap.add_argument("--days", type=int, default=3,
                     help="Trailing local calendar days to include, ending today (default: 3)")
    ap.add_argument("--date", default=None,
                     help="YYYY-MM-DD, local calendar day the window ends on (default: today, local)")
    ap.add_argument("--output", default="gradient_obs.json")
    return ap.parse_args()


if __name__ == "__main__":
    args = parse_args()
    station_a_id = normalize_station_id(args.station_a)
    station_b_id = normalize_station_id(args.station_b)
    tz = ZoneInfo(args.timezone)

    end_date = date.fromisoformat(args.date) if args.date else datetime.now(tz).date()
    start_date = end_date - timedelta(days=args.days - 1)
    window_start = datetime(start_date.year, start_date.month, start_date.day, tzinfo=tz)
    window_end = datetime(end_date.year, end_date.month, end_date.day, tzinfo=tz) + timedelta(days=1)
    start_utc = window_start.astimezone(timezone.utc)
    end_utc = min(window_end, datetime.now(tz)).astimezone(timezone.utc) + timedelta(minutes=1)

    name_a = fetch_station_name(station_a_id)
    name_b = fetch_station_name(station_b_id)

    series_a = pressure_series(station_a_id, start_utc, end_utc)
    series_b = pressure_series(station_b_id, start_utc, end_utc)
    merged = merge_gradient(series_a, series_b, MATCH_TOLERANCE)

    observations = [{
        "time": datetime.fromtimestamp(epoch, tz).isoformat(),
        "gradient_mb": round(pressure_a - pressure_b, 2),
        f"{args.label_a.lower()}_mb": round(pressure_a, 1),
        f"{args.label_b.lower()}_mb": round(pressure_b, 1),
    } for epoch, pressure_a, pressure_b in merged]

    out = {
        "source": "api.weather.gov per-station /observations feed for both stations "
                   "(NWS ASOS/AWOS specials included, ~5-minute cadence, not just the "
                   "hourly METAR). Uses barometricPressure directly -- already an "
                   "altimeter-setting-equivalent, near-sea-level value despite the field "
                   "name, not raw station pressure (see README.md) -- "
                   f"differenced as {args.label_a} minus {args.label_b}.",
        "station_a": {"id": station_a_id, "label": args.label_a, "name": name_a},
        "station_b": {"id": station_b_id, "label": args.label_b, "name": name_b},
        "timezone": args.timezone,
        "window_start": window_start.isoformat(),
        "window_days": args.days,
        "gradient_label": f"{args.label_a} minus {args.label_b}",
        "observations": observations,
    }
    with open(args.output, "w") as f:
        json.dump(out, f, indent=2)

    if observations:
        print(f"Saved {args.output}: {len(observations)} paired obs for "
              f"{args.label_a}-{args.label_b}, last {args.days} days ending {end_date} "
              f"({observations[0]['time']} .. {observations[-1]['time']})")
    else:
        print(f"Saved {args.output}: 0 paired observations for {args.label_a}-{args.label_b}, "
              f"last {args.days} days ending {end_date}")

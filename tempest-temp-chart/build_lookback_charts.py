"""
Fetches and renders a temperature chart for each of the past N station-local
calendar days (not including today) -- a "look back" companion to the
always-current today chart (build_chart.py with no flags), the same idea as
the lightning maps having both a realtime and a rolling-window view, just
per complete day here instead of a rolling time window.

Each day is fetched and rendered by shelling out to fetch_tempest.py and
build_chart.py exactly as a user would run them by hand for that date, so
behavior (day boundary handling, gap-breaking, dew point, etc.) always
matches the today chart -- this script only adds the loop over dates and
the --no-current-conditions flag (there's no "current" reading to highlight
on a complete, past day) plus --mark-low --mark-high (a full day's low/high
are already known, so there's no reason not to show them, unlike today's
still-in-progress chart where that's opt-in).

Requires a Tempest API key (get one at https://tempestwx.com/settings/tokens),
passed via --api-key or the TEMPEST_API_KEY environment variable -- same as
fetch_tempest.py, since each day's fetch re-resolves the station itself.
"""
import argparse
import os
import subprocess
import sys
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from fetch_tempest import fetch_stations, find_tempest_device  # noqa: E402

from zoneinfo import ZoneInfo

PYTHON = sys.executable


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--api-key", default=os.environ.get("TEMPEST_API_KEY"))
    ap.add_argument("--station-id", type=int, default=None,
                     help="Pin a specific station id (default: first station with a Tempest device)")
    ap.add_argument("--label", default=None, help="Display label override, passed through to "
                                                    "fetch_tempest.py for every day")
    ap.add_argument("--days", type=int, default=5,
                     help="How many past days to fetch and render (default 5)")
    ap.add_argument("--output-dir", default="lookback",
                     help="Directory for each day's obs/chart files (default: lookback/)")
    args = ap.parse_args()

    if not args.api_key:
        raise SystemExit("Tempest API key required: pass --api-key or set TEMPEST_API_KEY")

    # Only used here to resolve the station's own local calendar day, so
    # the loop below walks the right dates -- each day's own fetch_tempest.py
    # call re-resolves the station independently either way, same as running
    # it by hand.
    stations = fetch_stations(args.api_key)
    station, device = find_tempest_device(stations, args.station_id)
    if device is None:
        raise SystemExit("No Tempest ('ST') device found for this API key/station-id")
    tz = ZoneInfo(station["timezone"])
    today = datetime.now(tz).date()

    os.makedirs(os.path.join(SCRIPT_DIR, args.output_dir), exist_ok=True)
    env = os.environ.copy()
    env["TEMPEST_API_KEY"] = args.api_key

    for days_back in range(1, args.days + 1):
        target_date = today - timedelta(days=days_back)
        obs_path = os.path.join(args.output_dir, f"tempest_obs_{target_date}.json")
        chart_path = os.path.join(args.output_dir, f"tempest_temp_chart_{target_date}.png")
        # Points --forecast at a path that won't exist rather than the
        # default forecast.json -- a past day has no forecast to extend the
        # axis with (fetch_forecast.py only ever pulls today's), and this
        # keeps build_chart.py's "no forecast file" note pointing at a name
        # that makes that obvious, instead of the unrelated default.
        missing_forecast_path = os.path.join(args.output_dir, f"forecast_{target_date}.json")

        fetch_cmd = [PYTHON, "fetch_tempest.py", "--date", str(target_date), "--output", obs_path]
        if args.station_id is not None:
            fetch_cmd += ["--station-id", str(args.station_id)]
        if args.label:
            fetch_cmd += ["--label", args.label]
        subprocess.run(fetch_cmd, cwd=SCRIPT_DIR, check=True, env=env)

        build_cmd = [PYTHON, "build_chart.py", "--data", obs_path, "--forecast", missing_forecast_path,
                     "--output", chart_path, "--no-current-conditions", "--mark-low", "--mark-high"]
        subprocess.run(build_cmd, cwd=SCRIPT_DIR, check=True, env=env)

    print(f"Rendered {args.days} day(s) of look-back charts into {args.output_dir}/")


if __name__ == "__main__":
    main()

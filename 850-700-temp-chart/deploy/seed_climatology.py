#!/usr/bin/env python3
"""
One-time (or "re-run only when LOCATIONS/PRESSURE_LEVEL changes") setup
step: fetches each location's 1991-2020 climatology and caches it under
deploy/climatology/<slug>.json. publish_charts.py's hourly cron run reads
these cached files rather than re-fetching from NOAA PSL's OPeNDAP server
every cycle -- climatology is a static long-term normal, not something that
changes run to run, so re-fetching it hourly for 9 locations would just be
unnecessary load on someone else's public server for data that never
changes underneath us.

Run this once after adding/changing a location in publish_charts.py's
LOCATIONS list, or after changing PRESSURE_LEVEL. Safe to re-run any time --
it just overwrites the cached files with the same values.
"""
import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 850-700-temp-chart/
CLIMATOLOGY_DIR = os.path.join(BASE_DIR, "deploy", "climatology")
PYTHON = os.path.join(BASE_DIR, "venv", "bin", "python3")

sys.path.insert(0, os.path.join(BASE_DIR, "deploy"))
from publish_charts import LOCATIONS, PRESSURE_LEVEL  # noqa: E402


def main():
    os.makedirs(CLIMATOLOGY_DIR, exist_ok=True)
    for loc in LOCATIONS:
        output_path = os.path.join(CLIMATOLOGY_DIR, f"{loc['slug']}.json")
        print(f"Fetching climatology for {loc['label']} ({loc['slug']}) ...")
        subprocess.run(
            [PYTHON, "fetch_climatology.py", "--lat", str(loc["lat"]), "--lon", str(loc["lon"]),
             "--level", str(PRESSURE_LEVEL), "--output", output_path],
            cwd=BASE_DIR, check=True,
        )


if __name__ == "__main__":
    main()

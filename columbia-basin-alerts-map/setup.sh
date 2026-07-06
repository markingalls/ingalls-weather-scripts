#!/bin/bash
# Run once when a Claude Code cloud session starts.
# cartopy needs GDAL at the system level, and the map-kit-building side of
# this project (not needed just to run build_map.py/fetch_alerts.py, but
# harmless to have) uses osmium-tool -- both come from apt, not pip.
set -e

apt-get update
apt-get install -y gdal-bin osmium-tool

pip install -r requirements.txt

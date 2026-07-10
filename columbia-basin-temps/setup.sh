#!/bin/bash
# Run once when a Claude Code cloud session starts.
# cartopy needs GDAL, and cfgrib/eccodes (GRIB2 decoding for hrrr/ecmwf-ifs/
# ecmwf-aifs) needs libeccodes, both at the system level -- only installs
# via apt, not pip.
set -e

apt-get update
apt-get install -y gdal-bin libeccodes0 libeccodes-dev

pip install -r requirements.txt

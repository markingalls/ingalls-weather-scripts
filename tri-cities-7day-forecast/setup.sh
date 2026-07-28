#!/bin/bash
# Run once when a Claude Code cloud session starts.
# cfgrib (GRIB2 decoding for the HRRR smoke fetch) needs libeccodes at the
# system level on some platforms -- harmless to install even where the pip
# eccodes wheel already bundles its own copy.
set -e

apt-get update
apt-get install -y libeccodes0 libeccodes-dev

pip install -r requirements.txt

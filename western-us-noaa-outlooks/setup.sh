#!/bin/bash
# Run once when a Claude Code cloud session starts.
# cartopy needs GDAL at the system level, which only installs via apt, not pip.
set -e

apt-get update
apt-get install -y gdal-bin

pip install -r requirements.txt

#!/bin/bash
# Run once when a Claude Code cloud session starts.
# cartopy needs GDAL, and cfgrib/eccodes (GRIB2 decoding for RTMA) needs
# libeccodes, both at the system level -- only installs via apt, not pip.
# The Poppins font used for titles/labels isn't packaged for apt.
set -e

apt-get update
apt-get install -y gdal-bin libeccodes0 libeccodes-dev

pip install -r requirements.txt

mkdir -p /usr/share/fonts/truetype/google-fonts
for f in Poppins-Regular Poppins-SemiBold Poppins-Bold; do
  if [ ! -f "/usr/share/fonts/truetype/google-fonts/${f}.ttf" ]; then
    curl -sSL -o "/usr/share/fonts/truetype/google-fonts/${f}.ttf" \
      "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/${f}.ttf"
  fi
done

#!/bin/bash
# Run once when a Claude Code cloud session starts.
# Python deps (cfgrib/eccodes decode the GRIB2 subsets) plus the Poppins
# font used for chart text, which isn't packaged for apt.
set -e

pip install -r requirements.txt

mkdir -p /usr/share/fonts/truetype/google-fonts
for f in Poppins-Regular Poppins-Medium Poppins-Bold; do
  if [ ! -f "/usr/share/fonts/truetype/google-fonts/${f}.ttf" ]; then
    curl -sSL -o "/usr/share/fonts/truetype/google-fonts/${f}.ttf" \
      "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/${f}.ttf"
  fi
done

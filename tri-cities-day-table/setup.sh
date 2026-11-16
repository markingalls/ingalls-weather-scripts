#!/bin/bash
# Run once when a Claude Code cloud session starts. Poppins isn't packaged
# for apt, so it's fetched from Google's font repo (same as
# columbia-basin-alerts-map/setup.sh); build_table.py falls back to
# Montserrat if this step is skipped.
set -e

pip install -r requirements.txt

mkdir -p /usr/share/fonts/truetype/google-fonts
for f in Poppins-Regular Poppins-Medium Poppins-Bold; do
  if [ ! -f "/usr/share/fonts/truetype/google-fonts/${f}.ttf" ]; then
    curl -sSL -o "/usr/share/fonts/truetype/google-fonts/${f}.ttf" \
      "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/${f}.ttf"
  fi
done

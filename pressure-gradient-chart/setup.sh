#!/bin/bash
# Run once when a Claude Code cloud session starts.
# The Poppins font used for chart labels isn't packaged for apt, so it's
# pulled directly here, same as tempest-temp-chart/setup.sh -- build_chart.py
# needs all three weights (Regular/Medium/Bold). Self-contained even though
# a droplet with tempest-temp-chart/tempest-wind-chart/tempest-pressure-chart
# already deployed will already have these files.
set -e

pip install -r requirements.txt

mkdir -p /usr/share/fonts/truetype/google-fonts
for f in Poppins-Regular Poppins-Medium Poppins-Bold; do
  if [ ! -f "/usr/share/fonts/truetype/google-fonts/${f}.ttf" ]; then
    curl -sSL -o "/usr/share/fonts/truetype/google-fonts/${f}.ttf" \
      "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/${f}.ttf"
  fi
done

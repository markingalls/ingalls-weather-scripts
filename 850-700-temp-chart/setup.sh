#!/bin/bash
# Run once when a Claude Code cloud session starts.
# The Poppins font used for chart labels isn't packaged for apt, so it's
# pulled directly here, same as western-us-noaa-outlooks/setup.sh --
# build_chart.py needs all three weights (Regular/Medium/Bold), one more
# than that project since this chart's title uses Bold.
set -e

pip install -r requirements.txt

mkdir -p /usr/share/fonts/truetype/google-fonts
for f in Poppins-Regular Poppins-Medium Poppins-Bold; do
  if [ ! -f "/usr/share/fonts/truetype/google-fonts/${f}.ttf" ]; then
    curl -sSL -o "/usr/share/fonts/truetype/google-fonts/${f}.ttf" \
      "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/${f}.ttf"
  fi
done

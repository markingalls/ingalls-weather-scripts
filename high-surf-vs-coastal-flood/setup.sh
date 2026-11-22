#!/bin/bash
# Run once when a Claude Code cloud session starts. The Poppins font used
# for all text isn't packaged for apt, so it's curled from Google's font
# repo (build_graphic.py falls back to Montserrat if it's missing).
set -e

pip install -r requirements.txt

mkdir -p /usr/share/fonts/truetype/google-fonts
for f in Poppins-Regular Poppins-Medium Poppins-Bold; do
  if [ ! -f "/usr/share/fonts/truetype/google-fonts/${f}.ttf" ]; then
    curl -sSL -o "/usr/share/fonts/truetype/google-fonts/${f}.ttf" \
      "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/${f}.ttf"
  fi
done

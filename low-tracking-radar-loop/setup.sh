#!/bin/bash
# Run once when a Claude Code cloud session starts.
# Everything here is pip-installable: pygrib's wheels bundle eccodes, and
# imageio-ffmpeg ships its own ffmpeg binary for the MP4 encode. The
# Poppins font used for labels isn't packaged for apt, so it's fetched
# directly.
set -e

pip install -r requirements.txt

mkdir -p /usr/share/fonts/truetype/google-fonts
for f in Poppins-Regular Poppins-Medium Poppins-SemiBold Poppins-Bold; do
  if [ ! -f "/usr/share/fonts/truetype/google-fonts/${f}.ttf" ]; then
    curl -sSL -o "/usr/share/fonts/truetype/google-fonts/${f}.ttf" \
      "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/${f}.ttf"
  fi
done

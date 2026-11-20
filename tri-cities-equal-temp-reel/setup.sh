#!/bin/bash
# Run once when a Claude Code cloud session starts.
# ffmpeg encodes the reel (apt-only); Poppins isn't packaged for apt, so
# it's fetched manually like the other projects here.
set -e

if ! command -v ffmpeg >/dev/null 2>&1; then
  apt-get update
  apt-get install -y ffmpeg
fi

pip install -r requirements.txt

mkdir -p /usr/share/fonts/truetype/google-fonts
for f in Poppins-Regular Poppins-Medium Poppins-Bold; do
  if [ ! -f "/usr/share/fonts/truetype/google-fonts/${f}.ttf" ]; then
    curl -sSL -o "/usr/share/fonts/truetype/google-fonts/${f}.ttf" \
      "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/${f}.ttf"
  fi
done

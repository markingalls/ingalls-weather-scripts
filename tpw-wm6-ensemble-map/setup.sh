#!/bin/bash
# Run once when a Claude Code cloud session starts.
# cartopy needs GDAL at the system level -- only installs via apt, not pip.
# The Poppins/Baloo 2 fonts used for map labels also need installing
# manually here since neither is packaged for apt.
set -e

apt-get update
apt-get install -y gdal-bin

pip install -r requirements.txt

mkdir -p /usr/share/fonts/truetype/google-fonts
for f in Poppins-Regular Poppins-Medium; do
  if [ ! -f "/usr/share/fonts/truetype/google-fonts/${f}.ttf" ]; then
    curl -sSL -o "/usr/share/fonts/truetype/google-fonts/${f}.ttf" \
      "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/${f}.ttf"
  fi
done

# Baloo 2 (bold, rounded -- used for the L/H pressure-center markers) only
# ships as a variable font in the google/fonts repo, with no static
# per-weight file to curl the way Poppins' static files above work, so
# this instead asks Google Fonts' CSS API for weight 700 and follows
# whatever gstatic URL it hands back for a pre-built static instance.
if [ ! -f "/usr/share/fonts/truetype/google-fonts/Baloo2-Bold.ttf" ]; then
  baloo_url=$(curl -sSL "https://fonts.googleapis.com/css2?family=Baloo+2:wght@700&display=swap" \
    | grep -o 'https://fonts.gstatic.com/[^)]*\.ttf' | head -1)
  curl -sSL -o "/usr/share/fonts/truetype/google-fonts/Baloo2-Bold.ttf" "$baloo_url"
fi

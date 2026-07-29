#!/bin/bash
# Run once when a Claude Code cloud session starts.
# cartopy needs GDAL at the system level -- only installs via apt, not pip.
# The Poppins font used for most map labels also needs installing manually
# here since it isn't packaged for apt. (Baloo 2, used for the L/H
# pressure-center markers, is checked into ../assets/fonts instead --
# fm.FontProperties(fname=...) loads a TTF straight from that path, no
# system font install needed -- since it only ships as a variable font
# upstream, with no static per-weight file this setup script could fetch
# the way Poppins' can.)
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

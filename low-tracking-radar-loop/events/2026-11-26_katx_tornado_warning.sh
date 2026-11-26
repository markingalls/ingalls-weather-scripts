#!/bin/bash
# 2026-11-26: the cell that tracked from near Shelton to North Bend and
# drew KSEW Tornado Warning #1 (King County, 11:58-12:15 PST; landspout
# confirmed near Renton). Two reels: lowest-tilt reflectivity and base
# velocity from KATX, camera following the cell's rotation track.
#
# The waypoints are the velocity couplet's position, from
# rotation_track.py seeded with the warning's motion (249 deg / 24 kt),
# hand-trimmed where it jumped to neighboring features; after ~19:57Z the
# rotation weakens and the last points follow the reflectivity core.
#
# Pace: a constant 13.4 real minutes per video second -- the pace the
# loop had around the warning, where SAILS cuts come every ~1.8 min
# (4 frames per scan at 30 fps). Earlier, sparser scans (~5 min apart)
# are held instead of rushing past.
set -e
cd "$(dirname "$0")/.."
WP="2026-11-26T17:29Z,47.103,-123.499;2026-11-26T17:35Z,47.126,-123.460;2026-11-26T17:48Z,47.197,-123.329;2026-11-26T17:59Z,47.221,-123.167;2026-11-26T18:09Z,47.249,-123.034;2026-11-26T18:19Z,47.291,-122.919;2026-11-26T18:29Z,47.301,-122.840;2026-11-26T18:38Z,47.333,-122.747;2026-11-26T18:51Z,47.399,-122.572;2026-11-26T18:58Z,47.425,-122.509;2026-11-26T19:07Z,47.438,-122.412;2026-11-26T19:14Z,47.465,-122.348;2026-11-26T19:21Z,47.485,-122.287;2026-11-26T19:29Z,47.490,-122.230;2026-11-26T19:38Z,47.472,-122.164;2026-11-26T19:44Z,47.489,-122.101;2026-11-26T19:51Z,47.502,-122.035;2026-11-26T19:57Z,47.525,-121.985;2026-11-26T20:03Z,47.516,-121.935;2026-11-26T20:12Z,47.525,-121.864"
for P in ref vel; do
  python3 build_loop.py --site KATX --product $P --sails --waypoints "$WP" \
    --start 2026-11-26T17:45Z --end 2026-11-26T20:22Z \
    --view-km 100 --north-km 15 --towns puget --warnings TO \
    --highways --minutes-per-sec 13.4 \
    --title "Tornado-Warned Storm"
done

# Combined reel: reflectivity then velocity, the pair played twice.
# Stream copy (both reels share encode settings), plus a CRF 27 re-encode
# ("_share") that fits under ~30 MB upload limits.
FF=$(python3 -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())")
cd output
REF=$(ls -t katx_ref_loop_20261126_*.mp4 | head -1)
VEL=$(ls -t katx_vel_loop_20261126_*.mp4 | head -1)
OUT=katx_ref_vel_x2_${REF#katx_ref_loop_}
printf "file '%s'\n" "$REF" "$VEL" "$REF" "$VEL" > concat.txt
"$FF" -loglevel error -y -f concat -safe 0 -i concat.txt -c copy -movflags +faststart "$OUT"
rm concat.txt
"$FF" -loglevel error -y -i "$OUT" -c:v libx264 -preset slow -crf 27 \
  -pix_fmt yuv420p -movflags +faststart "${OUT%.mp4}_share.mp4"
echo "saved output/$OUT and output/${OUT%.mp4}_share.mp4"

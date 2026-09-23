---
name: pnw-low-landfall-map
description: Make the Ingalls Weather Instagram map of where a Pacific surface low will make landfall on the Pacific Northwest coast. It shows WM-6 ensemble member tracks, the mean track or cluster means, and landfall odds within 100 km along the coast. Use when asked about landfall, track, or landfall-location uncertainty for an incoming PNW/Pacific low or windstorm.
---

# PNW low landfall map

The code and full method are in `pnw-low-landfall-map/` (read its
README first). This skill covers running it for a new low.

1. Setup, in a fresh environment only:
   `cd pnw-low-landfall-map && bash setup.sh`.
   If pip fails with "Cannot uninstall numpy ... installed by debian", run
   `pip install --ignore-installed numpy -r requirements.txt`.
2. `WB_API_KEY` must be set. Ask the user for a key if it's missing, and
   never commit it.
3. Run `python build_map.py`. By default it uses the latest WM-6 run, the
   next 72 h, and the deepest ensemble-mean low in `SEED_BOX`.
4. **Check the console before trusting the map.**
   - `Seed (...)` should be the low the user means. If it isn't, re-run
     with `--start <UTC YYYY-MM-DDTHH when the low is offshore>` and
     `--seed LAT LON`.
   - Most members should make landfall. A low count means the seed or
     window is off, or the low stays offshore, which is worth saying
     either way.
   - `Clustering:` tells you whether the map shows one mean track or
     north/south cluster means.
5. Look at the PNG in `output/` for label collisions before sending it.
   For tweaks, iterate with `--file output/snapshot_<init>.npz` so you
   don't re-fetch.
6. Give the user the PNG and the key numbers: median landfall time
   (24-hour Pacific), the landfall latitude spread, the top town
   percentages, and whether it's clustered. Outputs are gitignored, so
   don't commit them.

Only edit the domain or coast constants for a low coming ashore outside
Cape Mendocino to Vancouver Island (see the README's "Running it for a
future low" section).

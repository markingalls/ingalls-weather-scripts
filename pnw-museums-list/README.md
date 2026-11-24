# Pacific Northwest Museums List

A to-do-style graphic of a Pacific Northwest museum bucket list — two
columns of open-circle "City - Museum" lines — sized modestly wide for
Instagram (2000×1680, ~1.19:1). Same visual style as the repo's map
products: Poppins type, the `#f7f6f2` page tone throughout, a black
outline frame around the list, a muted credit line, and the Ingalls
Weather logo.

## Files

- `build_list.py` — renders the graphic. The museum list itself lives in
  `MUSEUMS` near the top of the file as `(city, museum)` pairs, sorted by
  city; edit it there and re-run. Entries fill the left column then the
  right, and the list font auto-shrinks (from 12.5pt) until the longest
  line fits its column.
- `requirements.txt` / `setup.sh` — Python dependencies, plus the Poppins
  font (not packaged for apt).

The Ingalls Weather logo (top-right) lives in
[`../assets/ingalls_weather_logo.png`](../assets/ingalls_weather_logo.png).

## Usage

```bash
bash setup.sh                 # first time / fresh environment only
python3 build_list.py         # output/pnw_museums.png
python3 build_list.py --out some.png
```

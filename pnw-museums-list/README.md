# Pacific Northwest Museums List

A styled, Instagram-ready (4:5, 1680×2100) graphic of a Pacific Northwest
museum bucket list, grouped by city — in the same visual style as the
repo's map products (Poppins type, `#f7f6f2` page tone, black-framed
panel, muted credit line, Ingalls Weather logo).

## Files

- `build_list.py` — renders the graphic. The museum list itself lives in
  `MUSEUMS` near the top of the file as `(city, museum)` pairs, sorted by
  city; edit it there and re-run. City groups are split across two
  columns so their line counts balance, and the block is vertically
  centered in the panel.
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

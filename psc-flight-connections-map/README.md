# PSC Flight Connections Maps

Two styled maps of every airport you can fly to from Tri-Cities Airport
(PSC, Pasco WA) with **zero or one layover**, built entirely from
Wikipedia's airport "Airlines and destinations" tables:

- **US + southern Canada** (Lambert Conformal, Baja/Caribbean edges
  included) -- nonstop destinations labeled with their IATA codes, with
  great-circle spokes from PSC.
- **World** (Robinson) -- same data, global, without the spokes or the
  PSC label (they just smudge over the dense western-US cluster at that
  scale).

Both render at 300 dpi (3240x2580 and 3600x2400 px).

Dot colors:

- **Black** -- nonstop from PSC (these are also the layover airports).
- **One color per layover airport** ("Only via SEA", "Only via DEN", ...)
  -- one-stop destinations reachable through exactly one of PSC's nonstop
  destinations. Hub colors are fixed per IATA code (`HUB_COLORS`), so a hub
  keeps its color run to run.
- **Gray** -- one-stop destinations reachable through two or more
  different layover airports.

Legend counts are per map (only airports inside that map's frame).

## Files

- `build_map.py` -- scrapes Wikipedia, builds the route network, and
  renders both maps. Saves a `.json` snapshot of the network to `output/`
  each live run, so `--file` can re-render without re-fetching.
- `requirements.txt` / `setup.sh` -- Python + system dependencies (cartopy
  needs GDAL, apt-only; `setup.sh` also installs Poppins).

Shared basemap data in [`../maps/`](../maps/): `world_countries_50m.json`
(Natural Earth 1:50m admin-0 countries, slimmed to name/ISO code and
rounded to 0.001 deg -- added for this project since the other basemap
files only cover North America), `world_lakes_50m.json` (Natural Earth
1:50m lakes, painted back in as water on the US map so all five Great
Lakes show -- `states_lakes_slim.json` only carries Superior and
Michigan), plus `states_lakes_slim.json` and
`admin0_boundary_lines.json` for state/province and US/Canada/Mexico border
lines on the US map.

## Usage

```bash
bash setup.sh                                   # first time / fresh environment only
python3 build_map.py                            # scrape Wikipedia, render both maps
python3 build_map.py --map us                   # just one map (us | world | both)
python3 build_map.py --file output/snapshot_....json   # re-render, no fetch
```

A live run makes ~20 Wikipedia/Wikidata API requests, spaced
`REQUEST_SPACING_S` (2 s) apart; Wikimedia answers bursts with HTTP 429, so
`wiki_get()` backs off and retries (honoring `Retry-After`). Expect a
minute or two.

## Methodology

1. **Nonstops** -- the passenger "Airlines and destinations" table on
   [Tri-Cities Airport (Washington)](https://en.wikipedia.org/wiki/Tri-Cities_Airport_(Washington)).
2. **One stop** -- the same table on each nonstop destination's own
   article. Anything listed there that PSC doesn't already serve nonstop
   (and isn't PSC itself) is a one-layover destination, tagged with every
   hub it can be reached through.

Parsing details (`parse_destination_cell()`):

- Each wikilink in a destinations cell is one airport. The link target is
  the airport's article, and redirects are resolved via the API, so the
  same airport linked under two spellings merges into one dot.
- **Passenger routes only, no cargo.** A table is read only if it sits
  directly under a "Passenger" heading, or under "Airlines and
  destinations" itself on a page with no Passenger/Cargo split. Tables
  under any other heading (Cargo, Charter, ...) are skipped, as is any
  table whose header or caption mentions cargo. As a backstop, rows whose
  airline is a freight operator (`CARGO_AIRLINE_RE`: "... Cargo", FedEx,
  UPS, DHL, Amazon Air, Atlas, Kalitta, Ameriflight, ...) are dropped even
  inside a passenger table. Audited 2026-11-25: every one of the 12 pages
  read (PSC + its 11 nonstops) keeps cargo under its own "Cargo" heading
  (SLC and DEN have none listed), and no freight carrier appears in the
  scraped routes.
- `Seasonal:` routes are **kept**; `Charter:` / `Seasonal charter:` routes
  are **dropped**.
- `(begins <date>)` notes dated after today drop the route (not flying
  yet); `(ends <date>)` notes dated before today drop it too. The date, not
  just the note's presence, decides, since editors don't always clean
  these up promptly. `(resumes ...)` routes are kept, as seasonal gaps.
- Coordinates: the article's primary `{{coord}}` (API
  `prop=coordinates`), falling back to Wikidata P625. IATA codes: Wikidata
  P238 (the item behind the article's infobox). An airport with no IATA
  code on Wikidata is still plotted, just shown by name in the summary.

### Caveats

- **"One layover" means physically possible, not one ticket.** Any airline
  into the hub, any airline out -- Wikipedia's tables don't say what
  interlines or codeshares. Allegiant (PSC's LAS / AZA / SNA service)
  doesn't sell connections at all, so those hubs' destinations are
  self-transfer only.
- Same-day schedule alignment isn't checked.
- Only as current as Wikipedia's tables, which are volunteer-maintained
  and occasionally stale or inconsistent between articles.

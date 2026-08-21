# Where the cron schedule in crontab.example comes from

Each product group's refresh cadence matches NOAA's own real issuance
schedule for that product, not a blind fixed interval. Sourced directly
from NOAA/SPC/CPC's own pages (checked live, not from memory):

- **SPC Day 1** (categorical, tornado/wind/hail probability): issued
  5x/day at 0600Z, 1300Z, 1630Z, 2000Z, 0100Z, per
  `origin-west-www-spc.woc.noaa.gov/misc/about.php`. Confirmed the
  tornado/wind/hail probability layers update on this same schedule (not
  less often) by checking a live `day1otlk_wind.kmz`'s `ISSUE_ISO`
  timestamp against the outlook page's stated issuance time for the same
  cycle. All three hazards (plus categorical) come from IEM as one bundled
  fetch per cycle now (see the IEM fetch/parse comment in build_map.py),
  so they share this same schedule structurally, not just by coincidence.
- **SPC Day 2** (categorical, tornado, wind, hail): issued 2x/day,
  ~0600-0700Z and 1730Z, same source.
- **SPC Day 3** (categorical only -- SPC doesn't publish separate Day 3
  tornado/wind/hail products, only a combined all-hazard "Probabilistic"
  outlook): issued 2x/day, ~0730-0830Z and 1930Z, same source.
- **SPC Fire Weather** (Day 1 and Day 2): both issued once together at
  ~2:00am CST/CDT (~0700-0800Z depending on daylight saving), per
  `origin-west-www-spc.woc.noaa.gov/misc/about.php`; Day 1 gets a separate
  update by 1700Z, Day 2 by 2000Z.
- **SPC Fire Weather Day 3-8** (probabilistic Dry Thunderstorm + Wind/Low-RH
  risk, all six days from one issuance): issued once daily at 2200Z, per
  `spc.noaa.gov/misc/about.php`'s "Day 3-8 Fire Weather Outlook" section.
  Scheduled at 2220Z, a 20-minute buffer -- confirmed live that every
  day's ISSUE timestamp within one fetch lands a few minutes *before*
  2200Z (e.g. 2153Z), so this isn't racing the data landing, same
  early-release pattern seen on the SPC Day 2 outlook elsewhere in this
  file. Sourced from NOAA's own ArcGIS MapServer
  (`mapservices.weather.noaa.gov/vector/rest/services/fire_weather/
  SPC_firewx/MapServer`), not IEM's bulk shapefile mirror used for Day 1/2
  above -- confirmed directly that IEM's `outlooks.py` silently ignores
  `day` past 2 for `type=F`, returning Day 1/2's own records again rather
  than an error, so it doesn't carry this product at all.
- **CPC 6-10 Day and 8-14 Day** (temp + precip): issued daily between
  3-4pm Eastern, per `cpc.ncep.noaa.gov/products/predictions/610day/` and
  `.../814day/`. Scheduled at 2100Z, which covers 3-4pm Eastern under
  both EST and EDT with margin.
- **CPC Week 3-4** (temp + precip): issued Fridays between 3-4pm Eastern,
  per `cpc.ncep.noaa.gov/products/predictions/WK34/`. Same 2100Z time,
  Fridays only.
- **U.S. Drought Monitor**: released Thursdays (long-standing NDMC
  practice; data valid as of the preceding Tuesday). Scheduled 1400Z,
  which covers the commonly-cited ~8:30am Eastern release under both EST
  and EDT with margin -- worth double-checking against actual observed
  publish times after this has run for a couple of weeks, since I
  couldn't find an explicit UTC issuance time on NDMC's own site to
  confirm precisely.

All times in crontab.example add roughly 10-15 minutes of buffer past
the stated issuance time, so the fetch isn't racing the file actually
landing on NOAA's server.

**Operational stagger, not a NOAA-schedule fact**: two pairs of tiers
above genuinely share the same issuance minute (Fire Weather Day 2's PM
update and SPC Day 1's 2000Z tier both land at :15 past 2000Z; CPC
Week 3-4 and the daily CPC tier both land at :00 past 2100Z on Fridays).
crontab.example's own lock is shared across every tier (see
publish_outlooks.py's docstring -- deliberate, to avoid two memory-heavy
cartopy renders stacking up on this droplet), so two tiers scheduled at
the exact same minute don't queue -- one wins the flock() race and the
other is skipped outright, silently, until its own next scheduled tick
(confirmed happening in practice: state/publish.log showed the winner
alternating day to day for the 2000Z pair, and the daily CPC tier lost
outright on the one Friday checked). crontab.example offsets Fire
Weather Day 2's PM update to :25 and CPC Week 3-4 to :10 past their
respective hours -- a few minutes clear of each real run's own runtime
(seconds, not minutes) -- specifically to avoid this, not because NOAA
issues either product at a different minute than its same-hour
counterpart.

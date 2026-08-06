# Image Hit Stats

A small, self-hosted hit-count dashboard for everything served from
`images.ingallswx.com`. Not connected to Jetpack Stats -- Jetpack has no
mechanism to ingest hit data from a server outside WordPress's own
pipeline, and `images.ingallswx.com` is plain nginx on the droplet with no
WordPress/PHP involved at all. This reads nginx's own access log instead
and builds its own page.

Deliberately kept out of search engines: `robots.txt` disallows `/stats/`,
and nginx adds an `X-Robots-Tag: noindex, nofollow` header on that path as
a second, independent layer that holds even if a crawler never reads
`robots.txt` (e.g. something links to the page directly).

## How it works

`update_stats.py` does two things every time it runs, meant to be cron'd
frequently (see `deploy/crontab.example`):

1. **Fold new log lines into a SQLite database.** Reads only the *new*
   bytes since its last run (tracked in `state/cursor.json` by
   `(inode, byte offset)`, not just a byte offset -- correctly detects a
   logrotate rotation or an in-place truncation and restarts from the top
   of whatever file is current, rather than going blind or double-counting).
   Only `GET` requests returning `200` or `304` for a real `.png` path
   count as a "hit" -- 404s, redirects, and non-image paths (`/stats/`
   itself, `robots.txt`) are excluded. Counts land in `state/hits.sqlite3`,
   one row per `(date, path)`, permanently -- independent of whatever
   retention logrotate is configured with, since a line only needs to be
   read once to be folded in for good.
2. **Render the dashboard** from that database to
   `/var/www/images/stats/index.html` (atomic temp-file + rename, like
   every other published image in this repo). Four tabs -- Today, This
   Month, This Year, All-Time -- each with a total and two breakdowns (by
   category, by individual image).

No third-party Python dependencies -- `sqlite3` and everything else used
here is standard library, so this doesn't need its own venv; the crontab
line runs it with the system `python3` directly.

## Categorization

`CATEGORY_PATTERNS` in `update_stats.py` maps filename patterns to
categories (7-Day Forecasts, SPC Outlooks, CPC Outlooks, Drought Monitor,
850mb Temp Charts, ...), first match wins, anything unmatched falls into
"Other". Extend this list when a new product is added elsewhere in the
repo -- otherwise its hits will still count, just bucketed as "Other"
instead of its own category.

## Setup

Needs one nginx change beyond what's already in
`tri-cities-7day-forecast/deploy/nginx-images.conf`: a dedicated
`access_log` directive (rather than falling into nginx's shared default
log) and a `/stats/` location block with the noindex header -- both
already in that file. `deploy/robots.txt` needs to land at
`/var/www/images/robots.txt`.

```bash
# One-time: put robots.txt where nginx will actually serve it from
cp deploy/robots.txt /var/www/images/robots.txt

# First run creates state/ (needed before the cron line's log redirect
# will work) and does an initial fold + render
python3 update_stats.py
```

Then install `deploy/crontab.example`'s line and visit
`https://images.ingallswx.com/stats/` (not linked from anywhere on
purpose -- bookmark it).

## Limitations

- **No historical backfill.** Stats start accumulating from whenever the
  dedicated access log is turned on, not retroactively -- there's no
  earlier per-image data to recover from nginx's previous shared default
  log.
- **Per-request, not per-visitor.** A single page load can generate
  several image requests (browser cache misses, revalidation checks,
  RSS/embed fetches elsewhere), so this counts image *fetches*, not
  unique visitors or pageviews. Jetpack Stats' own pageview counts for the
  WordPress pages that embed these images are a better (if indirect)
  signal for "how many people looked at this," if that's what you're
  after instead.

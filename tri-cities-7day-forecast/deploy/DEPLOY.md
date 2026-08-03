# Deploying the Tri-Cities forecast image to a DigitalOcean droplet

This is the reference copy of the walkthrough. Follow along here or in
chat -- they match. Each phase says what you're doing and why.

Money note up front: the only required recurring cost is the droplet
itself (~$12/mo for the 2 GiB/1 vCPU "Basic" tier). Everything else here
(nginx, Certbot/Let's Encrypt SSL, the WordPress.com DNS record) is free.
DigitalOcean will offer optional paid add-ons (backups, monitoring alerts,
extra volumes) during droplet creation -- none are required for this
project; skip them unless you want the peace of mind.

## Phase 1 -- DigitalOcean account, SSH key, droplet

1. Generate an SSH key pair **on your own laptop** (not the droplet -- it
   doesn't exist yet). This key is how you'll log in without a password.
   - Mac/Linux/WSL: `ssh-keygen -t ed25519 -C "ingallswx-droplet"`
   - Windows (PowerShell, has OpenSSH built in since Win10): same command.
   - Accept the default file location; a passphrase is optional (adds
     protection if your laptop is compromised, at the cost of typing it
     each login).
   - This creates `~/.ssh/id_ed25519` (private -- never share this) and
     `~/.ssh/id_ed25519.pub` (public -- this is what you upload).
2. Sign up at digitalocean.com, verify email, add a payment method.
3. Create Droplet:
   - Image: Ubuntu (latest LTS, e.g. 24.04).
   - Plan: Basic, Regular SSD, the $12/mo (2 GiB RAM / 1 vCPU) tier.
   - Datacenter region: pick one close to you or to your site's audience;
     doesn't functionally matter for this project.
   - Authentication: choose **SSH Key**, not Password. Paste the contents
     of `id_ed25519.pub` (`cat ~/.ssh/id_ed25519.pub`) into "New SSH Key".
   - Hostname: anything memorable, e.g. `ingallswx-images`.
   - Skip the backups/monitoring add-ons unless you specifically want them
     (each adds a small recurring cost).
   - Click Create Droplet. Note the public IPv4 address once it's up.
4. Test login from your laptop: `ssh root@<droplet-ip>`. You should get a
   shell with no password prompt (SSH key does the authentication).

## Phase 2 -- Base server setup

```
apt update && apt upgrade -y
apt install -y python3 python3-venv python3-pip fonts-montserrat libeccodes0 libeccodes-dev git
```

`fonts-montserrat` and the `libeccodes*` packages are system-level
dependencies `build_graphic.py` and `fetch_hrrr_smoke_forecast.py` need
(font rendering and GRIB2 decoding for the seasonal smoke layer) --
`pip install` alone can't provide these.

## Phase 3 -- nginx

```
apt install -y nginx
mkdir -p /var/www/images
chown root:root /var/www/images && chmod 755 /var/www/images
cp deploy/nginx-images.conf /etc/nginx/sites-available/images
ln -s /etc/nginx/sites-available/images /etc/nginx/sites-enabled/images
nginx -t && systemctl reload nginx
```

At this point `http://<droplet-ip>/` (port 80, no domain yet) should
return a plain 404 from nginx -- that's expected, there's no file there
yet.

## Phase 4 -- DNS (images.ingallswx.com -> droplet IP)

Since ingallswx.com's domain is managed through WordPress.com even though
this subdomain is served entirely by the droplet, add an **A record**
there: Upgrades -> Domains -> ingallswx.com -> DNS records -> Add record.
- Type: A
- Name/host: `images`
- Value: the droplet's public IPv4 address
- TTL: default is fine

DNS propagation is usually minutes, sometimes up to ~1 hour.

## Phase 5 -- SSL via Certbot

```
apt install -y certbot python3-certbot-nginx
certbot --nginx -d images.ingallswx.com
```

Certbot edits the nginx config to add the 443/SSL server block and an
HTTP->HTTPS redirect, and installs a systemd timer that auto-renews the
certificate before it expires (Let's Encrypt certs last 90 days). This
step needs the DNS record from Phase 4 to have already propagated.

## Phase 6 -- Get the script onto the droplet

The repo is private, so cloning needs a deploy key (an SSH key scoped to
read-only access to just this one repo -- safer than a personal token on
a server you don't fully control).

```
ssh-keygen -t ed25519 -f /root/.ssh/deploy_key -N "" -C "ingallswx-droplet-deploy"
cat /root/.ssh/deploy_key.pub
```

Add that public key at GitHub: repo -> Settings -> Deploy keys -> Add
deploy key -> paste it in, leave "Allow write access" unchecked.

```
cat >> /root/.ssh/config <<'EOF'
Host github-ingalls
    HostName github.com
    User git
    IdentityFile /root/.ssh/deploy_key
    IdentitiesOnly yes
EOF

git clone github-ingalls:markingalls/ingalls-weather-scripts.git /opt/ingalls-weather-scripts
cd /opt/ingalls-weather-scripts/tri-cities-7day-forecast
python3 -m venv venv
venv/bin/pip install -r requirements.txt

cp deploy/.env.example .env
chmod 600 .env
# edit .env and set the real WB_API_KEY
```

## Phase 7/8 -- Scheduled cron job + lock file

Fixed cron times, not hourly polling: `build_graphic.py`'s pipeline pulls
from four sources (NWS, WindBorne MetaMesh, Open-Meteo, Open-Meteo
ensemble), and Open-Meteo's own ECMWF ingestion lags ECMWF's completion by
a variable amount. The GitHub Actions schedule's four offsets -- 07:15,
12:30, 19:15, 00:30 UTC -- were already tuned to land safely after all
four sources have absorbed a given ECMWF cycle. Polling a single source
(e.g. WindBorne's `ecmwf-det/initialization_times`) risks firing before
the other three catch up, mixing a fresh source with a stale one. So the
droplet reuses those same four proven offsets instead.

`deploy/build_and_publish.py` is lock-file-protected (Phase 8's
requirement) via `fcntl.flock` on `state/run.lock` -- if a build is still
running when the next scheduled tick fires (a run takes unusually long),
the new tick logs a line and exits immediately instead of starting a
second build that would collide with it.

Install the cron job:

```
crontab -e
```

Paste in the contents of `deploy/crontab.example`, with your real
`WB_API_KEY`. This fires the build at the same four UTC times as the
GitHub Actions version.

## Phase 9 -- Overwrite in place + caching

Already handled:
- `build_and_publish.py` always writes to the same filename
  (`/var/www/images/tricities_forecast.png`), via a temp file + atomic
  rename so nginx never serves a half-written PNG mid-save.
- `nginx-images.conf` sets `Cache-Control: no-cache` on that file, so
  every normal browser reload revalidates with the server (a cheap 304
  if unchanged, courtesy of nginx's automatic Last-Modified/ETag support
  on static files) instead of trusting a stale cached copy -- no hard
  refresh or cache-busting query string needed. Whether WordPress.com's
  Jetpack Photon image CDN honors this when the image is embedded in a
  post is a separate, unverified question -- worth checking once it's
  live there, since Photon may apply its own cache policy regardless of
  the origin's headers.

## Phase 10 -- End-to-end test

```
cd /opt/ingalls-weather-scripts/tri-cities-7day-forecast
venv/bin/python3 deploy/build_and_publish.py
tail -f state/build.log
```

Confirm `/var/www/images/tricities_forecast.png` exists and is fresh,
then load `https://images.ingallswx.com/tricities_forecast.png` in a
browser (should load padlock-secure, no warnings). Wait for the next
scheduled cron time (07:15, 12:30, 19:15, or 00:30 UTC) and confirm the
file's timestamp updates on its own while the URL stays the same.

# Deployment Guide — Raspberry Pi (private registry)

Goal: run garmin-dash **indefinitely** on a Raspberry Pi inside your network,
with a repeatable update loop. One dev machine builds images (amd64 + arm64),
pushes them to your private registry at **`ghcr.io/yourname`**, and the Pi
pulls + runs. Push/pull access is already network/ACL-managed — no
`docker login` step is required in the normal flow.

```
┌─────────────────────────┐          ┌──────────────────────────────┐
│  Dev machine (x86)      │  push   │  ghcr.io/yourname           │
│  docker buildx (multi-  │ ──────► │  garmin-dash:latest           │
│  arch amd64+arm64)      │         └──────────────┬───────────────┘
└─────────────────────────┘                        │ pull
                                                   ▼
                              ┌──────────────────────────────┐
                              │  Raspberry Pi (arm64)         │
                              │  compose: app + scheduler     │
                              │  volumes: ./data ./logs       │
                              │  restart: unless-stopped      │
                              └──────────────────────────────┘
```

**What runs on the Pi** (two containers from the same image):

| Service    | Runs | Purpose |
|------------|------|---------|
| `app`      | web | uvicorn dashboard (port `GARMINDASH_PORT`) |
| `scheduler`| bg  | incremental sync every 15 min + (Phase 4) Signal jobs |

Both survive reboots (`restart: unless-stopped`), write to the shared
`./data` volume (SQLite DB + Garmin tokens), and `alembic upgrade head`
runs at boot so a fresh volume self-initializes (schema + default user).

---

## 0. Prerequisites

- **Dev machine**: Docker with buildx (`docker buildx version`), network
  access to `ghcr.io/yourname` with push rights (already granted).
- **Raspberry Pi**: Raspberry Pi OS (64-bit, Bookworm or newer) with Docker
  Engine + Compose v2 (see step 4 for the install commands), reachable via
  SSH from your dev machine, network access to `ghcr.io/yourname` with
  pull rights (already granted).

---

## 1. Dev machine — one-time setup

Enable cross-arch emulation once (needed for the arm64 build on x86):

```bash
docker run --privileged --rm tonistiigi/binfmt --install all
```

That's it — no registry login needed since `ghcr.io/yourname` access is
already managed. `docker buildx ls` should show a builder; the script
creates one (`garmin-builder`, docker-container driver) automatically on
first run.

## 2. Dev machine — build & push (repeatable)

From the repo root:

```bash
cd docker
./build-push.sh
```

What it does:

1. switches to repo root (build context),
2. creates/reuses a `docker-container` buildx builder (required for
   multi-arch `--push`),
3. builds `linux/amd64,linux/arm64` and pushes:

```
ghcr.io/yourname/garmin-dash:latest
```

Version tags are optional but recommended for rollbacks:

```bash
TAG=v0.1.0 ./build-push.sh
# → pushes both ghcr.io/yourname/garmin-dash:latest and :v0.1.0
```

First build takes a while (pip installs for both architectures). Later
builds are fast thanks to layer caching.

## 3. Dev machine — prepare the Pi's files

```bash
# On the Pi, create the app directory and the data skeleton:
ssh pi@<pi-ip> 'mkdir -p ~/garmin-dash/data/garmin'

# Copy the compose file + env template + your cached Garmin tokens:
scp docker/docker-compose.prod.yml pi@<pi-ip>:~/garmin-dash/
scp docker/.env.prod.example pi@<pi-ip>:~/garmin-dash/.env
scp -r data/garmin/tokens pi@<pi-ip>:~/garmin-dash/data/garmin/
```

Copying `data/garmin/tokens` (the cached `garmin_tokens.json`) means the Pi
**starts authenticated** — no MFA flow needed. It's a single self-contained
JSON file; if you ever want to re-auth on the Pi instead, set
`GARMIN_EMAIL`/`GARMIN_PASSWORD` and run `gdash auth start|code` inside the
container (see troubleshooting).

## 4. Pi — configure `.env`

SSH into the Pi and edit `~/garmin-dash/.env`:

```bash
ssh pi@<pi-ip>
cd ~/garmin-dash
nano .env
```

| Setting | Value / note |
|---------|--------------|
| `GARMINDASH_PORT` | host port for the dashboard (default `8000`) |
| `GARMINDASH_IMAGE` | optional — pin a version tag, e.g. `ghcr.io/yourname/garmin-dash:v0.1.0` (defaults to `:latest`) |
| `PUID` / `PGID` | your Pi user's ids (`id -u` / `id -g`, usually 1000/1000) — the containers run as this user; the entrypoint chowns `./data` + `./logs` to it at every boot, so fresh installs work even if Docker created those dirs as root |
| `GARMIN_EMAIL` / `GARMIN_PASSWORD` | optional (only for re-auth) |
| `GARMINTOKENS` | keep `data/garmin/tokens` (container-relative; maps to the mounted volume) |
| `TIMEZONE` | keep `Europe/Amsterdam` (or your zone) |
| `SYNC_INTERVAL_MINUTES` / `SYNC_DAYS_BACK` | ingestion cadence (defaults 15 / 3) |

Signal (`SIGNAL_*`) and LLM (`LLM_*`) stay commented until those phases are
provisioned.

> Path note: `./data` in the compose file resolves next to the compose file,
> i.e. `~/garmin-dash/data` — the same layout as the dev repo, so DB, tokens
> and backups are in one place.

## 5. Pi — one-time Docker install (if not already installed)

```bash
# Raspberry Pi OS (Bookworm+), official install script:
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker        # or log out/in
docker compose version   # → Docker Compose version v2.x
```

## 6. Pi — pull

```bash
cd ~/garmin-dash
docker compose -f docker-compose.prod.yml pull
```

No login needed — pull access to `ghcr.io/yourname` is already granted on
the Pi's network. If your registry ever requires auth, see the
troubleshooting table below.

## 7. Pi — start (and keep running)

```bash
cd ~/garmin-dash
docker compose -f docker-compose.prod.yml up -d
```

Verify:

```bash
docker compose -f docker-compose.prod.yml ps
# NAME                STATUS
# garmin-dash-app-1         Up ... (healthy)
# garmin-dash-scheduler-1   Up ...

curl -s http://localhost:8000/healthz   # → {"status":"ok"}
curl -s http://localhost:8000/api/summary | head -c 200   # JSON with today's data
```

Then open **http://<pi-ip>:8000** from any device on your network.

First sync happens within ~15 minutes (scheduler). You can force it:

```bash
docker compose -f docker-compose.prod.yml exec scheduler gdash ingest sync 3
```

Both containers restart automatically after a reboot or crash.

## 8. Updating (the repeatable loop)

```bash
# ── dev machine ──────────────────────────────────────────────────────
cd ~/Projects/garmin-dash/docker
./build-push.sh                        # build+push :latest (or TAG=vX.Y.Z)

# ── Pi ──────────────────────────────────────────────────────────────
ssh pi@<pi-ip>
cd ~/garmin-dash
docker compose -f docker-compose.prod.yml pull   # fetch the new image
docker compose -f docker-compose.prod.yml up -d  # restart changed services
docker compose -f docker-compose.prod.yml ps     # check healthy
```

Rollback (when you used version tags):

```bash
# Pi: pin the previous tag via .env, then restart
echo "GARMINDASH_IMAGE=ghcr.io/yourname/garmin-dash:v0.1.0" >> .env
docker compose -f docker-compose.prod.yml up -d
```

## 9. Backup / restore

Everything lives in `~/garmin-dash/data/` on the Pi. Backup = copy that dir:

```bash
# on the Pi (SQLite WAL-safe snapshot):
docker compose -f docker-compose.prod.yml stop app scheduler
tar czf ~/garmin-dash-backup-$(date +%F).tar.gz -C ~/garmin-dash data
docker compose -f docker-compose.prod.yml start
# or pull the DB file off:  scp -r pi@<pi-ip>:~/garmin-dash/data ./pi-backup/
```

Restore = stop, replace `data/`, start. (A cron job that tars `data/` nightly
is a good idea.)

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Recovery/Strain cards and Trends empty after a successful sync | Scores are materialized by a compute step, not by sync alone. **Fix now**: `docker compose exec scheduler gdash metrics compute 365`. **Fix permanently**: pull the latest image — the scheduler now recomputes scores after every sync pass |
| `sqlalchemy.exc.OperationalError: table ... already exists` at boot (one container) | Migration race: app and scheduler both run `alembic upgrade head` on a fresh DB. The image now serializes migrations with a shared-volume flock (`gdash-migrate`) — pull the latest image. If the DB is left mid-migration, the next boot fixes it; to force a clean slate: `docker compose down && sudo rm -f data/garmin_dash.db*` (only when there is nothing to keep) |
| `chown: changing ownership of ... Operation not permitted` at boot (restart loop) | Your compose still has `user: "${PUID:-1000}:${PGID:-1000}"` — the entrypoint needs root to fix ownership. **Remove the `user:` line** (the image drops privileges itself). If you keep `user:` anyway, the entrypoint skips its fix and you must pre-create the dirs: `sudo chown -R 1000:1000 data logs` (match your `PUID`/`PGID`), then `docker compose up -d` |
| `sqlite3.OperationalError: unable to open database file` at boot (both containers) | The `data/` dir on the Pi is not writable by the container uid (classic: Docker auto-created `./data` as root before you ever wrote into it). The image now auto-fixes this: the entrypoint chowns `./data` + `./logs` to `PUID:PGID` at every start. For an **already-running** broken stack: `sudo chown -R 1000:1000 data logs` (match your `PUID`/`PGID`), then `docker compose up -d` again — and make sure you pulled the latest image |
| `docker pull` on Pi fails auth | Registry access changed / not yet granted on this host — confirm with your registry admin, or set `REGISTRY_USER`/`REGISTRY_TOKEN` env vars and `docker login ghcr.io/yourname` manually |
| Build fails on arm64 | binfmt emulation not installed (step 1); run the binfmt container again after a reboot of the dev machine |
| `data/... permission denied` | `PUID`/`PGID` don't match your Pi user; check `id -u` and fix `.env`, then `docker compose up -d` again |
| Dashboard 500s on first load | schema not applied — check `docker compose logs app`; normally `alembic upgrade head` at boot does this automatically |
| `Login failed` / tokens expired | the app re-auths using `GARMIN_EMAIL`/`GARMIN_PASSWORD` from `.env` (run `docker compose -f docker-compose.prod.yml exec scheduler gdash auth start` and follow the MFA flow if prompted) |
| Port 8000 taken on the Pi | set `GARMINDASH_PORT=8123` in `.env` and `up -d` again |
| Image still old after `up -d` | run `docker compose -f docker-compose.prod.yml pull` first, or `up -d --pull always` |
| Watchdog: dashboard down | `docker compose ... ps` → container should be `Up (healthy)`; check `docker compose logs --tail 50 app` |

## Phase 4 note (Signal)

The `signal-api` service ships in a compose **profile** — it does not run
unless you opt in (it needs a provisioned number first, see ROADMAP):

```bash
docker compose -f docker-compose.prod.yml --profile signal up -d
```

Once `SIGNAL_ENABLED=true` is set in `.env`, the `scheduler` service handles
the morning report + command replies.

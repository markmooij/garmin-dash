# Deployment Guide — Raspberry Pi (private registry)

Goal: run garmin-dash **indefinitely** on a Raspberry Pi inside your network,
with a repeatable update loop. One dev machine builds images (amd64 + arm64),
pushes them to a **private** container registry, and the Pi pulls + runs.

```
┌─────────────────────────┐          ┌──────────────────────────────┐
│  Dev machine (x86)      │  push   │  Private registry (GHCR)     │
│  docker buildx (multi-  │ ──────► │  ghcr.io/<you>/garmin-dash   │
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
runs at boot so a fresh volume self-initializes.

---

## 0. Prerequisites

- **Dev machine**: Docker with buildx (`docker buildx version`), git.
- **Raspberry Pi**: Raspberry Pi OS (64-bit, Bookworm or newer) with Docker
  Engine + Compose v2 (see step 5 for the install commands), reachable via
  SSH from your dev machine, and a user account (uid 1000 = default `pi`).
- **GitHub account** (for a private GHCR package) — or any OCI registry you
  prefer (Harbor, registry:2, …) — adjust `REGISTRY`/`APP_NAME` accordingly.

---

## 1. Dev machine — one-time registry login

Create a GitHub **Personal Access Token (classic)** with the `write:packages`
scope (github.com → Settings → Developer settings → Personal access tokens),
then:

```bash
export GHCR_USER=<your-github-username>
echo <your-PAT> | docker login ghcr.io -u "$GHCR_USER" --password-stdin
# → Login Succeeded
```

Enable the cross-arch emulation once (needed for the arm64 build on x86):

```bash
docker run --privileged --rm tonistiigi/binfmt --install all
```

Verify: `docker buildx ls` should show a builder; the script creates
`garmin-builder` (docker-container driver) automatically on first run.

## 2. Dev machine — build & push (repeatable)

From the repo root:

```bash
cd docker
APP_NAME=<your-github-username>/garmin-dash ./build-push.sh
```

What it does:

1. switches to repo root (build context),
2. creates/reuses a `docker-container` buildx builder,
3. logs in to GHCR if `GHCR_USER`/`GHCR_TOKEN` are set (or use step 1),
4. builds `linux/amd64,linux/arm64` and pushes:

```
ghcr.io/<you>/garmin-dash:latest
ghcr.io/<you>/garmin-dash:v0.1.0   (when TAG=v0.1.0)
```

Version tags are optional but recommended for rollbacks:

```bash
APP_NAME=<your-github-user>/garmin-dash TAG=v0.1.0 ./build-push.sh
```

First build takes a while (pip installs for both architectures). Later
builds are fast thanks to layer caching.

> **Private by default:** packages under `ghcr.io/<you>/` are private.
> The Pi must be logged in to pull them (step 6).

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
| `PUID` / `PGID` | your Pi user's ids (`id -u` / `id -g`, usually 1000/1000) — the containers run as this user so `./data` stays writable |
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

## 6. Pi — login to the private registry & pull

```bash
cd ~/garmin-dash
echo <your-PAT> | docker login ghcr.io -u <your-github-username> --password-stdin
docker compose -f docker-compose.prod.yml pull
```

(Pull once now; updates use `docker compose up -d` which pulls changed
images automatically.)

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
APP_NAME=<your-github-user>/garmin-dash ./build-push.sh     # build+push (or TAG=vX.Y.Z)

# ── Pi ──────────────────────────────────────────────────────────────
ssh pi@<pi-ip>
cd ~/garmin-dash
docker compose -f docker-compose.prod.yml up -d   # pulls new image, restarts changed services
docker compose -f docker-compose.prod.yml ps      # check healthy
```

Rollback (when you used version tags):

```bash
# Pi: pin the previous tag and restart
sed -i 's#garmin-dash:latest#garmin-dash:v0.1.0#' docker-compose.prod.yml
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
| `docker pull` on Pi fails auth | Pi not logged in to ghcr.io (step 6); or PAT lacks `read:packages` |
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

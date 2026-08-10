# ROADMAP.md: Garmin Dash — Self-Hosted Garmin Health & Training Analytics

> Revision 2 (replaces `ROADMAP.v1.md`). Revision 2 incorporates a critical review of v1,
> ecosystem research (PyPI / GitHub / Docker Hub, Aug 2026), and locked product decisions.

## Vision

A self-hosted, open-source health & athletic-performance dashboard that turns raw Garmin
Connect data (Venu 2) into a **Whoop-style experience**: Recovery score, 0–21 Strain,
training-load balance, a behavioral journal with correlation insights, and an LLM coach —
delivered via a local web dashboard and Signal. It **complements, not clones**: Garmin's own
metrics (Training Status, Body Battery, VO2max, Training Effect…) are surfaced alongside
computed ones, because re-deriving them is wasted effort.

## Locked Decisions (v2)

| # | Area | Decision |
|---|---|---|
| 1 | Frontend | **Single-container stack, no Node**: FastAPI + Jinja2 + Alpine.js + Tailwind + uPlot. Extensible via server-rendered pages + a small JSON API. |
| 2 | Messaging | **Signal is mandatory**, implemented as a **standalone, reusable library** (`libs/signal_messenger`) with a clean `Messenger` interface — no app dependencies, so it can be published/used in other projects. |
| 3 | LLM | **Private OpenAI-compatible endpoint** (vLLM/llama.cpp/OpenAI-proxy). Use the `openai` SDK with a configurable `base_url`; no Ollama, no LiteLLM. LLM never computes numbers — it only words them. |
| 4 | Deployment | Dev machine (x86, RTX 2080 Ti) builds **multi-arch images** (`linux/amd64,linux/arm64` via buildx) → push to **private registry (GHCR)** → pull on **Raspberry Pi (arm64)**, the production host. Git repo is public-ready from day 1 (secrets never committed, MIT license, clean history). |
| 5 | Training profile | **Strength-heavy first**; load model is pluggable so cardio/strength weighting adapts per user. Metric engine is **multi-user capable** (schema reserves `user_id`) even though deployment is single-user. |
| 6 | Scope | All of it: computed Whoop-style metrics **and** Garmin-native metrics (Training Status, VO2max, Training Effect, Body Battery, HRV Status, Sleep Score). |
| 7 | Users | Single user for now; `user_id` reserved in schema, engine parameterized by profile (age, max HR, resting HR, sport mix). |
| 8 | Docs | This roadmap is the plan of record. Original preserved as `ROADMAP.v1.md`. |

## Architecture

```
┌───────────────────────────── Garmin Dash container (arm64 on RPi / amd64 on dev) ─────────────────────────────┐
│                                                                                                               │
│  FastAPI app (package: garmin_dash)                                                                            │
│  ├─ ingestion/     APScheduler worker → GarminClient adapter → garminconnect (garth auth, MFA, token cache)    │
│  │                 FIT download + fitparse · idempotent upserts · backoff/retry · backfill · TZ handling      │
│  ├─ metrics/       Strain (0–21) · Recovery (0–100) · ATL/CTL/TSB · baselines · strength volume-load           │
│  ├─ insights/      Journal correlation engine (gated, effect sizes, never p-values)                            │
│  ├─ coach/         Context assembler (exact numbers only) → openai SDK → private OpenAI-compatible endpoint   │
│  ├─ api/           JSON REST routes (dashboard + Signal commands share this)                                   │
│  ├─ web/           Jinja2 templates + Alpine.js + uPlot + Tailwind (Whoop-style UI)                            │
│  └─ db/            SQLAlchemy 2 + Alembic → SQLite (WAL)                                                       │
│                                                                                                               │
│  ┌─────────────────────────────────────────────────────────────────────────────────────────────────────────┐  │
│  │ libs/signal_messenger — standalone package: Messenger interface + SignalClient (httpx → signal-cli-    │  │
│  │ rest-api container). Zero imports from garmin_dash. Reusable in other projects.                        │  │
│  └─────────────────────────────────────────────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
        │                                             │                                              │
        ▼                                             ▼                                              ▼
Garmin Connect (unofficial API)            signal-cli-rest-api (separate container,   Private OpenAI-compatible
(cloud, polling, ToS gray zone —           linked/registered number)                   LLM endpoint (external)
adapter layer isolates it)                                                             
```

Data flow: `GarminClient` (adapter) → ingestion worker → SQLite → metrics/insights engines →
REST API → web UI + Signal bridge. The Signal bridge and the coach both call the same REST API
— one source of truth, no duplicated logic.

## Repository Layout (monorepo, public-ready)

```
garmin-dash/
├── app/                        # FastAPI application (package: garmin_dash)
├── libs/signal_messenger/      # STANDALONE reusable package (own pyproject.toml, README, tests)
├── docker/
│   ├── Dockerfile              # multi-stage, multi-arch (buildx), non-root, healthcheck
│   ├── docker-compose.dev.yml  # app + signal-api (dev machine)
│   ├── docker-compose.prod.yml # app + signal-api (RPi)
│   └── build-push.sh           # buildx amd64+arm64 → GHCR
├── tests/                      # pytest; metrics golden tests from captured Garmin JSON
├── .github/workflows/          # (Phase 7) CI: lint+tests, multi-arch build & publish
├── Makefile                    # dev ergonomics: setup, test, lint, compose-up, build-push
├── pyproject.toml              # project metadata, deps, ruff/pytest config
├── .gitignore                  # venv, .env, *.db, garmin token files, .pi/, caches
├── LICENSE                     # MIT (swap freely; see Open Items)
├── README.md                   # public-facing intro + quickstart
├── ROADMAP.md                  # this file
└── ROADMAP.v1.md               # archived original plan
```

## Tech Stack (final)

| Layer | Choice | Rationale |
|---|---|---|
| Language | Python **≥ 3.12** | `garminconnect` v0.3.9 requires ≥3.12 (verified on PyPI) |
| Web | FastAPI + uvicorn | Async, typed, auto-docs |
| DB | SQLite (WAL) + SQLAlchemy 2 + Alembic | One user ≈ tens of MB/yr; WAL for concurrent reads; Postgres/Timescale is overkill — revisit only if multi-user grows |
| Sync | `garminconnect` behind a `GarminClient` adapter | Actively maintained (2.8k★); adapter isolates the app from API breakage; auth via garth (MFA + token chain, env `GARMINTOKENS`) |
| Scheduler | APScheduler (in-process) | Deterministic intervals; survives restarts via SQLite jobstore |
| FIT parsing | `fitparse` | Accurate intra-activity HR/pace for strain, not lossy summary JSON |
| Frontend | Jinja2 + Alpine.js + Tailwind + **uPlot** | Zero Node runtime, one container; uPlot handles 1,440-pt intraday series that Recharts chokes on |
| Messaging | `libs/signal_messenger` → `bbernhard/signal-cli-rest-api` (Docker) | Mandated; bridge is active (2.75k★) and multi-arch |
| LLM | `openai` SDK → private OpenAI-compatible endpoint | Single provider contract; `base_url`/`api_key` from settings; works with vLLM/llama.cpp servers |
| Deploy | Docker Compose, multi-arch images via buildx | Dev x86 → private GHCR → RPi arm64 |

## Data Model (summary)

- `users` — profile (age, max HR, resting HR, sport mix, calibration state) — seeded with 1 row
- `daily_wellness` — sleep score, RHR, stress summary, respiration, SpO2, Body Battery, HRV (nightly avg)
- `sleep_sessions` — stages (light/deep/REM/awake) with per-stage duration, efficiency; **session-bucketed, stored UTC + device TZ**
- `activities` — summary + sport type + HR zones + `fit_file` reference
- `activity_hr_series` — parsed FIT intra-activity HR/pace (source of strain)
- `exercise_sets` — strength sets/reps (volume-load input; Venu 2 accelerometer rep counting)
  *(deprecated in v2: replaced by training type + duration for strength load)*
- `intraday_series` — 1-min stress / HR / Body Battery for the timeline view
- `journal_entries` — responses to pre-registered questions + free tags + timestamps
- `computed_scores` — strain, recovery, ATL/CTL/TSB per day (materialized; recompute-on-new-data)
- `raw_payloads` — JSON snapshot of each API response (debuggability, re-derivation, golden tests)
- Every table carries `user_id` (default 1) and idempotency keys (unique on `user_id + source_id + date`).

## Metrics Engine Specification

- **Strain (0–21)**: compute *raw load* = Banister TRIMP + Edwards zone-minutes (canonical,
  stored raw). Map to 0–21 via **personal calibration curve** (rolling 90-day 95th percentile ≈ 20,
  capped). Strength sessions add a **duration-based load component** (muscle group type + session
  duration, configurable per sport profile). Scale changes never touch stored history — the curve
  is applied at read time.
- **Recovery (0–100)**: dominant factor = **ln(RMSSD) z-score vs 60-day rolling baseline**
  (RMSSD is log-normal — never z-score raw values); plus RHR deviation from baseline, sleep
  efficiency/deficit, respiration. Weights configurable. Missing night → recovery not shown as
  "low", never zero-filled. Cross-validated against Body Battery / Training Readiness bands.
- **TSB**: standard Coggan ATL (7d) / CTL (42d) exponential weighted load from *strain* (not raw
  TRIMP, so strength counts); cross-checked against Garmin's own acute/chronic load ratio.
- **Journal insights**: pre-registered questions + free tags; **minimum-sample gates** (≥5 logged
  vs ≥5 baseline days); output = direction + effect size + window, labeled *insight*. Engine
  refuses to report below threshold.
- **Garmin-native passthrough** (stored, displayed, fed to coach): Training Status, Training
  Effect (aerobic/anaerobic), VO2max, Body Battery, HRV Status, Sleep Score, Intensity Minutes.

## Hardware & Ecosystem Boundaries (updated from v1)

1. **No barbell velocity / true muscular strain**: Venu 2 does not expose reliable rep counts or
   estimated weights. Instead, strength load is estimated from **training type (muscle group) +
   duration** — configurable per sport profile. Strength strain is approximate; flagged in UI as
   estimate.
2. **No continuous intraday raw HRV**: only overnight average + HRV Status. Sufficient — Whoop's
   recovery is likewise dominated by overnight HRV. Health Snapshots are manual/low-value: dropped.
3. **Unofficial Garmin API**: undocumented, can break, ToS gray zone, account-ban risk. Mitigations:
   conservative polling (≥15 min, jittered), backoff + rate limiting, adapter layer, backfill via
   paging, optional manual bulk-export fallback.
4. **Signal registration friction**: needs a real number (new SIM + captcha, or QR-link your own
   Signal as secondary device — notifications then come from your own number). Locked as a setup
   prerequisite; the messenger library abstracts the bridge so the channel contract never leaks
   into the app.
5. **RPi production constraints**: arm64, ~4–8 GB RAM, no GPU. SQLite + single app container fits;
   the LLM is external by design (decision 3), so no local GPU is needed.

## Phases (each gated by a "Done when")

### Phase 0 — Foundation & API Spike (≈1 wk)
Repo hygiene (git init, .gitignore, LICENSE, README), Python 3.12 venv, pyproject/Makefile,
pytest+ruff scaffold, `settings.py`. Then the risk-killer: **auth spike + endpoint inventory** —
garth MFA login, token cache, dump sleep/HRV/stress/BB/respiration/SpO2/activities/FIT to JSON
fixtures; confirm field shapes and cadence limits; draft Alembic migration v1.
*Done when:* 90 days of history backfilled to JSON with zero manual steps; tokens survive restart;
fixtures committed (sanitized) as golden-test inputs.

### Phase 1 — Ingestion Pipeline
APScheduler worker; `GarminClient` adapter; idempotent upserts; backoff/retry + jittered polling;
FIT download + fitparse parse; TZ/session bucketing; `raw_payloads` capture.
*Done when:* 2 weeks unattended syncing, crash-recovery clean, no duplicate rows, no API 429s.

### Phase 2 — Metrics Engine
TRIMP/Edwards load, strain calibration curve, strength volume-load, ln(RMSSD) recovery composite,
ATL/CTL/TSB, Garmin-native passthrough ingestion. **Golden tests** from Phase 0 fixtures: metrics
must be byte-reproducible. CLI report (`gdash report --today`).
*Done when:* computed trends track Garmin's own Training Load / Body Battery within sane bands;
tests green.

### Phase 3 — Web Dashboard (single container)
Jinja2 + Alpine + uPlot + Tailwind. Views: Today (recovery dial red/yellow/green, strain gauge,
sleep card, Garmin-native strip) → Trends (ATL/CTL/TSB, HRV baseline, RHR) → Intraday timeline
(1-min stress/HR/BB, uPlot, downsampled).
*Done when:* "how am I / what happened" answerable from localhost in <3 s; page structure
extensible (new card ≈ new Jinja partial + API route).

### Phase 4 — Signal Messenger + Morning Report
`libs/signal_messenger` package (interface + signal-cli-rest-api client, own tests, own README);
wire into compose (dev + prod profiles); morning readiness briefing (07:30, configurable);
command parsing (`/summary`, `/strain`, `/recovery`, `/sleep`) routed through the REST API.
*Done when:* report arrives unattended daily; commands answer from the Pi over the weekend;
the package builds/installs standalone (`pip install ./libs/signal_messenger` in a scratch venv).

### Phase 5 — Journal & Correlation Insights
Evening survey (Signal-first, web fallback); pre-registered questions + free tags; gated insight
engine (≥5/≥5 samples, effect size + direction); insights surfaced in dashboard + weekly Signal digest.
*Done when:* engine demonstrably refuses under-powered claims; a real alcohol/HRV-style insight
renders end-to-end after ~2 weeks of logging.

### Phase 6 — LLM Coach
Context assembler (7-day TSB, recovery, sleep deficit, recent load, journal — exact numbers, no
free text from raw data); `openai` SDK → private endpoint (config: `LLM_BASE_URL`, `LLM_API_KEY`,
`LLM_MODEL`); morning briefing injection; Signal Q&A with system prompt enforcing "never invent
numbers; cite the values given; recommend at user's risk level".
*Done when:* all model output is verifiably grounded (a test asserts no hallucinated figures
against a fixture context); Q&A works end-to-end.

### Phase 7 — Release Pipeline & Open-Source Polish
GitHub Actions: lint+tests on push; multi-arch buildx build (`amd64`+`arm64`) → GHCR on tag;
compose prod profile tested on the Pi; README with architecture diagram + screenshots; LICENSE
confirmed; CHANGELOG; docs for the signal_messenger package.
*Done when:* `git push` + tag → image lands on Pi via `docker compose pull && up -d`.

## Cross-Cutting Concerns (built-in, not afterthoughts)

- **Secrets/tokens**: `.env` never committed; Garmin tokens + Signal + LLM keys live in a Docker
  volume / env with `600` permissions; `.gitignore` enforced with a `make check-secrets` guard.
- **Backups**: nightly `sqlite3 .backup` to a volume + optional restic to external storage; restore
  drill documented.
- **Timezones**: all storage UTC; device-TZ retained per record; day bucketing by *session*, not
  local midnight (DST/travel safe).
- **Observability**: structured logging, `/healthz`, sync-status endpoint (dashboard shows last
  successful sync + next poll); alert via Signal when sync fails 3×.
- **Security**: dashboard bound to LAN by default; Tailscale recommended for remote; optional
  basic-auth env toggle. No cloud dependency besides Garmin (and the private LLM endpoint).

## Getting Started (dev machine)

1. `git clone` (or continue this repo) — Python 3.12, venv, `make setup`
2. `cp .env.example .env` → Garmin credentials, `LLM_BASE_URL`/`LLM_API_KEY`/`LLM_MODEL`
3. `make auth` → interactive MFA login, token cache written (gitignored)
4. `make ingest-backfill` (Phase 0/1) → fixtures + DB
5. `make compose-dev` → dashboard on `:8000`, signal-api on `:8080`
6. `make build-push` → multi-arch image to GHCR → `make compose-prod` on the Pi

## Open Items (small, non-blocking)

- **License**: MIT placeholder committed; swap to AGPL-3.0 if you prefer copyleft for the
  self-hosted-SaaS scenario — one-line change.
- **Registry**: GHCR assumed for `docker/build-push.sh`; swap `REGISTRY` env for a self-hosted
  `registry:2`/Harbor if preferred.
- **Signal number**: decide SIM-vs-secondary-device-linking before Phase 4 setup.
- **LLM endpoint**: confirm it speaks the OpenAI chat-completions contract (vLLM, llama.cpp
  server, or a proxy all do).

# Garmin Dash

A self-hosted, open-source health & athletic-performance dashboard that turns raw Garmin Connect data (Venu 2) into a **Whoop-style experience**: Recovery score, 0–21 Strain, training-load balance, a behavioral journal with correlation insights, and an LLM coach — delivered via a local web dashboard and Signal.

## Features

- 📊 **Recovery Score**: 0–100 composite score based on HRV, RHR, sleep efficiency
- 🏃 **Strain (0–21)**: Cardio + strength load with personal calibration
- 📈 **Training Load**: ATL/CTL/TSB (Acute/Chronic Training Load)
- 📱 **Signal Integration**: Morning readiness reports, command responses
- 🧠 **LLM Coach**: Context-aware, private endpoint, grounded in real data
- 📚 **Behavioral Journal**: Correlate habits with recovery/strain
- 🖥️ **Local Dashboard**: Whoop-style UI, extensible via Jinja2

## Quick Start

```bash
# Clone and setup
git clone <repo-url>
cd garmin-dash
make setup

# Configure authentication
cp .env.example .env
# fill in GARMIN_EMAIL / GARMIN_PASSWORD, then:
gdash auth start        # begins MFA login
gdash auth code <CODE>  # complete with the emailed code

# Ingest + compute
gdash ingest backfill 90   # pull 90 days of history
gdash metrics compute      # materialize strain/recovery/ATL/CTL/TSB
gdash report today         # 📊 text report

# Background sync (every 15 min ±2 jitter)
gdash ingest schedule

# Web dashboard (dev; port overridable via GARMINDASH_PORT)
uvicorn app.app:app --port 8123
# → Today:  http://localhost:8123/  ·  Trends: /trends  ·  Intraday: /intraday
# → JSON:   /api/summary · /api/trends · /api/intraday

# Start dev containers (app + signal-api)
make compose-dev

# Access dashboard at http://localhost:8000
```

## Deployment (Raspberry Pi)

See [DEPLOY.md](DEPLOY.md) for the full walkthrough: build a multi-arch image
(amd64 + arm64) on your dev machine, push to a private registry (GHCR), and run
`app` + `scheduler` containers on the Pi with `restart: unless-stopped`.

```bash
# dev machine — build & push (one command, repeatable)
cd docker && APP_NAME=<your-github-user>/garmin-dash ./build-push.sh

# Raspberry Pi — start (and it stays up)
cd ~/garmin-dash
# (copy docker-compose.prod.yml + .env.prod.example → .env + data/, see DEPLOY.md)
docker compose -f docker-compose.prod.yml up -d
curl http://localhost:8000/healthz   # → {"status":"ok"}
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  Garmin Dash Container                   │
│  FastAPI + Jinja2 + Alpine.js + uPlot + Tailwind        │
├─────────────────────────────────────────────────────────┤
│  • ingestion/     APScheduler → garminconnect           │
│  • metrics/       Strain, Recovery, ATL/CTL/TSB         │
│  • insights/      Journal correlation engine            │
│  • coach/         LLM context assembler + OpenAI SDK    │
│  • api/           JSON REST + Signal commands           │
│  • web/           Server-rendered dashboard             │
│  • db/            SQLite (WAL)                          │
├─────────────────────────────────────────────────────────┤
│  • libs/signal_messenger (standalone, reusable)         │
└─────────────────────────────────────────────────────────┘
         │                    │
         ▼                    ▼
   Garmin Connect      Private OpenAI-compatible
   (unofficial API)        LLM endpoint
```

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the complete development plan.

## License

MIT License — see [LICENSE](LICENSE) for details.

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
#   Journal: /journal  ·  Insights: /insights  ·  Coach: /coach  ·  Uitleg: /uitleg
# → JSON:   /api/summary · /api/trends · /api/intraday · /api/journal · /api/insights

# Journal (Phase 5) — web form, CLI, or Signal (/log alcohol 2)
# The Signal evening reminder asks at most JOURNAL_PROMPT_FACTORS_PER_DAY (3)
# questions and rotates through the registry, prioritising the factors
# furthest from clearing the insight gate; the web form always has all of them.
# The factor vocabulary is editable at /journal/factors (add/edit/soft-delete).
# Set DASHBOARD_URL so those messages link the full form (highly recommended:
# it is what keeps the Signal message short without losing the other factors).
gdash journal log stress_hoog j   # log a factor for today
gdash journal log stretchen 2     # count factors take a number
gdash journal insights            # gated correlation insights

# Insights (Phase 5.5) — /insights sorts by date/effect/alphabet (asc/desc),
# caps at 8 cards, and can show a short LLM interpretation per correlation
# (grounded + cached; needs LLM_ENABLED=true).

# LLM coach (Phase 6) — needs LLM_ENABLED=true + LLM_BASE_URL in .env
gdash coach ask "Hoe ging deze week?"   # or Signal /ask, or web /coach

# Start dev containers (app + signal-api)
make compose-dev

# Access dashboard at http://localhost:8000
```

## Deployment (Raspberry Pi)

See [DEPLOY.md](DEPLOY.md) for the full walkthrough: build a multi-arch image
(amd64 + arm64) on your dev machine, push to a container registry (e.g.
GHCR — set `REGISTRY=ghcr.io/<you>` when building), and run `app` +
`scheduler` containers on the Pi with `restart: unless-stopped`.

```bash
# dev machine — build & push (one command, repeatable, no login needed)
cd docker && ./build-push.sh

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
│  • journal/       Factor registry + gated insights      │
│  • coach/         LLM context assembler + OpenAI SDK    │
│  • messaging/     Signal commands + briefings           │
│  • web/           Server-rendered dashboard + JSON API  │
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

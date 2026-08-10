# ROADMAP.md: Self-Hosted Garmin-to-Whoop Health Analytics Engine

## Project Vision & Core Strategy
Build a fully self-hosted, open-source health and athletic performance dashboard that leverages raw data from the Garmin Venu 2 to replicate the core analytical capabilities of Whoop—without recurring subscription fees or cloud dependencies. 

The system will automatically pull all available health/activity streams from Garmin Connect, process them through sports-science algorithms (TRIMP, HRV baseline tracking, Acute vs. Chronic Training Load), present them on a local web dashboard, and interactively communicate with the user via Signal Messenger and an integrated LLM.

---

## Technical Stack Recommendation

*   **Core Backend**: Python 3.11+ using **FastAPI** (Async, high-performance API, clean documentation).
*   **Data Ingestion**: `garminconnect` Python client + `APScheduler` for scheduled background cron syncing.
*   **Database**: **SQLite** (via SQLAlchemy & Alembic) for zero-config single-user deployment; optionally **PostgreSQL + TimescaleDB** for time-series optimization.
*   **Frontend Dashboard**: **Next.js** (React) with **Tailwind CSS** and **Recharts / Chart.js** for modern, responsive Whoop-style visualizations.
*   **Messaging System**: **`signal-cli-rest-api`** running in Docker + a lightweight Python wrapper (`httpx`) to send/receive Signal messages.
*   **LLM Engine**: **Ollama** (Local execution using `llama3` or `mistral`) or **LiteLLM** (Unified bridge to Local, OpenAI, or Anthropic models).
*   **Deployment**: **Docker Compose** multi-container setup (`backend`, `frontend`, `db`, `signal-api`, `ollama`).

---

## Hardware & Data Bottlenecks (What CANNOT Be Replicated)

Documenting known physical and ecosystem boundaries between the Garmin Venu 2 hardware and Whoop 4.0:

1.  **Muscular Strain (Strength Velocity)**: Whoop's "Strength Trainer" uses accelerometer-based barbell/movement velocity tracking to scale strain for low-heart-rate heavy resistance training. The Venu 2 does not expose accelerometer velocity data at this granular level; weightlifting strain will remain primarily cardio-based.
2.  **Continuous 24/7 Raw HRV Stream**: The Venu 2 processes heart rate variability continuously for internal metrics (Body Battery & Stress), but only exposes raw HRV values during overnight sleep summaries and manual 2-minute "Health Snapshots." Continuous intraday raw HRV cannot be scraped.
3.  **Form Factor / Wearability**: Whoop is a screenless, non-obtrusive, high-flex fabric band wearable on the upper arm or bicep. The Venu 2 is a wrist-mounted AMOLED smartwatch; wearability comfort during sleep remains subject to hardware form factor.

---

## Development Roadmap & Feature Phases

### Phase 1: Data Pipeline & Processing Engine
**Goal**: Pull 100% of available data endpoints from Garmin Connect and compute missing Whoop metrics.

*   [ ] **Garmin Authenticator & Sync Worker**:
    *   Implement `garminconnect` background worker to authenticate, store session tokens, and execute daily interval fetches (every 15–30 mins).
    *   Pull Daily Summaries: Sleep stages, Resting Heart Rate (RHR), Stress timeline, Body Battery timeline, Respiration, SpO2, and Health Snapshots.
    *   Pull Activity Summaries: Heart rate zones, `.FIT` activity files, calories, duration, and exercise split details.
*   [ ] **Database Schema Design**:
    *   Define models for `daily_wellness`, `sleep_sessions`, `activities`, `hrv_snapshots`, `journal_entries`, and `computed_scores`.
*   [ ] **Algorithmic Metric Engine**:
    *   **Cardio Strain (Whoop 0–21 Scale)**: Implement Banister TRIMP (Training Impulse) or Edwards Heart Rate Zone weighting on activity HR time-series to normalize daily strain from 0 to 21.
    *   **Recovery Score (0–100%)**: Build a composite score using overnight HRV (RMSSD), RHR deviation from 7-day baseline, and sleep efficiency.
    *   **Training Stress Balance (TSB)**: Calculate Acute Training Load (ATL, 7-day exponentially weighted fatigue) vs. Chronic Training Load (CTL, 42-day exponentially weighted fitness) to establish daily Form:
        $$TSB = CTL - ATL$$

---

### Phase 2: Local Web Dashboard (UI/UX)
**Goal**: Build a responsive web portal mimicking Whoop's metric cards and analytics.

*   [ ] **Overview Hub**:
    *   Daily Recovery Dial (Red / Yellow / Green), Day Strain Gauge (0–21), and Body Battery vs. Sleep performance overview.
*   [ ] **Deep-Dive Views**:
    *   **Sleep & HRV View**: Sleep architecture breakdown (Light, Deep, REM), overnight respiration, RHR trends, and HRV baseline ranges.
    *   **Strain & Fitness View**: ATL / CTL / TSB chart (Fitness, Fatigue, Form over time) to identify overtraining risks.
    *   **Intraday Timeline**: High-resolution chart mapping Stress levels, HR, and Body Battery drain across a selected 24-hour window.

---

### Phase 3: Signal Messenger Integration
**Goal**: Provide interactive, phone-native push notifications and status reporting via Signal.

*   [ ] **Signal Docker Bridge**:
    *   Set up `signal-cli-rest-api` in Docker, register/link a secondary or dedicated phone number.
*   [ ] **Automated Morning Readiness Report**:
    *   Trigger an automated morning message (e.g., at 07:30 AM):
        > *"Good morning! Recovery: 82% (Green). Sleep: 7h 42m. RHR: 52 bpm. Strain Target: 12.5–15.0. Form is optimal for a heavy workout today."*
*   [ ] **Outbound Command Parsing**:
    *   Enable command listening (`/summary`, `/strain`, `/recovery`, `/sleep`) to retrieve instant metric snapshots directly in the Signal chat.

---

### Phase 4: Daily Routine Interview & Behavioral Journal
**Goal**: Replicate Whoop's Behavioral Journal to quantify how daily choices affect recovery.

*   [ ] **Interactive Evening Survey (Signal or Web UI Prompt)**:
    *   Send a daily evening message or render a lightweight web modal with optional survey questions:
        1.  *Workout*: Type & subjective effort scale (1–10).
        2.  *Nutrition*: Healthy eating rating (Yes / Moderate / Poor).
        3.  *Substances*: Caffeine intake past 2 PM? Alcohol consumed (number of drinks)?
        4.  *Sleep Quality*: Subjective sleep score (1–5).
*   [ ] **Habit Impact & Correlation Engine**:
    *   Correlate logged journal habits against next-day HRV, Sleep Efficiency, and Recovery scores over a rolling 30/60/90-day period.
    *   Output statistical impact insights (e.g., *"Alcohol consumption reduces your overnight HRV by an average of 14% and sleep score by 18 points"*).

---

### Phase 5: LLM Health Intelligence & Actionable Coach
**Goal**: Integrate an AI model to evaluate full-spectrum data and generate human-like training advice.

*   [ ] **Context Assembler**:
    *   Build a pipeline that constructs a structured daily prompt containing: 7-day TSB trajectory, morning Recovery score, sleep deficit, recent activity load, and recent journal responses.
*   [ ] **LLM Integration**:
    *   Connect Ollama (e.g., `llama3.1`) or an external API via LiteLLM with a system prompt tuned for sports science coaching.
*   [ ] **Daily Conversational Advice**:
    *   Inject LLM summary directly into the morning Signal briefing:
        > *"AI Coach: You've accumulated high fatigue over the last 3 days (TSB: -28). Although your recovery is moderate (64%), your journal notes 2 drinks last night. Recommend an active recovery session or light yoga today rather than your planned leg day."*
*   [ ] **Interactive Q&A**:
    *   Allow the user to reply directly in Signal (*"Why is my recovery low today?"* or *"Can I do a short run tonight?"*), passing chat context to the LLM for real-time responses.

---

## Getting Started: Initial Setup Checklist

1. Clone repo framework and setup Python virtual environment (`python -m venv venv`).
2. Install primary dependencies: `pip install fastapi uvicorn garminconnect sqlalchemy alembic httpx`.
3. Run authentication test script (`test_garmin.py`) to verify multi-factor authentication and initial token caching with Garmin Connect.
4. Launch local database migrations and initialize `docker-compose.yml`.

"""Endpoint inventory / backfill — dump raw Garmin responses to JSON fixtures.

Phase 0 deliverable: capture real API payloads so the schema and the metrics
golden tests are built against real shapes rather than assumptions.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

from ..auth.session import resume_from_tokens


FIXTURES_DIR = Path("tests/fixtures/garmin")


def _probe(name: str, fn: Callable[[], Any]) -> dict[str, Any]:
    """Call one endpoint and capture the result or the error."""
    try:
        data = fn()
        return {"endpoint": name, "ok": True, "data": data}
    except Exception as e:  # noqa: BLE001
        return {"endpoint": name, "ok": False, "error": f"{type(e).__name__}: {e}"}


def backfill_data(days: int = 7) -> int:
    """Dump a sample of each endpoint to tests/fixtures/garmin/."""
    client = resume_from_tokens()
    if client is None:
        print("❌ Not authenticated. Run: gdash auth start")
        return 1

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    today = date.today()
    yesterday = today - timedelta(days=1)
    start = today - timedelta(days=days)
    cday = yesterday.isoformat()

    probes: dict[str, Callable[[], Any]] = {
        "user_summary": lambda: client.get_user_summary(cday),
        "sleep_data": lambda: client.get_sleep_data(cday),
        "hrv_data": lambda: client.get_hrv_data(cday),
        "stress_data": lambda: client.get_stress_data(cday),
        "body_battery": lambda: client.get_body_battery(start.isoformat(), cday),
        "respiration": lambda: client.get_respiration_data(cday),
        "spo2": lambda: client.get_spo2_data(cday),
        "heart_rates": lambda: client.get_heart_rates(cday),
        "rhr_day": lambda: client.get_rhr_day(cday),
        "training_status": lambda: client.get_training_status(cday),
        "training_readiness": lambda: client.get_training_readiness(cday),
        "max_metrics": lambda: client.get_max_metrics(cday),
        "activities": lambda: client.get_activities(0, 20),
        "activities_by_date": lambda: client.get_activities_by_date(
            start.isoformat(), cday
        ),
    }

    print(f"📥 Endpoint inventory  ({start} → {cday})")
    print("=" * 60)

    results = []
    for name, fn in probes.items():
        result = _probe(name, fn)
        results.append(result)

        out = FIXTURES_DIR / f"{name}.json"
        out.write_text(json.dumps(result["data"] if result["ok"] else result, indent=2, default=str))

        if result["ok"]:
            data = result["data"]
            size = len(data) if isinstance(data, (list, dict)) else 1
            print(f"  ✅ {name:<22} {size:>5} items  → {out}")
        else:
            print(f"  ❌ {name:<22} {result['error'][:60]}")

    ok = sum(1 for r in results if r["ok"])
    print()
    print(f"✅ {ok}/{len(results)} endpoints captured → {FIXTURES_DIR}")
    return 0

"""Tests for the web dashboard: routes, JSON API, query functions."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from app.db.models import IntradaySeries
from app.web import query


if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@pytest.fixture
def client(seeded: Session, session: Session):  # noqa: ARG001
    """TestClient with the DB dependency pointed at the temp DB."""
    from app.web import create_app
    from app.web import routes as web_routes

    def override_db() -> Session:
        return session

    app = create_app()
    app.dependency_overrides[web_routes._db] = override_db
    with TestClient(app) as c:
        yield c


# ── query layer ────────────────────────────────────────────────────────

def test_summary_contains_all_cards(seeded: Session):
    d = query.summary_for(seeded, date(2026, 8, 9))
    assert d["recovery"]["score"] == 71.5
    assert d["recovery"]["band"] == "green"
    assert d["recovery"]["hrv_used"] is False
    assert d["strain"] == 15.25
    assert d["tsb"] == pytest.approx(-2.9)
    assert d["vo2max"] == 51.0
    assert d["wellness"]["rhr"] == 45.0
    assert d["wellness"]["bb_at_wake"] == 80
    assert d["sleep"]["score"] == 81.0
    assert len(d["activities"]) == 1
    a = d["activities"][0]
    assert a["trimp"] == pytest.approx(1707.8)
    assert a["strength"] == pytest.approx(2391.1)
    assert a["aerobic_te"] == 2.5


def test_summary_empty_day_returns_nulls(seeded: Session):
    d = query.summary_for(seeded, date(2026, 8, 1))
    assert d["recovery"]["score"] is None
    assert d["strain"] is None
    assert d["activities"] == []


def test_trends_series_aligned(seeded: Session):
    t = query.trends_for(seeded, days=30, end=date(2026, 8, 9))
    n = len(t["dates"])
    assert n == 1  # only one day of data in the window
    assert t["recovery"] == [71.5]
    assert t["strain"] == [15.25]
    assert t["tsb"] == [pytest.approx(-2.9)]
    assert t["vo2max"] == [51.0]
    # every series has the same length
    for key in ("recovery", "strain", "atl", "ctl", "tsb", "rhr", "stress", "sleep_score", "bb_wake", "steps", "vo2max"):
        assert len(t[key]) == n, key


def test_intraday_series_and_windows(seeded: Session):
    d = query.intraday_for(seeded, date(2026, 8, 9))
    assert len(d["series"]["heart_rate"]) == 30
    assert len(d["series"]["stress"]) == 30
    assert len(d["series"]["body_battery"]) == 5
    assert len(d["activity_windows"]) == 1
    w = d["activity_windows"][0]
    assert w["type"] == "strength_training"
    assert w["end_s"] - w["start_s"] == 3600
    # epochs must be true UTC; naive .timestamp() would shift every sample
    # by the local UTC offset (Europe/Amsterdam = +2)
    assert d["series"]["heart_rate"][0][0] == 1786233600
    assert d["series"]["body_battery"][0][0] == 1786233600


def test_intraday_local_day_bucket(seeded: Session):
    """A local day spans 22:00Z→22:00Z (UTC+2), not a UTC day."""
    ts = (
        datetime(2026, 8, 8, 23, 0, tzinfo=UTC),   # 01:00 local Aug 9
        datetime(2026, 8, 9, 21, 30, tzinfo=UTC),  # 23:30 local Aug 9
        datetime(2026, 8, 9, 22, 30, tzinfo=UTC),  # 00:30 local Aug 10
    )
    for t in ts:
        seeded.add(IntradaySeries(user_id=1, kind="heart_rate", ts_gmt=t, value=60.0))
    seeded.commit()
    d9 = query.intraday_for(seeded, date(2026, 8, 9))
    hrs9 = [r[0] for r in d9["series"]["heart_rate"]]
    assert hrs9[0] == datetime(2026, 8, 8, 23, 0, tzinfo=UTC).timestamp()
    assert datetime(2026, 8, 9, 21, 30, tzinfo=UTC).timestamp() in hrs9
    assert datetime(2026, 8, 9, 22, 30, tzinfo=UTC).timestamp() not in hrs9
    d10 = query.intraday_for(seeded, date(2026, 8, 10))
    hrs10 = [r[0] for r in d10["series"]["heart_rate"]]
    assert datetime(2026, 8, 9, 22, 30, tzinfo=UTC).timestamp() in hrs10


# ── HTTP layer ─────────────────────────────────────────────────────────

def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_today_view_renders(client):
    r = client.get("/?date=2026-08-09")
    assert r.status_code == 200
    html = r.text
    assert "Herstel" in html
    assert "Belasting" in html
    assert "Slaap" in html
    assert "Garmin-native" in html
    assert "Kracht" in html


def test_today_view_date_param(client):
    r = client.get("/?date=2026-08-09")
    assert r.status_code == 200
    assert "81" in r.text  # sleep score


def test_trends_view_renders(client):
    r = client.get("/trends?days=30")
    assert r.status_code == 200
    assert "chart-tsb" in r.text
    assert "ATL" in r.text


def test_intraday_view_renders(client):
    r = client.get("/intraday?date=2026-08-09")
    assert r.status_code == 200
    assert "chart-intraday" in r.text


def test_api_summary_json(client):
    d = client.get("/api/summary?date=2026-08-09").json()
    assert d["date"] == "2026-08-09"
    assert d["recovery"]["score"] == 71.5
    assert d["strain"] == 15.25


def test_api_trends_json(client):
    d = client.get("/api/trends?days=90").json()
    assert len(d["dates"]) == 1
    assert d["recovery"][0] == 71.5


def test_api_intraday_json(client):
    d = client.get("/api/intraday?date=2026-08-09").json()
    assert len(d["series"]["heart_rate"]) == 30
    assert len(d["activity_windows"]) == 1


def test_api_invalid_date(client):
    assert client.get("/api/intraday?date=not-a-date").status_code == 422
    assert client.get("/api/trends?days=9999").status_code == 422









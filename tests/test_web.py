"""Tests for the web dashboard: routes, JSON API, query functions."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from app.db.models import IntradaySeries
from app.web import explanation, query


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


# last sync time + morning advice (dashboard header / card)

def test_latest_sync_time_none_when_never_synced(seeded: Session):
    assert query.latest_sync_time(seeded) is None


def test_latest_sync_time_returns_most_recent_across_streams(seeded: Session):
    from app.db.models import SyncState

    older = datetime(2026, 8, 9, 6, 0, tzinfo=UTC)
    newer = datetime(2026, 8, 9, 7, 58, tzinfo=UTC)
    seeded.add(
        SyncState(user_id=1, stream="sleep", last_date=date(2026, 8, 9), last_sync_at=older)
    )
    seeded.add(
        SyncState(user_id=1, stream="activities", last_date=date(2026, 8, 9), last_sync_at=newer)
    )
    seeded.commit()
    got = query.latest_sync_time(seeded)
    assert got is not None
    assert got.replace(tzinfo=UTC) == newer  # the max, not the first row


def test_latest_morning_report_none_when_never_sent(seeded: Session):
    assert query.latest_morning_report(seeded) is None


def test_latest_morning_report_returns_most_recent(seeded: Session):
    from app.db.models import MorningReport

    seeded.add(
        MorningReport(
            user_id=1, report_date=date(2026, 8, 8), briefing="oud", commentary="oud advies"
        )
    )
    seeded.add(
        MorningReport(
            user_id=1, report_date=date(2026, 8, 9), briefing="nieuw", commentary="nieuw advies"
        )
    )
    seeded.commit()
    assert query.latest_morning_report(seeded) == {
        "date": "2026-08-09",
        "briefing": "nieuw",
        "commentary": "nieuw advies",
    }


def test_latest_morning_report_handles_missing_commentary(seeded: Session):
    from app.db.models import MorningReport

    seeded.add(
        MorningReport(
            user_id=1, report_date=date(2026, 8, 9), briefing="tekst", commentary=None
        )
    )
    seeded.commit()
    got = query.latest_morning_report(seeded)
    assert got["commentary"] is None
    assert got["briefing"] == "tekst"


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


def test_today_view_shows_last_sync_time(client, session: Session):
    from app.db.models import SyncState

    session.add(
        SyncState(
            user_id=1,
            stream="activities",
            last_date=date(2026, 8, 9),
            last_sync_at=datetime(2026, 8, 9, 5, 58, tzinfo=UTC),
        )
    )
    session.commit()
    html = client.get("/?date=2026-08-09").text
    assert "gesynchroniseerd" in html
    # 05:58 UTC rendered in Europe/Amsterdam (CEST, +02:00) = 07:58 local
    assert "07:58" in html


def test_today_view_omits_sync_line_when_never_synced(client):
    assert "gesynchroniseerd" not in client.get("/?date=2026-08-09").text


def test_today_view_shows_morning_advice(client, session: Session):
    from app.db.models import MorningReport

    session.add(
        MorningReport(
            user_id=1,
            report_date=date(2026, 8, 9),
            briefing="Garmin Dash\nHerstel 71/100",
            commentary="Rustig aan vandaag.",
        )
    )
    session.commit()
    html = client.get("/?date=2026-08-09").text
    assert "Ochtendadvies" in html
    assert "Rustig aan vandaag." in html
    assert "Herstel 71/100" in html  # full message available behind the toggle


def test_today_view_omits_advice_card_when_no_report(client):
    assert "Ochtendadvies" not in client.get("/?date=2026-08-09").text


def test_today_view_advice_card_without_commentary(client, session: Session):
    """A briefing sent with the LLM off still shows the card + full message."""
    from app.db.models import MorningReport

    session.add(
        MorningReport(
            user_id=1,
            report_date=date(2026, 8, 9),
            briefing="Garmin Dash\nHerstel 71/100",
            commentary=None,
        )
    )
    session.commit()
    html = client.get("/?date=2026-08-09").text
    assert "Ochtendadvies" in html
    assert "Geen coach-advies" in html


def test_today_view_date_param(client):
    r = client.get("/?date=2026-08-09")
    assert r.status_code == 200
    assert "81" in r.text  # sleep score


def test_today_view_days_buttons_present(client):
    html = client.get("/?date=2026-08-09").text
    assert "30d" in html
    assert "90d" in html
    assert "180d" in html


def test_today_view_days_defaults_to_90(client):
    html = client.get("/?date=2026-08-09").text
    # the 90d button is the active one by default
    assert "days: 90" in html


def test_today_view_invalid_days_falls_back_to_90(client):
    html = client.get("/?date=2026-08-09&days=999").text
    assert "days: 90" in html


def test_today_view_days_param_reflected(client):
    html = client.get("/?date=2026-08-09&days=30").text
    assert "days: 30" in html


def test_today_view_shows_trend_averages(client):
    """The chosen-day value is shown against the trend average."""
    html = client.get("/?date=2026-08-09").text
    assert "gem." in html  # recovery card average label
    assert "(90d)" in html  # the window is labelled


def test_today_view_shows_abbr_tooltips(client):
    """Abbreviations carry a hover tooltip and a link to the Uitleg page."""
    html = client.get("/?date=2026-08-09").text
    # RHR tooltip + link to its uitleg anchor
    assert "Rusthartslag" in html
    assert "/uitleg#rhr-rusthartslag" in html
    # ATL / CTL / TSB tooltips link to the TSB card
    assert "/uitleg#tsb-training-stress-balance" in html
    assert "Acute Training Load" in html
    assert "Chronic Training Load" in html
    assert "Training Stress Balance" in html
    # VO2max tooltip
    assert "/uitleg#vo2max" in html


def test_trend_averages_computes_means(seeded: Session):
    """Averages are computed over the window and exclude missing days."""
    d = query.trend_averages(seeded, days=30, end=date(2026, 8, 9))
    assert d["days"] == 30
    assert d["recovery"] == pytest.approx(71.5)
    assert d["strain"] == pytest.approx(15.25)
    assert d["tsb"] == pytest.approx(-2.9)
    assert d["rhr"] == pytest.approx(45.0)
    assert d["sleep_score"] == pytest.approx(81.0)
    assert d["vo2max"] == pytest.approx(51.0)


def test_trend_averages_none_when_no_data(seeded: Session):
    """A metric with no data in the window yields None, not 0."""
    d = query.trend_averages(seeded, days=30, end=date(2026, 1, 1))
    assert d["recovery"] is None
    assert d["rhr"] is None


def test_trend_averages_intensity_is_sum_then_mean(seeded: Session):
    """Intensity minutes = moderate + vigorous summed per day, then averaged."""
    d = query.trend_averages(seeded, days=30, end=date(2026, 8, 9))
    # seeded day has 7 moderate + 10 vigorous = 17 intensity minutes
    assert d["intensity_min"] == pytest.approx(17.0)


def test_explanation_metrics_have_unique_slugs():
    """Every uitleg metric card gets a stable, unique anchor slug."""
    from app.web.explanation import SECTIONS

    slugs = [m.slug for s in SECTIONS for m in s.metrics]
    assert len(slugs) == len(set(slugs)), "duplicate anchor slugs"
    assert all(slugs)  # none empty
    assert "vo2max" in slugs
    assert "rhr-rusthartslag" in slugs
    assert "tsb-training-stress-balance" in slugs


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


# ── journal + insights (Phase 5) ───────────────────────────────────

def test_journal_for_empty_day(seeded: Session):
    d = query.journal_for(seeded, date(2026, 8, 9))
    assert d["responses"] == {}
    assert len(d["factors"]) >= 5


def test_journal_for_logged_day(seeded: Session):
    from app.journal.entries import upsert_response

    upsert_response(seeded, date(2026, 8, 9), "alcohol", 2.0)
    d = query.journal_for(seeded, date(2026, 8, 9))
    assert d["responses"] == {"alcohol": 2.0}


def test_journal_history_most_recent_first(seeded: Session):
    from app.journal.entries import upsert_response

    upsert_response(seeded, date(2026, 8, 5), "alcohol", 1.0)
    upsert_response(seeded, date(2026, 8, 7), "alcohol", 2.0)
    hist = query.journal_history(seeded, days=30, end=date(2026, 8, 9))
    assert [e["date"] for e in hist["entries"]] == ["2026-08-07", "2026-08-05"]


def test_insights_for_empty_when_ungated(seeded: Session):
    d = query.insights_for(seeded, end=date(2026, 8, 9))
    assert d["insights"] == []
    assert d["min_samples"] >= 1


def test_journal_view_renders(client):
    r = client.get("/journal?date=2026-08-09")
    assert r.status_code == 200
    assert "Dagboek" in r.text
    assert "Alcohol" in r.text


def test_journal_save_roundtrip(client):
    r = client.post(
        "/journal",
        data={"entry_date": "2026-08-09", "f_alcohol": "2", "f_stress_hoog": "on", "notes": "test"},
    )
    assert r.status_code == 200  # TestClient follows the 303 redirect
    assert len(r.history) == 1
    assert r.history[0].status_code == 303
    r2 = client.get("/api/journal?date=2026-08-09")
    body = r2.json()
    assert body["responses"]["alcohol"] == 2.0
    assert body["responses"]["stress_hoog"] is True
    assert body["notes"] == "test"


def test_journal_save_unchecked_bool_is_false(client):
    client.post("/journal", data={"entry_date": "2026-08-09", "f_ziek": "on"})
    body = client.get("/api/journal?date=2026-08-09").json()
    assert body["responses"]["ziek"] is True
    # resubmitting without the checkbox flips it back to False (form omits unchecked boxes)
    client.post("/journal", data={"entry_date": "2026-08-09"})
    body2 = client.get("/api/journal?date=2026-08-09").json()
    assert body2["responses"]["ziek"] is False


def test_insights_view_renders_empty_state(client):
    r = client.get("/insights")
    assert r.status_code == 200
    assert "Nog geen inzichten" in r.text


def test_insights_view_accepts_sort_params(client):
    for sort in ("effect", "date", "alphabet"):
        for direction in ("asc", "desc"):
            r = client.get(f"/insights?sort={sort}&dir={direction}")
            assert r.status_code == 200
    # invalid sort/direction fall back to defaults without erroring
    r = client.get("/insights?sort=bogus&dir=sideways")
    assert r.status_code == 200
    assert "Nog geen inzichten" in r.text  # empty state still renders


def test_factors_view_renders_registry(client):
    r = client.get("/journal/factors")
    assert r.status_code == 200
    assert "Factoren beheren" in r.text
    assert "Alcohol" in r.text
    assert "Nieuwe factor" in r.text


def test_factors_add_edit_delete_restore_roundtrip(client):
    # add
    r = client.post(
        "/journal/factors",
        data={"key": "meditatie", "label": "Meditatie", "kind": "bool", "prompt": "10+ min gemediteerd"},
    )
    assert r.status_code == 200
    body = client.get("/api/journal?date=2026-08-09").json()
    keys = [f["key"] for f in body["factors"]]
    assert "meditatie" in keys

    # edit
    r = client.post(
        "/journal/factors/meditatie/edit",
        data={"label": "Meditatie (nieuw)", "kind": "bool", "prompt": "10+ min"},
    )
    assert r.status_code == 200
    body = client.get("/api/journal?date=2026-08-09").json()
    f = next(f for f in body["factors"] if f["key"] == "meditatie")
    assert f["label"] == "Meditatie (nieuw)"

    # delete (soft) → hidden from the journal form
    r = client.post("/journal/factors/meditatie/delete")
    assert r.status_code == 200
    body = client.get("/api/journal?date=2026-08-09").json()
    assert "meditatie" not in [f["key"] for f in body["factors"]]

    # restore
    r = client.post("/journal/factors/meditatie/restore")
    assert r.status_code == 200
    body = client.get("/api/journal?date=2026-08-09").json()
    assert "meditatie" in [f["key"] for f in body["factors"]]


def test_factors_add_invalid_key_shows_error(client):
    r = client.post(
        "/journal/factors",
        data={"key": "Ongeldig!", "label": "X", "kind": "bool", "prompt": "y"},
    )
    assert r.status_code == 400
    assert "key" in r.text.lower()


def test_api_journal_json(client):
    d = client.get("/api/journal?date=2026-08-09").json()
    assert d["date"] == "2026-08-09"
    assert "factors" in d


def test_api_insights_json(client):
    d = client.get("/api/insights").json()
    assert "insights" in d
    assert "window_days" in d


# ── coach (Phase 6) ──────────────────────────────────────────────

def test_coach_view_renders_disabled_state(client):
    r = client.get("/coach")
    assert r.status_code == 200
    assert "uitgeschakeld" in r.text


def test_coach_ask_disabled_returns_message(client):
    r = client.post("/api/coach/ask", json={"question": "Hoe gaat het?"})
    assert r.status_code == 200
    assert "niet beschikbaar" in r.json()["answer"].lower()


def test_coach_ask_empty_question_400(client):
    r = client.post("/api/coach/ask", json={"question": ""})
    assert r.status_code == 400


def test_explanation_view_renders_all_metric_sections(client):
    r = client.get("/uitleg")
    assert r.status_code == 200
    for needle in (
        "Wat is het?",
        "Wat doet het?",
        "Hoe ontwikkelt het zich overdag?",
        "Herstel",
        "Strain",
        "TSB",
        "Dagboek",
        "Inzichten",
    ):
        assert needle in r.text


def test_explanation_link_in_nav(client):
    r = client.get("/")
    assert 'href="/uitleg"' in r.text










def test_explanation_covers_every_dashboard_metric():
    """Guard against a metric being added to the dashboard but not documented."""
    names = [m.name for s in explanation.SECTIONS for m in s.metrics]
    for expected in ("Herstel", "Strain", "Slaap", "TSB", "Stress", "Body Battery"):
        assert any(expected in name for name in names), f"undocumented metric: {expected}"


def test_explanation_entries_are_complete():
    """Every documented metric must answer all three questions, non-trivially."""
    for section in explanation.SECTIONS:
        assert section.metrics, f"empty section: {section.title}"
        for m in section.metrics:
            assert len(m.what) > 30, m.name
            assert len(m.does) > 30, m.name
            assert len(m.develops) > 30, m.name

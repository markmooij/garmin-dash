"""Tests for the Garmin-native SVG visualisations and the recent_series query."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from app.db.models import DailyWellness, DeviceMetrics
from app.web import query, viz


if TYPE_CHECKING:
    from sqlalchemy.orm import Session


# ── colour bands ────────────────────────────────────────────────────────

def test_rhr_color_bands():
    assert viz.rhr_color(50) == "#34d399"  # fit
    assert viz.rhr_color(60) == "#fbbf24"  # elevated
    assert viz.rhr_color(70) == "#f87171"  # high
    assert viz.rhr_color(None) == "#71717a"  # neutral


def test_stress_color_garmin_zones():
    assert viz.stress_color(20) == "#34d399"  # rest
    assert viz.stress_color(30) == "#fbbf24"  # low
    assert viz.stress_color(60) == "#fb923c"  # medium
    assert viz.stress_color(80) == "#f87171"  # high


def test_bb_color_charge():
    assert viz.bb_color(80) == "#34d399"  # charged
    assert viz.bb_color(50) == "#fbbf24"  # moderate
    assert viz.bb_color(20) == "#f87171"  # depleted


def test_vo2_color_fitness_bands():
    assert viz.vo2_color(35) == "#f87171"  # poor
    assert viz.vo2_color(40) == "#fb923c"  # fair
    assert viz.vo2_color(44) == "#fbbf24"  # good
    assert viz.vo2_color(48) == "#a3e635"  # excellent
    assert viz.vo2_color(52) == "#34d399"  # superior


def test_spo2_color_clinical_zones():
    assert viz.spo2_color(97) == "#34d399"  # normal
    assert viz.spo2_color(92) == "#fbbf24"  # borderline
    assert viz.spo2_color(88) == "#f87171"  # low


def test_resp_color_clinical_zones():
    assert viz.resp_color(15) == "#34d399"  # normal
    assert viz.resp_color(11) == "#fbbf24"  # borderline low
    assert viz.resp_color(22) == "#fbbf24"  # borderline high
    assert viz.resp_color(8) == "#f87171"  # concerning low
    assert viz.resp_color(28) == "#f87171"  # concerning high


def test_steps_color_goal():
    assert viz.steps_color(120) == "#34d399"  # over goal
    assert viz.steps_color(85) == "#fbbf24"  # near goal
    assert viz.steps_color(40) == "#f87171"  # far from goal


# ── SVG builders ────────────────────────────────────────────────────────

def test_sparkline_returns_svg_for_series():
    svg = viz.sparkline([50, 48, 46, 47, 45], "#34d399")
    assert svg.startswith("<svg")
    assert "polyline" in svg
    assert "circle" in svg  # latest-value dot


def test_sparkline_empty_when_too_few_points():
    assert viz.sparkline([], "#34d399") == ""
    assert viz.sparkline([50], "#34d399") == ""
    assert viz.sparkline([None, None], "#34d399") == ""


def test_sparkline_skips_none_gaps():
    svg = viz.sparkline([50, None, 46, 47, 45], "#34d399")
    assert svg != ""  # still draws the non-None points


def test_gauge_returns_svg_with_zones_and_needle():
    svg = viz.stress_gauge(30)
    assert svg.startswith("<svg")
    assert svg.count("<rect") >= 5  # track + 4 zones + needle


def test_gauge_empty_when_no_value():
    assert viz.stress_gauge(None) == ""
    assert viz.spo2_gauge(None) == ""
    assert viz.resp_gauge(None) == ""
    assert viz.vo2_gauge(None) == ""


def test_ring_returns_svg_for_goal():
    svg = viz.ring(75, "#34d399")
    assert svg.startswith("<svg")
    assert "stroke-dasharray" in svg


def test_ring_empty_when_no_value():
    assert viz.ring(None, "#34d399") == ""


def test_ring_clamps_over_100():
    svg = viz.ring(150, "#34d399")
    assert "stroke-dasharray" in svg  # no crash on over-goal


def test_battery_returns_svg():
    svg = viz.battery(60, "#fbbf24")
    assert svg.startswith("<svg")
    assert svg.count("<rect") >= 2  # outline + fill


def test_battery_empty_when_no_value():
    assert viz.battery(None, "#34d399") == ""


# ── recent_series query ─────────────────────────────────────────────────

def test_recent_series_aligned_dates_and_values(seeded: Session):
    """The series must be date-aligned (oldest→newest) ending on the seeded day."""
    series = query.recent_series(seeded, days=14, end=date(2026, 8, 9))
    assert len(series["dates"]) == 14
    assert series["dates"][-1] == "2026-08-09"
    # seeded day has RHR 45, stress 25, bb_at_wake 80, steps 8223
    assert series["rhr"][-1] == 45.0
    assert series["stress"][-1] == 25.0
    assert series["bb_wake"][-1] == 80
    assert series["steps"][-1] == 8223
    # earlier days in the window have no data → None
    assert series["rhr"][0] is None


def test_recent_series_excludes_negative_stress(seeded: Session):
    """Garmin uses -1 as a sentinel for 'no stress'; it must become None."""
    day = date(2026, 8, 8)
    seeded.add(DailyWellness(
        user_id=1, calendar_date=day,
        resting_heart_rate=46.0, avg_stress=-1.0,
    ))
    seeded.commit()
    series = query.recent_series(seeded, days=14, end=date(2026, 8, 9))
    assert series["stress"][-2] is None  # the -1 day is treated as missing


def test_recent_series_intensity_sums_moderate_and_vigorous(seeded: Session):
    """Intensity minutes = moderate + vigorous, computed per day."""
    day = date(2026, 8, 8)
    seeded.add(DailyWellness(
        user_id=1, calendar_date=day,
        resting_heart_rate=46.0,
        moderate_intensity_minutes=20, vigorous_intensity_minutes=15,
    ))
    seeded.commit()
    series = query.recent_series(seeded, days=14, end=date(2026, 8, 9))
    assert series["intensity"][-2] == 35  # 20 + 15


def test_recent_series_vo2_from_device_metrics(seeded: Session):
    """VO2max comes from DeviceMetrics, not DailyWellness."""
    day = date(2026, 8, 8)
    seeded.add(DeviceMetrics(user_id=1, metric_date=day, vo2max=52.0))
    seeded.commit()
    series = query.recent_series(seeded, days=14, end=date(2026, 8, 9))
    assert series["vo2max"][-2] == 52.0

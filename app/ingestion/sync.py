"""Sync worker — pull Garmin streams into SQLite with idempotent upserts.

Streams (one sync per day, catch-up window for late-arriving sleep):
    daily_wellness  ← user_summary
    sleep_sessions  ← sleep_data
    intraday_series ← stress_data, heart_rates, body_battery
    activities      ← activities list + FIT files (activity_hr_series)

Idempotency: every table has a unique key on (user_id, source_id); upserts
use SQLite ON CONFLICT, so re-syncing never duplicates rows.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ..db import get_session
from ..db.models import (
    Activity,
    ActivityHrSeries,
    DailyWellness,
    DeviceMetrics,
    IntradaySeries,
    RawPayload,
    SleepSession,
    SyncState,
)
from .adapter import GarminAdapterError, GarminClientAdapter


if TYPE_CHECKING:
    from sqlalchemy.orm import Session


FIT_DIR = Path("data/fit")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _epoch_ms_to_dt(ms: int | str) -> datetime:
    """Convert Garmin epoch-milliseconds (or ISO string) to UTC datetime."""
    if isinstance(ms, str):
        dt = datetime.fromisoformat(ms)
        return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt
    return datetime.fromtimestamp(int(ms) / 1000, tz=UTC)


def _date_str(d: date) -> str:
    return d.isoformat()


def _save_raw(session: Session, endpoint: str, key: str, payload: Any) -> None:
    session.add(
        RawPayload(endpoint=endpoint, key=key, payload=_jsonable(payload))
    )


def _jsonable(payload: Any) -> Any:
    try:
        json.dumps(payload)
        return payload
    except TypeError:
        return json.loads(json.dumps(payload, default=str))


def _unique_cols(model: type) -> list[str]:
    """Column names of the model's first UniqueConstraint."""
    from sqlalchemy import UniqueConstraint

    table = getattr(model, "__table__", None)
    if table is None:
        raise ValueError(f"{model.__name__} has no table")
    for constraint in table.constraints:
        if isinstance(constraint, UniqueConstraint):
            return [c.name for c in constraint.columns]
    raise ValueError(f"No UniqueConstraint on {model.__name__}")


def _upsert(session: Session, model: type, values: dict) -> None:
    """SQLite ON CONFLICT upsert keyed on the model's first unique constraint."""
    stmt = sqlite_insert(model).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=_unique_cols(model),
        set_={k: getattr(stmt.excluded, k) for k in values},
    )
    session.execute(stmt)


def _touch_sync(
    session: Session, stream: str, day: date, error: str | None = None
) -> None:
    stmt = sqlite_insert(SyncState).values(
        user_id=1, stream=stream, last_date=day, error=error
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "stream"],
        set_={"last_date": day, "last_sync_at": datetime.now(UTC), "error": error},
    )
    session.execute(stmt)



# ---------------------------------------------------------------------------
# per-stream sync
# ---------------------------------------------------------------------------


def sync_wellness(session: Session, adapter: GarminClientAdapter, day: date) -> None:
    """daily_wellness ← user_summary."""
    dstr = _date_str(day)
    try:
        raw = adapter.get_user_summary(dstr)
    except Exception as e:  # noqa: BLE001
        _touch_sync(session, "daily_wellness", day, error=str(e))
        raise
    if not raw or "userProfileId" not in raw:
        _touch_sync(session, "daily_wellness", day, error="empty payload")
        return

    _save_raw(session, "user_summary", dstr, raw)
    _upsert(
        session,
        DailyWellness,
        {
            "user_id": 1,
            "calendar_date": day,
            "resting_heart_rate": raw.get("restingHeartRate"),
            "last_7d_avg_rhr": raw.get("lastSevenDaysAvgRestingHeartRate"),
            "min_heart_rate": raw.get("minHeartRate"),
            "max_heart_rate": raw.get("maxHeartRate"),
            "avg_stress": raw.get("averageStressLevel"),
            "max_stress": raw.get("maxStressLevel"),
            "stress_duration": {
                k: raw.get(k)
                for k in (
                    "restStressDuration",
                    "activityStressDuration",
                    "lowStressDuration",
                    "mediumStressDuration",
                    "highStressDuration",
                )
            },
            "stress_qualifier": raw.get("stressQualifier"),
            "avg_spo2": raw.get("averageSpo2"),
            "lowest_spo2": raw.get("lowestSpo2"),
            "avg_respiration": raw.get("avgWakingRespirationValue"),
            "bb_charged": raw.get("bodyBatteryChargedValue"),
            "bb_drained": raw.get("bodyBatteryDrainedValue"),
            "bb_highest": raw.get("bodyBatteryHighestValue"),
            "bb_lowest": raw.get("bodyBatteryLowestValue"),
            "bb_most_recent": raw.get("bodyBatteryMostRecentValue"),
            "bb_at_wake": raw.get("bodyBatteryAtWakeTime"),
            "moderate_intensity_minutes": raw.get("moderateIntensityMinutes"),
            "vigorous_intensity_minutes": raw.get("vigorousIntensityMinutes"),
            "steps": raw.get("totalSteps"),
            "calories": raw.get("totalKilocalories"),
            "floors": raw.get("floorsAscended"),
        },
    )
    _touch_sync(session, "daily_wellness", day)


def sync_device_metrics(session: Session, adapter: GarminClientAdapter, day: date) -> None:
    """device_metrics ← max_metrics (VO2max, fitness age).

    Garmin only reports the value for the date it was last measured (often
    yesterday, today is empty until the next measurement). Probe the target
    day, then yesterday as fallback. Store per-date snapshots so the
    dashboard can show what Garmin reported over time.
    """
    dstr = _date_str(day)
    raw = None
    probed: list[date] = [day]
    try:
        raw = adapter.get_max_metrics(dstr)
    except Exception as e:  # noqa: BLE001
        _touch_sync(session, "device_metrics", day, error=str(e))
        return
    if not raw:
        # fall back to yesterday once (value is keyed by measurement date)
        prev = day - timedelta(days=1)
        probed.append(prev)
        try:
            raw = adapter.get_max_metrics(_date_str(prev))
        except Exception as e:  # noqa: BLE001
            _touch_sync(session, "device_metrics", day, error=str(e))
            return

    if isinstance(raw, list):
        raw = raw[0] if raw else {}
    if not isinstance(raw, dict) or not raw:
        _touch_sync(session, "device_metrics", day, error="empty payload")
        return

    generic = raw.get("generic") or {}
    vo2 = generic.get("vo2MaxValue") or generic.get("vo2MaxPreciseValue")
    if vo2 is None:
        _touch_sync(session, "device_metrics", day, error="no vo2max in payload")
        return

    metric_date_str = generic.get("calendarDate") or _date_str(probed[0])
    try:
        metric_date = date.fromisoformat(metric_date_str)
    except ValueError:
        metric_date = day
    _save_raw(session, "max_metrics", dstr, raw)
    _upsert(
        session,
        DeviceMetrics,
        {
            "user_id": 1,
            "metric_date": metric_date,
            "vo2max": generic.get("vo2MaxValue"),
            "vo2max_precise": generic.get("vo2MaxPreciseValue"),
            "fitness_age": generic.get("fitnessAge"),
            "max_met_category": generic.get("maxMetCategory"),
            "payload": {"cycling": raw.get("cycling"), "queried_on": dstr},
        },
    )
    _touch_sync(session, "device_metrics", day)


def sync_sleep(session: Session, adapter: GarminClientAdapter, day: date) -> None:
    """sleep_sessions ← sleep_data."""
    dstr = _date_str(day)
    try:
        raw = adapter.get_sleep_data(dstr)
    except Exception as e:  # noqa: BLE001
        _touch_sync(session, "sleep", day, error=str(e))
        raise

    daily = (raw or {}).get("dailySleepDTO") or {}
    if not daily.get("sleepStartTimestampGMT") or not daily.get("sleepEndTimestampGMT"):
        _touch_sync(session, "sleep", day, error="no sleep session")
        return

    _save_raw(session, "sleep_data", dstr, raw)

    scores = daily.get("sleepScores") or {}
    overall = scores.get("overall") or {}

    _upsert(
        session,
        SleepSession,
        {
            "user_id": 1,
            "calendar_date": day,
            "sleep_start_gmt": _epoch_ms_to_dt(daily["sleepStartTimestampGMT"]),
            "sleep_end_gmt": _epoch_ms_to_dt(daily["sleepEndTimestampGMT"]),
            "sleep_start_local": daily.get("sleepStartTimestampLocal"),
            "sleep_end_local": daily.get("sleepEndTimestampLocal"),
            "sleep_seconds": daily.get("sleepTimeSeconds"),
            "deep_seconds": daily.get("deepSleepSeconds"),
            "light_seconds": daily.get("lightSleepSeconds"),
            "rem_seconds": daily.get("remSleepSeconds"),
            "awake_seconds": daily.get("awakeSleepSeconds"),
            "unmeasurable_seconds": daily.get("unmeasurableSleepSeconds"),
            "sleep_score": overall.get("value"),
            "sleep_qualifier": overall.get("qualifierKey"),
            "awake_count": daily.get("awakeCount"),
            "avg_sleep_stress": daily.get("avgSleepStress"),
            "avg_spo2": daily.get("averageSpO2Value"),
            "lowest_spo2": daily.get("lowestSpO2Value"),
            "avg_respiration": daily.get("averageRespirationValue"),
            "resting_heart_rate": raw.get("restingHeartRate"),
            "body_battery_change": raw.get("bodyBatteryChange"),
        },
    )
    _touch_sync(session, "sleep", day)


def sync_intraday(
    session: Session,
    adapter: GarminClientAdapter,
    day: date,
    kinds: tuple[str, ...] = ("stress", "heart_rate", "body_battery"),
) -> None:
    """intraday_series ← stress_data / heart_rates / body_battery (1-min arrays)."""
    dstr = _date_str(day)
    batches: dict[str, list[tuple[int, float]]] = {}

    if "stress" in kinds:
        try:
            raw = adapter.get_stress_data(dstr)
            if raw:
                _save_raw(session, "stress_data", dstr, raw)
                batches["stress"] = [
                    (ts, float(v))
                    for ts, v in (raw.get("stressValuesArray") or [])
                    if v is not None
                ]
        except Exception as e:  # noqa: BLE001
            _touch_sync(session, "intraday_stress", day, error=str(e))

    if "heart_rate" in kinds:
        try:
            raw = adapter.get_heart_rates(dstr)
            if raw:
                _save_raw(session, "heart_rates", dstr, raw)
                batches["heart_rate"] = [
                    (ts, float(v))
                    for ts, v in (raw.get("heartRateValues") or [])
                    if v is not None
                ]
        except Exception as e:  # noqa: BLE001
            _touch_sync(session, "intraday_heart_rate", day, error=str(e))

    if "body_battery" in kinds:
        try:
            bb_raw: object = adapter.get_body_battery(dstr, dstr)
            # Accept both the range form (list of day dicts) and the
            # single-day dict form; normalize to a list.
            if isinstance(bb_raw, dict) and bb_raw.get("bodyBatteryValuesArray"):
                entries: list[dict[str, Any]] = [bb_raw]
                _save_raw(session, "body_battery", dstr, entries)
            elif isinstance(bb_raw, list) and bb_raw:
                entries = bb_raw
                _save_raw(session, "body_battery", dstr, bb_raw)
            else:
                entries = []
            # values are [ts, "MEASURED", value, drain] or [ts, value].
            # Garmin emits [ts, None] placeholders for a day with no data yet
            # (e.g. today before the watch syncs) — skip those instead of
            # crashing on float(None), matching the stress/heart_rate guards.
            batches["body_battery"] = []
            for item in entries:
                for row in item.get("bodyBatteryValuesArray") or []:
                    if len(row) >= 3:
                        val = row[2]
                    elif len(row) == 2:
                        val = row[1]
                    else:
                        continue
                    if val is not None:
                        batches["body_battery"].append((row[0], float(val)))
        except Exception as e:  # noqa: BLE001
            _touch_sync(session, "intraday_body_battery", day, error=str(e))

    for kind, rows in batches.items():
        if not rows:
            continue
        _bulk_upsert_intraday(session, kind, rows)
        _touch_sync(session, f"intraday_{kind}", day)


def _bulk_upsert_intraday(
    session: Session, kind: str, rows: list[tuple[int, float]]
) -> None:
    """Bulk-upsert intraday samples in one statement (~1440 rows/day/kind)."""
    stmt = sqlite_insert(IntradaySeries).values(
        [
            {"user_id": 1, "kind": kind, "ts_gmt": _epoch_ms_to_dt(ts), "value": value}
            for ts, value in rows
        ]
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "kind", "ts_gmt"],
        set_={"value": stmt.excluded.value},
    )
    session.execute(stmt)


def sync_activities(
    session: Session, adapter: GarminClientAdapter, limit: int = 20, fetch_fit: bool = False
) -> None:
    """activities ← get_activities; optionally download + parse FIT files."""
    raw_list = adapter.get_activities(0, limit)
    if not raw_list:
        return

    for raw in raw_list:
        _save_raw(session, "activities", str(raw.get("activityId")), raw)
        atype = (raw.get("activityType") or {}).get("typeKey") or "unknown"
        etype = raw.get("eventType")
        if isinstance(etype, dict):
            etype = etype.get("typeKey") or etype.get("typeId")
        _upsert(
            session,
            Activity,
            {
                "user_id": 1,
                "activity_id": raw["activityId"],
                "activity_name": raw.get("activityName"),
                "activity_type": atype,
                "event_type": str(etype) if etype is not None else None,
                "start_time_gmt": _epoch_ms_to_dt(raw["startTimeGMT"]),
                "start_time_local": raw.get("startTimeLocal"),
                "timezone_id": raw.get("timeZoneId"),
                "duration": raw.get("duration"),
                "elapsed_duration": raw.get("elapsedDuration"),
                "moving_duration": raw.get("movingDuration"),
                "distance_m": raw.get("distance"),
                "calories": raw.get("calories"),
                "avg_hr": raw.get("averageHR"),
                "max_hr": raw.get("maxHR"),
                "hr_time_in_zone_1": raw.get("hrTimeInZone_1"),
                "hr_time_in_zone_2": raw.get("hrTimeInZone_2"),
                "hr_time_in_zone_3": raw.get("hrTimeInZone_3"),
                "hr_time_in_zone_4": raw.get("hrTimeInZone_4"),
                "hr_time_in_zone_5": raw.get("hrTimeInZone_5"),
                "aerobic_training_effect": raw.get("aerobicTrainingEffect"),
                "anaerobic_training_effect": raw.get("anaerobicTrainingEffect"),
                "difference_body_battery": raw.get("differenceBodyBattery"),
            },
        )

    if fetch_fit:
        FIT_DIR.mkdir(parents=True, exist_ok=True)
        for raw in raw_list:
            activity_id = raw["activityId"]
            target = FIT_DIR / f"{activity_id}.fit"
            if target.exists():
                continue
            try:
                fit_bytes = adapter.download_activity_fit(activity_id)
                target.write_bytes(fit_bytes)
                # resolve the row PK for the FK on activity_hr_series
                row = session.execute(
                    select(Activity.id).where(
                        Activity.user_id == 1, Activity.activity_id == activity_id
                    )
                ).scalar_one_or_none()
                if row is not None:
                    _parse_fit(session, row, target)
                # remember the file path on the activity row (plain UPDATE)
                from sqlalchemy import update

                session.execute(
                    update(Activity)
                    .where(Activity.user_id == 1, Activity.activity_id == activity_id)
                    .values(fit_file_path=str(target))
                )
            except Exception as e:  # noqa: BLE001
                print(f"  ⚠️ FIT download failed for {activity_id}: {e}")

    _touch_sync(session, "activities", date.today())


def _parse_fit(session: Session, activity_pk: int, fit_path: Path) -> None:
    """Parse HR/pace samples from a FIT file into activity_hr_series."""
    try:
        from fitparse import FitFile
    except ImportError:
        return

    try:
        start = session.execute(
            select(Activity.start_time_gmt).where(Activity.id == activity_pk)
        ).scalar_one_or_none()
        fit = FitFile(str(fit_path))
        for record in fit.get_messages("record"):
            fields = {f.name: f.value for f in record}
            elapsed = fields.get("timestamp")
            if elapsed is None:
                continue
            hr = fields.get("heart_rate")
            speed = fields.get("speed")
            cadence = fields.get("cadence")
            ts = elapsed.timestamp() if hasattr(elapsed, "timestamp") else float(elapsed)
            elapsed_s = int(ts - start.timestamp()) if start is not None else int(ts)
            _upsert(
                session,
                ActivityHrSeries,
                {
                    "activity_pk": activity_pk,
                    "elapsed_s": elapsed_s,
                    "hr": int(hr) if hr is not None else None,
                    "speed_mps": float(speed) if speed is not None else None,
                    "cadence": int(cadence) if cadence is not None else None,
                },
            )
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠️ FIT parse failed for {fit_path.name}: {e}")


# ---------------------------------------------------------------------------
# orchestrators
# ---------------------------------------------------------------------------


def sync_day(day: date, adapter: GarminClientAdapter, session: Session | None = None) -> None:
    """Sync all daily streams for one calendar day.

    Per-stream failures are recorded in sync_state and swallowed, so a single
    bad day (missing sleep, 404, …) never aborts a multi-day backfill.
    Authentication failures are re-raised to stop the run.
    """
    own = session is None
    session = session or get_session()
    try:
        for stream_fn in (sync_wellness, sync_device_metrics, sync_sleep, sync_intraday):
            try:
                stream_fn(session, adapter, day)
                session.commit()
            except GarminAdapterError as e:
                session.rollback()
                if "Not authenticated" in str(e):
                    raise
                print(f"  ⚠️ {day} {stream_fn.__name__}: {e}")
            except Exception as e:  # noqa: BLE001
                # Unexpected payload shape etc. — record and keep going;
                # a single day's quirk must not abort a 90-day backfill.
                session.rollback()
                _touch_sync(session, stream_fn.__name__, day, error=f"{type(e).__name__}: {e}")
                session.commit()
                print(f"  ⚠️ {day} {stream_fn.__name__}: {type(e).__name__}: {e}")
        print(f"  ✅ {day}: sync pass complete")
    finally:
        if own:
            session.close()


def incremental_sync(days_back: int = 3) -> None:
    """Sync the last N days (catch-up window for late sleep data)."""
    session = get_session()
    adapter = GarminClientAdapter()
    today = date.today()
    try:
        for i in range(days_back, -1, -1):
            day = today - timedelta(days=i)
            sync_day(day, adapter, session)
        sync_activities(session, adapter, limit=20, fetch_fit=True)
        session.commit()
        print("✅ Incremental sync complete")
    except Exception as e:  # noqa: BLE001
        session.rollback()
        print(f"❌ Sync failed: {e}")
        raise
    finally:
        session.close()
        adapter.close()


def backfill(days: int = 90) -> None:
    """Backfill the last N days from today backwards (oldest first)."""
    session = get_session()
    adapter = GarminClientAdapter()
    today = date.today()
    try:
        # skip days already fully synced (watermark per stream)
        for i in range(days, 0, -1):
            day = today - timedelta(days=i)
            sync_day(day, adapter, session)
        print(f"✅ Backfill complete: {days} days")
    except Exception as e:  # noqa: BLE001
        session.rollback()
        print(f"❌ Backfill failed at: {e}")
        raise
    finally:
        session.close()
        adapter.close()

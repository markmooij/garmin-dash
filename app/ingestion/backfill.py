"""Backfill script — sync last 90 days to JSON fixtures."""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from garth import GarminClient
from garth.credentials import GarminCredentials


def backfill_data():
    """Backfill last 90 days to JSON fixtures."""
    print("📥 Backfilling last 90 days to JSON fixtures")
    print("=" * 60)

    # Load credentials
    try:
        credentials = GarminCredentials.from_token_store("data/garmin/garmin_tokens.json")
    except FileNotFoundError:
        print("❌ Token cache not found. Run 'gdash auth setup' first.")
        return

    client = GarminClient(credentials=credentials)

    # Set date range (last 90 days)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=90)

    print(f"📅 Date range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    print()

    fixtures_dir = Path("tests/fixtures")
    fixtures_dir.mkdir(exist_ok=True)

    # Endpoints to backfill
    endpoints = {
        "sleep": "get_sleep_data",
        "hrv": "get_hrv_data",
        "stress": "get_stress_data",
        "body_battery": "get_body_battery",
        "respiration": "get_respiration_data",
        "spo2": "get_spo2_data",
        "activities": "get_activities",
        "activities_details": "get_activity_details",
        "hr_series": "get_activity_hr_in_timezones",
        "exercise_sets": "get_activity_exercise_sets",
        "daily_steps": "get_daily_steps",
        "calories": "get_calories_daily",
        "heart_rates": "get_heart_rates",
        "training_status": "get_training_status",
        "training_effect": "get_training_effect",
        "vo2max": "get_endurance_score",
    }

    for name, method in endpoints.items():
        print(f"📥 Fetching {name}...")
        try:
            data = getattr(client, method)()
            # Handle paginated results
            if hasattr(data, 'get') and 'data' in data:
                data = data['data']
            elif isinstance(data, dict):
                data = data.get('data', [data])
            elif isinstance(data, list):
                pass
            else:
                data = [data] if data else []

            # Save to fixture file
            fixture_file = fixtures_dir / f"{name}.json"
            with open(fixture_file, 'w') as f:
                json.dump(data, f, indent=2, default=str)

            print(f"   ✅ Saved {len(data)} records to {fixture_file}")
        except Exception as e:
            print(f"   ❌ Failed: {e}")

    print()
    print("✅ Backfill complete!")
    print(f"📁 Fixtures saved to: {fixtures_dir}")

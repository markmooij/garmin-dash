"""GarminClient adapter — isolates the app from garminconnect API breakage.

Wraps every call with retry/backoff (jittered) and a polite minimum delay so
we never hammer the undocumented Garmin endpoints (roadmap: conservative
polling, no 429s). Swap the backend without touching callers.
"""

from __future__ import annotations

import random
import time
from typing import TYPE_CHECKING, Any, TypeVar

from garminconnect.exceptions import (
    GarminConnectNotFoundError,
    GarminConnectTooManyRequestsError,
)

from ..auth.session import resume_from_tokens


if TYPE_CHECKING:
    from collections.abc import Callable

    from garminconnect import Garmin


T = TypeVar("T")

_DEFAULT_MAX_RETRIES = 5
_DEFAULT_BASE_DELAY = 2.0  # seconds between attempts (exponential)
_DEFAULT_POLL_DELAY = 1.5  # seconds between independent API calls


class GarminAdapterError(RuntimeError):
    """Raised when the Garmin API cannot be reached after retries."""


class GarminClientAdapter:
    """Thread-safe facade over garminconnect with retry + rate limiting.

    Not async on purpose: APScheduler runs jobs in worker threads, and the
    garminconnect client is synchronous.
    """

    def __init__(
        self,
        client: Garmin | None = None,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        base_delay: float = _DEFAULT_BASE_DELAY,
        poll_delay: float = _DEFAULT_POLL_DELAY,
    ):
        self._client = client
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.poll_delay = poll_delay
        self._last_call_ts = 0.0

    # -- lifecycle --------------------------------------------------------

    @property
    def client(self) -> Garmin:
        """Return a logged-in client, resuming from token cache as needed."""
        if self._client is None:
            self._client = resume_from_tokens()
            if self._client is None:
                raise GarminAdapterError(
                    "Not authenticated — run 'gdash auth start' first."
                )
        return self._client

    def close(self) -> None:
        """Release the underlying client (if it needs cleanup)."""
        self._client = None

    # -- rate limiting + retry --------------------------------------------

    def _throttle(self) -> None:
        """Enforce a minimum gap between API calls (jittered)."""
        now = time.monotonic()
        gap = self.poll_delay * random.uniform(0.8, 1.2)
        wait = gap - (now - self._last_call_ts)
        if wait > 0:
            time.sleep(wait)
        self._last_call_ts = time.monotonic()

    def call(self, fn: Callable[[], T]) -> T:
        """Run an API call with jittered exponential backoff on retryable errors."""
        delay = self.base_delay
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                return fn()
            except GarminConnectTooManyRequestsError as e:
                # 429 — always retryable; back off harder
                if attempt < self.max_retries:
                    wait = delay * random.uniform(1.5, 2.0)
                    print(
                        f"  ⏳ Rate limited (attempt {attempt}/{self.max_retries}) "
                        f"— retrying in {wait:.1f}s"
                    )
                    time.sleep(wait)
                    delay *= 2.5
                    continue
                raise GarminAdapterError(f"Garmin rate limited: {e}") from e
            except GarminConnectNotFoundError as e:
                # 404 — data genuinely absent (e.g. no sleep recorded that day)
                raise GarminAdapterError(f"Garmin 404 (data absent): {e}") from e
            except (ConnectionError, TimeoutError, OSError) as e:
                if attempt < self.max_retries:
                    wait = delay * random.uniform(0.9, 1.1)
                    print(f"  ⏳ Network error (attempt {attempt}) — retrying in {wait:.1f}s")
                    time.sleep(wait)
                    delay *= 2
                    continue
                raise GarminAdapterError(f"Network error: {e}") from e
        raise GarminAdapterError("Unreachable")  # pragma: no cover

    # -- domain methods ----------------------------------------------------

    def get_user_summary(self, cdate: str) -> dict[str, Any]:
        return self.call(lambda: self.client.get_user_summary(cdate))

    def get_sleep_data(self, cdate: str) -> dict[str, Any]:
        return self.call(lambda: self.client.get_sleep_data(cdate))

    def get_stress_data(self, cdate: str) -> dict[str, Any]:
        return self.call(lambda: self.client.get_stress_data(cdate))

    def get_body_battery(self, start: str, end: str) -> list[dict[str, Any]]:
        return self.call(lambda: self.client.get_body_battery(start, end))

    def get_heart_rates(self, cdate: str) -> dict[str, Any]:
        return self.call(lambda: self.client.get_heart_rates(cdate))

    def get_hrv_data(self, cdate: str) -> dict[str, Any]:
        return self.call(lambda: self.client.get_hrv_data(cdate))

    def get_respiration_data(self, cdate: str) -> list[dict[str, Any]]:
        return self.call(lambda: self.client.get_respiration_data(cdate))

    def get_spo2_data(self, cdate: str) -> list[dict[str, Any]]:
        return self.call(lambda: self.client.get_spo2_data(cdate))

    def get_training_status(self, cdate: str) -> dict[str, Any]:
        return self.call(lambda: self.client.get_training_status(cdate))

    def get_activities(self, start: int = 0, limit: int = 20) -> list[dict[str, Any]]:
        return self.call(lambda: self.client.get_activities(start, limit))

    def get_activity_details(self, activity_id: int) -> dict[str, Any]:
        return self.call(lambda: self.client.get_activity_details(activity_id))

    def download_activity_fit(self, activity_id: int) -> bytes:
        """Download and unwrap the .FIT file for an activity.

        Garmin's ORIGINAL format returns a zip archive containing exactly one
        .fit member; unwrap it so callers always get raw FIT bytes.
        """
        import io
        import zipfile

        fmt = self.client.ActivityDownloadFormat.ORIGINAL
        raw: Any = self.call(lambda: self.client.download_activity(activity_id, dl_fmt=fmt))

        if isinstance(raw, bytes) and raw[:2] == b"PK":  # zip magic
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                fit_names = [n for n in zf.namelist() if n.lower().endswith(".fit")]
                if fit_names:
                    data = zf.read(fit_names[0])
                    if isinstance(data, bytes):
                        return data
        return raw if isinstance(raw, bytes) else b""

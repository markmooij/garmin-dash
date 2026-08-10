"""Fitness-fatigue: Coggan ATL / CTL / TSB from daily strain.

ATL (7-day) and CTL (42-day) are exponential moving averages of the
calibrated 0–21 strain — NOT raw TRIMP, so strength-duration load counts
(roadmap decision). TSB = CTL − ATL (positive = fresh, negative = fatigued).

State must be computed chronologically; the first strain value seeds the
EMAs (no warm-up period assumption).
"""

from __future__ import annotations

import math


ATL_TAU_DAYS = 7.0
CTL_TAU_DAYS = 42.0


def _ema(prev: float, load: float, tau: float) -> float:
    """Coggan EMA update: prev + (load − prev) × (1 − e^(−1/τ))."""
    alpha = 1.0 - math.exp(-1.0 / tau)
    return prev + (load - prev) * alpha


class FitnessState:
    """Running ATL/CTL/TSB tracker, updated one day at a time."""

    def __init__(self) -> None:
        self.atl: float | None = None
        self.ctl: float | None = None
        self._seeded = False

    def update(self, strain: float | None) -> dict | None:
        """Feed one day's strain; returns ATL/CTL/TSB or None if no data."""
        if strain is None:
            return self.snapshot()
        if not self._seeded:
            self.atl = strain
            self.ctl = strain
            self._seeded = True
        else:
            assert self.atl is not None and self.ctl is not None
            self.atl = _ema(self.atl, strain, ATL_TAU_DAYS)
            self.ctl = _ema(self.ctl, strain, CTL_TAU_DAYS)
        return self.snapshot()

    def snapshot(self) -> dict | None:
        if self.atl is None or self.ctl is None:
            return None
        tsb = self.ctl - self.atl
        return {
            "atl": round(self.atl, 3),
            "ctl": round(self.ctl, 3),
            "tsb": round(tsb, 3),
        }

    def __repr__(self) -> str:  # pragma: no cover
        return f"<FitnessState atl={self.atl} ctl={self.ctl}>"

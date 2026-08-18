"""Pre-registered journal questions.

Fixed vocabulary — not free-form — so the correlation engine has a stable
key space to gate and label insights against. Free-form color lives in
`tags` (list[str]) and `notes` (text), never used for correlation.

Each factor is boolean ("did X happen today?") or a count (alcohol drinks).
`/log` (Signal) and the web form both drive off this registry, so adding a
question is a one-line change here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Factor:
    key: str
    label: str  # Dutch label, shown in Signal + web
    kind: str  # "bool" | "count"
    prompt: str  # short description for /help and the web form


FACTORS: list[Factor] = [
    Factor("alcohol", "Alcohol", "count", "aantal drankjes"),
    Factor("cafeine_laat", "Cafeïne laat", "bool", "koffie/cafeïne na 14:00"),
    Factor("laat_eten", "Laat gegeten", "bool", "maaltijd < 2u voor slapen"),
    Factor("stress_hoog", "Hoge stress", "bool", "subjectief stressvolle dag"),
    Factor("scherm_laat", "Scherm laat", "bool", "beeldscherm vlak voor slapen"),
    Factor("spierpijn", "Spierpijn", "bool", "spierpijn / DOMS"),
    Factor("ziek", "Ziek", "bool", "verkouden / ziekteverschijnselen"),
]

FACTORS_BY_KEY: dict[str, Factor] = {f.key: f for f in FACTORS}

# Outcomes the insight engine correlates factors against. Both are read from
# computed_scores / sleep_sessions the *day after* the logged day by default
# (JOURNAL_OUTCOME_OFFSET_DAYS) — a factor logged for day D describes what
# happened during D; the behavioral effect shows up in the night D→D+1.
OUTCOMES = ("recovery_score", "sleep_score")

OUTCOME_LABELS = {"recovery_score": "herstel", "sleep_score": "slaap"}


def parse_bool(raw: str) -> bool | None:
    """'j'/'ja'/'y'/'yes'/'1'/'true' → True, 'n'/'nee'/'no'/'0'/'false' → False."""
    v = raw.strip().lower()
    if v in ("j", "ja", "y", "yes", "1", "true", "waar"):
        return True
    if v in ("n", "nee", "no", "0", "false", "onwaar"):
        return False
    return None

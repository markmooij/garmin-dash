"""Groundedness verification: catch LLM replies that invent numbers.

The coach's system prompt instructs the model to only use numbers
literally present in the assembled context, but LLMs occasionally
hallucinate anyway. `find_ungrounded` is a cheap, deterministic safety
net: every numeric token in the reply must be within tolerance of some
numeric token that appears in the context text. It is NOT a substitute
for the prompt instruction — it is the backstop that turns a
hallucination into a dropped reply instead of a wrong one reaching the
user (see `client.ask_coach` / `client.morning_commentary`).
"""

from __future__ import annotations

import re


_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")

# Small integers are common as list/ordinal markers or trivially safe
# conversational counts ("1 sessie", "2 dagen") — not treated as claims
# that require grounding. Larger or decimal numbers (recovery/strain/
# sleep/RHR scores, effect sizes) always must trace back to the context.
_SAFE_SMALL = {0.0, 1.0, 2.0, 3.0}

_TOLERANCE = 0.6  # rounding slack (context mixes 0- and 1-decimal formatting)


def _extract_numbers(text: str) -> list[float]:
    return [float(m) for m in _NUMBER_RE.findall(text)]


def find_ungrounded(reply: str, context_text: str) -> list[float]:
    """Numbers in `reply` with no match (within tolerance) in `context_text`.

    Empty list = fully grounded.
    """
    context_numbers = _extract_numbers(context_text)
    ungrounded: list[float] = []
    for n in _extract_numbers(reply):
        if n in _SAFE_SMALL:
            continue
        if any(abs(n - c) <= _TOLERANCE for c in context_numbers):
            continue
        ungrounded.append(n)
    return ungrounded


def is_grounded(reply: str, context_text: str) -> bool:
    return not find_ungrounded(reply, context_text)

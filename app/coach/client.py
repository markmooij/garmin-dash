"""LLM coach: openai SDK -> private OpenAI-compatible endpoint.

The LLM never computes numbers — it only words the numbers already
computed by the metrics/journal engines (roadmap decision). Enforced two
ways: (1) the system prompt instructs the model to use only the figures
given and never invent numbers; (2) `grounding.find_ungrounded` checks
the reply afterward and the caller drops/retries on failure rather than
forwarding a hallucinated number to the user.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..settings import get_settings
from .context import build_context
from .grounding import find_ungrounded


if TYPE_CHECKING:
    from datetime import date

    from sqlalchemy.orm import Session

logger = logging.getLogger("garmin_dash.coach")

SYSTEM_PROMPT = (
    "Je bent een training- en herstelcoach voor een self-hosted Garmin-dashboard. "
    "Je krijgt exacte cijfers (herstel, strain, TSB, slaap, RHR, dagboekfactoren, "
    "gevalideerde inzichten) in de context. Regels:\n"
    "1. Gebruik UITSLUITEND de cijfers die letterlijk in de context staan — nooit "
    "een getal verzinnen, schatten of afronden naar een ander getal.\n"
    "2. Noem als correlatie/verband ALLEEN de items onder 'Gevalideerde inzichten' — "
    "verzin nooit een eigen correlatie tussen dagboekfactoren en herstel/slaap.\n"
    "3. Voor weekoverzichten gebruik je de gemiddelden/aantallen uit 'Weekoverzicht' "
    "(die zijn al door de app berekend) — reken zelf niets uit.\n"
    "4. Wees kort en concreet (max ~4 zinnen), Nederlands, adviserend, geen diagnoses.\n"
    "5. Als de context niets zinnigs bevat om op te reageren, zeg dat expliciet "
    "in plaats van iets te verzinnen."
)


def get_client():
    """Build the openai client, or None when the coach is disabled/unconfigured.

    Imported lazily so a missing/misconfigured LLM never breaks app import
    (mirrors messaging.loop.get_messenger's SIGNAL_ENABLED gate).
    """
    settings = get_settings()
    if not settings.LLM_ENABLED:
        return None
    if not settings.LLM_BASE_URL:
        logger.warning("LLM_ENABLED=true but LLM_BASE_URL unset")
        return None
    try:
        from openai import OpenAI
    except ImportError:  # pragma: no cover - openai missing in this environment
        logger.error("openai package not installed \u2014 coach disabled")
        return None
    return OpenAI(base_url=settings.LLM_BASE_URL, api_key=settings.LLM_API_KEY or "not-needed")


def _chat(client, prompt: str) -> str | None:
    settings = get_settings()
    try:
        resp = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=settings.LLM_MAX_TOKENS,
            temperature=settings.LLM_TEMPERATURE,
        )
    except Exception:  # noqa: BLE001
        logger.exception("LLM request failed")
        return None
    choices = getattr(resp, "choices", None) or []
    if not choices:
        return None
    return (choices[0].message.content or "").strip() or None


def _grounded_reply(client, context_text: str, prompt: str) -> tuple[str | None, str | None]:
    """One chat call + groundedness check.

    Returns (reply, failure) where failure is None (ok), "error" (LLM call
    failed — check endpoint/config/logs) or "ungrounded" (model cited
    numbers not in the context — dropped by design, never forwarded).
    """
    reply = _chat(client, prompt)
    if reply is None:
        return None, "error"
    ungrounded = find_ungrounded(reply, context_text)
    if ungrounded:
        logger.warning("Coach reply dropped \u2014 ungrounded numbers: %s", ungrounded)
        return None, "ungrounded"
    return reply, None


def morning_commentary(session: Session, day: date | None = None) -> str | None:
    """One short grounded line to append to the Signal morning briefing.

    None when the coach is disabled, the endpoint fails, or the reply
    doesn't pass the groundedness check — callers must treat None as
    "say nothing", never fall back to an ungrounded reply.
    """
    client = get_client()
    if client is None:
        return None
    context = build_context(session, day)
    context_text = context.to_prompt_text()
    prompt = (
        f"{context_text}\n\n"
        "Geef een korte coach-opmerking (1-2 zinnen) bij het herstel/strain van vandaag, "
        "puttend uit bovenstaande cijfers."
    )
    reply, _failure = _grounded_reply(client, context_text, prompt)
    return reply


def ask_coach(session: Session, question: str, day: date | None = None) -> str:
    """Answer a free-form question (Signal /ask or web) grounded in the context.

    Always returns text (never None) — falls back to an explicit
    "coach unavailable" message rather than silence, since this is a
    direct user request (unlike the optional morning commentary).
    """
    client = get_client()
    if client is None:
        return "Coach niet beschikbaar (LLM_ENABLED=false of niet geconfigureerd)."
    context = build_context(session, day)
    context_text = context.to_prompt_text()
    prompt = f"{context_text}\n\nVraag: {question.strip()}"
    reply, failure = _grounded_reply(client, context_text, prompt)
    if reply is None:
        if failure == "ungrounded":
            return (
                "Kon geen betrouwbaar antwoord genereren — de coach noemde cijfers "
                "die niet in de context staan. Stel een specifiekere vraag (bijv. "
                "'hoe was mijn herstel deze week?')."
            )
        return (
            "Kon geen antwoord genereren (LLM-fout). Controleer LLM_BASE_URL / "
            "LLM_API_KEY / LLM_MODEL en de logs (docker compose logs)."
        )
    return reply

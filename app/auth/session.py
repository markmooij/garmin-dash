"""Garmin session management.

Real auth flow (garminconnect >= 0.3.9 / garth 0.8):

    1. Garmin(email, password, return_on_mfa=True).login()
       -> ("needs_mfa", client_state)  when MFA is enabled
       -> (None, None)                 when it logged straight in
    2. resume_login(client_state, mfa_code)
    3. garth.dump(token_dir)  -> writes oauth1_token.json + oauth2_token.json

There is NO browser OAuth flow. The MFA code is delivered by Garmin via
email/SMS to the account owner.

Tokens are cached on disk so subsequent runs skip login entirely; the OAuth1
token is valid for about a year.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from garminconnect import Garmin


# Where tokens and the pending-MFA handshake are stored.
TOKEN_DIR = Path(os.getenv("GARMINTOKENS", "data/garmin/tokens"))
MFA_STATE_PATH = Path("data/garmin/.mfa_state.json")


class AuthError(RuntimeError):
    """Raised when authentication cannot proceed."""


def _credentials() -> tuple[str, str]:
    """Read credentials from the environment (.env is loaded by the CLI)."""
    email = os.getenv("GARMIN_EMAIL", "").strip()
    password = os.getenv("GARMIN_PASSWORD", "").strip()
    if not email or not password:
        raise AuthError(
            "GARMIN_EMAIL and GARMIN_PASSWORD must be set in .env "
            "(copy .env.example to .env and fill them in)."
        )
    return email, password


def resume_from_tokens() -> Garmin | None:
    """Return a logged-in client from cached tokens, or None if unavailable."""
    if not TOKEN_DIR.exists():
        return None
    try:
        client = Garmin()
        client.login(str(TOKEN_DIR))
        return client
    except Exception:
        return None


def start_login() -> tuple[str, Garmin | None]:
    """Begin login.

    Returns:
        ("authenticated", client)  - logged in, tokens written
        ("needs_mfa", None)        - MFA required; state saved for finish_login()
    """
    email, password = _credentials()

    client = Garmin(email=email, password=password, return_on_mfa=True)
    result, client_state = client.login()

    if result == "needs_mfa":
        MFA_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        MFA_STATE_PATH.write_text(json.dumps(client_state, default=str))
        MFA_STATE_PATH.chmod(0o600)
        return "needs_mfa", None

    # A (None, None) return does not guarantee a usable session -- verify.
    _verify(client)
    _save_tokens(client)
    return "authenticated", client


def finish_login(mfa_code: str) -> Garmin:
    """Complete an MFA login using the code Garmin sent to the user."""
    if not MFA_STATE_PATH.exists():
        raise AuthError("No pending MFA login. Run 'gdash auth start' first.")

    client_state: dict[str, Any] = json.loads(MFA_STATE_PATH.read_text())

    email, password = _credentials()
    client = Garmin(email=email, password=password, return_on_mfa=True)
    client.resume_login(client_state, mfa_code.strip())

    _verify(client)
    _save_tokens(client)
    MFA_STATE_PATH.unlink(missing_ok=True)
    return client


def _save_tokens(client: Garmin) -> None:
    """Persist OAuth tokens to disk with restrictive permissions."""
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    client.client.dump(str(TOKEN_DIR))
    TOKEN_DIR.chmod(0o700)
    for token_file in TOKEN_DIR.glob("*.json"):
        token_file.chmod(0o600)


def _verify(client: Garmin) -> None:
    """Confirm the session actually works before we claim success."""
    client.get_user_profile()


def whoami(client: Garmin) -> str:
    """Return a human-readable identity string for a logged-in client."""
    try:
        return client.get_full_name() or client.display_name or "unknown"
    except Exception:
        return client.display_name or "unknown"

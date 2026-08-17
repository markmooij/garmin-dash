"""Signal REST client — httpx implementation of the Messenger interface.

Talks to the HTTP API of `bbernhard/signal-cli-rest-api`:

  * POST /v2/send          — send a message to one recipient
  * GET  /v1/receive/{nr}  — poll incoming messages (consuming)
  * GET  /v1/health        — health probe

Provisioning (linking the number via QR or registering a SIM) is an
operational step done against the container directly — see README.md —
not part of this client.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .base import Message, Messenger

logger = logging.getLogger("signal_messenger.signal_rest")

_API_TOKEN_HEADER = "X-Signal-Cli-Rest-Api-Token"


class SignalRestClient(Messenger):
    """Messenger backed by signal-cli-rest-api."""

    def __init__(
        self,
        base_url: str,
        account: str | None = None,
        token: str | None = None,
        timeout: float = 15.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.account = account
        self.token = token
        self.timeout = timeout
        # injectable for tests; otherwise a plain pooled client
        self._client = client or httpx.Client(timeout=timeout)

    # -- low-level --------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {_API_TOKEN_HEADER: self.token} if self.token else {}

    def _post(self, path: str, payload: dict[str, Any]) -> httpx.Response:
        resp = self._client.post(f"{self.base_url}{path}", json=payload, headers=self._headers())
        resp.raise_for_status()
        return resp

    def _get(
        self, path: str, params: dict[str, Any] | None = None, request_timeout: float | None = None
    ) -> httpx.Response:
        resp = self._client.get(
            f"{self.base_url}{path}",
            params=params,
            headers=self._headers(),
            timeout=request_timeout,
        )
        resp.raise_for_status()
        return resp

    # -- Messenger --------------------------------------------------------

    def send_message(self, recipient: str, text: str) -> str | None:
        """Send `text` to a single recipient (E.164, e.g. "+31612345678")."""
        resp = self._post(
            "/v2/send",
            {
                "message": text,
                "numberType": "single",
                "recipients": [recipient],
                "textMode": "normal",
            },
        )
        try:
            body = resp.json()
        except ValueError:
            return None
        # v2/send responds 201 with {"timestamp": "..."} (newer API) or
        # {"id": ..., "timestamp": ...} (older API)
        if isinstance(body, dict):
            return body.get("id") or body.get("timestamp")
        return None

    def receive_messages(self, timeout: int = 10) -> list[Message]:
        """Poll for incoming messages (consuming). Requires `account`.

        Handles two envelope shapes:

        * ``dataMessage`` — a normal message from another number.
        * ``syncMessage.sentMessage`` — what "Note to Self" produces (Signal
          delivers self-chat as a sync of your own linked devices, not a
          dataMessage). Treated as incoming *only* when its destination is
          your own account (self-chat) — sync echoes of messages you sent to
          *other* people are still ignored, so replying never loops.
        """
        if not self.account:
            raise ValueError("SignalRestClient.receive_messages needs `account` (the registered number)")
        # /v1/receive long-polls for up to `timeout` seconds — the HTTP read
        # timeout must be larger than the long-poll window, or the client cuts
        # the request while the API is still holding it (ReadTimeout right
        # after linking, during signal-cli's initial sync).
        resp = self._get(
            f"/v1/receive/{self.account}",
            params={"timeout": timeout},
            request_timeout=max(timeout + 15, 30.0),
        )
        if resp.status_code == 204:
            return []
        payload = resp.json()
        if isinstance(payload, dict):
            # signal-cli-rest-api >= 0.100 (Go rewrite) returns ONE message
            # per call as {"account": ..., "envelope": {...}} — not an array.
            entries = [payload] if payload.get("envelope") else []
        elif isinstance(payload, list):
            entries = payload
        else:
            entries = []
        messages: list[Message] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            envelope = entry.get("envelope") or {}
            sender = envelope.get("source") or envelope.get("sourceUuid") or "unknown"

            # Message content is either a sibling of "envelope" (signal-cli
            # JSON passthrough in the older API) or nested INSIDE the
            # envelope (>= 0.100 Go API: {"account", "envelope": {...}}).
            data = entry.get("dataMessage") or envelope.get("dataMessage") or {}
            text = data.get("message")
            ts_raw = data.get("timestamp")

            if not text:
                sync = entry.get("syncMessage") or envelope.get("syncMessage") or {}
                sent = sync.get("sentMessage") or {}
                destination = sent.get("destination") or sent.get("destinationUuid")
                is_self_chat = destination is not None and destination in (self.account, sender)
                if is_self_chat:
                    text = sent.get("message")
                    ts_raw = sent.get("timestamp")
                    sender = self.account  # "Note to Self" — route as a command from you

            if not text:
                continue
            ts = int(ts_raw or envelope.get("timestamp") or 0) // 1000
            messages.append(Message(sender=sender, text=str(text), timestamp=ts, raw=entry))
        return messages

    def health(self) -> bool:
        try:
            resp = self._get("/v1/health")
            return resp.status_code == 200
        except httpx.HTTPError:
            logger.warning("signal-api health check failed", exc_info=True)
            return False

    def close(self) -> None:
        self._client.close()

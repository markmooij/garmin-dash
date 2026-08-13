"""Messenger interface — the contract every backend implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Message:
    """An incoming Signal message."""

    sender: str
    text: str
    timestamp: int  # epoch seconds
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


class Messenger(ABC):
    """Minimal messaging contract: send, receive, health.

    Backends (e.g. signal-cli-rest-api, a Telegram bot, an SMTP gateway)
    implement exactly these three operations; callers depend only on this
    interface.
    """

    @abstractmethod
    def send_message(self, recipient: str, text: str) -> str | None:
        """Send a plain-text message; return the backend message id if known."""

    @abstractmethod
    def receive_messages(self, timeout: int = 10) -> list[Message]:
        """Block up to `timeout` seconds for incoming messages.

        Receiving is *consuming*: a message returned here will not be
        returned again by a later call (queue semantics).
        """

    @abstractmethod
    def health(self) -> bool:
        """True when the backend is reachable and healthy."""

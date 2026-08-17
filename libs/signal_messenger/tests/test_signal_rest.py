"""Unit tests for SignalRestClient using an httpx MockTransport — no network."""

from __future__ import annotations

import httpx
import pytest

from signal_messenger import Message, SignalRestClient


def _client(handler) -> tuple[SignalRestClient, httpx.MockTransport]:
    transport = httpx.MockTransport(handler)
    c = SignalRestClient(
        base_url="http://signal.local:8080",
        account="+31612345678",
        token="sekrit",
        client=httpx.Client(transport=transport),
    )
    return c, transport


def test_send_message_payload_and_headers():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = request.content
        return httpx.Response(201, json={"id": "abc-123", "timestamp": 1786000000000})

    c, _ = _client(handler)
    msg_id = c.send_message("+31612345678", "Hallo")
    assert msg_id == "abc-123"
    assert seen["url"] == "http://signal.local:8080/v2/send"
    lowered = {k.lower(): v for k, v in seen["headers"].items()}
    assert lowered["x-signal-cli-rest-api-token"] == "sekrit"
    import json

    body = json.loads(seen["body"])
    assert body == {
        "message": "Hallo",
        "numberType": "single",
        "recipients": ["+31612345678"],
        "textMode": "normal",
    }


def test_send_message_no_token_header_when_unset():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "x-signal-cli-rest-api-token" not in {k.lower(): v for k, v in request.headers.items()}
        return httpx.Response(201, json={})

    c, _ = _client(handler)
    c.token = None
    assert c.send_message("+31612345678", "x") is None


def test_receive_messages_parses_envelopes():
    envelope = {
        "envelope": {
            "source": "+31612345678",
            "sourceUuid": "deadbeef",
            "sourceDevice": 1,
            "timestamp": 1786000000000,
        },
        "dataMessage": {"timestamp": 1786000000000, "message": "/summary"},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[envelope])

    c, _ = _client(handler)
    msgs = c.receive_messages(timeout=5)
    assert msgs == [
        Message(sender="+31612345678", text="/summary", timestamp=1786000000, raw=envelope)
    ]
    assert msgs[0].raw == envelope


def test_receive_messages_skips_sync_and_empty_envelopes():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                # sync echo of a message *I sent to someone else* -> ignored
                {
                    "envelope": {"source": "+31612345678", "timestamp": 1},
                    "syncMessage": {"sentMessage": {"destination": "+9999999", "message": "hi there"}},
                },
                {"envelope": {"source": "+2", "timestamp": 2}},  # typing indicator / receipt
                {"envelope": {"source": "+3", "timestamp": 3}, "dataMessage": {"message": "hi"}},
                {"envelope": {"source": "+4", "timestamp": 4}, "dataMessage": {"message": ""}},
            ],
        )

    c, _ = _client(handler)
    msgs = c.receive_messages()
    assert [m.sender for m in msgs] == ["+3"]


def test_receive_messages_parses_note_to_self():
    """'Note to Self' arrives as syncMessage.sentMessage with destination == own account."""
    envelope = {
        "envelope": {"source": "+31612345678", "sourceUuid": "deadbeef", "timestamp": 1786000000000},
        "syncMessage": {
            "sentMessage": {
                "destination": "+31612345678",
                "timestamp": 1786000000000,
                "message": "/summary",
            }
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[envelope])

    c, _ = _client(handler)
    msgs = c.receive_messages(timeout=5)
    assert msgs == [
        Message(sender="+31612345678", text="/summary", timestamp=1786000000, raw=envelope)
    ]


def test_receive_messages_uses_request_timeout_larger_than_long_poll():
    """The HTTP read timeout must exceed the API long-poll window, else the
    client cuts the request while the API still holds it (ReadTimeout)."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["read_timeout"] = request.extensions["timeout"]["read"]
        return httpx.Response(200, json=[])

    c, _ = _client(handler)
    c.receive_messages(timeout=1)  # 1s long-poll -> 30s floor
    assert seen["read_timeout"] == 30.0
    c.receive_messages(timeout=60)  # long polls -> window + 15s margin
    assert seen["read_timeout"] == 75.0


def test_receive_messages_handles_204():
    """The API may answer a timed-out long-poll with 204 — treat as empty."""
    c, _ = _client(lambda r: httpx.Response(204))
    assert c.receive_messages() == []


def test_receive_requires_account():
    c, _ = _client(lambda r: httpx.Response(200, json=[]))
    c.account = None
    with pytest.raises(ValueError):
        c.receive_messages()


def test_health_ok_and_failure():
    def ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    c, _ = _client(ok)
    assert c.health() is True

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    c2, _ = _client(down)
    assert c2.health() is False


def test_send_raises_on_non_2xx():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    c, _ = _client(handler)
    with pytest.raises(httpx.HTTPStatusError):
        c.send_message("+31612345678", "x")

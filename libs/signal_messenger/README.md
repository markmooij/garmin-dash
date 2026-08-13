# signal_messenger

Standalone Signal messaging client for
[`bbernhard/signal-cli-rest-api`](https://github.com/bbernhard/signal-cli-rest-api)
(the Docker wrapper around `signal-cli`). Zero application dependencies —
just `httpx` — so it can be installed and used from any project:

```bash
pip install ./libs/signal_messenger
```

## Usage

```python
from signal_messenger import SignalRestClient

client = SignalRestClient(
    base_url="http://localhost:8080",
    account="+31612345678",      # the number registered in signal-cli
    token="my-api-token",        # optional, matches SIGNAL_CLI_HTTP_TOKEN
)

client.send_message("+31612345678", "Goedemorgen ☕")   # sends to your phone

for msg in client.receive_messages(timeout=10):        # consuming queue
    print(msg.sender, msg.text)
```

`Messenger` (in `signal_messenger.base`) is the abstract contract —
`send_message`, `receive_messages`, `health` — so callers can swap in a
different backend (Telegram, SMTP, …) without touching their logic.

## Interface

| Method | REST call | Notes |
|---|---|---|
| `send_message(recipient, text)` | `POST /v2/send` | returns message id |
| `receive_messages(timeout=10)` | `GET /v1/receive/{account}` | consuming; skips sync/typing envelopes |
| `health()` | `GET /v1/health` | `bool` |

## Provisioning the number (one-time, ops)

signal-cli must be linked to a Signal account before anything can be sent.
Two options — **pick one** (see the open decision in the ROADMAP):

### Option A — QR link of a secondary device (no SIM needed)

Works with the Signal app already on your phone (the number stays linked
to the phone; signal-cli acts as a *linked device*).

```bash
# 1. start the container (see docker-compose.{dev,prod}.yml)
# 2. fetch the QR code — scan it inside Signal: Settings → Linked devices
curl "http://localhost:8080/v1/qrcodes?device_name=garmin-dash" -o qr.png
# 3. check it is linked
curl http://localhost:8080/v1/health
```

### Option B — SIM registration (dedicated number, SMS verification)

```bash
curl -X POST "http://localhost:8080/v1/register/+31612345678" \
     -H "Content-Type: application/json" -d '{"captcha": ""}'
curl -X POST "http://localhost:8080/v1/register/+31612345678/verify/+31612345678" \
     -H "Content-Type: application/json" -d '{"pin": "123456"}'
```

## Development

```bash
cd libs/signal_messenger
uv run --with pytest pytest tests          # run the unit tests
pip install -e .                           # install into your venv
```

## License

MIT

# Security Policy

## Reporting a vulnerability

This is a small self-hosted hobby project. If you find a security issue, please
open a **private** GitHub Security Advisory instead of a public issue:

1. Go to **Security → Report a vulnerability** on this repository.
2. Describe the issue, including how to reproduce it and the affected version.

You can also email the maintainer directly (see the author field in
`pyproject.toml`). Please do **not** open a public issue for a vulnerability.

## Scope

The following are in scope:

- Remote code execution, SQL injection, or path traversal in the web app or
  CLI.
- Leakage of Garmin tokens, Signal credentials, or LLM API keys.
- The Signal command router (untrusted message input → app actions).

The following are **out of scope** (by design, documented in `README.md`):

- The dashboard is intended to be bound to a trusted LAN only; it has no
  authentication layer and should not be exposed to the public internet
  without a reverse proxy + auth in front of it.
- Garmin Connect access uses the unofficial `garminconnect` API and can break
  when Garmin changes their endpoints.

## Supported versions

Only the latest release on `main` is supported. Security fixes land in the next
release; there is no backport window for older tags.

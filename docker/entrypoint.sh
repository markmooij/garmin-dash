#!/bin/sh
# Garmin Dash entrypoint: make the bind mounts usable, then drop privileges.
#
# Docker auto-creates missing bind-mount host dirs as root, and SQLite cannot
# create a DB file in a root-owned dir when the container runs as an unprivileged
# uid. This script (running as root) fixes ownership for the configured PUID/PGID
# before the real command starts, so `docker compose up` "just works" on a fresh
# Pi even when the user never touched the host dirs.
#
# Env: PUID (default 1000), PGID (default 1000) — see .env.prod.example.

set -e

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

mkdir -p /app/data /app/logs
chown -R "${PUID}:${PGID}" /app/data /app/logs

exec setpriv --reuid "${PUID}" --regid "${PGID}" --clear-groups "$@"

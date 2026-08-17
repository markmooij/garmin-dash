#!/bin/sh
# Garmin Dash entrypoint: make the bind mounts usable, then drop privileges.
#
# Running as root (recommended — no `user:` in compose):
#   Docker auto-creates missing bind-mount host dirs as root, and SQLite cannot
#   create a DB file in a root-owned dir when the app runs as an unprivileged
#   uid. This script fixes ownership for the configured PUID/PGID before the
#   real command starts, then drops privileges with setpriv.
#
# Running as a non-root user (legacy compose with `user: PUID:PGID`):
#   chown/setpriv need root, so they are skipped and the command runs as the
#   current user. That works as long as the host dirs are already owned by
#   that uid (e.g. `sudo chown -R 1000:1000 data logs` on the Pi).
#
# Env: PUID (default 1000), PGID (default 1000) — see .env.prod.example.

set -e

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

if [ "$(id -u)" -eq 0 ]; then
    mkdir -p /app/data /app/logs
    chown -R "${PUID}:${PGID}" /app/data /app/logs
    exec setpriv --reuid "${PUID}" --regid "${PGID}" --clear-groups "$@"
fi

echo "gdash-entrypoint: not running as root — skipping ownership fix." >&2
echo "gdash-entrypoint: if the DB cannot be created, run on the host:" >&2
echo "  sudo chown -R ${PUID}:${PGID} data logs" >&2
exec "$@"

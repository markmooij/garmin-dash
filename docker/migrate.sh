#!/bin/sh
# Run schema migrations under an inter-container lock.
#
# app and scheduler both start `alembic upgrade head` at boot against the
# same SQLite file on the shared ./data volume. SQLite DDL is
# non-transactional, so a simultaneous fresh-boot race makes one of them
# fail with "table ... already exists". flock on a lockfile inside the
# shared volume serializes the runs.

set -e

LOCK=/app/data/.migration.lock

if touch "$LOCK" 2>/dev/null; then
    (
        flock -x 9
        alembic upgrade head
    ) 9>"$LOCK"
else
    echo "gdash-migrate: cannot write $LOCK — running migration without lock" >&2
    alembic upgrade head
fi

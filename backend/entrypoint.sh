#!/bin/sh
# Backend container entrypoint.
#
# Self-initialisation so an operator never has to run any command:
#   1. wait for the database, apply migrations (alembic upgrade head)
#   2. seed baseline data (roles, admin, policies, holidays) — idempotent
#   3. start the API server
#
# Set AUTO_INIT=false to skip steps 1-2 (advanced/manual operation).
# Only the backend service runs this; celery overrides the command in compose.
set -e

if [ "${AUTO_INIT:-true}" = "true" ]; then
    echo "[init] applying database migrations..."
    n=0
    until alembic upgrade head; do
        n=$((n + 1))
        if [ "$n" -ge 30 ]; then
            echo "[init] database did not become ready after retries — aborting"
            exit 1
        fi
        echo "[init] database not ready yet (attempt $n) — retrying in 2s"
        sleep 2
    done
    echo "[init] migrations applied"

    echo "[init] seeding baseline data (idempotent)..."
    python seed_db_full.py || echo "[init] seed reported issues — continuing startup"
fi

echo "[init] starting API server"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000

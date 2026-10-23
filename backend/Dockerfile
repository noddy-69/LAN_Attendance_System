FROM python:3.12-slim

WORKDIR /app

# PostgreSQL client tools (pg_dump / pg_restore) — power the in-app backup & restore
# feature (Admin → Settings → Data). The Debian-provided client is always >= our
# pinned PG16 server, which is all pg_dump/pg_restore require (client >= server).
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies as root so pip can write to /usr/local/lib
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Drop to a non-root user for all runtime operations
RUN adduser --disabled-password --gecos "" --uid 1000 appuser

# Copy the entire project (respects .dockerignore — .env is excluded)
COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 8000

# Self-initialising start: migrate + seed (idempotent) then run uvicorn.
# Uses CMD (not ENTRYPOINT) so the celery service can fully override it in compose.
CMD ["sh", "/app/entrypoint.sh"]

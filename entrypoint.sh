#!/bin/bash
set -euo pipefail

echo "[entrypoint] Running database migrations..."
aerich upgrade

echo "[entrypoint] Starting application..."
exec gunicorn app.main:app \
  --workers "${GUNICORN_WORKERS:-1}" \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind "0.0.0.0:${PORT:-8000}" \
  --timeout 60 \
  --graceful-timeout 30 \
  --keep-alive 5 \
  --access-logfile "-" \
  --error-logfile "-" \
  --log-level "${LOG_LEVEL:-info}"

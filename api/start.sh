#!/bin/bash
set -e

if [ "$SERVICE_TYPE" = "worker" ]; then
  echo "[start] launching Celery worker"
  exec celery -A dialer.workers.celery_app worker -B \
    --loglevel=info \
    --concurrency=4 \
    -Q default,pacing,campaigns
else
  echo "[start] running DB migrations"
  alembic upgrade head

  echo "[start] launching API server"
  exec uvicorn dialer.main:app --host 0.0.0.0 --port 8000 --reload
fi

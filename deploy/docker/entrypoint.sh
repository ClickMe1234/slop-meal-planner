#!/bin/sh
set -eu

if [ "$(id -u)" = "0" ]; then
  run_uid="${PUID:-10001}"
  run_gid="${PGID:-10001}"
  case "$run_uid:$run_gid" in
    *[!0-9:]*|:*|*:) echo "PUID and PGID must be numeric" >&2; exit 64 ;;
  esac

  mkdir -p /data /backups
  chown "$run_uid:$run_gid" /data /backups
  exec gosu "$run_uid:$run_gid" "$0" "$@"
fi

role="${1:-web}"
if [ "$#" -gt 0 ]; then
  shift
fi

run_migrations() {
  if [ "${RUN_MIGRATIONS:-true}" != "true" ]; then
    return
  fi

  python - <<'PY'
import os
import subprocess

import psycopg

database_url = os.environ["MEAL_PLANNER_DATABASE_URL"].replace(
    "postgresql+psycopg://", "postgresql://", 1
)
lock_id = 0x4D45414C504C414E  # "MEALPLAN" as one stable signed-64-bit-safe value.

with psycopg.connect(database_url, autocommit=True) as connection:
    connection.execute("SELECT pg_advisory_lock(%s)", (lock_id,))
    try:
        subprocess.run(
            ["alembic", "-c", "alembic.ini", "upgrade", "head"],
            check=True,
        )
        subprocess.run(
            ["python", "-m", "scripts.reparse_ingredients"],
            check=True,
        )
        subprocess.run(
            ["python", "-m", "scripts.normalise_quantities"],
            check=True,
        )
    finally:
        connection.execute("SELECT pg_advisory_unlock(%s)", (lock_id,))
PY
}

case "$role" in
  web)
    run_migrations
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 "$@"
    ;;
  worker)
    exec celery -A app.worker.celery_app worker --loglevel="${LOG_LEVEL:-INFO}" "$@"
    ;;
  scheduler)
    exec celery -A app.worker.celery_app beat \
      --loglevel="${LOG_LEVEL:-INFO}" \
      --schedule="${CELERY_BEAT_SCHEDULE:-/data/celerybeat-schedule}" \
      "$@"
    ;;
  migrate)
    run_migrations
    ;;
  *)
    echo "Unknown role: $role (expected web, worker, scheduler, or migrate)" >&2
    exit 64
    ;;
esac

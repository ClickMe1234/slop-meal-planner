#!/bin/sh
set -eu
umask 077

: "${PGHOST:?PGHOST is required}"
: "${PGUSER:?PGUSER is required}"
: "${PGDATABASE:?PGDATABASE is required}"
: "${BACKUP_ROOT:?BACKUP_ROOT is required}"
: "${DATA_DIR:?DATA_DIR is required}"

lock_file="${BACKUP_LOCK_FILE:-$BACKUP_ROOT/.backup.lock}"
case "$lock_file" in
  /*) ;;
  *) echo "BACKUP_LOCK_FILE must be an absolute path" >&2; exit 64 ;;
esac
mkdir -p "$(dirname "$lock_file")"
# API-triggered backups use the same POSIX advisory lock.  Maintenance jobs
# must not race a backup (or another restore) against the live database/files.
if [ "${BACKUP_LOCK_HELD:-0}" != "1" ]; then
  exec 9>"$lock_file"
  if ! flock -n 9; then
    echo "Another backup or restore is already running" >&2
    exit 75
  fi
fi

case "$PGDATABASE:$PGUSER" in
  *[!A-Za-z0-9_:]*) echo "Database and role names may contain only letters, numbers, and underscores" >&2; exit 64 ;;
esac

case "$BACKUP_ROOT" in
  /*) ;;
  *) echo "BACKUP_ROOT must be an absolute path" >&2; exit 64 ;;
esac
if [ "$BACKUP_ROOT" = "/" ]; then
  echo "Refusing to use / as BACKUP_ROOT" >&2
  exit 64
fi

timestamp="$(date '+%Y%m%d-%H%M%S')"
day_of_month="$(date '+%d')"
day_of_week="$(date '+%u')"

if [ "$day_of_month" = "01" ]; then
  tier="monthly"
  retain="${RETAIN_MONTHLY:-12}"
elif [ "$day_of_week" = "7" ]; then
  tier="weekly"
  retain="${RETAIN_WEEKLY:-8}"
else
  tier="daily"
  retain="${RETAIN_DAILY:-14}"
fi

tier_dir="$BACKUP_ROOT/$tier"
temporary="$tier_dir/.${timestamp}.incomplete"
destination="$tier_dir/$timestamp"
mkdir -p "$temporary"

cleanup() {
  if [ -d "$temporary" ]; then
    rm -rf -- "$temporary"
  fi
}
trap cleanup EXIT HUP INT TERM

echo "Creating $tier backup $timestamp"
pg_dump \
  --format=custom \
  --compress=9 \
  --no-owner \
  --no-privileges \
  --file="$temporary/database.dump" \
  "$PGDATABASE"

# Listing a custom-format dump checks that PostgreSQL can read its archive index.
pg_restore --list "$temporary/database.dump" >/dev/null

if [ -d "$DATA_DIR" ]; then
  tar -czf "$temporary/data.tar.gz" -C "$DATA_DIR" .
else
  tar -czf "$temporary/data.tar.gz" --files-from /dev/null
fi

schema_revision="$(psql --tuples-only --no-align --command='SELECT version_num FROM alembic_version LIMIT 1' 2>/dev/null || true)"
schema_revision="${schema_revision:-unknown}"

cat >"$temporary/manifest.txt" <<EOF
created_at=$timestamp
tier=$tier
application_version=${APP_VERSION:-unknown}
schema_revision=$schema_revision
database=$PGDATABASE
EOF

(
  cd "$temporary"
  sha256sum database.dump data.tar.gz manifest.txt > SHA256SUMS
)

mv "$temporary" "$destination"
trap - EXIT HUP INT TERM
echo "Backup complete: $destination"

case "$retain" in
  ''|*[!0-9]*) echo "Invalid retention count: $retain" >&2; exit 64 ;;
esac

# Backup folder names are generated timestamps. Validate every deletion remains
# directly under the expected tier before applying retention.
find "$tier_dir" -mindepth 1 -maxdepth 1 -type d ! -name '.*.incomplete' -print \
  | sort -r \
  | awk -v keep="$retain" 'NR > keep' \
  | while IFS= read -r expired; do
      case "$expired" in
        "$tier_dir"/*)
          echo "Removing expired backup: $expired"
          rm -rf -- "$expired"
          ;;
        *)
          echo "Refusing to remove unexpected path: $expired" >&2
          exit 65
          ;;
      esac
    done

#!/bin/sh
set -eu
umask 077

if [ "${1:-}" != "--confirm" ] || [ -z "${2:-}" ]; then
  echo "Usage: restore.sh --confirm /backups/<daily|weekly|monthly>/<timestamp>" >&2
  exit 64
fi

backup_dir="$2"
: "${PGHOST:?PGHOST is required}"
: "${PGUSER:?PGUSER is required}"
: "${PGDATABASE:?PGDATABASE is required}"
: "${DATA_DIR:?DATA_DIR is required}"

case "$PGDATABASE:$PGUSER" in
  *[!A-Za-z0-9_:]*) echo "Database and role names may contain only letters, numbers, and underscores" >&2; exit 64 ;;
esac

case "$backup_dir" in
  /backups/daily/*|/backups/weekly/*|/backups/monthly/*) ;;
  *) echo "Backup must be a timestamp directory below /backups" >&2; exit 64 ;;
esac
case "$backup_dir" in
  *'/../'*|*'/..') echo "Parent traversal is not allowed" >&2; exit 64 ;;
esac
case "$DATA_DIR" in
  /*) ;;
  *) echo "DATA_DIR must be absolute" >&2; exit 64 ;;
esac
if [ "$DATA_DIR" = "/" ]; then
  echo "Refusing to restore application data into /" >&2
  exit 64
fi

for required in SHA256SUMS database.dump data.tar.gz manifest.txt; do
  if [ ! -f "$backup_dir/$required" ]; then
    echo "Backup is incomplete: missing $required" >&2
    exit 66
  fi
done

(
  cd "$backup_dir"
  sha256sum --check SHA256SUMS
)
pg_restore --list "$backup_dir/database.dump" >/dev/null

echo "Restoring database $PGDATABASE from $backup_dir"
psql --dbname=postgres --set=ON_ERROR_STOP=1 --command="
  SELECT pg_terminate_backend(pid)
  FROM pg_stat_activity
  WHERE datname = '$PGDATABASE' AND pid <> pg_backend_pid();
"
dropdb --if-exists --force "$PGDATABASE"
createdb --owner="$PGUSER" "$PGDATABASE"
pg_restore \
  --exit-on-error \
  --no-owner \
  --no-privileges \
  --dbname="$PGDATABASE" \
  "$backup_dir/database.dump"

echo "Restoring application files"
mkdir -p "$DATA_DIR"
find "$DATA_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
tar -xzf "$backup_dir/data.tar.gz" -C "$DATA_DIR"

echo "Restore completed successfully"

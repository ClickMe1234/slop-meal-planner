#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 <daily|weekly|monthly>/<timestamp>" >&2
  exit 64
fi

relative_backup="$1"
case "$relative_backup" in
  daily/*|weekly/*|monthly/*) ;;
  *) echo "Backup must be relative to BACKUP_ROOT" >&2; exit 64 ;;
esac
case "$relative_backup" in
  *'..'*) echo "Parent traversal is not allowed" >&2; exit 64 ;;
esac

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
deploy_dir="$(dirname "$script_dir")"

compose() {
  docker compose --env-file "$deploy_dir/.env" -f "$deploy_dir/compose.yaml" "$@"
}

echo "Stopping application services before destructive restore"
compose stop web worker scheduler

echo "Restoring /backups/$relative_backup"
if ! compose --profile maintenance run --rm restore --confirm "/backups/$relative_backup"; then
  echo "Restore failed. Application services remain stopped for investigation." >&2
  exit 1
fi

echo "Starting the restored application"
compose up -d postgres redis web worker scheduler
compose ps

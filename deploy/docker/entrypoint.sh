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

exec python /opt/meal-planner/launcher.py "$@"

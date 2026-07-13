# Meal Planner deployment and operations

The supported production deployment is the five-service Docker Compose stack in
[`compose.yaml`](compose.yaml):

- `web`: FastAPI, the built React PWA, and database migrations.
- `worker`: background imports, nutrition jobs, and planning work.
- `scheduler`: scheduled maintenance and recurring jobs.
- `postgres`: authoritative application data.
- `redis`: the worker queue and disposable job results.

Only the web port is published. PostgreSQL and Redis are reachable only on the
private Compose network. The application is designed for a trusted home LAN; it
must not be forwarded directly to the internet.

## 1. Prepare an Unraid installation

Install Docker Compose Manager (or use Unraid's terminal with Docker Compose
v2), copy this repository to a stable location, and open a terminal in the
repository root.

Create the configuration file:

```sh
cp deploy/.env.example deploy/.env
```

Generate independent secrets. These commands print values; paste each value
into its matching field in `deploy/.env` and do not save the terminal output in
the repository:

```sh
openssl rand -hex 32
openssl rand -hex 32
openssl rand -hex 32
```

Use them for:

1. `POSTGRES_PASSWORD`
2. `SECRET_KEY`
3. `SETUP_TOKEN`

Keep the PostgreSQL password URL-safe because Compose embeds it in an internal
connection URL. Hex output from the command above is safe. Set:

- `APPDATA_ROOT=/mnt/user/appdata/meal-planner`
- `BACKUP_ROOT=/mnt/user/backups/meal-planner`
- `ALLOWED_HOSTS` to the Unraid hostname/IP and names used by household devices.
- `WEB_PORT` to the desired LAN port (default `8080`).
- `APP_VERSION` to an immutable release such as `0.1.0`; never use `latest`.

Create the host folders before first startup:

```sh
mkdir -p /mnt/user/appdata/meal-planner/data
mkdir -p /mnt/user/appdata/meal-planner/postgres
mkdir -p /mnt/user/appdata/meal-planner/redis
mkdir -p /mnt/user/backups/meal-planner
chown -R 99:100 /mnt/user/appdata/meal-planner/data
```

Validate and start the stack:

```sh
docker compose --env-file deploy/.env -f deploy/compose.yaml config --quiet
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --build postgres redis web worker scheduler
docker compose --env-file deploy/.env -f deploy/compose.yaml ps
```

Open `http://<unraid-host>:8080`. The first-owner setup screen asks for the
`SETUP_TOKEN`. After the owner exists, keep the token in the protected `.env`
file for disaster recovery, but it cannot create a second owner.

For a developer workstation, change `APPDATA_ROOT` to `./.runtime` and
`BACKUP_ROOT` to `./backups`. Compose resolves these from the `deploy` directory.
On Linux, also set `PUID` and `PGID` to the
output of `id -u` and `id -g`.

## 2. Routine commands

Run commands from the repository root:

```sh
# Status and health
docker compose --env-file deploy/.env -f deploy/compose.yaml ps

# Application logs (secrets are deliberately not logged)
docker compose --env-file deploy/.env -f deploy/compose.yaml logs -f --tail=200 web worker scheduler

# Restart application processes without touching data services
docker compose --env-file deploy/.env -f deploy/compose.yaml restart web worker scheduler

# Stop the stack without deleting bind-mounted data
docker compose --env-file deploy/.env -f deploy/compose.yaml down
```

Liveness and readiness URLs are:

```text
http://<unraid-host>:8080/api/v1/health/live
http://<unraid-host>:8080/api/v1/health/ready
```

`live` confirms the process is running. `ready` confirms dependencies are ready
and is the endpoint used by Docker health checks.

## 3. Backups

A backup contains:

- `database.dump`: PostgreSQL custom-format archive.
- `data.tar.gz`: custom images and application files.
- `manifest.txt`: application/schema metadata.
- `SHA256SUMS`: integrity checks for all three files.

Create one manually:

```sh
docker compose --env-file deploy/.env -f deploy/compose.yaml --profile maintenance run --rm backup
```

Schedule that command nightly using the Unraid User Scripts plugin. The job is
classified as:

- `monthly` on the first day of a month (12 retained by default).
- `weekly` on Sunday (8 retained by default).
- `daily` otherwise (14 retained by default).

The backup is written to an `.incomplete` directory and is made visible only
after `pg_restore` can read the dump and checksums have been generated. Keep an
additional copy on another physical device; Unraid parity is not a backup.

### Test a restore

List backup folders under the configured `BACKUP_ROOT`, then run:

```sh
sh deploy/scripts/restore-stack.sh daily/20260712-020000
```

Replace the example with an existing tier/timestamp. The wrapper:

1. Stops web, worker, and scheduler.
2. Verifies all backup checksums.
3. Terminates database connections and recreates the application database.
4. Replaces `/data` with the archived application files.
5. Starts the stack only after a successful restore.

This is intentionally destructive and requires the exact backup path. If a
restore fails, application services remain stopped so the failure can be
investigated without writing into a partial database.

## 4. Upgrade and rollback

Before every upgrade:

```sh
docker compose --env-file deploy/.env -f deploy/compose.yaml --profile maintenance run --rm backup
```

Then set an immutable `APP_VERSION` in `deploy/.env` and run:

```sh
docker compose --env-file deploy/.env -f deploy/compose.yaml build --pull
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d postgres redis web worker scheduler
docker compose --env-file deploy/.env -f deploy/compose.yaml ps
```

The web entrypoint obtains a PostgreSQL advisory lock before running Alembic, so
only one process can migrate at a time. Startup fails rather than serving a
partially migrated application. Worker and scheduler wait for healthy web.

Do not roll back only the image after a database migration. Restore the
pre-upgrade backup, set the prior `APP_VERSION`, then start the prior image.

## 5. Security notes

- Never commit `deploy/.env`; it is ignored by Git and Docker build context.
- Do not publish ports `5432` or `6379`.
- Do not expose the web port through router port forwarding.
- `COOKIE_SECURE=false` is necessary for plain HTTP on a LAN. Change it to
  `true` if a trusted local reverse proxy or Tailscale supplies HTTPS.
- Add every actual hostname to `ALLOWED_HOSTS`; do not use `*`.
- The application containers run as Unraid's `nobody:users` (`99:100`) by
  default and have no Docker socket or privileged mode.
- Database and Redis images use exact version tags. Review release notes before
  changing a major version.

## 6. Troubleshooting

### Web is unhealthy

```sh
docker compose --env-file deploy/.env -f deploy/compose.yaml logs --tail=200 postgres web
```

Typical causes are an incorrectly URL-encoded PostgreSQL password, an invalid
bind-folder owner, a missing required secret, or a failed migration.

### Worker is not processing jobs

```sh
docker compose --env-file deploy/.env -f deploy/compose.yaml logs --tail=200 redis worker
docker compose --env-file deploy/.env -f deploy/compose.yaml restart worker
```

Redis queue data is operational state, not authoritative household data. Do not
restore an old Redis directory alongside a newer PostgreSQL backup.

### Permission error under `/data`

```sh
chown -R 99:100 /mnt/user/appdata/meal-planner/data
docker compose --env-file deploy/.env -f deploy/compose.yaml restart web worker scheduler
```

### PostgreSQL major-version upgrade

Never point a new PostgreSQL major version at an old data directory. Create a
verified application backup, deploy the new PostgreSQL major version with an
empty data directory, and restore through the maintenance job.

## 7. Unraid XML template

`unraid-template.xml` documents the application-container fields used by Unraid
Community Applications. It represents only `web`; PostgreSQL, Redis, worker and
scheduler are still required. For that reason, Docker Compose Manager is the
supported one-click stack and the XML is not a replacement for `compose.yaml`.

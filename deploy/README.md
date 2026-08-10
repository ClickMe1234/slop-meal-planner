# Slop deployment and operations

The primary production path is the Unraid **Add Container** WebGUI using the
public immutable image. PostgreSQL and Redis are installed separately. The
existing five-service Compose stack remains supported as an alternative.

## Unraid WebGUI installation

### Install dependencies first

Install or identify standalone PostgreSQL 15–18 and Redis 7.2/7.4. Create a
dedicated PostgreSQL database and role for Slop, normally `meal_planner`, and
reserve two unused Redis logical databases, normally `0` for the broker and `1`
for results. Existing services are supported if Slop can reach their host/IP
and port. Redis Cluster and Sentinel URL shapes are not supported.

Generate three independent random values and keep them in a password manager:

```sh
openssl rand -hex 32  # PostgreSQL password
openssl rand -hex 32  # MEAL_PLANNER_SECRET_KEY
openssl rand -hex 32  # MEAL_PLANNER_SETUP_TOKEN
```

The application secret must be preserved permanently. Rotating it makes
encrypted integration credentials unreadable. The setup token is used to
create the first owner and should remain available for disaster recovery.

### Add the application container

In **Apps → Add Container**, use these main fields:

| Field | Value |
| --- | --- |
| Name | `Slop Meal Planner` |
| Repository | `ghcr.io/clickme1234/slop-meal-planner:1.2.0` |
| Network Type | `Bridge` |

The Repository field is a Docker image reference, not the GitHub source URL.
No Label or Device entries are required. The GHCR package must be public so
Unraid can pull it anonymously.

For the `v1.2.0` release, verify once that
`ghcr.io/clickme1234/slop-meal-planner:1.2.0` is public and that an
unauthenticated `docker pull` succeeds. Later releases are not complete until
the same anonymous-pull check passes for their immutable tag.

Add these Port and Path entries through **Add another Port or Path**:

| Type | Name | Container target | Default host value | Mode |
| --- | --- | --- | --- | --- |
| Port | Web UI | `8000` | `8080` | TCP |
| Path | Application data | `/data` | `/mnt/user/appdata/slop-meal-planner/data` | Read/Write |
| Path | Backups | `/backups` | `/mnt/user/backups/slop-meal-planner` | Read/Write |

Only the host side of the Web UI port may be changed. Keep the container port
at `8000`; the frontend is same-origin and needs no URL change. The container
targets `/data` and `/backups` are persistent contracts.

Add these always-visible Variables. The variable target is the exact value in
the second column:

| Name | Target | Default / guidance |
| --- | --- | --- |
| PostgreSQL host | `POSTGRES_HOST` | Unraid LAN IP, hostname, or reachable container name |
| PostgreSQL port | `POSTGRES_PORT` | `5432` |
| PostgreSQL database | `POSTGRES_DB` | `meal_planner` |
| PostgreSQL user | `POSTGRES_USER` | `meal_planner` |
| PostgreSQL password | `POSTGRES_PASSWORD` | Strong random value; masked |
| Redis host | `REDIS_HOST` | Unraid LAN IP, hostname, or reachable container name |
| Redis port | `REDIS_PORT` | `6379` |
| Redis password | `REDIS_PASSWORD` | Strong value when Redis is LAN-published; masked |
| Application secret | `MEAL_PLANNER_SECRET_KEY` | Independent random value ≥32 characters; masked |
| Setup token | `MEAL_PLANNER_SETUP_TOKEN` | Independent random value ≥32 characters; masked |
| Allowed hosts | `MEAL_PLANNER_ALLOWED_HOSTS` | Actual LAN IPs, hostnames, and proxy names |
| Secure cookies | `MEAL_PLANNER_COOKIE_SECURE` | `true`; production requires HTTPS |
| HSTS | `MEAL_PLANNER_HSTS_ENABLED` | `true` after HTTPS is configured |
| Timezone | `TZ` | `Europe/London`; application timezone is derived from it |
| Runtime user | `PUID` | `99` |
| Runtime group | `PGID` | `100` |

The template also exposes these advanced Variables for TLS, ACLs, retention,
food providers, and existing connection URLs:

| Target | Default |
| --- | --- |
| `POSTGRES_SSLMODE` | `prefer` |
| `REDIS_USERNAME` | blank |
| `REDIS_TLS` | `false` |
| `REDIS_BROKER_DB` / `REDIS_RESULT_DB` | `0` / `1` (must differ) |
| `MEAL_PLANNER_DATABASE_URL` | blank, masked override |
| `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | blank, masked overrides |
| `LOG_LEVEL` | `INFO` |
| `RETAIN_DAILY` / `RETAIN_WEEKLY` / `RETAIN_MONTHLY` | `14` / `8` / `12` |
| `MEAL_PLANNER_USDA_API_KEY` | blank, masked |
| `MEAL_PLANNER_REMOTE_FOOD_SEARCH_ENABLED` | `true` |
| `MEAL_PLANNER_OPEN_FOOD_FACTS_ENABLED` | `true` |
| `MEAL_PLANNER_OPEN_FOOD_FACTS_TIMEOUT_SECONDS` | `10` |

When a full URL override is non-empty it wins over its friendly fields. The
launcher validates supported standalone URLs, encodes credentials, and parses
the PostgreSQL override back into `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`,
`PGPASSWORD`, and `PGSSLMODE` for backup/restore. Internal variables such as
`DATA_DIR`, `BACKUP_ROOT`, `FRONTEND_DIST_DIR`, `RUN_MIGRATIONS`, and
`CELERY_BEAT_SCHEDULE` are intentionally not GUI fields.

Start PostgreSQL and Redis before Slop. Slop retries dependency startup for up
to 120 seconds, then migrates once and starts one web server, one Celery worker,
and one Celery Beat scheduler. If any process fails, the container exits so
Unraid can restart the complete unit. Open the chosen host port and use the
setup token to create the owner.

### Networking choices

The zero-CLI path puts all three containers on the default Bridge network. Give
PostgreSQL and Redis chosen host ports and set `POSTGRES_HOST` and `REDIS_HOST`
to the Unraid server's LAN IP. This is convenient but publishes those services
to the LAN. Use strong credentials, do not forward any port from the router,
and do not expose the server outside the trusted LAN.

For stronger isolation, create one user-defined Docker bridge once, attach all
three containers to it, use the PostgreSQL and Redis container names with their
internal ports, and leave their host ports unpublished. User-defined bridges
provide container-name resolution and better isolation. This advanced option
requires the normal one-time Docker network setup; the application itself still
uses the same variables.

## Operations

### Backups

Create a verified backup from **Settings → Data & Backup**. It contains:

- `database.dump`, a PostgreSQL custom-format archive;
- `data.tar.gz`, the `/data` application files;
- `manifest.txt`, application and schema metadata; and
- `SHA256SUMS`, checksums for all three files.

The image bundles PostgreSQL 18.4 `pg_dump`, `pg_restore`, `psql`, `dropdb`, and
`createdb` clients for supported PostgreSQL 15–18 servers. The backup script
finishes an `.incomplete` directory only after archive readability and checksums
are valid. Schedule the backup role with Unraid User Scripts if desired.

Local archives are readable by the configured backup administrator so they can
be restored automatically. Encrypt every backup before copying it off the host
with a separately managed key (for example, age, restic, or encrypted object
storage). Do not reuse `MEAL_PLANNER_SECRET_KEY` as the backup key or store the
backup key beside the archives.

### Selective restore

For a migration into an existing installation, open **Settings > Data & Backup**
and choose **Restore selected data**. Select a backup folder, inspect its
contents, choose the source household, and tick the domains to import. Recipes
and their linked nutrition records, saved ingredients, pantry, shopping lists,
plans, household settings, and user accounts can be selected independently.

Selective restore verifies every archive file against `SHA256SUMS` before
opening the database dump. It merges missing records into the current household and keeps
matching records already present. Active sessions and encrypted integration
credentials are never imported, so the target installation's login and secret
configuration remain in place. The feature can inspect older database archives;
the imported copy is migrated inside a temporary database before it is read.

The PostgreSQL account used by Slop must be allowed to create and drop a
temporary database for this operation. If the target uses a restricted
application role, grant that capability temporarily or perform the operation
with the database administrator account, then restore the normal application
credentials afterward. This is separate from the destructive full restore below.

### Restore

Stop the Slop container. Edit the same container and set Post Arguments once to:

```text
restore --confirm /backups/<daily|weekly|monthly>/<timestamp>
```

Apply/start it once, verify that the container exits successfully, then clear
Post Arguments and start the normal `all` command. The restore verifies
checksums, PostgreSQL archive readability, tar readability, and safe data paths
before changing the database or `/data`; it never restarts application
processes automatically. Existing databases may require temporary
database-admin `POSTGRES_USER`/`POSTGRES_PASSWORD` values for the destructive
recreate step. Do not restore while another Slop application container is
running.

### Upgrades and rollback

Before an upgrade, create and verify a backup. Edit the immutable Repository tag
to the desired release, pull/apply the image, and verify `/api/v1/health/ready`.
Never roll back only the image after a database migration; restore the matching
pre-upgrade backup before returning to an older image.

`/api/v1/health/live` checks only that the process is running. Readiness checks
PostgreSQL and every configured Redis endpoint with short timeouts. Redis is
skipped only for local SQLite development when no Redis URL is configured.

## Compose alternative

Compose remains a five-service deployment: `web`, `worker`, `scheduler`,
`postgres`, and `redis`. The documented baseline is PostgreSQL `17.10-bookworm`
and Redis `7.4.9-alpine`; no PostgreSQL major-version data migration is
performed.

```sh
cp deploy/.env.example deploy/.env
docker compose --env-file deploy/.env -f deploy/compose.yaml config --quiet
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --build postgres redis web worker scheduler
```

Run a Compose backup with:

```sh
docker compose --env-file deploy/.env -f deploy/compose.yaml --profile maintenance run --rm backup
```

For a restore, use `deploy/scripts/restore-stack.sh <tier>/<timestamp>`. It
stops web, worker, and scheduler, validates the archive, restores the database
and `/data`, and starts the application only after a successful restore. Keep an
additional backup copy on another physical device; Unraid parity is not a
backup.

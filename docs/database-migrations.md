# Database migration safety

Alembic migrations are the authoritative, replayable history of the database.
Every migration must be self-contained and must describe only the schema change
introduced by that revision.

## Required rules

1. Never import `app.models`, `app.db.Base`, or other live application model
   metadata from a historical migration.
2. Use explicit Alembic operations such as `op.create_table`, `op.add_column`,
   or `op.batch_alter_table`.
3. Keep server defaults portable between PostgreSQL and SQLite unless a migration
   contains an explicit dialect branch.
4. Preserve existing rows when adding a required field: add a safe default or use
   a staged nullable/backfill/non-null migration.
5. Test both a clean replay and an upgrade containing representative existing data.

Migration 0001 is frozen from Git revision
`9980af3b001b93fc9d336f2fd01326b731212371`. It must not be regenerated from the
current SQLAlchemy models.

## Automated safeguards

The backend test suite now:

- upgrades an empty SQLite database to `head`;
- runs `alembic check` to detect model/schema drift;
- downgrades to `base` and replays the entire history a second time;
- upgrades a populated 0007 database to `head` and verifies its recipe survives;
- rejects migrations that import live application modules.

CI also performs the clean upgrade, schema check, full downgrade, and second
upgrade against PostgreSQL 17, matching the production database engine.

Run the local checks from `backend`:

```text
python -m pytest tests/test_migrations.py
alembic -c alembic.ini upgrade head
alembic -c alembic.ini check
```

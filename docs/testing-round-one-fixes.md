# Testing round one: findings and fixes

Date: 13 July 2026  
Branch: `codex/fix-testing-round-one`

This note records the first hands-on testing findings, their verified causes,
and the implementation decisions made to resolve them.

## Onboarding and household settings

The original onboarding and settings screens were presentation-only mock-ups.
Their buttons changed no React state and called no API endpoints. The screens
now use the existing household-member API to list, create, rename, activate and
deactivate planning profiles. Optimistic-looking controls were avoided: buttons
show a saving state and API failures are displayed in the page.

The owner can now change their password from Household settings. The current
password is required and the existing backend minimum of 12 characters remains
enforced.

## Login

Usernames were matched case-sensitively. The configured owner is `Zach`, so a
later login as `zach` failed even with the same password. Usernames are now
trimmed and compared case-insensitively at setup, login and collaborator
creation. Passwords remain case-sensitive and are never trimmed or normalised.

## Preferences and restrictions

The static preference chips have been replaced with stored restriction data.
Allergies and exclusions are persisted as hard rules; preferences and dislikes
are stored as ranking inputs. A new authorised DELETE endpoint allows a chip to
be removed. Every operation is scoped to the current household.

## Recipe search ranking

Publisher result pages contain navigation and category links in addition to
recipe cards. The adapters previously accepted those links in source order,
which allowed unrelated headings such as “Sourdough & Focaccia” to appear above
chicken curry results.

Each publisher's parsed results are now scored against normalised query terms.
Exact phrases and titles containing every query term rank first, partial matches
rank later, and results containing none of the terms are discarded. This is a
post-parse safety layer, so it works consistently across all supported source
adapters without relying on a publisher's page ordering.

## Ingredient nutrition matching

The local `food_record` catalogue was empty, so the review dropdown could not
offer any match. Food search now remains local-first, but when fewer than three
local records match it queries USDA FoodData Central for generic Foundation and
SR Legacy records. Only records containing energy, protein, carbohydrate and
fat are accepted. They are normalised to the app's per-100-g schema, stored with
provider/version/provenance, and reused by all later searches and calculations.

The review screen starts with the first unmatched ingredient as its food query,
which makes the first set of real matches visible without an extra discovery
step. A failed remote request does not hide local records. `DEMO_KEY` is usable
for light personal testing; a personal USDA API key can be set with
`USDA_API_KEY` if rate limits become noticeable.

## Blank recipe review page

Saved recipes in `needs_review` state linked to
`/imports/<recipe-id>/review`. That route interprets its identifier as a worker
job ID, so it repeatedly requested a job that did not exist and never obtained
the recipe.

Saved drafts now link to `/recipes/<recipe-id>/review`, while imports continue
to use `/imports/<job-id>/review`. The shared review component accepts either
route and only polls jobs while their state is `queued` or `running`.

## Backups

“Back up now” was static. It now calls an owner-only system endpoint which runs
the existing fixed-path backup script, prevents concurrent runs, reports useful
errors, and returns the latest backup status.

The first live smoke test also found that Debian Bookworm installed PostgreSQL
15 client tools while the database image is PostgreSQL 17. PostgreSQL refuses
that version mismatch. The application image now copies PostgreSQL 17.5
`pg_dump` and `pg_restore` from the same pinned image family as the database.
A successful live archive was created and verified at
`deploy/backups/daily/20260713-090236`.

## Verification

- Frontend TypeScript and production Vite build: passed in Docker.
- Backend regression suite: 28 passed.
- Added regressions cover case-insensitive login, member editing,
  adding/removing restrictions, and search relevance filtering.
- USDA live cache smoke test: 8 complete chickpea food records imported.
- PostgreSQL 17 backup and archive verification: passed.
- Docker services after recreation: web healthy; PostgreSQL and Redis healthy;
  worker and scheduler running.

Because the frontend is a PWA, an already-open tab can briefly retain the old
JavaScript bundle. Refresh the page once before retesting these fixes.

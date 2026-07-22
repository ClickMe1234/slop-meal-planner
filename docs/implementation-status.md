# Implementation status — 19 July 2026

This file connects the product specification to the first runnable release.

## End-to-end path now available

1. Deploy the five-service Compose stack and create the owner.
2. Choose calorie or macro targets and a hard tolerance during onboarding.
3. Add a custom recipe or search/import a publisher recipe.
4. Search or scan foods into the household ingredient library and optionally
   add a measured quantity directly to pantry stock.
5. Review serving yield, detected ingredient amounts/units, and nutrition
   matches for a custom recipe.
6. Use complete publisher-reported or ingredient-calculated per-serving
   nutrition and mark the recipe planner-ready.
7. Optionally expose a saved single-food serving as a tagged planner choice.
8. Select who attends each meal and when each meal gets a new cooked batch.
9. Generate a multi-day plan from meal-tagged, planner-ready choices.
10. Review daily calories/macros, collapse days, swap a whole cooked batch, and
   add up to two batch-wide sides or snacks before accepting it atomically while
   reserving pantry stock and building shopping.
11. Use the generated shopping list online or from its local offline copy.
12. Explicitly add checked purchases to the pantry.
13. Mark a cooked batch to consume its reservations.

## Implemented as hard rules

- Target mode is mutually exclusive: calories or protein/carbohydrate/fat.
- Protein and carbohydrate use 4 kcal/g; fat uses 9 kcal/g for feasibility
  validation.
- Tolerance is chosen by the user and never silently widened.
- Calorie-mode macro minima/maxima remain hard bounds.
- Shared meals can assign each member portions from 0.5 to 2.0 in 0.25 steps.
- A grouped batch is cooked once and sums all occurrence portions.
- Attendance is stored per member, date and meal; servings and shopping scale
  follow the people who are actually attending.
- Recipes carry optional breakfast/lunch/dinner/snack tags in the backend. An
  untagged recipe remains saved but is visibly excluded from planning until
  tagged.
- Recipes can also carry a side tag. Breakfast, lunch and dinner batches accept
  added recipes tagged side or snack; snack batches accept only additional
  snacks. Added components inherit the main batch's dates and participants.
- Changing a main recipe or an added component re-quantifies fixed recipes
  across the whole plan in quarter-serving increments before acceptance.
- Allocations beyond 48 hours require an acknowledgement; freezing is not
  modelled.
- Optional ingredients default to excluded until explicitly included.
- Pantry reservations and transactions are separate; acceptance does not
  pretend food has already been consumed.
- Complete publisher-reported or ingredient-calculated per-serving nutrition is
  admitted to automatic planning with its source and dataset snapshot retained.
- Shopping quantities marked “to taste/already stocked” can be excluded from
  shopping; unresolved quantities return an actionable recipe-review link.
- Food records and private corrections are household-scoped where appropriate;
  recipes and pantry lots cannot link to another household's private record.
- Open Food Facts access is read-only, on-demand, rate-limited locally, and
  recoverable when the external service is unavailable; transient failures are
  retried and successful searches are cached briefly.
- FoodData Central general-food search requires a private USDA API key, which an
  owner can save encrypted under System settings; missing or exhausted
  credentials are reported instead of appearing as empty results.
- Great British Chefs discovery is disabled; Good Food and Allrecipes are active.

## Validation completed

- 156 backend tests and 67 frontend tests pass.
- The production frontend build and PWA manifest build pass.
- Docker Desktop smoke test passed for the rebuilt Compose stack (PostgreSQL,
  Redis, web, worker and scheduler), including migrations, readiness, live
  PWA serving, owner setup, and a database-backed household member query.

## External work required by the operator

- Review the licence/attribution terms of any bulk food dataset the operator
  chooses to load; the repository does not redistribute dataset contents.
- Supply HTTPS if live phone-camera scanning is required on the LAN. Photo and
  typed-barcode fallbacks work without camera permission.
- Maintain source adapters when publishers change public markup or access rules.
- Add the real Unraid hostname/IP to `ALLOWED_HOSTS`.
- Schedule the documented nightly backup command.
- Keep Docker Desktop's CLI directory available on the operator's PATH, or use
  Docker Desktop directly; the Compose stack itself is ready for an Unraid
  deployment after the production `.env` values are supplied.

## Later, intentionally excluded

- Budget optimisation and the separate larger pricing idea.
- Equipment and active-cooking-time constraints.
- Specialist medical populations.
- Freezing workflows.
- Native mobile clients.
- One-way Mealie export and optional tool-restricted OpenClaw extraction bridge.

Those items do not block the household planning loop above and should be added
as separate migrations/features rather than weakening current provenance or
nutrition rules.

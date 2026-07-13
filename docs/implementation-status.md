# Implementation status — 13 July 2026

This file connects the product specification to the first runnable release.

## End-to-end path now available

1. Deploy the five-service Compose stack and create the owner.
2. Choose calorie or macro targets and a hard tolerance during onboarding.
3. Add a custom recipe or search/import a publisher recipe.
4. Review serving yield and detected ingredient amounts/units.
5. Use complete per-serving nutrition reported by the recipe website and mark
   the recipe planner-ready.
7. Select who attends each meal and when each meal gets a new cooked batch.
8. Generate a multi-day plan from meal-tagged, planner-ready recipes.
9. Review daily calories/macros, collapse days, swap a whole cooked batch, and
   accept it atomically while reserving pantry stock and building shopping.
10. Use the generated shopping list online or from its local offline copy.
11. Explicitly add checked purchases to the pantry.
12. Mark a cooked batch to consume its reservations.

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
- Allocations beyond 48 hours require an acknowledgement; freezing is not
  modelled.
- Optional ingredients default to excluded until explicitly included.
- Pantry reservations and transactions are separate; acceptance does not
  pretend food has already been consumed.
- Complete publisher-reported per-serving nutrition is attributed to its website
  and is the only nutrition source admitted to automatic planning.
- Shopping quantities marked “to taste/already stocked” can be excluded from
  shopping; unresolved quantities return an actionable recipe-review link.
- Ingredient-to-food matching and calculated nutrition are parked.
- Great British Chefs discovery is disabled; Good Food and Allrecipes are active.

## Validation completed

- 50 backend tests and 21 frontend tests pass.
- The production frontend build and PWA manifest build pass.
- Docker Desktop smoke test passed for the rebuilt Compose stack (PostgreSQL,
  Redis, web, worker and scheduler), including migrations, readiness, live
  PWA serving, owner setup, and a database-backed household member query.

## External work required by the operator

- Supply legal food datasets; they are not redistributed in this repository.
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

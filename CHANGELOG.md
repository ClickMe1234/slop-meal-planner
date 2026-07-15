# Changelog

Every pull request that changes the application release updates `VERSION` and
adds an entry here. Versions follow Semantic Versioning.

## 0.4.0 - 2026-07-15

- Parse ingredient names with a local NLP model so preparation adjectives and comma-separated descriptors do not replace the ingredient itself.
- Treat descriptive measures such as handfuls and sprigs as quantities, retain confidence metadata, and route uncertain results through recipe review.
- Reparse existing URL imports during migration while preserving user overrides and leaving active shopping lists unchanged until an explicit rebuild.
- Let shoppers edit ingredient names inline and remember generated-item corrections for the whole household.
- Queue name edits offline and require an explicit resolution if another device changed the same name before synchronisation.

## 0.3.0 - 2026-07-14

- Redesign the application shell and primary workflows for responsive desktop and mobile use.
- Add touch-friendly, safe-area-aware navigation and retain every page action on small screens.
- Reflow meal attendance and cooking-day grids into labelled mobile cards without horizontal scrolling.
- Improve responsive layouts across weekly planning, recipes, pantry, shopping, settings, and modals.

## 0.2.0 - 2026-07-13

- Add up to two side or snack selections per cooking batch.
- Rebalance main and side servings together against calorie and macro targets.
- Include attached batch components in summaries, shopping, pantry, and cooking flows.
- Add the `side` recipe tag and batch-side database migration.

## 0.1.0

- Initial application release.

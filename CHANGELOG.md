# Changelog

Every pull request that changes the application release updates `VERSION` and
adds an entry here. Versions follow Semantic Versioning.

## 0.10.0 - 2026-07-23

- Guide new households through API-key setup, nutritional targets, household members, and meal allocations during onboarding.
- Add calorie-boost days with meal-specific sliders so extra calories can be distributed across selected meals and reflected in planned portions.
- Add guest days with meal-specific attendance, scale cooking batches using the largest household serving, and show each guest as a separate serving row.
- Show selected-day portion weights in the week view, including calorie-boosted household servings and per-guest gram guidance.

## 0.9.2 - 2026-07-22

- Keep the current Discover query, filters, results and scroll position in place while imported recipe ingredients are corrected in a contextual review drawer.
- Preserve the existing full-page ingredient review for direct links, saved-recipe editing, Planning and Shopping flows.
- Keep saved household ingredients visible and filter them immediately while ingredient searches are edited or submitted, including libraries larger than one API page.
- Preserve Open Food Facts product images through saved ingredients so packaged foods can display their image when used by the meal planner.

## 0.9.1 - 2026-07-22

- Make the sidebar sign-out control visible and reliable in dark mode, including when the server logout request fails.
- Rename the saved-recipe action from "Edit meal types" to "Edit recipe".
- Prepare backup and application-data bind mounts for the configured unprivileged runtime identity so in-app backups can write their verified archives.

## 0.9.0 - 2026-07-19

- Add a household Ingredients page with saved-food search, manual nutrition entry, barcode camera/photo/number scanning, and explicit packaged-product search through the public Open Food Facts read API.
- Add pantry quantities directly from ingredient results, including package-count conversion, expiry, use-soon, and always-stocked options linked to the selected nutrition record.
- Let saved ingredients become serving-sized breakfast, lunch, dinner, snack, or side candidates in meal planning without cluttering the normal Recipes page.
- Match custom-recipe ingredients to household or shared nutrition records and calculate complete per-serving calories and macros for planning.
- Integrate general-food search, packaged-product search, and barcode camera/photo/number lookup directly into each custom-recipe ingredient row.
- Show compact calories, carbohydrate, fat, and protein values on custom-recipe nutrition search results.
- Retry and briefly cache transient Open Food Facts searches, run USDA and Open Food Facts only after an explicit search, match multi-word USDA names regardless of word order, and report USDA configuration or quota failures explicitly.
- Add clear General and Packaged source selectors so ingredient searches can query USDA, Open Food Facts, or both from one Search action.
- Let household owners securely save an encrypted USDA API key in System settings, with contextual signup links and guidance when ingredient searches need one.
- Normalise surrounding and repeated whitespace in ingredient searches, and only show packaged-food empty states after an explicit packaged search.
- Keep household nutrition corrections private, preserve source attribution, enforce household record access, and degrade cleanly when remote product services are unavailable.

## 0.8.1 - 2026-07-18

- Recover from stale browser CSRF tokens when saving recipe meal types and other protected changes.

## 0.8.0 - 2026-07-18

- Add pantry sorting, item editing and deletion, and batch deletion.
- Add automatic low-stock indicators, manual use-soon flags, and dark-mode-safe destructive controls.
- Link shopping-list ingredients to pantry stock with exact and user-confirmed fuzzy matches, including rejection, matched-item details, and undo.
- Flag incompatible shopping-list and pantry units for user review instead of assuming an unsafe conversion.

## 0.7.0 - 2026-07-17

- Record and edit the finished weight of a cooked meal batch from the week screen.
- Calculate rounded gram portions from each household member's planned fractional serving allocation.
- Show member-specific portion guidance when household calorie requirements differ.

## 0.6.0 - 2026-07-17

- Add a unified recipe-category catalogue for BBC Good Food and Allrecipes, with match-any filtering for up to three categories across discovery and saved recipes.
- Preserve and display publisher recipe tags, and safely backfill metadata for existing URL imports without changing reviewed recipe content.
- Keep category labels, aliases, rankings, and provider mappings in one registry so the taxonomy can be revised without redesigning search or storage.
- Harden the Alembic migration history for PostgreSQL and SQLite, including immutable historical schemas and automated upgrade, downgrade, replay, and model-parity checks.

## 0.5.0 - 2026-07-16

- Combine mass and volumetric recipe requirements using reviewed ingredient densities while keeping shopping-list and pantry calculations stable.
- Let shoppers display supported ingredients in grams, millilitres, tablespoons, teaspoons, or cups without changing the underlying quantity.
- Persist unit choices across shopping-list rebuilds and reconcile choices made while offline.
- Add reviewed density profiles for chia seeds and fresh, dried, and seed forms of coriander.

## 0.4.2 - 2026-07-15

- Calculate explicit ingredient arithmetic such as `2 x 55 g` package sizes and nested item counts instead of retaining only the multiplier.
- Convert unambiguous fractional item descriptions such as four chicken breast halves into two whole chicken breasts.
- Repair stale calculated quantities in existing URL imports at startup while leaving ordinary reviewed quantities unchanged.

## 0.4.1 - 2026-07-15

- Round shopping and pantry quantities according to their units, including whole metric amounts, culinary fractions, indivisible items, and two-decimal litre values.
- Apply the same policy to pantry stock, adjustments, reservations, and cooking deductions so stored balances match the displayed quantities.
- Normalise existing quantity data safely at startup and return human-readable quantity labels for the shopping, pantry, copy, share, download, and offline views.

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

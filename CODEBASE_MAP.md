# Slop Meal Planner codebase map

This is the orientation guide for developers and agents working in Slop Meal
Planner. It describes the repository as inspected on 15 August 2026, at
release 1.4.0. The source files and tests are authoritative when this guide
and an implementation disagree; update this document when a structural
change makes it misleading.

## What this project is

Slop is a private, self-hosted household meal-planning application. It turns
saved or imported recipes into nutrition-aware multi-day plans, accounts for
household attendance and preferences, reserves pantry stock, and produces a
shopping list that can be used offline.

The application is deliberately not an LLM recipe generator. Recipe text,
ingredient quantities, nutrition data, publisher metadata, and provenance come
from user input, supported public publisher pages, or named nutrition
providers. See [README.md](README.md) for the product narrative and the
complete release changelog.

The main mental model is:

    React PWA
        -> React Query and frontend/src/api/client.ts
        -> same-origin /api/v1 FastAPI API
        -> route modules -> domain services -> SQLAlchemy models
        -> SQLite in local development or PostgreSQL in deployment

    FastAPI and Celery worker
        -> Good Food / Allrecipes public pages
        -> USDA FoodData Central
        -> Open Food Facts
        -> Redis broker/result backend

An accepted plan is the point where the domains connect:

    planner-ready recipes
        -> generated plan
        -> review/edit/re-quantify
        -> atomic acceptance
        -> pantry reservations
        -> shopping-list build
        -> cook a batch
        -> pantry consumption and serving guidance

## Fastest route to understanding the repository

Read in this order:

1. This file for the architecture and invariants.
2. [README.md](README.md) for product intent, installation, screenshots,
   boundaries, and release history.
3. [frontend/src/App.tsx](frontend/src/App.tsx) for the route tree.
4. [frontend/src/api/client.ts](frontend/src/api/client.ts) for the browser
   API contract.
5. [backend/app/main.py](backend/app/main.py) for API assembly and middleware.
6. [backend/app/models.py](backend/app/models.py) and
   [backend/app/schemas.py](backend/app/schemas.py) for persisted and wire
   models.
7. The relevant route module, then the service it calls.
8. The nearest backend or frontend test before changing behavior.

For an environment or deployment question, jump directly to
[Configuration and runtime](#configuration-and-runtime) and
[Deployment and operations](#deployment-and-operations). For a schema change,
read [Database and migrations](#database-and-migrations) first.

## Product surface and implemented features

### Accounts, households, and preferences

- The first owner is created through setup-token-protected onboarding.
- Users authenticate with Argon2 password hashes and server-side sessions.
- A household can have an owner and collaborators; owner-only operations are
  enforced on the API.
- Household members are separate profiles from login users. Members can have
  their own nutrition targets, attendance, restrictions, and portions.
- Targets support calorie mode or macro mode, configurable hard tolerance,
  meal-level allocations, and calorie-mode macro minimum/maximum guardrails.
- Allergies, hard exclusions, dislikes, and preferred ingredients participate
  in plan eligibility and ranking.
- Users can choose UK or US ingredient vocabulary, summary or written method
  view, and source/metric/US measurement display.
- A household can save default meal groups, such as shared meals or separate
  recipes for different members. A particular plan can override those groups.

### Recipes and discovery

- Custom recipes use a draft-friendly live editor for both creation and later
  editing. Recipe-facing quantity/unit remains authoritative for shopping and
  pantry, while an explicitly confirmed, versioned nutrition mapping resolves
  package or count units against a matched food label.
- Recipes can be imported from a URL, with a persisted job and a review step.
- Supported live discovery sources are Good Food and Allrecipes. Search can
  filter by source and publisher category, rank by relevance and rating
  evidence, show thumbnails and publisher nutrition, and mark already-saved
  URLs.
- Generic URL import uses JSON-LD first and a constrained semantic HTML
  fallback. Imported values are retained for review rather than silently
  guessed.
- Imported recipes retain source URL, publisher, image/provenance metadata,
  publisher tags, source nutrition, ingredient text, optional ingredients,
  serving yield, and an immutable recipe-version snapshot.
- A recipe can be tagged for breakfast, lunch, dinner, snack, or side. A saved
  recipe without a usable meal tag or without complete nutrition remains in
  the library but is excluded from automatic planning.
- Ingredients are parsed with preparation descriptors, descriptive measures
  such as handfuls and sprigs, package expressions such as 2 x 55 g, nested
  item counts, and fractional item quantities. Low-confidence names and
  missing quantities are surfaced for review.
- Review lets a user confirm yield, meal tags, shopping-list names, included
  or optional ingredients, food matches, shopping exclusions, and quantities.
- The custom editor gets a side-effect-free nutrition preview from locally
  persisted food data. Missing matches or package/count conversions keep a
  revision a draft; only complete custom revisions synchronize ready/accepted
  plans and shopping state.
- Import review also exposes editable per-serving nutrition (with publisher
  values pre-filled when available); a complete set is persisted with the
  recipe version for planning, and an explicit source refresh can restore the
  publisher values after an accidental edit.
- Recipe changes can synchronize eligible current plans and shopping lists
  through the recipe-plan sync service.
- Recipes can have attributed publisher cooking methods or concise
  ingredient-flow summaries. Methods are stored as version snapshots, not
  mutable copies of the source page.

### Cooking methods

- A method can be explicitly fetched from a publisher page after the recipe is
  opened; discovery search itself does not fetch instructions.
- The parser turns ordered source blocks into stages and actions with semantic
  annotations for ingredients, actions, time, temperature, equipment, and
  doneness cues.
- The method view can scale quantities to a requested serving count or the
  authoritative planned batch.
- Users can drag an ingredient onto the exact source words that use it, correct
  labels and source ranges, group or separate actions, split long actions at a
  cursor, and reorder cooking stages with touch, mouse, or keyboard controls.
- The editor supports authored methods for custom recipes and refresh-preview
  plus apply-refresh for publisher recipes.
- A saved method is marked reviewed through the same save operation that
  persists edits. Unreviewed clauses remain visible and explain what needs
  attention.

### Ingredients, food records, and nutrition

- The Ingredients page searches the household food library and general
  nutrition records, accepts manual nutrition labels, and searches packaged
  foods explicitly.
- CoFID can be imported from a CSV as a reproducible local UK dataset.
- USDA FoodData Central is used for general-food search/cache when a private
  API key is available. The key can be stored encrypted per household in
  Settings -> System; a server-managed fallback is also supported.
- Open Food Facts is a read-only, on-demand packaged-food and barcode source.
  It requires no Open Food Facts account. Requests use an identifying user
  agent, conservative local rate limiting, caching, and recoverable failures.
- Barcodes can be entered manually, scanned from a photo, or scanned live from
  the camera over HTTPS. Only the decoded barcode is sent to the server.
- Saved household foods can retain private display names and nutrition
  corrections without changing the community source record.
- Saved foods can be enabled as planner choices, assigned meal tags, and given
  confirmed serving information.
- Package and label-serving descriptions are retained locally for explicit
  confirmation. Household product-and-unit conversion memories are append-only
  suggestions, never silently applied metadata; each recipe version retains an
  independent immutable mapping snapshot.
- Nutrition provenance, provider record IDs, dataset versions, assumptions,
  and ingredient contributions are persisted.
- Publisher-reported complete per-serving nutrition is authoritative for URL
  imports. Custom recipes can use a complete calculation when every included
  ingredient has a compatible complete food record.

### Planning and the week

- The Plan flow collects dates, selected members, meal slots, attendance,
  meal groups, special days, cook days, guest attendance, calorie boosts,
  must-use ingredients, preferred ingredients, and excluded ingredients.
- The planner chooses a recipe and per-person portion for every shared recipe
  group using hard nutrition bounds and soft preference/variety objectives.
- Portion choices are 0.5 to 2.0 servings in quarter-serving increments. A
  calorie boost can extend the allowed range when its target requires it.
- A group shares a recipe but members can receive different portions. Guests
  attach to a selected meal group and scale the shared batch.
- Cooked batches can cover multiple occurrences and leftovers. The UI warns
  when an allocation extends past the standard 48-hour leftover window.
- Up to two batch-wide side or snack components can be attached. Sides flow
  through plan summaries, shopping, pantry reservations, and cooking.
- Generation returns explicit infeasibility diagnostics and actionable review
  links. It does not silently relax hard target tolerance.
- A ready plan can be reviewed by day, replaced by whole-batch recipe, edited
  while preserving valid recipes, regrouped, re-quantified, and accepted.
- The Week view shows planned meals, batch/leftover relationships, per-person
  portions, guests, daily nutrition, calorie boosts, and serving guidance.
- Marking a batch cooked consumes its reserved pantry stock. A cooked batch can
  store total cooked weight so the UI can give weight-based portions.

### Pantry and shopping

- Pantry lots have quantities, normalized units, optional expiry, use-soon,
  always-stocked flags, food matches, reservations, and transaction history.
- Accepted plans reserve compatible pantry stock in expiry-first order. A
  shortage is bought; a unit conflict is surfaced for explicit review.
- Shopping builds from accepted plan recipe ingredients, subtracts plan
  reservations and usable pantry stock, and preserves recipe-level source
  provenance.
- Exact required quantity is kept separately from practical purchase quantity.
  Countable units round up; metric units, culinary fractions, and litre values
  use unit-specific rules.
- Generated names can be edited inline. Corrections are remembered for the
  household; manual shopping items remain manual.
- Shopping supports checked-state persistence, manual items, rebuild-safe
  active lists, recipe/source detail, unit changes, and manual combining.
- Fuzzy pantry matching proposes likely matches. Match, reject, undo, buy, and
  use decisions are explicit and version-checked.
- The shopping list is available offline on the device. Offline name changes
  queue in IndexedDB, fall back to localStorage where necessary, and expose
  conflicts when another device changed the same item.
- The list can use the platform share sheet, clipboard copy, or plain-text
  export.

### Operations and interface

- The frontend is a responsive installable React PWA with mobile navigation,
  safe-area support, touch-friendly controls, and system/light/dark themes.
- Demo mode is the default when VITE_DEMO_MODE is omitted. It uses seeded
  frontend data and does not need an account, database, or API keys.
- Live mode is enabled by setting VITE_DEMO_MODE to exactly false. In local
  development Vite proxies /api to localhost:8000; in production the built
  frontend is served same-origin by FastAPI.
- Docker Compose supports web, worker, scheduler, PostgreSQL, Redis, and
  maintenance backup/restore roles.
- The production image also supports the Unraid WebGUI deployment contract.
- Alembic migrations, verified backups/restores, health endpoints, CI tests,
  dependency audits, production builds, and container scans are part of the
  maintained surface.

### Deliberate boundaries

The following are intentional product decisions, not missing implementation
tasks:

- No LLM generation of recipes, ingredients, missing quantities, or nutrition.
- Open Food Facts is read-only and on-demand; Slop does not upload corrections,
  bulk mirror the database, or copy product images.
- Great British Chefs is present as a disabled adapter and is not enabled in
  the default source registry.
- Publisher access controls are not bypassed: no login, challenge solving,
  identity rotation, or undocumented private API use.
- There is no medical, paediatric, pregnancy, therapeutic-diet, budget,
  equipment, active-cooking-time, freezing, hosted multi-tenant, public
  internet, native mobile, or Google Keep integration.
- Mealie export and the tool-restricted OpenClaw bridge remain excluded.

## Repository map

| Path | Purpose |
| --- | --- |
| [AGENTS.md](AGENTS.md) | Instructions for coding agents, especially UI consistency, accessibility, responsive checks, and test expectations. |
| [README.md](README.md) | Public product overview, installation, feature list, screenshots, nutrition notes, validation history, and boundaries. |
| [CODEBASE_MAP.md](CODEBASE_MAP.md) | This developer/agent orientation guide. |
| [CHANGELOG.md](CHANGELOG.md) | Full release history. |
| [VERSION](VERSION) | Release version used by packaging and container workflows. |
| [Makefile](Makefile) | Compose shortcuts for build, lifecycle, migration, backup, restore, tests, and config validation. |
| [Dockerfile](Dockerfile) | Multi-stage production image: frontend build, Python environment, runtime files, and healthcheck. |
| [.github/workflows/](.github/workflows/) | CI, container publishing, and dev-image workflows. |
| [backend/](backend/) | FastAPI service, domain model, migrations, scripts, and pytest suite. |
| [frontend/](frontend/) | Vite/React/TypeScript PWA, API client, pages, browser persistence, and Vitest suite. |
| [deploy/](deploy/) | Compose stack, Unraid template, container launcher, and backup/restore scripts. |
| [docs/](docs/) | Product research, implementation status, migration safety, testing notes, category research, and visual assets. |

## Technology and dependency map

### Backend

The backend is Python 3.12+, FastAPI, SQLAlchemy 2, Alembic, Pydantic
Settings, psycopg, httpx, Argon2, cryptography/Fernet,
ingredient-parser-nlp, and recipe-scrapers. Celery plus Redis are the optional
worker/runtime dependencies used by production and live URL imports. Pytest,
pytest-cov, and pip-audit are development dependencies. The optional planner
extra in backend/pyproject.toml exists for compatibility with earlier planning
experiments; the current planner service uses its own deterministic search and
does not require an external solver.

The locked files backend/requirements.lock and
backend/requirements-dev.lock are used by CI/container installation. Change
backend/pyproject.toml first, then regenerate or update the appropriate lock
file through the project’s dependency workflow rather than hand-editing only
one side.

### Frontend

The frontend is React 19 with TypeScript 5.7, Vite 6, React Router, TanStack
React Query 5, Lucide icons, dnd-kit, ZXing browser/library, and
vite-plugin-pwa. Vitest, React Testing Library, user-event, jsdom, and
jest-dom support tests. package.json is the script/dependency boundary;
frontend/vite.config.ts owns the dev API proxy, PWA manifest/service worker,
image cache policy, and test environment. The tsconfig files split app and
Vite/node compilation.

The browser wire types intentionally allow API decimals as number or string.
Do not assume every SQLAlchemy Numeric value is serialized as a JavaScript
number; use the existing mapping/display helpers.

Generated or local-only directories are not source of truth:

- frontend/dist is build output and is regenerated by npm run build.
- frontend/node_modules, backend virtual environments, caches, coverage, local
  databases, deploy/.runtime, and deploy/backups are ignored.
- Do not edit generated TypeScript build-info files or bundled assets.

## Backend architecture

### Application assembly

[backend/app/main.py](backend/app/main.py) creates the FastAPI application and
mounts every API router under /api/v1. It also:

- installs TrustedHostMiddleware from MEAL_PLANNER_ALLOWED_HOSTS;
- bounds request bodies with RequestSizeLimitMiddleware;
- sends security headers including CSP, HSTS when enabled, frame protection,
  no-sniff, referrer policy, and a restrictive Permissions-Policy;
- disables API caching with Cache-Control: no-store;
- converts DomainError and Pydantic validation errors into
  application/problem+json responses;
- serves frontend/dist as an SPA when FRONTEND_DIST_DIR is configured;
- exposes /api/v1/health/live and /api/v1/health/ready.

Readiness checks the database and every configured Redis endpoint. Redis is
optional only when no Redis URL is configured, which is useful for local
SQLite-only API work.

[backend/app/db.py](backend/app/db.py) owns the SQLAlchemy engine, declarative
Base, session factory, and FastAPI database dependency. SQLite enables
check_same_thread handling for local tests/development; production uses the
PostgreSQL URL configured by the launcher.

[backend/app/config.py](backend/app/config.py) is the Pydantic settings
boundary. It reads MEAL_PLANNER_ variables and an optional .env file. Keep
deployment-friendly URL parsing and secret validation in
[backend/app/deployment.py](backend/app/deployment.py), not in route code.

### Authentication and authorization

[backend/app/auth.py](backend/app/auth.py) is the common dependency layer:

- passwords are hashed and verified with Argon2;
- the raw mp_session cookie is HttpOnly, SameSite=Lax, and optionally Secure;
- only a SHA-256 token hash is stored in UserSession;
- each session has a separately hashed CSRF token;
- state-changing browser requests use X-CSRF-Token;
- sessions expire and persistent sessions are renewed through /auth/me;
- login is rate-limited by source and account and uses a dummy hash path for
  unknown users;
- require_owner adds the owner role check.

Every route obtains an AuthContext, then scopes queries to the current
household. Do not accept a household ID from the browser as an authorization
boundary.

### API route index

All paths below are relative to /api/v1. GET-style reads normally use
get_auth_context. Mutations normally use require_csrf. A route called out as
owner-only uses require_owner.

| Module | Endpoints | Responsibility |
| --- | --- | --- |
| [auth_routes.py](backend/app/routes/auth_routes.py) | GET /auth/setup-status; POST /auth/setup, /auth/login, /auth/logout, /auth/change-password; GET/PATCH /auth/me; GET /auth/csrf; GET/POST /auth/users; DELETE /auth/users/{user_id} | Setup, sessions, preferences, password changes, and collaborator accounts. |
| [household_routes.py](backend/app/routes/household_routes.py) | GET /households/current; GET/PUT /households/current/meal-group-defaults; GET/POST /household-members; PATCH /household-members/{member_id}; GET /household-members/targets; GET/PUT /household-members/{member_id}/target; GET/POST/DELETE /household-members/{member_id}/restrictions... | Household metadata, member profiles, meal-group defaults, targets, allocations, and restrictions. |
| [recipe_routes.py](backend/app/routes/recipe_routes.py) | GET /recipes, /recipes/{recipe_id}, /recipe-ingredients, /foods, /jobs/{job_id}; POST /recipes, /recipes/nutrition-preview, /recipes/{recipe_id}/calculate, /recipe-imports, /foods; PUT /recipes/{recipe_id}, /recipes/{recipe_id}/review; DELETE /recipes/{recipe_id} | Recipe collection, side-effect-free custom nutrition previews and draft saves, publisher-import review, versioned calculations, jobs, general food search, and owner-only food records. |
| [discovery_routes.py](backend/app/routes/discovery_routes.py) | GET /recipe-discovery, /recipe-discovery/categories, /recipe-discovery/nutrition-preview, /recipe-discovery/image | Supported publisher search, category catalogue, cached nutrition preview, and authenticated image proxy. |
| [recipe_method_routes.py](backend/app/routes/recipe_method_routes.py) | POST/GET /recipe-discovery/method-previews and POST .../{preview_token}/save; GET/POST/PUT /recipes/{recipe_id}/method...; POST method/extract, method/refresh-preview, method/refresh | Explicit method extraction, ephemeral preview tokens, method snapshots, editing, review, scaling, and refresh. |
| [food_routes.py](backend/app/routes/food_routes.py) | GET /food-lookups/barcode/{barcode}, /saved-foods; POST /food-lookups/search, /saved-foods; PATCH/DELETE /saved-foods/{saved_food_id} | Open Food Facts lookup, packaged-food search, and household saved-food library. |
| [planning_routes.py](backend/app/routes/planning_routes.py) | POST /meal-plans/generate, /meal-plans/{plan_id}/accept, /meal-plans/{plan_id}/batches/{batch_id}/sides, .../cooked; GET /meal-plans, /meal-plans/{plan_id}; PUT /meal-plans/{plan_id}/preserving-edit and .../occurrences/{occurrence_id}/recipe; DELETE .../{side_batch_id}/sides; PATCH .../cooked-weight; DELETE .../cooked | Plan generation, retrieval, recipe-preserving edit, regrouping, recipe replacement, sides, acceptance, cooking, and cooked weight. |
| [pantry_shopping_routes.py](backend/app/routes/pantry_shopping_routes.py) | GET/POST/PATCH/DELETE /pantry-items...; POST /pantry-items/{lot_id}/adjust, /pantry-items/batch-delete; GET /shopping-lists/active and .../items/{item_id}/sources; POST /shopping-lists/build, items, pantry-match, pantry-review, ingredient-change; PATCH shopping items; PUT item names; POST add-purchased-to-pantry | Pantry lots and balances, shopping-list construction, sources, unit/name changes, fuzzy match review, and purchased-item intake. |
| [system_routes.py](backend/app/routes/system_routes.py) | GET/POST /system/backups; GET /system/restores; POST /system/restores/preview and /system/restores; GET/PUT/DELETE /system/integrations/usda | Backup status/creation, owner-only selective restore, and encrypted USDA credentials. |

The exact decorator definitions are the definitive API contract. OpenAPI is
disabled by default; set public API docs intentionally through configuration if
you need /api/docs or /api/openapi.json.

### Errors and concurrency

[backend/app/errors.py](backend/app/errors.py) defines DomainError,
ConflictError, and NotFoundError. The response shape includes:

- code and human detail;
- status and trace_id;
- field_errors for request validation;
- actions containing review links or repair instructions;
- issues containing structured nutrition violations.

Mutable records use version fields and compare-and-set payloads. Look for
expected_version, expected_plan_version, and expected_list_version in schemas
and routes. A stale mutation must return a conflict and leave the caller able
to reload; do not silently overwrite another household device's change.

### Domain model

[backend/app/models.py](backend/app/models.py) is the relational source of
truth. Most entities use UUID-like string IDs. AuditMixin adds created_at,
updated_at, and version for optimistic concurrency.

| Domain | Models/tables | Key relationships |
| --- | --- | --- |
| Identity | Household, User, UserSession, IntegrationCredential | Users and encrypted provider credentials belong to a household; sessions belong to users. |
| Names and household rules | IngredientNameEquivalent, IngredientNameOverride, HouseholdMember, HouseholdMealGroupAssignment, TargetProfile, MealAllocation, Restriction | Members carry targets/rules; name overrides are household-wide; meal groups map members to a meal type. |
| Recipes | Recipe, RecipeMealType, RecipePublisherTag, RecipeVersion, RecipeIngredient, RecipeMethodSnapshot | Recipe is the current library identity; versions preserve title, tag, ingredient, and method snapshots, including confirmed nutrition-unit mappings. Recipe-level tags remain the last complete planner-safe choice while an incomplete custom draft is edited. |
| Food and nutrition | FoodRecord, FoodNutrient, SavedFood, FoodAlias, HouseholdFoodUnitConversion, NutritionCalculation | Food records retain provider/dataset provenance; saved foods make them household choices; append-only household product/unit mappings are reusable suggestions; calculations record contributions and assumptions. |
| Async work | Job | Import jobs belong to a household/user and carry status, stage, progress, result, and errors. |
| Plans | MealPlan, MealBatch, MealOccurrence, PortionAllocation | A plan contains occurrences; occurrences reference batches; batches reference recipe versions; allocations map members to portions. |
| Pantry | PantryLot, PantryTransaction, PantryReservation | Lot balance is initial quantity plus movements minus reservations; accepted plan batches reserve lots. |
| Shopping | ShoppingList, ShoppingItem | A list belongs to a plan or household; generated items retain exact/purchase quantities, source ingredients, name keys, and match conflicts. |

Important enum/state values live near the top of models.py:

- RecipeEligibility: draft, needs_review, planner_ready, archived.
- JobStatus: queued, running, awaiting_review, succeeded, failed, cancelled.
- PlanStatus: draft, generating, ready, accepted, superseded.
- RecipeMethodStatus: needs_review, reviewed.
- MealType: breakfast, lunch, dinner, snack; RecipeTag also includes side.

Recipe versioning is distinct from Recipe.version. Recipe.version is the
optimistic concurrency counter for the library identity. RecipeVersion is an
immutable content snapshot used by plans and calculations. A plan batch points
at a recipe version so historical meals do not change when a recipe is edited.

### Backend services

Route handlers own HTTP validation, authorization, transaction boundaries, and
response shaping. Reusable domain rules belong in services.

| Service | Role |
| --- | --- |
| [planner.py](backend/app/services/planner.py) | Candidate selection, target bounds, quarter-serving choices, preference/variety scoring, infeasibility diagnostics, and fixed-plan portion rebalancing. |
| [nutrition.py](backend/app/services/nutrition.py) | Shared Decimal resolver for preview and persisted calculations, explicit package/serving/manual mapping options, publisher-nutrition validation, contribution/provenance snapshots, and planner values. |
| [recipe_versions.py](backend/app/services/recipe_versions.py) | Chooses editable versus planner-safe complete custom revisions, and allocates version numbers around plan-only shopping snapshots. |
| [ingredients.py](backend/app/services/ingredients.py) | NLP ingredient parsing, fractions, descriptive units, package arithmetic, preparation extraction, confidence, and review flags. |
| [quantities.py](backend/app/services/quantities.py) | Canonical unit aliases, storage/display precision, countable-unit rounding, culinary fraction formatting, and purchase round-up. |
| [measurement_conversion.py](backend/app/services/measurement_conversion.py) | Reviewed ingredient density profiles and safe mass/volume conversion. It never invents density for an unknown ingredient. |
| [shopping.py](backend/app/services/shopping.py) | Aggregates plan recipe requirements, subtracts reservations and pantry stock, records source ingredients, detects conflicts, and creates practical purchase amounts. |
| [pantry.py](backend/app/services/pantry.py) | Computes on-hand/reserved/usable balances, records adjustments, and reserves accepted batches FEFO. |
| [pantry_matching.py](backend/app/services/pantry_matching.py) | Similarity candidates for shopping-to-pantry matching; broad matches require user confirmation. |
| [recipe_plan_sync.py](backend/app/services/recipe_plan_sync.py) | Clones changed recipe versions into mutable current plans and rebuilds linked shopping state safely. |
| [recipe_methods.py](backend/app/services/recipe_methods.py) | Parses source instructions into method documents, snapshots, bindings, scaling, and rendered blocks. |
| [regional_ingredients.py](backend/app/services/regional_ingredients.py) | UK/US equivalents, query expansion, canonical ingredient keys, and displayed vocabulary. |
| [ingredient_names.py](backend/app/services/ingredient_names.py) | Stable name keys, household display-name overrides, and reapplication of saved corrections. |
| [saved_foods.py](backend/app/services/saved_foods.py) | Household food access, provider record persistence, manual records, planner-food synchronization, and saved-food version checks. |
| [food_search.py](backend/app/services/food_search.py) | USDA query normalization, cache/fetch behavior, API-key handling, cooldowns, and remote failure translation. |
| [open_food_facts.py](backend/app/services/open_food_facts.py) | Barcode/search requests, response normalization, cache, local request limits, and provider error classes. |
| [integration_credentials.py](backend/app/services/integration_credentials.py) | Fernet-encrypted household credentials and effective USDA-key selection. Preserve MEAL_PLANNER_SECRET_KEY permanently. |
| [backups.py](backend/app/services/backups.py) | API-facing backup status and serialized backup execution with a process lock. |
| [selective_restore.py](backend/app/services/selective_restore.py) | Archive resolution/checksum verification, temporary database migration, household-scoped component import, ID remapping, and idempotent merge. |
| [ingredient_reparse.py](backend/app/services/ingredient_reparse.py) | Reprocesses stale imported ingredients while preserving explicit user name overrides and flagging active shopping rebuilds. |
| [quantity_normalization.py](backend/app/services/quantity_normalization.py) | One-time/idempotent repair of stored pantry and shopping quantities after quantity rules evolve. |

#### Planner algorithm in one paragraph

planner-ready recipe versions become RecipeCandidate values with complete
nutrition. choose_shared_recipe tries each candidate and each allowed quarter
portion for every participant, rejects candidates outside hard bounds, and
scores closeness to allocated targets. Preferred food records and preferred
terms improve ranking; disliked terms and prior recipe use are soft penalties.
rebalance_plan_portions performs a deterministic coordinate search from several
starts for fixed plans, preferring a feasible result and then the lowest score.
This is intentionally deterministic and does not depend on a solver service.

#### Nutrition authority

For URL imports, planning_values and calculate_recipe use complete publisher
per-serving values first and never fall back to ingredient calculations. Custom
recipes use a complete persisted calculation snapshot. Their shared preview/
calculation resolver requires an explicit mapping for count/package units but
safely handles compatible mass/volume and reviewed-density conversions. All
calculated recipes require energy_kcal, protein_g, carbohydrate_g, and fat_g.

### Discovery boundary

The [backend/app/discovery/](backend/app/discovery/) package is deliberately
separate from recipe persistence:

- adapters/base.py defines the public-source adapter contract;
- adapters/allrecipes.py and adapters/good_food.py are enabled sources;
- adapters/great_british_chefs.py documents a disabled source;
- registry.py controls which adapters are active;
- search.py provides debounced/cancellable policy, per-source queries,
  category pages, caching, deduplication, and relevance/rating ranking;
- extraction.py parses recipe JSON-LD and limited semantic HTML;
- html.py parses anchors and embedded JSON;
- urls.py canonicalizes URLs and validates every fetch/redirect;
- http.py uses bounded polite fetching, ordinary cookie-aware retry, response
  size limits, TLS/address validation, and image-content checks;
- categories.py maps publisher taxonomy to stable application category keys;
- models.py and errors.py define the boundary data/error objects.

Search uses public returned markup only. Recipe-page imports and explicit method
fetches use different paths so search does not unexpectedly download
instructions. Never add a scraper behavior that bypasses publisher controls.
Read [backend/app/discovery/README.md](backend/app/discovery/README.md) before
touching an adapter.

### Nutrition data-import boundary

[backend/app/data_import/](backend/app/data_import/) normalizes external food
data into a provider-neutral contract:

- models.py: NutrientValue, NormalizedFood, DatasetProvenance, FoodDataBatch.
- providers/base.py: provider contract.
- providers/usda.py: FoodData Central normalization and key requirement.
- providers/open_food_facts.py: branded/barcode normalization.
- cofid.py: tolerant CoFID CSV column and nutrient parsing.
- persistence.py: transactional upsert of food records/nutrients.
- README.md: source licensing, dry-run, provenance, and update rules.

[backend/scripts/import_cofid.py](backend/scripts/import_cofid.py) is the
operator-facing import command. The maintenance scripts
reparse_ingredients.py and normalise_quantities.py are also run by the
production migration step after Alembic succeeds.

## Frontend architecture

### Bootstrap and routing

[frontend/src/main.tsx](frontend/src/main.tsx) creates one React Query client,
wraps the app in StrictMode, QueryClientProvider, and BrowserRouter, and
registers the service worker. Query defaults are a 30-second stale time, one
query retry, no refetch on window focus, and no mutation retries.

[frontend/src/App.tsx](frontend/src/App.tsx) owns the route tree and protected
session gate. In live mode it checks api.me, redirects unauthenticated users
to login, and forces temporary-password users through change-password.
Background locations allow import review to appear as a drawer while retaining
the underlying recipe catalogue.

| Path | Page/component | Purpose |
| --- | --- | --- |
| /login | AuthPages.LoginPage | Live login or local demo entry. |
| /setup | AuthPages.SetupPage | First owner and household creation from setup token. |
| /change-password | AuthPages.ChangePasswordPage | Required temporary-password replacement. |
| /onboarding | AuthPages.OnboardingPage | Initial household/member/target setup. |
| /week | WeekPage | Accepted-plan week view, cooking state, cooked weight, portions, and nutrition. |
| /plan | PlanPage | Multi-step plan generator and review. |
| /plan/:planId/edit | PlanEditPage | Recipe-preserving plan edit and meal-group regrouping. |
| /plan/:planId/occurrences/:occurrenceId/recipes | PlanRecipePickerPage | Replace a main occurrence recipe. |
| /plan/:planId/batches/:batchId/sides/:componentSlot/recipes | PlanRecipePickerPage | Choose a side/snack component. |
| /recipes | RecipesPage | Saved catalogue plus Good Food/Allrecipes discovery. |
| /recipes/new | CustomRecipeEditor.CustomRecipePage | Create a custom recipe with a live, unit-aware nutrition preview. |
| /recipes/:recipeId/edit | CustomRecipeEditor.CustomRecipeEditPage | Edit a custom recipe, including its immutable nutrition-unit conversion snapshots. |
| /recipes/import | ImportPages.RecipeImportPage | Start a URL import. |
| /imports/:jobId/review | ImportPages.ImportReviewPage or drawer | Poll an import job and review extracted recipe data. |
| /recipes/:recipeId/review | ImportPages.ImportReviewPage | Review an existing recipe directly. |
| /recipes/method-preview | MethodPage.MethodPreviewPage | Preview an explicit method fetched from a URL. |
| /recipes/:recipeId/method | MethodPage.MethodPage | Read, scale, annotate, reorder, edit, and review a method. |
| /ingredients | IngredientsPage | Household foods, general nutrition, packaged search, barcode, manual labels, and planner foods. |
| /pantry | PantryPage | Pantry lots, balances, adjustments, matching, flags, and bulk deletion. |
| /shopping | ShoppingPage | Offline-capable active list, checks, name edits, matches, sharing, export, rebuild, and pantry intake. |
| /shopping/:listId/items/:itemId | ShoppingIngredientPages.ShoppingItemDetailPage | Recipe-level sources for a generated shopping item. |
| /shopping/:listId/ingredient-change | ShoppingIngredientPages.ShoppingIngredientChangePage | Preview/apply linked unit changes and manual ingredient combining. |
| /settings | SettingsPage.HouseholdSettings | Members, collaborator access context, household settings, and password change. |
| /settings/targets | SettingsPage.TargetSettings | Per-member targets and meal allocations. |
| /settings/preferences | SettingsPage.PreferenceSettings | Vocabulary, method view, measurements, allergies, exclusions, dislikes, preferences. |
| /settings/appearance | SettingsPage.AppearanceSettings | System/light/dark theme. |
| /settings/data | SettingsPage.DataSettings | Backup status, backup creation, archive preview, selective restore. |
| /settings/system | SettingsPage.SystemSettings | USDA credential and provider/system status. |

[frontend/src/components/AppShell.tsx](frontend/src/components/AppShell.tsx)
provides the authenticated layout, desktop sidebar, mobile top bar and bottom
navigation, theme shortcut, account chip, skip link, and logout behavior.

### API client and browser state

[frontend/src/api/client.ts](frontend/src/api/client.ts) is the only normal
frontend transport boundary. It:

- prepends VITE_API_URL and /api/v1;
- sends same-origin credentials;
- obtains and caches the CSRF token in sessionStorage;
- adds X-CSRF-Token to unsafe methods;
- refreshes and retries once after CSRF_FAILED;
- parses problem+json into ApiError with actions and nutrition issues;
- exposes typed-ish request methods for every API feature;
- treats VITE_DEMO_MODE as live only when its value is exactly false.

The page components use React Query for server state. After a mutation,
invalidate or update the nearest query keys rather than keeping a second
uncoordinated server cache. The API client contains the canonical endpoint
paths; frontend types are the wire representation used by pages.

Demo data lives in [frontend/src/data/demo.ts](frontend/src/data/demo.ts) and
the small domain display types live in [frontend/src/types.ts](frontend/src/types.ts).
Demo data is presentation seed data, not a replacement for API behavior.

### Frontend feature modules

| Path | Responsibility |
| --- | --- |
| components/ui.tsx | Shared Button, Card, Badge, PageHeader, Notice, EmptyState, Loading, ProgressBar, Segmented, and related primitives. |
| components/Nutrition.tsx | Nutrition strips/cards and display helpers. |
| components/BarcodeScanner.tsx | Camera/photo/manual barcode UX using ZXing. |
| components/FoodSearchSources.tsx | Provider/source selection for food search. |
| components/MealTypePicker.tsx | Shared meal-tag selection. |
| components/RecipeRating.tsx | Publisher rating display. |
| components/UsdaKeyGuidance.tsx | Explanation/link for private USDA key setup. |
| hooks/useDebouncedValue.ts | Debounced search input behavior. |
| lib/safeUrls.ts | External URL validation before opening publisher links. |
| lib/theme.ts | System/light/dark persistence in localStorage. |
| lib/offlineShopping.ts | IndexedDB shopping cache, localStorage fallback, queued name mutations, and conflict context. |
| pages/planner.ts | Client-side planning wizard draft/group/boost/guest helpers and payload shaping. |
| pages/planEditDraft.ts | Plan-preserving-edit draft types and transformations. |
| pages/quantityDisplay.test.ts and pantrySorting.test.ts | Pure display/sorting behavior tests. |
| styles.css | Shared tokens, layout, states, responsive breakpoints, dark theme, PWA-safe spacing, and feature-specific styles. |

The visual language is intentionally shared: use the primitives in ui.tsx,
Lucide icons, and CSS variables in styles.css. The primary responsive
breakpoints are around 760px and 430px, with additional feature-specific
breakpoints. Keep flex/grid children shrinkable, action rows wrap, and
interactive targets usable at small heights.

### Frontend data flows by page

- RecipesPage queries saved recipes and remote discovery independently, then
  maps both into the catalogue card shape. Saving a remote result starts a
  job, polls it, opens review, and only becomes planner-ready after review.
- ImportPages owns the imported-recipe review form and preserves user corrections, including
  editable nutrition, in the review payload. Review validation blocks included
  shopping ingredients that have no amount/unit unless explicitly excluded.
- CustomRecipeEditor owns both new and existing custom recipes. It previews
  nutrition through POST /recipes/nutrition-preview using stable draft row IDs;
  recipe/shopping units remain distinct from explicitly confirmed g/ml food
  conversions, and incomplete revisions save as drafts without replacing a
  complete version in current plans.
- IngredientsPage composes local food records, USDA search, Open Food Facts,
  saved foods, manual labels, and BarcodeScanner; it maps provider failures to
  actionable notices.
- PlanPage builds a local wizard draft and submits one PlanGenerateRequest.
  It renders API actions/issues for infeasibility and allows recipe/side
  pickers to return to the plan.
- PlanEditPage turns the current detail into a preserving-edit payload. It
  carries meal_group_key through the draft so regrouping does not accidentally
  replace still-valid recipes.
- WeekPage reads the accepted plan and updates cooking/cooked-weight endpoints.
  Batch weight math is kept in exported pure helpers and tested separately.
- ShoppingPage keeps a server-backed active list plus an offline local copy.
  It reconciles queued name changes, detects online/offline transitions, and
  uses API versions for checked/unit/name mutations.
- MethodPage keeps an editable method document locally, saves with the recipe
  version as the concurrency guard, and reloads conflict data if another
  editor changed the recipe.
- SettingsPage splits settings into focused routes, with owner-only UI where
  the backend also enforces owner-only behavior.

## Key end-to-end flows

### First startup and login

1. The API starts with MEAL_PLANNER_DATABASE_URL, MEAL_PLANNER_SECRET_KEY, and
   MEAL_PLANNER_SETUP_TOKEN.
2. GET /auth/setup-status reports whether any user exists.
3. Setup validates the token, creates household/member/owner/user session, and
   returns a CSRF token.
4. Login creates a new UserSession, sets mp_session, and returns CSRF state.
5. Live protected routes call /auth/me. A stale or expired session redirects
   the frontend to /login.
6. Changing a temporary password clears the flag and revokes other sessions.

### URL recipe import

1. The browser canonicalizes/validates the submitted URL through the API.
2. POST /recipe-imports creates a Job and attempts to enqueue
   worker.process_recipe_import in Redis. If the worker is unavailable, the
   queued job remains inspectable and retryable.
3. The worker validates redirects, fetches bounded public HTML, extracts
   recipe JSON-LD/semantic fields, parses ingredients, stores publisher tags
   and a recipe-version snapshot, and sets the job to awaiting_review.
4. The review page polls GET /jobs/{job_id}, then loads GET /recipes/{id}.
5. PUT /recipes/{id}/review persists the corrected title/yield/tags,
   ingredients, and publisher nutrition values. Complete publisher nutrition
   remains authoritative for URL imports; imports never fall back to ingredient
   calculations.

### Live custom recipe editing

1. POST /recipes/nutrition-preview accepts stable draft-row IDs and only reads
   locally persisted food/nutrient data. It returns known totals, formulae,
   structured issues, and confirmable mapping choices without writing history
   or calculations.
2. A chosen mapping is stored alongside the recipe quantity/unit. Product
   metadata and household memory remain suggestions until explicitly confirmed.
3. PUT /recipes/{id} saves custom immutable versions even when incomplete.
   Only a complete calculated revision replaces a previous complete version in
   ready/accepted plans; a changed confirmed mapping is appended to household
   conversion history on save.

### Remote discovery

1. RecipesPage queries PostgreSQL saved recipes immediately.
2. After the debounced query, it calls /recipe-discovery with selected source
   and category filters.
3. LiveSearchService uses the enabled registry adapters concurrently, caches
   successful/error results for bounded TTLs, merges duplicate URLs, ranks
   relevance/rating evidence, and annotates saved URLs.
4. Selecting a card does not create a recipe until the user completes the
   save/review flow.

### Nutrition and ingredient matching

1. Imported or custom ingredient lines are parsed into quantity, unit, grams,
   food phrase, preparation, confidence, parser version, and review flags.
2. Household name keys and regional equivalence expand searches without losing
   the original text.
3. A food record can be matched from local CoFID/USDA/Open Food Facts/manual
   data. The match stays provider-attributed and household corrections remain
   private.
4. calculate_recipe either records complete publisher nutrition or sums the
   four required nutrients from matched records using compatible amounts.
5. NutritionCalculation stores contributions, dataset versions, assumptions,
   and per-serving values. Planner eligibility is updated only after the
   calculation succeeds.

### Plan generation, editing, and acceptance

1. PlanPage submits a date range and slots, member attendance, meal groups,
   special-day adjustments, guests, boosts, and ingredient guidance.
2. planning_routes validates dates, active members, targets, meal allocations,
   recipe tags, group uniqueness, cook-day topology, and side limits.
3. Candidate recipes are filtered to household recipes with the correct
   meal-tag, planner-ready nutrition, and restriction compatibility.
4. planner.choose_shared_recipe picks a feasible recipe and per-member
   quarter portion. Repeated recipes are allowed if constraints require them.
5. planning_routes creates MealPlan, MealBatch, MealOccurrence, and
   PortionAllocation records. Batches connect repeated leftovers and side
   component slots.
6. The review UI can replace a full batch, alter meal groups, add/remove sides,
   change cook days, or change dates/guests while preserving valid recipes.
7. POST /meal-plans/{id}/accept revalidates current restrictions/tags,
   atomically marks the plan accepted, supersedes the prior accepted plan, and
   reserves pantry stock.
8. The shopping build then reads the accepted batches and turns them into
   linked ShoppingItem rows.

### Cooking and serving

1. WeekPage loads the accepted plan and displays occurrences grouped by date,
   meal type, and meal group.
2. Marking a batch cooked creates pantry consumption movements for its
   reservations. Unmarking is guarded against invalid historical state.
3. Cooked weight can be stored on MealBatch. The frontend uses that weight and
   portion allocations to show practical serving weights.
4. The method page can be opened from Discover, saved recipes, or a planned
   batch and scales ingredient quantities to the authoritative context.

### Shopping/pantry loop

1. build_shopping_list aggregates every included recipe ingredient across
   accepted batches and attached components.
2. It normalizes units, groups by stable food/name keys, keeps recipe sources,
   subtracts reservations and usable pantry balances, and records incompatible
   pantry units as conflicts.
3. Generated shopping items store exact_quantity and purchase_quantity
   separately. Name edits may create a household name override.
4. A user can check items offline, rename offline, resolve pantry suggestions,
   change a linked unit through preview/apply, or manually combine items.
5. Purchased checked items can be explicitly added to pantry; this is never an
   implicit side effect of checking.

### Backup and selective restore

1. The owner starts a backup from Settings -> Data & backup or the maintenance
   role. The archive includes database.dump, data.tar.gz, manifest.txt, and
   SHA256SUMS.
2. Creation validates PostgreSQL archive readability and only renames the
   temporary .incomplete directory after checksums are written.
3. Selective restore first verifies all archive files, migrates a temporary
   copy of the source database, and previews available household/component
   counts.
4. The selected component merge remaps IDs and avoids importing sessions or
   encrypted integration credentials. Existing matching records remain.
5. Full restore is destructive and requires an explicit --confirm path with
   the application stopped. Read [deploy/README.md](deploy/README.md) before
   operating it.

## Configuration and runtime

### Local development

Backend dependencies require Python 3.12 or newer. Frontend dependencies use
Node 22 in CI. A typical live local setup is:

    python -m venv .venv
    .venv/bin/python -m pip install -e "backend[dev,workers]"
    cd backend
    export MEAL_PLANNER_DATABASE_URL=sqlite:///./meal_planner.db
    export MEAL_PLANNER_SETUP_TOKEN=development-setup-token
    export MEAL_PLANNER_SECRET_KEY=development-only-secret-change-this
    . ../.venv/bin/activate
    alembic -c alembic.ini upgrade head
    uvicorn app.main:app --reload

In a second shell:

    cd frontend
    npm ci
    VITE_DEMO_MODE=false npm run dev

Vite serves on port 5173 and proxies /api to port 8000. For UI-only work,
omit VITE_DEMO_MODE=false and use the seeded demo. The demo does not validate
the live API and is not a substitute for backend integration tests.

The Windows commands in [README.md](README.md) use
.\.venv\Scripts\python.exe and npm.cmd equivalents.

### Important environment variables

| Variable | Meaning |
| --- | --- |
| MEAL_PLANNER_DATABASE_URL | SQLAlchemy database URL; SQLite is the local default, PostgreSQL is the production contract. |
| MEAL_PLANNER_SECRET_KEY | Persistent Fernet/application secret. Rotating it makes encrypted integration credentials unreadable. |
| MEAL_PLANNER_SETUP_TOKEN | Secret required to create the first owner. |
| MEAL_PLANNER_ALLOWED_HOSTS | Comma-separated TrustedHost values. Include every hostname/proxy name used by household devices. |
| MEAL_PLANNER_COOKIE_SECURE | Set true when serving over HTTPS. |
| MEAL_PLANNER_HSTS_ENABLED | Enables HSTS; only use once HTTPS is correctly in place. |
| MEAL_PLANNER_TIMEZONE | Household/application timezone default. |
| MEAL_PLANNER_USDA_API_KEY | Optional server-level FoodData Central key. Household encrypted keys take precedence when set. |
| MEAL_PLANNER_REMOTE_FOOD_SEARCH_ENABLED | Enables USDA remote search/cache fallback. |
| MEAL_PLANNER_OPEN_FOOD_FACTS_ENABLED | Enables read-only packaged-food lookup. |
| MEAL_PLANNER_OPEN_FOOD_FACTS_TIMEOUT_SECONDS | Open Food Facts request timeout. |
| CELERY_BROKER_URL | Redis broker URL, normally logical database 0. |
| CELERY_RESULT_BACKEND | Redis result URL, normally logical database 1. Broker/result database indexes must differ. |
| FRONTEND_DIST_DIR | Built frontend directory served by FastAPI in the single-image deployment. |
| DATA_DIR and BACKUP_ROOT | Persistent application data and backup paths, normally /data and /backups in the image. |
| RUN_MIGRATIONS | Web-role control for whether the single web process runs the migration step. |
| CELERY_BEAT_SCHEDULE | Persistent scheduler file, normally /data/celerybeat-schedule. |

Production Unraid also accepts friendly POSTGRES_HOST/PORT/DB/USER/PASSWORD and
REDIS_HOST/PORT/USERNAME/PASSWORD/TLS/database fields. Full URL overrides win
over friendly fields. deployment.py validates ports, names, IPv6, credentials,
SSL modes, URL schemes, and minimum secret lengths before exporting the
application/backup environment.

### Production process model

The [Dockerfile](Dockerfile) builds:

1. a frontend stage with npm ci and npm run build;
2. a Python stage with locked backend dependencies;
3. a runtime image containing backend code, frontend/dist, PostgreSQL client
   utilities, backup/restore scripts, and a non-root runtime contract.

[deploy/docker/entrypoint.sh](deploy/docker/entrypoint.sh) creates/chowns
/data and /backups from PUID/PGID, then drops to that user.
[deploy/docker/launcher.py](deploy/docker/launcher.py) invokes
backend/app/runtime.py. The runtime:

- validates and normalizes deployment variables;
- waits up to 120 seconds for PostgreSQL and Redis;
- runs Alembic upgrade head, reparse_ingredients, and normalise_quantities
  once under a PostgreSQL advisory lock;
- in all mode supervises exactly one web process, one Celery worker, and one
  Celery Beat scheduler;
- terminates all children together if one exits or the container is stopped;
- supports standalone web, worker, scheduler, migrate, backup, and restore
  roles.

Do not run multiple scheduler instances for one installation. They would
duplicate scheduled cleanup and metadata-backfill work.

## Deployment and operations

### Compose

[deploy/compose.yaml](deploy/compose.yaml) defines:

- web: FastAPI plus built PWA, migrations enabled, port 8000;
- worker: Celery worker;
- scheduler: Celery Beat;
- postgres: PostgreSQL 17.10-bookworm baseline;
- redis: Redis 7.4.9-alpine baseline;
- backup and restore: maintenance-profile roles.

[deploy/.env.example](deploy/.env.example) is a template only. Copy it to
deploy/.env, replace every placeholder secret, validate with:

    docker compose --env-file deploy/.env -f deploy/compose.yaml config --quiet

The [Makefile](Makefile) wraps the common commands:

    make build
    make up
    make down
    make logs
    make ps
    make migrate
    make backup
    make test
    make config
    make restore BACKUP=daily/20260101-020000

### Unraid

Unraid is the primary documented production path. The application image runs
web, worker, and scheduler together; PostgreSQL and Redis are separate
containers. [deploy/unraid-template.xml](deploy/unraid-template.xml) is the
field contract and [deploy/README.md](deploy/README.md) explains:

- required ports/paths and persistent /data and /backups mounts;
- PostgreSQL/Redis friendly fields and full URL overrides;
- bridge-network choices and LAN exposure warnings;
- HTTPS, secure-cookie, HSTS, and allowed-host requirements;
- backup/restore, selective restore, upgrades, rollback, and troubleshooting.

Do not expose the application, PostgreSQL, or Redis ports through the router.
Use HTTPS or an authenticated private overlay for household access.

### Backups

[deploy/scripts/backup.sh](deploy/scripts/backup.sh) creates daily/weekly/
monthly timestamp directories, applies retention, runs pg_dump custom format,
tests pg_restore readability, archives /data, writes a manifest, and writes
checksums. [deploy/scripts/restore.sh](deploy/scripts/restore.sh) validates
paths, checksums, PostgreSQL readability, and tar safety before the destructive
database/data replacement. [deploy/scripts/restore-stack.sh](deploy/scripts/restore-stack.sh)
stops application services, invokes restore, and starts them only after success.

## Database and migrations

[backend/migrations/](backend/migrations/) is the authoritative, replayable
schema history. The current head is 0026_shopping_recipe_snapshots. There was
a historical two-branch 0020 around method flow tables and persistent sessions;
0021 reconciles the branches, followed by 0022-0026.

The high-level migration themes are:

- 0001 initial household, recipe, food, plan, pantry, and shopping schema;
- 0002-0007 meal tags, sides, regional names, ingredient parsing, measurements,
  and shopping display units;
- 0008-0013 publisher tags, cooked weights, use-soon, shopping/pantry keys,
  and rejected fuzzy matches;
- 0014-0018 saved foods, encrypted integration credentials, plan adjustments,
  unsafe URL quarantine, and recipe-linked shopping sources;
- 0019-0022 method snapshots/flow reconciliation, persistent sessions, and
  normalized method view;
- 0023 reusable household member meal groups;
- 0024 recipe-specific planner serving constraints;
- 0025 immutable recipe nutrition-conversion and meal-tag snapshots plus
  append-only household product/unit conversion memory.
- 0026 plan-only shopping snapshots, which preserve the newer editable draft.

Read [docs/database-migrations.md](docs/database-migrations.md) before editing
the schema. Required rules:

1. Historical migrations must not import live app models or Base metadata.
2. Use explicit Alembic operations and portable server defaults.
3. Preserve existing rows when adding required fields.
4. Test clean replay, representative upgrade paths, downgrade/replay, and
   alembic check/model parity.
5. Never regenerate 0001 from current SQLAlchemy models.

Useful commands from backend:

    alembic -c alembic.ini upgrade head
    alembic -c alembic.ini check
    alembic -c alembic.ini downgrade base
    alembic -c alembic.ini upgrade head

## Tests and CI

### Backend tests

Backend tests use pytest, fixtures in [backend/tests/conftest.py](backend/tests/conftest.py),
and both SQLite and PostgreSQL/migration paths where relevant.

| Test area | Files |
| --- | --- |
| Auth, sessions, configuration, health, runtime, security, deployment | test_auth_targets.py, test_config.py, test_health.py, test_runtime.py, test_security_controls.py, test_deployment.py, test_unraid_contract.py |
| Discovery, URL safety, extraction, categories, worker metadata | test_discovery_extract.py, test_discovery_search.py, test_discovery_urls.py, test_recipe_categories.py, test_worker_metadata.py |
| Food data and nutrition | test_data_import.py, test_food_search_resilience.py, test_nutrition.py, test_integration_credentials.py, test_saved_foods.py |
| Ingredient parsing and quantities | test_ingredients.py, test_ingredient_names.py, test_regional_ingredients.py, test_measurement_conversion.py, test_quantities.py |
| Recipes and methods | test_recipe_deletion.py, test_recipe_methods.py |
| Planning, pantry, shopping, and end-to-end loops | test_planner_shopping.py, test_planning_workflow.py, test_pantry_items.py, test_shopping_pantry_review.py, test_end_to_end.py |
| Migrations and restore | test_migrations.py, test_restore_validation.py, test_selective_restore.py |

The most valuable regression tests are the workflow tests because they verify
the boundaries between recipe versions, accepted plans, reservations,
shopping, and cooking. Add a focused unit test for a pure service rule and an
API/workflow test for a state transition.

### Frontend tests

Vitest runs in jsdom with React Testing Library and the shared setup in
frontend/src/test/setup.ts. Tests cover:

- App route/session/theme behavior;
- API CSRF recovery, login persistence, saved foods, and deletion;
- auth, import review, recipe catalogue, method editor, ingredients, pantry,
  plan wizard, preserving edit, picker, week, settings, and shopping pages;
- barcode scanner, food-source selector, meal-type picker, recipe rating;
- safe URLs, offline shopping, debouncing, planner helpers, quantity display,
  and pantry sorting.

Tests should assert behavior after a click or submit: route changes, visible
state, API call payloads, mutation results, or browser side effects. Presence
only tests are not sufficient for new controls.

### GitHub Actions

- .github/workflows/ci.yml runs backend migration replay/model parity, backend
  tests and pip audit, frontend npm ci/tests/build and npm audit, then a
  linux/amd64 container build and Trivy scan. Main and dev pushes plus pull
  requests are covered; main can create a release from VERSION.
- .github/workflows/container.yml verifies pull-request images and publishes
  immutable release/SHA or latest images to GHCR on main/release events.
- .github/workflows/dev.yml builds/publishes the dev image on the dev branch.
- `VERSION` is the release source of truth. A release bump keeps it aligned
  with the frontend and backend package versions, default API/user-agent
  versions, deployment image references, README, and CHANGELOG; the backend
  release-metadata test enforces that contract.

The expected local validation for a normal change is:

    cd backend
    python -m pytest
    cd ../frontend
    npm test
    npm run build

For schema or deployment changes, also run the relevant Alembic replay,
Compose config, deployment, restore, or container checks.

## Working safely in this codebase

### Add or change a user-facing feature

1. Find the nearest page and existing UI primitive.
2. Add or update the Pydantic request/response schema.
3. Add the route with household scoping, CSRF/owner dependency, version check,
   and a transaction boundary.
4. Put reusable domain rules in a service, not in a large route handler.
5. Add the matching api client method and frontend wire types.
6. Invalidate/update related React Query keys after mutation.
7. Cover the user behavior with the nearest backend/frontend test.
8. Check loading, duplicate-submit prevention, error, success, empty, and
   mobile states. Follow the UI requirements in AGENTS.md.

### Change recipe or nutrition behavior

Trace all downstream consumers before editing:

    RecipeVersion
        -> RecipeIngredient / NutritionCalculation
        -> MealBatch / MealOccurrence / PortionAllocation
        -> PantryReservation / PantryTransaction
        -> ShoppingItem.source_ingredients

Use recipe version cloning and recipe_plan_sync where needed. Do not mutate a
historical version referenced by an accepted plan.

### Change quantity or name behavior

Keep these concepts separate:

- original recipe text;
- parsed food phrase and preparation;
- canonical name keys;
- household display-name override;
- normalized storage unit;
- display unit;
- exact required quantity;
- rounded purchase quantity.

Changing one layer can affect pantry matching, reservations, shopping grouping,
offline conflict comparison, and existing plans. Add tests in quantities,
ingredient_names, measurement_conversion, planner_shopping, and/or
shopping_pantry_review as appropriate.

### Add a migration

Create one self-contained file in backend/migrations/versions with a unique
revision and correct down_revision. Use explicit historical table definitions,
not current model imports. Preserve old data and add a migration test for an
existing representative database. The production runtime will also run the
normalization scripts after upgrading, so make those scripts idempotent.

### Add a discovery adapter or provider

For a publisher, implement SourceAdapter behavior, add fixture HTML, test URL
canonicalization and failure behavior, and add the adapter to the registry
only when the source is permitted and stable enough. For a food provider,
normalize into the data_import models, retain source/dataset/license
provenance, distinguish missing values from zero, and test provider failures.

### Security and privacy invariants

- Keep the app private/self-hosted and require HTTPS for supported production
  access.
- Never log passwords, setup tokens, API keys, connection URLs, raw session
  tokens, or encrypted credential values.
- Preserve CSRF on all state-changing browser calls.
- Validate every fetched URL and redirect; defend against private/metadata
  address ranges and unsafe archive paths.
- Keep image fetching behind the authenticated proxy and validate content.
- Keep all queries household-scoped.
- Treat remote publisher/provider failure as a recoverable user-facing state,
  not as permission to guess or silently discard provenance.
- Preserve source content and publisher attribution when presenting methods.

## Reference documents

| Document | Use it for |
| --- | --- |
| [docs/product-discovery-and-research.md](docs/product-discovery-and-research.md) | Product reasoning, source constraints, nutrition research, domain decisions, and planned phases. |
| [docs/implementation-status.md](docs/implementation-status.md) | Historical end-to-end implementation checklist and known operator work. |
| [docs/database-migrations.md](docs/database-migrations.md) | Migration authoring and replay safety. |
| [docs/recipe-category-research.md](docs/recipe-category-research.md) | Publisher category mapping decisions. |
| [docs/testing-round-one-fixes.md](docs/testing-round-one-fixes.md) | Historical UI/product testing findings and fixes. |
| [backend/app/discovery/README.md](backend/app/discovery/README.md) | Scraper, URL, cache, attribution, and publisher boundary. |
| [backend/app/data_import/README.md](backend/app/data_import/README.md) | CoFID/provider import contract and provenance. |
| [deploy/README.md](deploy/README.md) | Unraid/Compose installation, backup, restore, networking, upgrades, and rollback. |

When the codebase feels inconsistent, start by checking whether the behavior
is a deliberate boundary recorded in one of these documents before “fixing”
it.

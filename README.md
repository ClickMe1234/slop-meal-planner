# Slop Meal Planner

Slop is a private, self-hosted household meal planner. It imports real
recipes, plans meals against per-person nutrition targets, reserves pantry
stock, and produces an offline-capable shopping list.

The production target is an Unraid server on a trusted LAN. The repository also
includes a demo mode so the complete responsive light/dark interface can be
evaluated without accounts, a database, or publisher access.

Current release: **0.6.0**. See [CHANGELOG.md](CHANGELOG.md) for the complete
release history.

## Implemented features

### Household and targets

- Owner and collaborator accounts with Argon2 password hashing, server-side
  sessions, CSRF protection, password changes, and account management.
- Multiple household member profiles with attendance recorded per person,
  date, and meal.
- Per-person calorie or macro targets with a user-defined hard tolerance.
  Calorie feasibility uses the 4/4/9 rule, and calorie mode can also enforce
  hard protein, carbohydrate, and fat minimums.
- Configurable meal-level target allocation across breakfast, lunch, dinner,
  and snacks.
- Saved allergies, exclusions, dislikes, and preferences that are applied to
  planning as household rules.
- British or American ingredient vocabulary, with equivalent names accepted in
  searches and the selected vocabulary used in recipes, pantry, and shopping.

### Recipes and discovery

- Versioned custom recipes and URL-imported recipes with source provenance.
  Publisher instructions are not copied into the application.
- Recipe review for serving yield, ingredient quantities, units, ambiguous
  parsing, and planner readiness. User corrections are preserved across later
  processing.
- Active Good Food and Allrecipes search adapters with source filters, stable
  thumbnails, publisher nutrition, publisher ratings/counts, relevance
  ranking, and saved-URL deduplication.
- Safe generic URL imports using JSON-LD first and a review-required semantic
  fallback.
- Meal tags for breakfast, lunch, dinner, snack, and side recipes. Untagged or
  unreviewed recipes remain saved but are excluded from automatic planning.
- Ingredient parsing that retains preparation descriptors, understands
  descriptive measures such as handfuls and sprigs, and routes low-confidence
  results to review.
- Explicit ingredient arithmetic, including package expressions such as
  `2 x 55 g`, nested item counts, and unambiguous fractional item descriptions.

### Nutrition and planning

- Automatic planning from recipes with complete publisher-reported per-serving
  calories, protein, carbohydrate, and fat. Nutrition provenance is retained.
- CoFID CSV ingestion plus USDA FoodData Central and Open Food Facts provider
  boundaries, with dataset version and source provenance retained for future
  catalogue and calculation work.
- Multi-day plans with per-person portions from 0.5 to 2.0 servings in
  quarter-serving increments.
- Shared cooked batches that can cover multiple meal occurrences, with an
  acknowledgement when an allocation extends beyond the 48-hour leftover
  window.
- Hard exclusions, must-use, preferred, and excluded ingredient guidance, plus
  explicit infeasibility errors and actionable review links.
- Plan review with daily per-person nutrition, collapsible days, whole-batch
  recipe replacement, and re-quantification before acceptance.
- Up to two batch-wide side or snack selections. Attached components flow
  through plan summaries, shopping, pantry reservations, and cooking.
- Atomic plan acceptance, pantry reservations, and separate consumption when a
  batch is marked cooked.

### Pantry and shopping

- Pantry inventory, adjustments, reservations, cooking deductions, and pantry
  subtraction from generated shopping requirements.
- Exact calculated requirements alongside practical unit-aware purchase
  quantities: whole countable items, culinary fractions, whole metric amounts,
  and two-decimal litre values are handled consistently in shopping and pantry
  balances.
- Manual shopping items, checked-state preservation, rebuild-safe active lists,
  and explicit confirmation when checked purchases are added to the pantry.
- Inline ingredient-name editing. Generated-name corrections are remembered
  for the household; manual items remain manual.
- Offline shopping storage with device sharing, queued offline name edits, and
  explicit conflict resolution when another device changed the same name.
- Platform share sheet, clipboard copy, and `.txt` export.

### Interface and operations

- Responsive installable React PWA with touch-friendly navigation, safe-area
  support, mobile planning cards, and system/light/dark themes.
- Demo mode for UI evaluation and a live API mode for the self-hosted service.
- Docker Compose deployment for the web app, worker, scheduler, PostgreSQL,
  and Redis.
- Alembic migrations, verified backup/restore scripts, an Unraid reference
  template, and GitHub Actions checks for backend tests, frontend tests, and
  the production build.

The full product reasoning, scraper constraints, data-source research, and
decision record live in
[docs/product-discovery-and-research.md](docs/product-discovery-and-research.md).
The end-to-end implementation checklist is in
[docs/implementation-status.md](docs/implementation-status.md).

## Recommended: run on Unraid

Follow [deploy/README.md](deploy/README.md). In outline:

```sh
cp deploy/.env.example deploy/.env
# Replace every placeholder secret and add the Unraid hostname/IP to ALLOWED_HOSTS.
docker compose --env-file deploy/.env -f deploy/compose.yaml config --quiet
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --build postgres redis web worker scheduler
```

Open `http://<unraid-host>:8080`. On first run, use the `SETUP_TOKEN` from the
private `deploy/.env` file to create the owner. Production images compile the UI
with `VITE_DEMO_MODE=false`.

Only port 8080 is published. Do not expose it through router port forwarding;
use Tailscale later if remote access is needed.

## Developer setup on Windows

Python 3.12+ and Node 22+ are expected.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".\backend[dev,workers]"
Set-Location frontend
npm.cmd install
npm.cmd run build
Set-Location ..
```

Run the API with its local SQLite development default:

```powershell
Set-Location backend
..\.venv\Scripts\alembic.exe -c alembic.ini upgrade head
..\.venv\Scripts\uvicorn.exe app.main:app --reload
```

In a second terminal, run the PWA against the live API:

```powershell
Set-Location frontend
$env:VITE_DEMO_MODE='false'
npm.cmd run dev
```

For UI-only evaluation, omit `VITE_DEMO_MODE=false`; demo mode requires no
accounts, database, or publisher access.

## Load nutrition data

Ingredient-to-food matching and calculated nutrition are currently parked, so
nutrition datasets are not required for automatic planning. CoFID can still be
loaded for future catalogue work. Download it from the official UK government
source, retain its licence/version notes, then run:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m scripts.import_cofid `
  C:\path\to\cofid.csv `
  --dataset-version "CoFID 2021" `
  --source-uri "official download URL" `
  --license-name "Open Government Licence" `
  --database-url "postgresql+psycopg://meal_planner:password@localhost/meal_planner"
```

See [backend/app/data_import/README.md](backend/app/data_import/README.md) for
column handling, reproducibility, and update behaviour.

## Validation

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m pytest
Set-Location ..\frontend
npm.cmd test
npm.cmd run build
```

The current repository passes 51 backend tests, 22 frontend tests, TypeScript
compilation, the production PWA build, the initial and incremental Alembic
upgrades, and Compose YAML parsing. A Docker Desktop smoke test also passed:
PostgreSQL, Redis, web, worker, and scheduler started; migrations ran; health
endpoints returned 200; the PWA served its HTML and manifest; and live owner
setup plus a database-backed household member query completed successfully.

## Repository map

- `backend/app/models.py` - relational domain model.
- `backend/app/routes/` - versioned HTTP API.
- `backend/app/services/` - nutrition, planner, pantry, shopping, quantity,
  and ingredient-name rules.
- `backend/app/discovery/` - publisher adapters, safe fetch, search, and
  extraction.
- `backend/app/data_import/` - normalized food-data pipelines.
- `frontend/src/` - responsive React PWA and live API client.
- `deploy/` - Compose, Unraid, backup, and restore operations.
- `docs/` - research, decisions, testing notes, and UI concept images.

## Deliberate boundaries and deferred work

- No recipe, ingredient, missing-quantity, or nutrition generation by an LLM.
- Ingredient-to-food matching and calculated nutrition are parked; automatic
  planning uses complete publisher per-serving nutrition only.
- Great British Chefs discovery is disabled. Publisher access controls are
  never bypassed, and a source can fail independently.
- No specialist medical-user logic or medical, paediatric, pregnancy, or
  therapeutic-diet recommendations.
- No budget optimisation, equipment constraints, active-cooking-time
  optimisation, or freezing workflows.
- No public internet exposure, hosted multi-tenant service, or native mobile
  application.
- No direct Google Keep integration; shopping uses the platform share sheet,
  clipboard, or text export.
- One-way Mealie export and the optional tool-restricted OpenClaw extraction
  bridge remain intentionally excluded.

These boundaries are part of the current product decision record. Add deferred
capabilities as separate migrations/features so they do not weaken provenance,
nutrition, privacy, or shopping consistency.

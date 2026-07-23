# Slop Meal Planner

> A free, self-hosted meal planner for real households.

Current release: **0.10.0**. See the [latest release notes](#changelog) or the
[full changelog](CHANGELOG.md).

## About

- Slop:
  - A thin, often unappetising liquid or semi-liquid food [dictionary definition](https://www.merriam-webster.com/dictionary/slop).
  - Low-quality content produced by AI, usually in
large quantities [Cambridge definition](https://dictionary.cambridge.org/us/dictionary/english/ai-slop).

Slop is a **100% AI-coded replacement for MyFitnessPal and Mealie**. The name
is a deliberate play on those two meanings: this is meal-planning software
made with AI, for turning a messy collection of recipes into an organised week
of food.

I created this project because MyFitnessPal is expensive and its recipe
selection is limited. Mealie is a great self-hosted recipe catalogue, but
adding recipes takes work and it does not automatically plan a week with a
shopping list. Slop is designed to close that gap.

It connects to two of the biggest recipe websites, [Allrecipes](https://www.allrecipes.com/)
and [BBC Good Food](https://www.bbcgoodfood.com/), and automates bringing those
recipes into a household library. It then plans meals against nutrition
targets, accounts for pantry stock, and builds a practical shopping list. Since
it is self-hosted, there is no subscription fee for the application.

## Features

### Plan the week automatically

![Weekly meal plan](docs/screenshots/week.png)

The week view puts every planned meal, portion, batch, leftover, and nutrition
summary in one place. Plans can be regenerated while keeping meals that you
have already chosen.

### Work through constraints step by step

![Automatic planning wizard](docs/screenshots/plan.png)

The planning flow takes dates, household members, attendance, special days,
cook days, and ingredient preferences into account before showing a reviewable
plan.

### Discover and import recipes

![Recipe discovery](docs/screenshots/recipes.png)

Search Good Food and Allrecipes from one catalogue, filter by meal type or
source, import a URL, and review nutrition, servings, tags, and ambiguous
ingredients before a recipe becomes eligible for automatic planning.

### Keep nutrition data reusable

![Household ingredients](docs/screenshots/ingredients.png)

Search general nutrition records, look up packaged products with Open Food
Facts, scan a barcode, or enter a label manually. Saved household ingredients
can be reused in recipes, planning, and pantry stock.

### Track pantry stock and reservations

![Pantry inventory](docs/screenshots/pantry.png)

Pantry quantities are reserved when a plan is accepted and deducted when food
is cooked. Use-soon, low-stock, expiry, and staple flags make the inventory
useful during the week.

### Generate a practical shopping list

![Shopping list](docs/screenshots/shopping.png)

Shopping quantities subtract usable pantry stock, round to practical units, and
remain available offline. Items can be checked, renamed, shared, copied, or
exported as text.

![Shopping list2](docs/screenshots/shopping2.png)

Fuzzy matching of shopping list to pantry ingredients supported!

## Changelog

### 0.10.0 - 2026-07-23

- Add onboarding for API-key setup, nutrition targets, household members, and
  meal allocations.
- Add calorie-boost days with meal-specific sliders and portion-aware plans.
- Add guest days with meal-specific attendance and batch scaling based on the
  largest household serving.
- Show selected-day portion weights in the week view, including calorie boosts
  and per-guest guidance.

See [CHANGELOG.md](CHANGELOG.md) for the complete release history.

## Installation

### Try the demo locally

The demo is the quickest way to evaluate the interface. It uses seeded sample
data and does not need an account, database, or API keys.

Requirements: Python 3.12+ and Node 22+.

```sh
git clone https://github.com/ClickMe1234/slop-meal-planner.git
cd slop-meal-planner/frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The Vite development server runs in demo mode by
default.

### Self-host with Docker Compose

The supported production deployment is Docker Compose on an Unraid server or
another trusted home-LAN machine. Docker Compose v2 and Git are required.

```sh
git clone https://github.com/ClickMe1234/slop-meal-planner.git
cd slop-meal-planner
cp deploy/.env.example deploy/.env
```

Generate three different secrets and put them in `deploy/.env` as
`POSTGRES_PASSWORD`, `SECRET_KEY`, and `SETUP_TOKEN`:

```sh
openssl rand -hex 32
openssl rand -hex 32
openssl rand -hex 32
```

Before starting the stack, set at least `APPDATA_ROOT`, `BACKUP_ROOT`,
`ALLOWED_HOSTS`, and an immutable `APP_VERSION` in `deploy/.env`. On Unraid,
the usual paths are `/mnt/user/appdata/meal-planner` and
`/mnt/user/backups/meal-planner`.

Validate the configuration and start all five services:

```sh
docker compose --env-file deploy/.env -f deploy/compose.yaml config --quiet
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --build postgres redis web worker scheduler
docker compose --env-file deploy/.env -f deploy/compose.yaml ps
```

Open `http://<your-host>:8080`. On the first run, use the private
`SETUP_TOKEN` from `deploy/.env` to create the owner account. Do not expose the
web port through router forwarding. For the complete Unraid setup, HTTPS
barcode-scanning notes, backups, restore procedures, upgrades, and
troubleshooting, read [deploy/README.md](deploy/README.md).

### Developer setup on Windows

From the repository root:

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

For UI-only evaluation, omit `VITE_DEMO_MODE=false` and use the demo setup
above.

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
- Household food matching for custom-recipe ingredients, with automatic
  per-serving calorie and macro calculation when every included amount has a
  compatible, complete nutrition record.

### Ingredients and packaged foods

- A dedicated Ingredients page for household-library search, general nutrition
  search, manual label entry, and explicit packaged-product search.
- Read-only barcode lookup through the public Open Food Facts API; no Open Food
  Facts account or login session is required. Slop sends an identifying user
  agent, applies conservative local request limits, and keeps remote failures
  recoverable.
- Live camera scanning over HTTPS, plus barcode-photo and manual-number
  fallbacks. Only the decoded barcode is sent to the application server.
- Private household names and nutrition corrections that leave the community
  source unchanged while retaining its URL and attribution.
- Optional confirmed servings and meal tags that make an individual food a
  breakfast, lunch, dinner, snack, or side choice for the planner.
- Direct pantry additions with a quantity, package-count conversion when pack
  size is known, optional expiry, use-soon, and always-stocked flags.

### Nutrition and planning

- Automatic planning from recipes with complete publisher-reported or
  ingredient-calculated per-serving calories, protein, carbohydrate, and fat.
  Nutrition provenance and dataset versions are retained.
- CoFID CSV ingestion, USDA FoodData Central search/cache, and on-demand Open
  Food Facts product records with source provenance.
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

## Nutrition data

The Ingredients page can cache general ingredient matches from USDA FoodData
Central and selected packaged products from Open Food Facts, or accept a
private manual label. CoFID remains available as a reproducible local base
dataset. Reliable FoodData Central search requires a free private USDA API key.
Household owners can save one under **Settings → System**; Slop encrypts it in
the database and uses it immediately. `USDA_API_KEY` remains available as a
server-managed fallback. USDA's shared `DEMO_KEY` is limited to 30 requests per hour
and 50 per day, so it is intended only for initial API exploration. Slop
debounces searches and caches records, but cannot increase that shared quota.

To load CoFID, download the official UK government source, retain its
licence/version notes, then run:

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

The current repository passes 156 backend tests, 67 frontend tests, TypeScript
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
- Open Food Facts integration is read-only and on-demand: Slop does not upload
  corrections, copy product images, or bulk-mirror the community database.
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

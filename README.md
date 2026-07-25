# Slop Meal Planner

> A free, self-hosted meal planner for real households.

Current release: **1.1.0**. See the [latest release notes](#changelog) or the
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

The week view puts every planned meal, portion, batch, leftover, and nutrition
summary in one place. Plans can be regenerated while keeping meals that you
have already chosen.

![Weekly meal plan](docs/examples/week.png)

### Serving suggestions

Enter the total weight of what you cooked and see how much to give each person in the house based on nutitional goals.

![Serving suggestions](docs/examples/servings.png)

### Work through constraints step by step

The planning flow takes dates, household members, attendance, special days,
cook days, and ingredient preferences into account before showing a reviewable
plan.

![Plan review](docs/examples/plan.png)

### Discover and import recipes

Search Good Food and Allrecipes from one catalogue, filter by meal type or
source, import a URL, and review nutrition, servings, tags, and ambiguous
ingredients before a recipe becomes eligible for automatic planning.

![Recipe catalogue](docs/examples/recipes.png)

### Keep nutrition data reusable

Search general nutrition records, look up packaged products with Open Food
Facts, scan a barcode, or enter a label manually. Saved household ingredients
can be reused in recipes, planning, and pantry stock.

![Pantry stock](docs/examples/pantry.png)

### Track pantry stock and reservations

Pantry quantities are reserved when a plan is accepted and deducted when food
is cooked. Use-soon, low-stock, expiry, and staple flags make the inventory
useful during the week.

![Ingredients](docs/examples/ingredients.png)

### Generate a practical shopping list

Shopping quantities subtract usable pantry stock, round to practical units, and
remain available offline. Items can be checked, renamed, shared, copied, or
exported as text.

Fuzzy matching of shopping list to pantry ingredients supported!

![Shopping list](docs/examples/shopping.png)

![Shopping list matching](docs/examples/shopping2.png)

## Changelog

### 1.1.0 - 2026-07-24

- Fix recipe customisation search so typing no longer replaces the page.
- Show which recipes contribute each shopping-list ingredient and add
  permanent, recipe-linked unit changes and manual combining.
- Add a recipe-preserving editor for active plans: remove days or guests and
  change calorie boosts without replacing meals, swap a cooking batch, merge a
  cook day back into its previous batch, or add a cook day by choosing its new
  recipe from the existing customisation screen.
- Keep current plans, pantry reservations, and shopping lists synchronised
  when saved recipe ingredients change.
- Pin patched frontend build dependencies to remove the `brace-expansion`
  denial-of-service advisory from CI.

### 1.0.1 - 2026-07-24

- Correct shopping-list aggregation for reviewed ingredient names.
- Restore fuzzy pantry matching across equivalent nutrition records and
  refresh suggestions after pantry additions.

### 1.0.0 - 2026-07-24

- Promote Slop Meal Planner to its first stable release.
- Establish a documented security baseline across source, history,
  dependencies, CI, containers, and deployment.

### 0.12.0 - 2026-07-24

- Add owner-only selective backup restore from Settings → Data & backup.
- Preview backup contents and import recipes, ingredients, pantry, shopping lists, plans, household settings, or user accounts independently without replacing the target installation's sessions or encrypted credentials.

### 0.11.0 - 2026-07-24

- Add a production Unraid WebGUI deployment using the public immutable GHCR image.
- Run the web server, worker, and scheduler under one supervised container with
  friendly PostgreSQL/Redis configuration, readiness checks, and bundled backup/restore roles.
- Keep the five-service Compose deployment available as an alternative.

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

### Production install through the Unraid WebGUI

Unraid is the primary production path. This uses one Slop container and
separately installed PostgreSQL and Redis containers; no Git checkout or Docker
Compose Manager is required for the application container.

1. Install or identify standalone PostgreSQL 15–18 and Redis 7.2/7.4 first.
   Create a dedicated `meal_planner` database and role, and reserve Redis
   logical databases `0` and `1`. Publish their ports for the zero-CLI Bridge
   setup, or use the safer user-defined Docker bridge described in
   [`deploy/README.md`](deploy/README.md).
2. Generate three independent values with `openssl rand -hex 32`: a PostgreSQL
   password, `MEAL_PLANNER_SECRET_KEY`, and `MEAL_PLANNER_SETUP_TOKEN`.
3. Configure an HTTPS reverse proxy or authenticated private overlay first.
   Direct LAN HTTP is not a supported production deployment because it exposes
   passwords, setup tokens, API keys, and session cookies to on-path devices.
4. In Unraid Apps, choose **Add Container** and use the exact values in
   [`deploy/unraid-template.xml`](deploy/unraid-template.xml):
   `ghcr.io/clickme1234/slop-meal-planner:1.1.0` as Repository, `Bridge` as
   Network Type, `Shell` as the console shell, Privileged off, and `--init` as
   Extra Parameters. The Repository is a Docker image reference, not the GitHub
   source URL. Leave Post Arguments blank.
5. Add the Web UI Port mapping `8080:8000` (the host side may be changed), map
   `/mnt/user/appdata/slop-meal-planner/data` to `/data`, and map
   `/mnt/user/backups/slop-meal-planner` to `/backups`.
6. Add the visible PostgreSQL, Redis, secret, host, cookie, timezone, PUID, and
   PGID variables. Set `MEAL_PLANNER_ALLOWED_HOSTS` to the reverse-proxy names
   used by household devices. Keep `MEAL_PLANNER_COOKIE_SECURE=true` and
   `MEAL_PLANNER_HSTS_ENABLED=true`.
7. Start PostgreSQL and Redis before Slop. Slop still retries dependencies for
   up to 120 seconds, then runs migrations once and starts its web, worker, and
   scheduler processes. Open the selected host port and use the setup token to
   create the owner.

The image supports optional advanced full-URL overrides for existing deployments
and safely encodes reserved characters, IPv6 hosts, and Redis ACL credentials.
Only one `all` container should run because multiple Celery Beat schedulers
would duplicate scheduled work. Do not forward the application, PostgreSQL, or
Redis ports from the router to the internet.

See [`deploy/README.md`](deploy/README.md) for the complete field table,
networking choices, backups, restore, upgrades, and troubleshooting.

### Self-host with Docker Compose (alternative)

The existing five-service Compose deployment remains supported for Unraid
Docker Compose Manager and other trusted home-LAN machines. It runs web,
worker, scheduler, PostgreSQL, and Redis separately.

```sh
git clone https://github.com/ClickMe1234/slop-meal-planner.git
cd slop-meal-planner
cp deploy/.env.example deploy/.env
docker compose --env-file deploy/.env -f deploy/compose.yaml config --quiet
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --build postgres redis web worker scheduler
```

Generate independent PostgreSQL, application, and setup secrets before
starting, keep `APP_VERSION` immutable, and follow the Compose backup/restore
workflow in [`deploy/README.md`](deploy/README.md).

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
$env:MEAL_PLANNER_DATABASE_URL = "postgresql+psycopg://meal_planner:password@localhost/meal_planner"
..\.venv\Scripts\python.exe -m scripts.import_cofid `
  C:\path\to\cofid.csv `
  --dataset-version "CoFID 2021" `
  --source-uri "official download URL" `
  --license-name "Open Government Licence"
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

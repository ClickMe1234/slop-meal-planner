# Savour Meal Planner

Savour is a private, self-hosted household meal planner. It imports recipes,
calculates nutrition consistently from ingredient data, builds plans against
per-person targets, reserves pantry stock, and produces an offline-capable
shopping list.

The production target is an Unraid server on a trusted LAN. The repository also
contains a demo mode so the complete responsive light/dark interface can be
evaluated without first loading a nutrition dataset.

## What is implemented

- Owner/collaborator accounts, Argon2 passwords, server-side sessions and CSRF.
- Calorie **or** macro target modes with user-set hard tolerance and 4/4/9
  feasibility validation.
- Versioned custom and URL-imported recipes; publisher instructions are not
  copied.
- Good Food, Great British Chefs and Allrecipes search adapters with combined
  results, publisher-only preview nutrition and saved-URL deduplication.
- Safe generic URL imports using JSON-LD first and a review-required semantic
  fallback.
- CoFID CSV ingestion plus USDA FoodData Central and Open Food Facts provider
  boundaries, retaining dataset version and provenance.
- Ingredient-based nutrition totals and per-serving values. Publisher nutrition
  is never used by the planner.
- Automatic shared-recipe planning with individual quarter-serving portions,
  hard exclusions, must/prefer/exclude ingredient guidance and explicit
  infeasibility errors.
- Multi-occurrence cooked batches and acknowledgement for allocations beyond
  the 48-hour leftover window.
- Pantry reservations on plan acceptance and consumption when a batch is marked
  cooked.
- Exact shopping requirements, practical rounding for countable items, pantry
  subtraction, manual-item/check-state preservation and explicit
  purchased-to-pantry confirmation.
- Responsive installable PWA, system/light/dark themes, local offline shopping
  storage, device sharing, clipboard and text export.
- Docker Compose stack for web, worker, scheduler, PostgreSQL and Redis, plus
  verified backup/restore scripts and an Unraid reference template.

The full product reasoning, scraper constraints, data-source research and
decision record live in
[docs/product-discovery-and-research.md](docs/product-discovery-and-research.md).

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
accounts, database or publisher access.

## Load nutrition data

Recipe calculation intentionally blocks until each included ingredient has a
real food record and a compatible amount. Download CoFID from the official UK
government source, retain its licence/version notes, then run:

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
column handling, reproducibility and update behaviour.

## Validation

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m pytest
Set-Location ..\frontend
npm.cmd test
npm.cmd run build
```

The current repository passes 25 backend tests, 2 frontend tests, TypeScript
compilation, the production PWA build, the initial Alembic upgrade, Compose YAML
parsing and Unraid XML parsing. A Docker Desktop smoke test also passed: the
PostgreSQL, Redis, web, worker and scheduler services started; migrations ran;
the health endpoints returned 200; the PWA served its HTML and manifest; and a
live owner setup plus calorie-target request completed successfully.

## Repository map

- `backend/app/models.py` — relational domain model.
- `backend/app/routes/` — versioned HTTP API.
- `backend/app/services/` — nutrition, planner, pantry and shopping rules.
- `backend/app/discovery/` — publisher adapters, safe fetch and extraction.
- `backend/app/data_import/` — normalized food-data pipelines.
- `frontend/src/` — responsive React PWA and live API client.
- `deploy/` — Compose, Unraid, backup and restore operations.
- `docs/` — research, decisions and UI concept images.

## Deliberate boundaries

- No recipe or ingredient generation by an LLM.
- No specialist medical-user logic yet.
- No budget, equipment or active-time optimisation yet.
- No public internet exposure or native mobile application yet.
- No direct Google Keep integration; shopping uses the platform share sheet.
- Publisher access controls are never bypassed. A source can fail independently
  and remains an adapter-maintenance concern.

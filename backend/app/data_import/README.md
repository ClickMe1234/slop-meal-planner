# Nutrition data import boundary

`CofidCsvImporter` turns a published CoFID CSV release into normalized per-100 g
food records. Each batch carries its source URI, release label, SHA-256 checksum,
license label, and import timestamp. Missing, trace, bounded (`<0.1`), and
unparseable cells remain distinguishable; they are never silently changed to
zero.

Validate a release without changing the database from the backend directory:

```shell
python -m scripts.import_cofid path/to/cofid.csv \
  --dataset-version "CoFID 2021" \
  --source-uri "https://publisher.example/exact-download" \
  --license-name "Open Government Licence" \
  --dry-run
```

Remove `--dry-run` and set `MEAL_PLANNER_DATABASE_URL` or `DATABASE_URL` in the
process environment to transactionally upsert the records. Credentials are not
accepted as command-line arguments, so they do not appear in process listings
or normal shell history.
A new dataset version replaces each food's nutrient rows rather than carrying old
values forward.

USDA FoodData Central and Open Food Facts providers normalize provider responses
to the same contract. USDA requires an API key before a network client is used.
Open Food Facts is intended for branded/barcode foods, while CoFID remains the
first-choice generic UK food dataset. Provider payloads still need human review
before a match becomes a reusable household ingredient alias.

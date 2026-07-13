# Meal Planner Product Discovery and Research

**Status:** Living discovery and decision record; initial implementation completed 12 July 2026
**Research date:** 12 July 2026
**Primary region assumed:** United Kingdom
**Purpose:** Preserve the initial product requirements, research findings, risks,
recommended data pipelines, and decisions needed before implementation.

This document should be updated as product decisions are made. Statements marked
as recommendations are design proposals rather than agreed requirements.

## 1. Product vision

Build a self-hostable web tool, with the option of a later native application,
that combines:

- A personal and household recipe catalogue.
- Recipe discovery across selected external publishers.
- URL and manual recipe import.
- Reliable ingredient, serving, calorie, and macro data.
- Automatic meal planning against calorie and macro targets.
- Multi-person portion and batch-cooking support.
- Consolidated, categorised, tickable shopping lists.
- Ingredient-led discovery of existing recipes. The application will not generate
  ingredients or recipes.

The intended experience resembles the planning element of MyFitnessPal, but is
recipe- and household-oriented rather than primarily a food diary.

## 2. Original requirements captured

### 2.1 Recipe catalogue

- Initially support recipes from:
  - Good Food (`bbcgoodfood.com`).
  - Great British Chefs (`greatbritishchefs.com`).
  - Allrecipes (`allrecipes.com`).
- Allow support for more publishers later.
- Allow users to create custom recipes.
- Allow URL import from unsupported sites where possible.
- Retain the original recipe URL and provenance.
- Store ingredients, quantities, yield, calories, and macros in PostgreSQL.
- Store nutrition on a per-serving basis while also retaining the total recipe
  basis needed for auditing and recalculation.
- Use imported and custom recipes as candidates for automatic meal planning.
- Seed an initial catalogue, originally suggested as the top 100 recipes from
  each of the three publishers.

### 2.2 Search and discovery

- One search should include:
  - Recipes already held in the internal catalogue.
  - Results from the three supported publishers.
- Results should identify their source.
- Show a recipe image, calories, and macros per serving where available.
- Importing an external result should add a validated recipe to PostgreSQL.
- Existing internal recipes must not disappear from combined search results.

### 2.3 Automatic meal planning

- Accept daily calorie and macro goals.
- Potentially derive calorie targets from weight-loss goals for the owner, subject
  to appropriate safety rules.
- Divide planned calories between breakfast, lunch, dinner, and snacks using
  custom percentages.
- Plan a user-selected number of days.
- Exclude individual meal slots, for example a dinner eaten away from home.
- Plan for multiple household members.
- Allow an additional or reduced calorie allocation per household member.
- Allow recipes to last for a user-selected number of days.
- Use specified ingredients or pantry ingredients when selecting meals.

### 2.4 Shopping list

- Aggregate ingredients from all planned recipe batches.
- Scale quantities by actual servings required.
- Categorise items and present a tickable list.
- Support the example calculation:

  ```text
  three people x three eating occasions = nine required servings
  source recipe yield = two servings
  recipe scale factor = 9 / 2 = 4.5
  ```

- Eventually account for household stock and practical purchase quantities.

## 3. Executive findings

### 3.1 Confirmed product decisions as of 12 July 2026

- This is a private personal/household application. It will not be a subscription
  service, commercial product, or revenue-generating service.
- Nutrition used by planning will always be calculated from normalised recipe
  ingredients. Publisher nutrition is preview/reference data only.
- Calculated nutrition will be presented per serving whenever a valid recipe yield
  is available.
- Publisher per-100g nutrition may be shown only when that is the available basis,
  and must be labelled clearly as per 100g rather than per serving.
- Search should feel live. Local results update on each keystroke; external search
  is debounced and cancellable.
- External results may initially show publisher-reported calories/macros. If none
  are present, the result offers a user-triggered `Calculate nutrition` action.
- Imported publisher recipes store source metadata, yield, and ingredients, but
  not copied cooking instructions. Cooking opens the original source page.
- Custom recipes remain supported; how their optional instructions are handled is
  still an explicit decision because they may not have an external source page.
- Active cooking-time optimisation is deferred.
- Budget limits and the larger budget concept are deferred.
- Equipment restrictions are out of scope.
- LLMs may assist extraction of fields already present on a page but must not
  generate recipes, ingredients, missing quantities, or nutrition values.
- A meal that lasts for multiple days is one cooked batch allocated across dated
  meal slots. Freezing behaviour is out of scope for this rule.
- The application will ultimately run in a Docker container on an Unraid server
  on the local network.
- Nutritional targets are always user-specified.
- A target profile uses either calorie mode or macro mode, never independent
  calorie and macro targets simultaneously.
- In calorie mode, optional macro minimum/maximum guardrails may be set where they
  are mathematically compatible with the calorie target.
- Missing/ambiguous recipe yield requires user confirmation before planning.
- Ambiguous ingredient-to-food matches require review and remembered corrections.
- Unplanned meals reserve their calorie allowance by default; the user may choose
  to redistribute it explicitly.
- Internal portion allocation supports quarter-serving increments.
- Allergies are hard exclusions; dislikes and preferences affect ranking.
- Ingredient-led discovery supports `must contain`, `prefer`, and `exclude`.
- Remote search thumbnails are displayed from their source where workable and are
  not permanently cached initially.
- Custom recipes may store optional user-authored instructions; publisher
  instructions are not stored.
- The private catalogue should grow through search and import rather than an
  automatic bulk seed of 100 recipes per publisher.
- Pantry inventory is in scope. Shopping generation subtracts available pantry
  quantities while preserving traceability and allowing manual corrections.
- Shopping lists round exact requirements to practical purchase quantities for
  countable items and known package sizes; for example, eggs are rounded to whole
  units. Exact calculated requirements remain visible behind the rounded item.
- The Unraid deployment is LAN-only. Tailscale may provide private remote access
  later without making the application itself publicly accessible.
- Target tolerances are user-specified. The UI suggests defaults of +/-5% for
  calorie mode and +/-10% for macro mode, with clear validation and the ability to
  change them.
- Specialist-user planning is out of scope. The initial application supports
  general-adult personal planning with user-specified targets and makes no
  paediatric, pregnancy, therapeutic-diet, or medical suitability claims.

1. **The concept is technically feasible.** Recipe import, household scaling,
   search, optimisation, and shopping-list generation all have viable technical
   approaches.
2. **The central engineering challenge is data quality.** Publisher pages contain
   inconsistent yields, units, ingredient descriptions, nutrition coverage, and
   definitions of a serving.
3. **Content permissions still matter, but the private scope materially reduces
   exposure.** Imports should remain user-initiated, private, attributed, and
   respectful of publisher terms and request limits.
4. **An LLM should be a fallback, not the primary scraper.** Structured Recipe
   metadata and existing site adapters cover many recipe pages more reliably and
   cheaply.
5. **Automatic planning should be deterministic.** Use a constraint optimiser for
   calorie, macro, portion, leftover, and household constraints. An LLM may
   explain or assist but should not be the source of truth.
6. **Shopping quantities must be generated from meal batches and allocated
   portions.** Multiplying people by days is only correct when everyone receives
   equal portions on every occurrence.
7. **Calculated nutrition needs to be a first-class subsystem.** Great British
   Chefs and arbitrary imported sites may not publish macros, and even published
   nutrition needs provenance and reconciliation.

## 4. Recipe extraction research

### 4.1 Structured recipe metadata

Many recipe publishers expose [Schema.org Recipe](https://schema.org/Recipe)
metadata, commonly as JSON-LD. Relevant fields include:

- `name`
- `image`
- `recipeYield`
- `recipeIngredient`
- `recipeInstructions`
- `prepTime`, `cookTime`, and `totalTime`
- `recipeCategory` and `recipeCuisine`
- `suitableForDiet`
- `nutrition`

Schema.org permits ingredients to remain free text, so it helps extraction but
does not eliminate the need for ingredient parsing and normalisation. Google also
documents Recipe structured data and indicates that yield should accompany
per-serving nutrition:
[Google Recipe structured-data documentation](https://developers.google.com/search/docs/appearance/structured-data/recipe).

### 4.2 Existing extraction library

The Python [`recipe-scrapers`](https://docs.recipe-scrapers.com/) library
currently lists more than 649 supported sites. Its supported-sites list includes:

- `allrecipes.com`
- `bbcgoodfood.com`
- `greatbritishchefs.com`

Source: [recipe-scrapers supported sites](https://docs.recipe-scrapers.com/getting-started/supported-sites/).

This materially reduces the need to build three bespoke importers initially.
Site-specific regression tests will still be required because publisher markup
changes over time.

### 4.3 Observed differences between proposed sources

- A sampled Good Food recipe exposes a numeric yield and nutrition per serving,
  including calories, fat, carbohydrate, protein, fibre, sugar, saturates, and
  salt: [Proper chicken curry](https://www.bbcgoodfood.com/recipes/proper-chicken-curry).
- A sampled Great British Chefs recipe exposes yield, ingredient groups,
  quantities, and instructions, but no visible calorie or macro panel:
  [Poulet Breton](https://www.greatbritishchefs.com/recipes/poulet-breton-recipe).
- Great British Chefs also contains member-only recipes, which must not be treated
  as generally importable catalogue content.
- Allrecipes is listed as technically supported by `recipe-scrapers`, but its
  current search behaviour, rate limits, access rules, and field completeness
  require a dedicated spike before implementation.

These examples are illustrative rather than a complete site audit.

### 4.4 Recommended extraction hierarchy

Use deterministic methods before involving an LLM:

```text
Submitted URL
  -> URL safety and source-policy checks
  -> Fetch public HTML with timeouts and rate limits
  -> Parse Schema.org JSON-LD or microdata
  -> Use a known recipe-scrapers adapter
  -> Try a generic Recipe/DOM extractor
  -> Use schema-constrained LLM extraction as a fallback
  -> Validate required fields and confidence
  -> User review when anything important is uncertain
  -> Normalise ingredients and enrich nutrition
  -> Persist an immutable recipe version and index it
```

Recommended minimum import validation:

- Non-empty title.
- A valid positive yield or an explicit review warning.
- At least one ingredient.
- Quantities retained in original text even when parsing fails.
- Valid canonical source URL.
- No unreviewed allergen or diet claims inferred solely from an LLM.
- Clear indication of missing or calculated nutrition.

### 4.5 Reusable adapters for unsupported sites

An LLM may help identify fields on an unsupported page, but it should not write
and execute arbitrary scraper code. Safer behaviour is:

1. Extract one page into a strict Recipe schema.
2. Suggest declarative JSON paths, CSS selectors, or structured-data paths.
3. Validate the proposed mapping against several pages on the same domain.
4. Store a domain adapter only after human approval and regression tests.
5. Disable the adapter automatically when completeness checks begin failing.

Avoid retaining full copyrighted HTML snapshots indefinitely. Prefer extraction
traces, checksums, permitted test fixtures, or synthetic/redacted fixtures unless
storage of the original page has a clear lawful basis.

## 5. Content rights, terms, and provenance

This section records product risk, not legal advice.

### 5.1 Findings

The `recipe-scrapers` project states that it is only an extraction tool, does not
grant rights in source content, and places responsibility for terms, copyright,
robots directives, and permissions on the user:
[recipe-scrapers copyright and usage](https://docs.recipe-scrapers.com/copyright-and-usage/).

Great British Chefs' published terms permit personal retrieval/display and one
personal copy, while restricting commercial republication and reuse and the
independent reuse of images:
[Great British Chefs terms](https://www.greatbritishchefs.com/terms-and-conditions).

Good Food's published app terms state that content may only be downloaded or used
for personal use:
[Good Food app terms](https://www.bbcgoodfood.com/good-food-app-terms-and-conditions).

Allrecipes' current applicable terms, robots policy, and licensing position need
to be reviewed directly before its connector is enabled. A scraper's technical
support is not permission to reuse content.

### 5.2 Consequences for the product

The application is confirmed as a private household instance. The other modes are
retained here only to document why the architecture must not quietly drift into
public redistribution later:

| Mode | Lower-risk content approach |
|---|---|
| Private household instance | User-initiated imports, private visibility, attribution and source links, minimal fetching, no public redistribution |
| Publicly distributed self-hosted software | Import tooling supplied to users; clear source-policy controls and user responsibility; no bundled unlicensed catalogue |
| Hosted subscription service | Publisher agreements or other explicit lawful basis before systematic ingestion, image display, or redistribution |

Before any bulk seed of 100 recipes per publisher, even for the private instance:

- Define what "top" means: current popularity, rating, review count, editorial
  list, or a balanced selection.
- Confirm permission to perform systematic extraction and retain/display content.
- Confirm whether images may be cached, proxied, hot-linked, or only represented
  by a link.
- Record attribution requirements.
- Do not store publisher instructions; send the user to the original recipe page.

A balanced seed catalogue may be more useful than a literal popularity list. It
could be stratified by meal type, calories, diet, cuisine, difficulty, cooking
time, and nutrition completeness. It should not be created until the content
basis is resolved.

### 5.3 Required provenance fields

Every imported recipe should record:

- Canonical source URL and domain.
- Publisher and author where available.
- Importing user.
- Import date and last checked date.
- Source recipe identifier if present.
- Extraction method and version.
- Source-page checksum.
- Attribution text.
- Rights basis or source policy.
- Original versus user-edited status.
- Per-field source for yield and nutrition.

## 6. Unified search research and proposed behaviour

### 6.1 Practical constraint

A unified search is possible, but it is not one uniform API. Each publisher needs
an approved connector or discovery mechanism. Site search results may provide only
titles, links, and images; showing calories and macros may require fetching every
individual result page. That produces an N+1 request pattern, slow responses, and
a greater likelihood of throttling or blocking.

No publisher search API should be assumed until it is confirmed directly. A
licensed general web-search API with site filters could assist discovery, but it
does not grant rights to reproduce the resulting recipe content.

### 6.2 Recommended search flow

1. Search PostgreSQL immediately using full-text and fuzzy matching.
2. Return internal results first, clearly marked as available.
3. After a minimum query length and short debounce, create asynchronous
   external-source jobs. Cancel superseded requests when the query changes.
4. Merge external previews as they arrive without blocking local results.
5. Deduplicate by canonical URL, source identifier, and cautious title/author
   similarity.
6. Mark matches already in the local catalogue.
7. Show publisher-reported per-serving nutrition immediately where present,
   labelled `Source estimate` and never use it for planning.
8. Where source nutrition is absent, offer `Calculate nutrition`. This fetches the
   recipe, parses yield and ingredients, resolves nutrition matches, and either
   returns calculated per-serving values or opens a focused review for ambiguity.
9. Reuse the completed extraction if the user subsequently saves the recipe.
10. Fully validate calculated nutrition on import before planner eligibility.
11. Cache search previews, nutrition calculations, and failures for a
    source-specific period.

Local search may run on every keystroke. External sources should use a short
debounce, a minimum query length, cancellation, pagination, request budgets, and
circuit breakers. This preserves a live-search feel without issuing a remote
request for every physical key event.

### 6.3 Result model

Each result should expose:

- Title.
- Source and source URL.
- Image only where display is permitted.
- Yield.
- Calories, protein, carbohydrate, and fat per serving where verified.
- Nutrition status: publisher-provided, calculated, missing, or awaiting import.
- Local/imported status.
- Extraction confidence and relevant warnings.

External nutrition is progressively enriched. Results are never withheld solely
because calculated nutrition is not yet available.

## 7. Nutrition data and calculation

### 7.1 Recommended source hierarchy for a UK product

1. Calculate nutrition from normalised recipe ingredients for every planner-ready
   recipe. This calculated value is the sole nutrition source used by the planner.
2. Preserve publisher-provided nutrition only as a separately labelled search
   preview and diagnostic comparison; never substitute it into the planner.
3. Use the UK government's Composition of Foods Integrated Dataset (CoFID) for
   generic UK ingredients:
   [CoFID publication](https://www.gov.uk/government/publications/composition-of-foods-integrated-dataset-cofid).
4. Use Open Food Facts for identified packaged or barcode products.
5. Use USDA FoodData Central as a broad generic and branded fallback. Its official
   API supplies search and food-detail endpoints:
   [FoodData Central API guide](https://fdc.nal.usda.gov/api-guide/).
6. Allow manual selection or correction for ambiguous matches.

Open Food Facts is crowdsourced and its database, contents, and images have
specific ODbL, Database Contents, and CC BY-SA conditions:
[Open Food Facts licensing](https://openfoodfacts.github.io/documentation/docs/Product-Opener/api/tutorials/license-be-on-the-legal-side/).
Attribution and any applicable share-alike obligations must be designed in rather
than added later.

### 7.2 Calculation pipeline

```text
Original ingredient line
  -> parse quantity, unit, food, preparation, optionality, and group
  -> normalise the unit where dimensionally valid
  -> resolve to a nutrition-database food
  -> determine edible grams and selected preparation state
  -> calculate nutrient contribution
  -> sum recipe totals
  -> divide by validated yield
  -> compare with publisher nutrition, if present
  -> store both sources and flag material differences
```

Never overwrite publisher nutrition with calculated nutrition. Store them as
separate observations with source, basis, dataset version, and confidence, but
mark calculated per-serving nutrition as the planning authority.

Calculated per-serving nutrition does not require the finished dish's cooked
weight. Sum the nutrient contribution of all ingredient quantities, then divide
the recipe total by the validated number of servings. Finished cooked weight is
needed only for a calculated per-100g result. If yield is missing or ambiguous,
per-serving nutrition cannot be trusted until the user confirms it.

If a publisher supplies only per-100g nutrition, it may be displayed as reference
data with a prominent `per 100g` basis. It must not be labelled as a serving and
must not be converted to per serving without a defensible cooked-weight or portion
weight.

### 7.3 Known sources of uncertainty

- Raw versus cooked weights.
- Drained versus undrained tins.
- Bones, shells, peel, and other inedible portions.
- Oil absorbed or left behind during frying.
- Water gain or loss during cooking.
- Ingredient ranges such as `2-3 tbsp`.
- Approximate units such as handful, bunch, medium, or knob.
- Package sizes that differ by country or brand.
- Ingredients described as `to taste`, `for frying`, or `as needed`.
- Optional garnishes and serving suggestions.
- Brand-specific recipe products such as stock, sauces, and protein powders.
- Publisher nutrition that excludes accompaniments shown in the image.
- Rounding, fibre, and alcohol causing calories to differ from simple 4/4/9 macro
  calculations.

The UI should display confidence and explain why a recipe is excluded from strict
automatic planning. Low-confidence recipes should require review before becoming
planner candidates.

### 7.4 How ingredient nutrition data enters the application

Publisher nutrition is not imported into the planner's nutrition authority. The
planner builds recipe nutrition from food-composition datasets as follows:

#### Food-data acquisition

1. Import the relatively compact UK CoFID dataset into local PostgreSQL as the
   primary generic-food catalogue.
2. Retain the source dataset version and original food identifiers.
3. Query USDA FoodData Central on demand when CoFID has no suitable generic match,
   then cache the selected record locally with its provenance.
4. Query Open Food Facts on demand for a specific packaged/barcoded product, then
   cache only the products actually selected by the user or importer.
5. Do not import the complete Open Food Facts or USDA branded catalogues into the
   personal server; they are unnecessarily large for this use case.

#### Recipe calculation example

Given an imported line such as `250g skinless chicken breast`:

```text
retain original text
  -> parse quantity: 250
  -> parse unit: gram
  -> parse food phrase: skinless chicken breast
  -> resolve canonical food: chicken breast, skinless, raw
  -> resolve CoFID/USDA record and its nutrients per 100g
  -> multiply every nutrient by 250 / 100
  -> add the contribution to the recipe total
```

Repeat this for every quantifiable ingredient, sum the recipe totals, and divide by
the validated recipe yield to obtain calculated nutrition per serving. The cooked
weight of the finished dish is not required for this calculation.

#### Units and ambiguity

- Grams and millilitres can usually be handled directly, subject to density where
  volume must become mass.
- Teaspoons, tablespoons, and cups need an ingredient-specific density or an
  established unit conversion.
- Countable foods such as one egg or one onion need an average edible weight or a
  selected size-specific record.
- `To taste`, `a splash`, `for frying`, and similar amounts cannot be calculated
  reliably and must be excluded with a warning or reviewed by the user.
- Ambiguous matches open a review step. Choosing a match creates a reusable alias,
  so subsequent imports of the same phrase normally resolve automatically.
- User corrections always override automatic matches while retaining the original
  ingredient text and audit history.

#### Updates and reproducibility

Nutrition records and recipe calculations store dataset versions. A later CoFID,
USDA, or Open Food Facts update does not silently change an accepted meal plan.
The application may flag affected recipes and offer an explicit recalculation and
comparison.

## 8. Proposed domain and data model

Recipes, recipe versions, nutrition observations, meal batches, portions, and
shopping items should remain distinct.

### 8.1 Core recipe entities

| Entity | Purpose and representative fields |
|---|---|
| `recipe` | Stable identity, household/owner, visibility, canonical source, planner eligibility |
| `recipe_version` | Immutable yield, ingredient set, reported times, metadata, source checksum, superseded version; publisher instructions are not stored |
| `recipe_source` | URL, publisher, attribution, rights basis, fetch policy |
| `ingredient_group` | Sauce, filling, garnish, or other sub-section |
| `recipe_ingredient` | Original text, amount min/max, unit, canonical food, note, preparation, optional flag, parse confidence |
| `food` | Canonical ingredient identity and shopping category |
| `food_alias` | Spelling, regional, plural, and publisher-specific aliases |
| `unit` | Dimension, abbreviations, conversion rules, package semantics |
| `nutrition_match` | Food-database source record, dataset version, match confidence, reviewer |
| `recipe_nutrition` | Total/per-serving observation, nutrients, source method, confidence, inclusion assumptions |

### 8.2 Household and planning entities

| Entity | Purpose and representative fields |
|---|---|
| `household` | Locale, unit system, aisle ordering, defaults |
| `household_member` | Name, target profile, restrictions, preferences, active dates |
| `nutrition_target` | Calories, macro targets/ranges, effective date, source/manual status |
| `meal_type` | Breakfast, lunch, dinner, snack, or user-defined type |
| `meal_slot` | Date, meal type, planned/unplanned state, calorie allocation, locked state |
| `meal_batch` | Recipe version, servings cooked, cook date, storage/freezing assumptions |
| `portion_allocation` | Batch portion assigned to a person and meal slot |
| `plan_generation` | Input snapshot, solver version, objective weights, status, explanation |

### 8.3 Shopping and pantry entities

| Entity | Purpose and representative fields |
|---|---|
| `shopping_list` | Household, plan, status, generated timestamp |
| `shopping_requirement` | Exact normalised amount generated from a batch |
| `shopping_item` | Human display amount, category, checked state, manual edits |
| `pantry_item` | Food/product, amount, unit, expiry, reserved amount |
| `package_option` | Purchasable pack size, product, store, price, last checked |

### 8.4 Import and audit entities

| Entity | Purpose and representative fields |
|---|---|
| `import_job` | URL, stage, status, timings, warnings, error codes |
| `extraction_result` | Extractor version, field confidence, raw structured-data fragments where permitted |
| `source_adapter` | Domain, declarative selectors, version, approval state |
| `audit_event` | User/system action and before/after references |

PostgreSQL full-text search and `pg_trgm` fuzzy matching should be adequate for
the first catalogue. A separate search cluster is not initially required.

## 9. Automatic meal-planning specification

### 9.1 Required inputs

- Planning start date and number of days.
- Household members participating on each day.
- Per-person target mode: calorie target with optional macro guardrails, or macro
  gram targets with no independently editable calorie target.
- Meal types and percentage/allocation by day.
- Unplanned meal slots and whether their allowance is retained or redistributed.
- Locked meals.
- Required ingredients and ingredients to avoid.
- Allergies and dietary restrictions per person.
- Recipe likes, dislikes, exclusions, and repetition preferences.
- Optional difficulty or total-time filters only where publishers report them
  reliably; active-time optimisation is deferred.
- Batch/leftover rules and freezer permission.
- Optional pantry, expiry, and food-waste preferences. Budget optimisation is
  deferred to a separate future concept.

### 9.2 Meal percentage semantics

- Percentages normally total 100% per person and day.
- Snack may contain more than one slot.
- A skipped/unplanned meal should default to retaining an external-food allowance,
  not redistributing it invisibly.
- The user may explicitly choose redistribution.
- Plans should distinguish the full daily target from calories covered by the
  generated plan.

### 9.3 Household and batch scaling

For equal portions:

```text
required servings = people eating x scheduled occurrences
scale factor = required servings / source yield
```

For unequal targets:

```text
required servings = sum of all assigned portion factors across people and slots
scale factor = required servings / source yield
```

The optimiser should support practical portion increments, initially one-quarter
or one-half serving. Recipes may define minimum batches or restricted scaling.

`Meal lasts for N days` was initially ambiguous. The considered meanings were:

- Cook once and schedule leftovers for N consecutive compatible slots.
- Allow the same recipe to repeat within N days but cook it each time.
- Produce exactly N days of portions, with user-selected storage behaviour.

The confirmed interpretation is an explicit **meal batch**: cook once and allocate
portions to dated meal slots. Freezing does not alter or extend the scheduling
rule in the initial design.

### 9.4 Nutritional target modes and feasibility

Target settings are mutually exclusive:

#### Calorie mode

- The user enters a daily calorie target.
- The planner minimises deviation from that target within a visible tolerance.
- The user may optionally set minimum and/or maximum grams for protein,
  carbohydrate, and fat as guardrails rather than separate exact targets.
- Actual recipe calories still come from the resolved ingredient nutrition data.

#### Macro mode

- The user enters gram targets for protein, carbohydrate, and fat.
- No independent calorie target can be entered.
- The UI displays the approximate energy implied by the macros, but it is derived
  and read-only.
- The planner minimises deviation from the macro targets within a visible
  tolerance and reports the resulting ingredient-calculated calories.

For configuration validation, use the UK food-labelling conversion factors:

```text
protein energy     = protein grams x 4 kcal
carbohydrate energy = carbohydrate grams x 4 kcal
fat energy         = fat grams x 9 kcal
implied energy     = protein energy + carbohydrate energy + fat energy
```

These 4/4/9 factors appear in the conversion factors used for UK food information
and are appropriate for validating a conventional macro-tracking interface:
[retained Regulation 1169/2011, Annex XIV](https://www.legislation.gov.uk/eur/2011/1169/pdfs/eur_20111169_2018-01-01_en.pdf).

In calorie mode, let the permitted calorie interval after tolerance be
`[K_min, K_max]`. Optional macro ranges are feasible only when their possible
implied-energy interval overlaps the calorie interval:

```text
minimum implied kcal = 4 x protein_min + 4 x carbohydrate_min + 9 x fat_min
maximum implied kcal = 4 x protein_max + 4 x carbohydrate_max + 9 x fat_max
```

- Minimums must not imply more than `K_max`.
- If maximums are supplied for all three macros, they must be capable of reaching
  at least `K_min`.
- Each minimum must be non-negative and no greater than its maximum.
- An individual maximum cannot exceed the whole calorie allowance on its own:
  approximately `K_max / 4` grams for protein or carbohydrate and `K_max / 9`
  grams for fat.
- With only partial maximums, the unbounded macros retain the remaining energy
  capacity; the UI should not invent missing limits.

The configuration check uses 4/4/9, but it should be described as approximate.
UK dietary-intake reporting may use 3.75 kcal/g for carbohydrate, and food energy
can also include fibre, alcohol, polyols, or organic acids. Therefore, the planner
must use each food record's energy value for recipe calories rather than forcing
calories to equal the displayed macro equation exactly. The current UK Scientific
Advisory Committee on Nutrition statement documents the dietary-intake factors and
the distinction:
[SACN energy conversion statement](https://www.gov.uk/government/publications/sacn-statement-on-expressing-fat-and-carbohydrate-recommendations/sacn-statement-on-expressing-energy-fat-and-carbohydrate-intakes-and-recommendations).

#### Recommended target tolerances

MyFitnessPal's current documentation describes exact calorie/macro goals, standard
macro allocation in 5% increments, and Premium gram-level goals; it does not
document a 10% success tolerance:
[MyFitnessPal goal customisation](https://support.myfitnesspal.com/hc/en-us/articles/360032274432-Customize-your-nutritional-goals).
Cronometer explicitly supports optional nutrient minimum and maximum values rather
than requiring an exact value:
[Cronometer nutrient targets](https://support.cronometer.com/hc/en-us/articles/360018069532-Nutrient-Targets-Summary).

Recommended defaults for this planner; the user may change the tolerance:

- **Calorie mode default:** target +/- 5% per day.
- **Macro mode default:** +/- 5% around each user-entered gram target.
- **User control:** the user may set a different tolerance (1-25%). It is always a
  hard boundary. The planner must report an infeasible result rather than widen
  it automatically; this supersedes the earlier idea of a hidden or automatic
  10% outer band.
- **Calorie-mode macro guardrails:** user-entered minimums and maximums are hard
  bounds, not additional percentage tolerances. If no plan can satisfy them, ask
  the user which bound to change.
- **Multi-day reporting:** show each day's result and the average across the plan.
  A good weekly average must not conceal a severely outlying day.

For a 2,000 kcal target at the default 5%, the hard range is 1,900-2,100 kcal.
If the user chooses 10%, it becomes 1,800-2,200 kcal. The interface shows the
selected range before planning.

### 9.5 Optimisation approach

Use a deterministic mixed-integer or constraint-programming solver such as
OR-Tools CP-SAT. Candidate variables can represent recipe selection, batch count,
portion size, and allocation.

Hard constraints may include:

- Allergens and strict diet exclusions.
- Meal-slot availability.
- Required household participants.
- Maximum safe leftover age.
- Valid portion and batch increments.
- Equipment that is genuinely unavailable.

Soft objectives may include:

- Daily calorie deviation.
- Protein shortfall or target deviation.
- Carbohydrate and fat range deviation.
- Per-meal calorie distribution.
- Recipe repetition.
- Cuisine and ingredient diversity.
- Reported total recipe time, if later shown to be sufficiently reliable. Active
  cooking time and cook-session optimisation are deferred.
- Pantry and expiring-ingredient use.
- Shopping cost and food waste.
- User ratings and prior feedback.

Do not require exact macro equality. A practical starting policy is calories
within a user-visible tolerance, protein as a minimum or narrow range, and fat and
carbohydrate as ranges. Tolerances must be configurable and visible.

When no feasible plan exists, return a structured explanation of conflicting
constraints and offer specific relaxations. Never silently ignore an allergy or
other hard constraint.

## 10. Shopping-list pipeline

```text
Selected recipes and meal batches
  -> calculate exact batch scale factors
  -> expand recipe ingredient requirements
  -> normalise compatible units and foods
  -> aggregate only genuinely equivalent ingredients
  -> subtract available/reserved pantry stock
  -> convert exact requirements to user-friendly units
  -> optionally round to purchasable pack sizes
  -> assign household-specific aisle categories
  -> generate tickable items while retaining calculation provenance
```

Important rules:

- Only combine quantities that have compatible physical dimensions.
- Do not directly combine `two onions` with `200 g onion` without an approved
  conversion assumption.
- Preserve recipe-level contribution details behind each shopping item.
- Keep optional ingredients visibly optional.
- Permit manual additions and edits without losing them on regeneration.
- Regenerating a plan should show a shopping-list diff rather than unexpectedly
  discarding checked or manual items.
- Pack-size rounding should be a separate step from nutritional calculation.
- Purchase rounding is enabled for whole/countable items and known package sizes.
  Preserve both the exact requirement and rounded purchase suggestion.
- Aisle categories should be customisable per household/store.

## 11. Ingredient-led discovery without recipe generation

The application will not generate recipes or ingredients. Ingredient-led features
mean retrieving real source or custom recipes:

1. **Catalogue retrieval:** find existing recipes containing the requested
   ingredients.
2. **External discovery:** include matching real recipes from supported search
   sources.
3. **Pantry ranking:** rank by maximum use of selected/on-hand ingredients and the
   fewest additional ingredients required.
4. **Strict matching controls:** allow the user to choose between `must contain`,
   `prefer`, and `exclude` for an ingredient.

An LLM fallback may extract quantities and ingredient names that are explicitly
present on a source page. Missing values remain missing and require user review;
the model must not invent them.

## 12. Mealie assessment

Current Mealie documentation and its project repository describe:

- Self-hosted recipe management.
- URL and manual recipe import.
- Meal planning.
- Shopping lists.
- Household use.
- A REST API.
- PostgreSQL fuzzy search support.

Sources:

- [Mealie introduction](https://docs.mealie.io/documentation/getting-started/introduction/)
- [Mealie repository](https://github.com/mealie-recipes/mealie)

Mealie is currently distributed under AGPL-3.0. Any fork, modification, hosted
deployment, or code reuse needs a deliberate licence assessment.

The official material reviewed did not establish that Mealie performs the full
ingredient-to-nutrition calculation proposed here. Treat that nutrition engine,
household macro optimiser, provenance model, and per-person allocation as product
differentiators that require new work.

### Recommendation

Do not decide to fork Mealie before a data-model spike. Options are:

- Build a companion optimiser/integration against Mealie's API for a quick
  personal prototype.
- Build a greenfield application using `recipe-scrapers` and provide Mealie
  import/export compatibility.
- Fork Mealie only if its current models can support recipe versioning,
  field-level provenance, nutrition matches, and person-level portions without
  extensive structural changes.

The current architectural preference is a greenfield modular monolith that reuses
specialised open-source libraries rather than a wholesale Mealie fork.

## 13. Security, privacy, and safety risks

### 13.1 URL ingestion

User-submitted URLs create server-side request forgery and resource-exhaustion
risks. Required controls include:

- Permit only HTTP/HTTPS.
- Resolve and reject private, loopback, link-local, and metadata-service addresses.
- Revalidate every redirect target.
- Limit redirects, response bytes, content types, and total processing time.
- Block unexpected downloads and active content.
- Run headless browsers in an isolated worker with restricted networking.
- Apply per-user and per-domain rate limits.
- Do not allow LLM-produced executable code to run automatically.

### 13.2 Accounts and health-related data

Targets, weights, food restrictions, and household profiles may be sensitive
personal data. Requirements should include:

- Minimal collection and clear purpose.
- Household access controls and role separation.
- Secure password or external identity support.
- Encryption in transit and protected secrets.
- Export and deletion workflows.
- Audit logs for material changes.
- Encrypted backups and tested restores.
- A defined retention policy.
- Privacy and data-protection review before a hosted service.

### 13.3 Nutrition and weight-loss safety

If the tool merely accepts user-entered targets, it should still explain that
recipe nutrition is estimated and not medical advice. If it calculates targets,
additional safeguards are needed for age, pregnancy, eating disorders, relevant
medical conditions, medication, and unusually low calorie goals.

NICE recommends individualised, nutritionally balanced approaches and clinical
support for low-energy and very-low-energy diets:
[NICE overweight and obesity guidance](https://www.nice.org.uk/guidance/ng246/chapter/Physical-activity-and-diet).

Allergies must be hard constraints, but the application must also state that
automatic ingredient classification cannot guarantee absence of allergens or
cross-contamination. Product labels remain authoritative.

#### Specialist-user scope

`Specialist user` does not mean an ordinary household member with a different
calorie target. It means someone whose diet requires clinical or age-specific
logic, for example:

- Children and adolescents.
- Pregnancy or breastfeeding.
- Eating disorders or disordered-eating risk.
- Kidney, liver, or metabolic disease.
- Diabetes where food planning interacts with medication or insulin.
- A prescribed therapeutic diet.

The scope question is whether the application merely accepts that person's
clinician/user-supplied targets or claims to calculate and validate a safe diet for
that condition. The confirmed scope is **general-adult personal planning only**:
accept user-specified targets, enforce declared ingredient exclusions, and make no
medical, paediatric, pregnancy, or therapeutic-diet recommendations. Specialist
planning features are not included.

## 14. Operational data pipelines

### 14.1 Import pipeline states

Suggested states:

```text
queued -> fetching -> extracted -> validating -> awaiting_review
       -> normalising -> nutrition_matching -> ready -> indexed
```

Terminal/error states should use stable error codes, support safe retry, and flow
to a dead-letter/review queue after repeated failures.

### 14.2 Source monitoring

- Maintain representative golden URLs for every supported publisher.
- Run scheduled extraction checks without excessive source traffic.
- Track yield coverage, ingredient count, instruction count, image status, and
  nutrition coverage.
- Alert on sudden completeness changes.
- Version every adapter and extraction result.
- Use per-domain circuit breakers when blocking or failures increase.
- Do not automatically overwrite user edits when a source recipe changes.

### 14.3 Nutrition monitoring

- Record nutrition dataset and release version.
- Recalculate only through explicit jobs, not silently on every read.
- Report match coverage and confidence distributions.
- Keep a review queue for ambiguous foods and material publisher/calculated
  discrepancies.
- Allow a resolved food match to improve future recipes through aliases while
  retaining its review history.

### 14.4 Planner monitoring

- Persist the complete generation input and solver version.
- Record runtime, candidate count, feasibility, relaxations, and objective scores.
- Make plans reproducible where practical.
- Never mutate an accepted plan merely because recipe or food data later changes;
  offer an explicit refresh.

## 15. Architecture recommendation

Recommended initial shape:

- Responsive progressive web application first; native app later only where it
  adds material value.
- Python API and background workers to take advantage of recipe extraction,
  ingredient processing, data, and optimisation libraries.
- PostgreSQL as the system of record, using full-text search and `pg_trgm`.
- Lightweight durable background queue for import, enrichment, and plan jobs.
- Optional object storage for user-owned images and permitted cached assets.
- Docker deployment targeting an Unraid server on the local network. Supply an
  Unraid-friendly template/configuration and persistent volume mappings. A Compose
  file may also be supplied for development and non-Unraid self-hosting.
- Modular monolith with clear modules for recipes, foods, nutrition, planning,
  shopping, search, and identity.

Do not introduce microservices or a separate search cluster until measured load
requires them.

### 15.1 Database decision

**Recommendation: retain PostgreSQL.** The domain is strongly relational:

- Recipes have many ingredient lines and immutable versions.
- Canonical foods appear in many recipes.
- Nutrition matches refer to versioned external dataset records.
- Meal slots, batches, people, and portion allocations form interdependent
  many-to-many relationships.
- Shopping requirements must be traceable back to exact recipe versions and
  batches.
- Accepting a plan and its shopping requirements benefits from transactions and
  referential constraints.

A document/NoSQL database would move these joins and integrity rules into
application code without providing a material advantage for this workload.
Source-specific or irregular extraction payloads can still be held in PostgreSQL
`JSONB` columns alongside the normalised relational data.

SQLite is a credible simpler option for a single-process desktop-only tool. It is
not the current recommendation because the proposed system has concurrent
background imports/nutrition jobs, a web API, possible multi-device use, fuzzy
search, and an eventual app client. PostgreSQL can be bundled in Docker Compose,
so its operational cost is acceptable while avoiding a later migration. Database
access should still go through migrations and a repository/data-access boundary
to preserve future flexibility.

## 16. Testing strategy

### 16.1 Import tests

- Golden URLs and permitted fixtures for every supported source.
- Schema.org variants including `@graph`, multiple recipes, and missing fields.
- Ingredient groups and sub-recipes.
- Fractions, ranges, Unicode units, imperial/metric variants, and package syntax.
- Missing and non-numeric yields.
- Redirect, paywall, blocked, removed, and malicious URLs.

### 16.2 Nutrition tests

- Known ingredient-to-food mappings.
- Dimensional unit conversion.
- Per-recipe and per-serving totals.
- Optional ingredient inclusion.
- Publisher-versus-calculated discrepancy handling.
- Dataset-version reproducibility.

### 16.3 Planner tests

- Property tests ensuring hard restrictions are never violated.
- Multi-person unequal portion allocation.
- Skipped meals under both allowance policies.
- Locked meals and partial regeneration.
- Batch leftovers across dates.
- Infeasible plans and useful explanations.
- Deterministic output with fixed inputs where supported.

### 16.4 Shopping tests

- The 4.5 scale-factor example.
- Combining equivalent foods in compatible units.
- Refusing unsafe cross-dimension aggregation.
- Pantry subtraction.
- Pack rounding.
- Preservation of checked and manual items across regeneration.

### 16.5 Operational tests

- Backup and restore.
- Database migrations and rollback strategy.
- Worker retry and idempotency.
- SSRF and redirect protections.
- Source outage and circuit-breaker behaviour.

## 17. Additional high-value features

These were not all in the initial request but should be considered:

- Lock meals and regenerate the remainder.
- Swap one meal while preserving nutrition and showing a shopping-list diff.
- Multiple snacks or custom meal types.
- Pantry inventory, expiry dates, and `use soon` mode.
- Freezer inventory and leftover tracking.
- Cuisine, seasonal, cultural, and sensory preferences.
- Recipe ratings, favourites, cook history, and `do not suggest again`.
- Recipe scaling warnings where scaling is culinary rather than purely linear.
- Print/export, calendar integration, reminders, and offline shopping mode.
- Barcode scanning for branded pantry products.
- User-owned recipe photos.
- Accessibility and large-touch cook mode.
- Household-specific supermarket aisle order.
- Data export/import, including possible Mealie-compatible formats.

Explicitly deferred or excluded:

- Active cooking-time optimisation is deferred because source coverage is
  inconsistent.
- Budget limits, retailers, and price optimisation belong to a separate future
  concept.
- Equipment restrictions are excluded.
- Generated recipes and generated ingredients are excluded.

## 18. Recommended implementation phases

### Phase 0: feasibility, policy, and data-model spike

- Review publisher terms, robots rules, and licensing directly.
- Test a representative URL set from all three proposed publishers.
- Measure extraction completeness and nutrition coverage.
- Prototype ingredient parsing and nutrition matching.
- Validate the proposed recipe/batch/portion data model.

### Phase 1: trustworthy personal recipe system

- Responsive self-hosted PWA.
- Accounts and household.
- Custom recipe editor.
- User-initiated URL import.
- Import review and correction screen.
- PostgreSQL catalogue and local search.
- Nutrition source display, matching, and manual correction.
- Pantry inventory and pantry subtraction.
- Manual meal calendar.
- Correctly scaled tickable shopping list with exact requirements and practical
  whole-unit/package rounding.

### Phase 2: automatic household planning

- Per-person targets and restrictions.
- Meal-slot calorie allocation.
- Skipped/unplanned meals.
- Batch cooking and leftovers.
- Constraint-based generation.
- Lock, swap, and partial regeneration.
- Explanations and infeasibility handling.

### Phase 3: external discovery

- Only approved publisher connectors or licensed search mechanisms.
- Asynchronous federated search.
- Cached previews, deduplication, and progressive enrichment.
- Live-feeling external search through debounce, cancellation, and cache reuse.
- `Calculate nutrition` on results that lack publisher preview nutrition.
- Import-on-selection.
- Source attribution and policy enforcement.
- Source health monitoring.

### Phase 4: broader intelligence and integrations

- Ingredient-led discovery.
- Pantry and barcode integrations.
- Native mobile app if PWA limitations justify it.

## 19. Outstanding decisions

The private, non-commercial scope; calculated nutrition authority; source-link
instruction policy; batch model; target modes and user-defined tolerances; pantry;
purchase rounding; LAN deployment; general-adult scope; and accepted
recommendations are now settled. The remaining decisions can be deferred until
the relevant feature is designed:

1. Which UK display conventions are preferred for mixed units and countable
   ingredients?
2. Is Mealie import/export interoperability required?

## 20. Initial product acceptance principles

Before automatic planning uses a recipe, it should have:

- A validated positive yield.
- Parsed or explicitly reviewed ingredient quantities sufficient for scaling.
- Calculated nutrition per serving with a valid yield, stated food-data sources,
  and match confidence.
- Known allergen/diet status or an explicit unknown warning.
- A current recipe version and provenance.
- Planner-eligibility approval.

Before a generated plan is accepted, it should:

- Satisfy every hard household restriction.
- Show planned versus unplanned calorie coverage.
- Show daily and per-person nutrition estimates and tolerances.
- State batch sizes and portion allocations.
- Explain significant target deviations.
- Produce a traceable shopping list from the selected recipe versions.
- Remain stable until the user explicitly regenerates or edits it.

## 21. Research sources

Sources consulted during the initial discovery pass:

- [Schema.org Recipe type](https://schema.org/Recipe)
- [Google Recipe structured data](https://developers.google.com/search/docs/appearance/structured-data/recipe)
- [recipe-scrapers documentation](https://docs.recipe-scrapers.com/)
- [recipe-scrapers supported sites](https://docs.recipe-scrapers.com/getting-started/supported-sites/)
- [recipe-scrapers copyright and usage](https://docs.recipe-scrapers.com/copyright-and-usage/)
- [Good Food: About Good Food](https://www.bbcgoodfood.com/about-good-food)
- [Good Food app terms](https://www.bbcgoodfood.com/good-food-app-terms-and-conditions)
- [Good Food recipe sample](https://www.bbcgoodfood.com/recipes/proper-chicken-curry)
- [Great British Chefs terms](https://www.greatbritishchefs.com/terms-and-conditions)
- [Great British Chefs recipe sample](https://www.greatbritishchefs.com/recipes/poulet-breton-recipe)
- [Mealie introduction](https://docs.mealie.io/documentation/getting-started/introduction/)
- [Mealie features](https://docs.mealie.io/documentation/getting-started/features/)
- [Mealie repository](https://github.com/mealie-recipes/mealie)
- [UK Composition of Foods Integrated Dataset](https://www.gov.uk/government/publications/composition-of-foods-integrated-dataset-cofid)
- [USDA FoodData Central API guide](https://fdc.nal.usda.gov/api-guide/)
- [USDA FoodData Central downloads](https://fdc.nal.usda.gov/download-datasets/)
- [Open Food Facts API introduction](https://openfoodfacts.github.io/documentation/docs/Product-Opener/api/)
- [Open Food Facts licensing guidance](https://openfoodfacts.github.io/documentation/docs/Product-Opener/api/tutorials/license-be-on-the-legal-side/)
- [NICE: Physical activity and diet in overweight and obesity management](https://www.nice.org.uk/guidance/ng246/chapter/Physical-activity-and-diet)
- [UK retained Regulation 1169/2011 energy conversion factors](https://www.legislation.gov.uk/eur/2011/1169/pdfs/eur_20111169_2018-01-01_en.pdf)
- [SACN statement on expressing energy, fat, and carbohydrate intakes](https://www.gov.uk/government/publications/sacn-statement-on-expressing-fat-and-carbohydrate-recommendations/sacn-statement-on-expressing-energy-fat-and-carbohydrate-intakes-and-recommendations)
- [MyFitnessPal goal customisation](https://support.myfitnesspal.com/hc/en-us/articles/360032274432-Customize-your-nutritional-goals)
- [Cronometer nutrient-target ranges](https://support.cronometer.com/hc/en-us/articles/360018069532-Nutrient-Targets-Summary)

### Research gaps to revisit

- Direct written permission/licensing options from each proposed publisher.
- Current robots directives and source-specific rate expectations at implementation
  time.
- Allrecipes' applicable current terms and search-page behaviour.
- A representative field-completeness audit across at least 20-30 recipes per
  source and recipe type.
- CoFID licence/attribution implementation details for the intended deployment.
- Open Food Facts ODbL implications for the combined application database.
- Whether a third-party nutrition API is preferable to maintaining a matching
  pipeline, regardless of the application's non-commercial scope.
- Actual Mealie schema/API fit through a local prototype rather than documentation
  review alone.
- Publisher image behaviour, including expiring URLs and hot-link protection.
- UK retailer product, price, and package-size API availability.

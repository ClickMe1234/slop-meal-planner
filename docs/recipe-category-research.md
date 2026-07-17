# Recipe category research

## Outcome

The product uses a reviewed cross-publisher vocabulary rather than exposing either
website's taxonomy directly. The July 2026 sitemap review found 2,303 Good Food
taxonomy URLs and 2,563 Allrecipes category URLs. After normalising spelling,
punctuation, plural forms, and URL wording, 332 labels overlapped exactly. Many
remaining labels were near-matches or very narrow publisher-specific collections.

The first release therefore prioritises broad, useful recipe searches with coverage
on both providers. Order reflects a blend of how often a category appears in the
publisher structures and its usefulness in a household meal-planning search.

| Rank | Product category | Good Food | Allrecipes | Mapping confidence |
| ---: | --- | --- | --- | --- |
| 1 | Healthy | Category page | Category page | High |
| 2 | Dinner / Main dishes | Category page | Category page | High |
| 3 | Quick & Easy | Category page | Category page | High |
| 4 | Breakfast & Brunch | Category page | Category page | High |
| 5 | Vegetarian | Category page | Category page | High |
| 6 | Soups | Category page | Category page | High |
| 7 | Salads | Category page | Category page | High |
| 8 | Desserts | Category page | Category page | High |
| 9 | Snacks / Appetizers | Search fallback | Category page | Medium |
| 10 | Pasta | Category page | Category page | High |
| 11 | Side dishes | Search fallback | Category page | Medium |
| 12 | Budget | Category page | Category page | High |
| 13 | Seafood / Fish | Category page | Category page | High |
| 14 | Lunch | Category page | Category page | High |
| 15 | Stews & Chilli | Search fallback | Category page | Medium |
| 16 | Slow cooker | Category page | Category page | High |
| 17 | One-pot / One-pan | Category page | Category page | High |
| 18 | High-protein | Category page | Search fallback | Medium |

The implementation registry is `backend/app/discovery/categories.py`. Each entry
contains a stable key, display label, raw-tag aliases, and one target per provider.
Changing a label, order, alias, category URL, or fallback query only requires a
registry edit and tests; saved publisher labels remain unchanged in the database.

## Runtime behaviour

- Up to three product categories can be selected, using match-any semantics.
- A text query narrows the category result union; it does not replace the category.
- Provider category pages are cached independently, so combining filters does not
  repeatedly fetch the same page.
- Results from successful providers remain available when another provider or
  category fails.
- Raw `recipeCategory`, `recipeCuisine`, `keywords`, `suitableForDiet`, Parsely
  tags, and structured breadcrumbs are stored for saved recipes.
- Publisher tags are search/display metadata only. They never become planner meal
  types and do not change nutrition, restrictions, or planner eligibility.

## Deliberately deferred

Vegan, chicken, and family-friendly were not included in the initial reviewed set.
They can be added later without a migration by adding registry entries and mappings.
The large publisher inventories are research inputs, not runtime dependencies, which
keeps searches deterministic if a website reorganises its navigation.

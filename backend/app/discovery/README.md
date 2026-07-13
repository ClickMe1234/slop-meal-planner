# Recipe discovery boundary

This package supports Good Food, Great British Chefs, and Allrecipes through small
publisher adapters. An adapter may build an ordinary public search URL and parse
fields already present in returned HTML. It must not log in, solve challenges,
rotate identities, call undocumented private APIs, or otherwise bypass a site's
controls. HTTP 403 and 429 responses are surfaced as limitation errors.

The UI should search PostgreSQL immediately. Remote source search begins only
after the `SearchPolicy.debounce_ms` interval (350 ms by default), is cancellable
through a stable request key, and is cached for 15 minutes. Search displays only
publisher-reported nutrition previews. Ingredient matching and repeatable
nutrition calculation happen after the user chooses a recipe.

All fetched URLs must pass `validate_fetch_url`, including every redirect. The
Docker deployment should additionally deny access from the app container to LAN
and metadata-service address ranges as defence in depth. Site markup and access
rules change; fixture tests make intentional adapter maintenance visible, but do
not guarantee a publisher will continue to permit or expose search.

Recipe-page extraction prefers Schema.org `Recipe` JSON-LD, then uses a limited
semantic HTML fallback. Imports always require review because quantities, ranges,
optional ingredients, units, serving yield, and food-record matches affect the
calculation. Publisher cooking instructions are not copied.

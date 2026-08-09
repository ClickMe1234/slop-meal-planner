# Recipe discovery boundary

This package currently supports Good Food and Allrecipes through small publisher
adapters. Great British Chefs is disabled while its public search is not usable
without client-side or member-only behaviour. An adapter may build an ordinary public search URL and parse
fields already present in returned HTML. It must not log in, solve challenges,
rotate identities, call undocumented private APIs, or otherwise bypass a site's
controls. HTTP 402, 403 and 429 responses are surfaced as limitation errors after
one ordinary cookie-aware retry.

The UI searches PostgreSQL immediately. Remote source search begins only after
the `SearchPolicy.debounce_ms` interval (350 ms by default), is cancellable,
limited by the selected website filters, and cached for 15 minutes. Complete
publisher-reported per-serving nutrition is the only nutrition source used by
automatic planning. Ingredient matching and calculated fallback nutrition are
currently parked.

All fetched URLs must pass `validate_fetch_url`, including every redirect. The
Docker deployment should additionally deny access from the app container to LAN
and metadata-service address ranges as defence in depth. Site markup and access
rules change; fixture tests make intentional adapter maintenance visible, but do
not guarantee a publisher will continue to permit or expose search.

Recipe-page extraction prefers Schema.org `Recipe` JSON-LD, then uses a limited
semantic HTML fallback. Imports retain quantities, ranges, optional ingredients,
units and serving yield for recipe and shopping use, but food-record matches are
not requested. Search never fetches cooking instructions. A separate explicit
method request may extract ordered Schema.org instruction blocks for an
attributed, private recipe-version snapshot.

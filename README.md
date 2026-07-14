# Howard County Building Permits Map

Interactive map of Howard County's monthly "Marketing Analysis Report —
Building" permit reports: clustered pins, full-text search, date and
category filters. Pure static site — no server, no API keys.

## Updating with a new monthly report

1. Download the new PDF from howardcountymd.gov and drop it in
   `pipeline/pdfs/` (any filename).
2. `nix-shell --run "python3 pipeline/build.py"`
3. Commit the regenerated `site/data/permits.js` and
   `pipeline/cache/geocode.json`, redeploy `site/`.

The build fails loudly if parsed records don't reconcile against the
report's own printed totals — never ship a dataset that failed the build.

## Deploying

Copy the `site/` directory to any static host (or open
`site/index.html` directly — it works over `file://`).

## Development

- Pipeline tests: `nix-shell --run "pytest pipeline/tests -v"`
- Frontend filter tests: `nix-shell --run "node --test site/filter.test.js"`
- Design: `docs/plans/2026-07-12-marketing-report-map-design.md`

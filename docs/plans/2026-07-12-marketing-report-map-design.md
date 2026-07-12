# Howard County Marketing Report Map — Design

Date: 2026-07-12
Status: Approved

## Purpose

A public, shareable web map of Howard County's monthly "Marketing Analysis
Report — Building" PDFs (building permits). Community members browse permits
as pins on a map, search all permit text, and filter by date and permit
category.

Example source report:
https://www.howardcountymd.gov/sites/default/files/2026-07/Marketing%20Report%20June%202026.pdf

## Requirements

- Public community site; static files that host anywhere (hosting undecided).
- ~1 year of monthly reports (~320 permits/month, ~4,000 total).
- Map pins with clustering; sidebar with text search, date-range filter, and
  commercial/residential + permit-type filter.
- Single-page app with data embedded; no server, no API keys.
- Updates are manual for now (rerun the pipeline when a new report posts);
  the pipeline must be rerunnable so automation can be added later.

## Source data

Each monthly PDF (~105 pages, ~320 records) lists permits grouped into
Commercial and Residential sections. Per record: permit type, permit #,
property owner, contractor + phone, description of work, subdivision, issue
date, census tract, street address, estimated construction cost, living
units. Reports print their own reconciliation lines (`Sub Total`,
`Total Number of Permits = N`, `Grand Totals = $X`).

The PDFs contain **no coordinates** — addresses must be geocoded.

## Architecture

Two independent halves connected by one generated data file:

```
marketing-report-site/
├── shell.nix               # python3 + pdfplumber + requests + pytest + nodejs
├── pipeline/               # Python, run manually on a dev machine
│   ├── pdfs/               # source PDFs, downloaded manually (committed)
│   ├── parse.py            # PDF → records (pdfplumber)
│   ├── geocode.py          # Census batch geocoder + committed cache
│   ├── build.py            # orchestrator: pdfs/*.pdf → site/data/permits.js
│   └── cache/geocode.json  # normalized address → lat/lng cache (committed)
└── site/                   # the deliverable — copy anywhere to deploy
    ├── index.html
    ├── app.js
    ├── style.css
    ├── vendor/             # Leaflet + Leaflet.markercluster, pinned local copies
    └── data/permits.js     # generated: window.PERMITS = [...]
```

The data file is `permits.js` (assigns `window.PERMITS`) instead of JSON so
the site works when opened via `file://` (no fetch/CORS issues) as well as
from any static host.

### Record schema

```json
{
  "id": "B26000127",
  "type": "Commercial Addition Permit",
  "category": "Commercial",
  "owner": "HOCK/BAVAR STAYTON JOINT",
  "contractor": "COMPLETE CONVERSION SVS INC",
  "phone": "4104933522",
  "description": "BLDG A/ THOR LABS/ EXTERIOR MAINTENANCE STAIRCASE...",
  "issued": "2026-06-11",
  "address": "10335 GUILFORD RD, BLDG A, JESSUP, MD 20794",
  "tract": "606901",
  "cost": 10000,
  "units": 0,
  "lat": 39.1612,
  "lng": -76.7901,
  "geoq": "exact",
  "source": "2026-06"
}
```

- `geoq`: geocode quality — `exact` | `approx` | `failed`. Failed permits
  appear in search/list but have no pin.
- `source`: which monthly report the record came from.
- Size: ~2 MB raw / ~400 KB gzipped per year of data. Embedding is fine.

## Pipeline

1. **Input** — the user downloads monthly report PDFs by hand into
   `pipeline/pdfs/` (any filename; the parser reads the report period from
   the `From Date:` header inside the PDF). `build.py` processes every PDF
   in that directory. Monthly update = drop in one PDF, rerun.
2. **Parse** — `pdfplumber` word coordinates drive column assignment
   (layout-text whitespace splitting is fragile; column boundaries shift
   between pages). Anchors: permit-type line starts a record, `Census Tract`
   line ends the address block, `Est Construction Cost=` closes the record.
3. **Reconcile (integrity gate)** — parsed per-section record counts and
   summed costs must match the report's printed `Sub Total` /
   `Total Number of Permits` / `Grand Totals` lines. Any mismatch fails the
   build loudly. We never silently ship a dataset that dropped permits.
4. **Geocode** — Census Bureau batch geocoder (free, no key, up to 10k
   addresses/request). Returned census tract is cross-checked against the
   report's printed tract. Non-matches retry via Nominatim at 1 req/sec.
   Still-failed → `geoq: "failed"`. Every build prints a quality summary
   (e.g. `3912 exact / 61 approx / 27 failed`). Results cached in
   `cache/geocode.json` keyed by normalized address; reruns only geocode new
   addresses.
5. **Emit** — write `site/data/permits.js`.

## Frontend

Stack: Leaflet + OpenStreetMap tiles + Leaflet.markercluster, vanilla JS,
no build step. Vendor libraries are pinned local copies (no CDN).

**Layout** — left sidebar (~380px), map fills the rest. On mobile the
sidebar collapses to a slide-up panel.

**Sidebar (top to bottom)**
- Search box: as-you-type (debounced), case-insensitive substring match
  across owner, contractor, description, address, subdivision, permit type,
  permit #.
- Date range: two month pickers (from/to), defaulting to full data range.
- Category: All / Commercial / Residential chips + expandable checklist of
  specific permit types.
- Result count with total estimated cost, then scrolling result cards
  (type, address, issue date, cost, owner/contractor).

Filters AND together; every change updates list and pins in the same pass.

**Map** — initial view framed on Howard County. Clustered pins; cluster
bubbles split on zoom. Pin color distinguishes Commercial vs Residential.
Same-address permits spiderfy on click.

**Pin ↔ list linking** — pin click opens a popup (type, permit #, date,
owner, contractor, cost, full description, source report month) and
highlights + scrolls to the sidebar card; card click pans/zooms to the pin
and opens its popup.

**Shareable URLs** — filter state mirrors into the URL hash
(`#q=solar&from=2026-01&to=2026-06&cat=res`) so filtered views can be
shared by copying the address bar.

Ungeocoded permits appear in the list with a "no map location" badge.

## Error handling

- Parser: hard-fail on reconciliation mismatch; individually malformed
  records log permit # + context.
- Geocoding: quality summary every build; failures don't block the build.
  Transient network errors retry; hard outage fails the build rather than
  emitting a half-geocoded dataset.
- Site: missing/malformed `permits.js` shows a visible error instead of a
  blank map. No other runtime failure surface (only network use is map
  tiles; Leaflet degrades gracefully).

## Testing

- **Parser (most important)**: pytest units against committed fixture
  excerpts — wrapped multi-line descriptions, two-line addresses, records
  split across page breaks, both sections. One integration test parses the
  full June 2026 PDF and asserts exactly 320 permits, grand total
  $222,245,719.52, and spot-checks known records field-by-field.
- **Geocoder**: mocked-API tests for cache hit/miss and failure paths; no
  live network in tests.
- **Frontend**: filter logic (search + date + category) is a pure module
  tested with the node test runner. Map/DOM layer verified by browser smoke
  test; no Playwright for v1.

## Out of scope (deliberate)

- Automated monthly updates (pipeline is rerunnable; add cron/Actions later).
- Cost-range filter, "filter to map view", fuzzy search.
- Other county report types (this covers the BUILDING report only).
- Google Maps API / vector-tile stacks — rejected in favor of Leaflet+OSM
  (no keys, no billing, no toolchain).

# Howard County Marketing Report Map — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Static web map of Howard County building-permit reports: Python pipeline turns monthly PDFs into `site/data/permits.js`; a no-build-step Leaflet page renders clustered pins with search, date, and category filters.

**Architecture:** Two independent halves (see `docs/plans/2026-07-12-marketing-report-map-design.md`). The pipeline (pdfplumber column-bucketing parser → reconciliation against the report's printed totals → Census batch geocoder with committed cache) emits one data file. The site is vanilla JS + Leaflet + markercluster loaded as plain scripts so it works over `file://`.

**Tech Stack:** Python 3 (pdfplumber, requests, pytest), Leaflet 1.9.4 + Leaflet.markercluster 1.5.3 (vendored), vanilla JS, node:test for the pure filter module. Nix shell provides all tools.

**Verified facts (from prototyping — do not re-derive):**
- June 2026 PDF (`pipeline/pdfs/2026-06.pdf`, already in repo) parses to exactly **320 records** with summed cost exactly **$222,245,719.52**, matching its printed grand totals. Subtotals: Commercial (56, $201,523,989.00), Residential (264, $20,721,730.52).
- Word column x-positions are stable: type≈20, permit#≈155, owner/address≈227, contractor/phone≈371, description/subdivision≈497, issue date≈686. Page is landscape 792×612.
- **Trap:** permit fields legitimately contain "HOWARD COUNTY" (owner/contractor). A sloppy header filter that skips lines containing "HOWARD COUNTY" silently drops 5 records (B25002340, B25003428, B26001195, B26001853, B26001969). Header/footer filters must match precisely. The integration test guards this.
- Every command below that needs python/node runs inside `nix-shell --run "..."` from the repo root.

---

### Task 1: Scaffolding

**Files:**
- Create: `shell.nix`, `.gitignore`, `pipeline/tests/conftest.py`

**Step 1: Write `shell.nix`**

```nix
{ pkgs ? import <nixpkgs> {} }:
pkgs.mkShell {
  packages = [
    (pkgs.python3.withPackages (ps: [ ps.pdfplumber ps.requests ps.pytest ]))
    pkgs.nodejs
  ];
}
```

**Step 2: Write `.gitignore`**

```
__pycache__/
.pytest_cache/
```

**Step 3: Write `pipeline/tests/conftest.py`**

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
```

**Step 4: Verify the shell works**

Run: `nix-shell --run "python3 -c 'import pdfplumber, requests, pytest' && node --version"`
Expected: node version prints, no import errors.

**Step 5: Commit**

```bash
git add shell.nix .gitignore pipeline/tests/conftest.py pipeline/pdfs/2026-06.pdf
git commit -m "chore: scaffolding — nix shell, gitignore, June 2026 source PDF"
```

---

### Task 2: Parser — line grouping and column bucketing

**Files:**
- Create: `pipeline/parse.py`
- Test: `pipeline/tests/test_parse.py`

**Step 1: Write the failing test**

```python
from parse import lines_from_words


def w(x0, top, text):
    return {"x0": x0, "top": top, "text": text}


def test_words_group_into_lines_by_top_and_bucket_by_column():
    words = [
        w(20.0, 165.4, "Commercial"), w(69.1, 165.4, "Addition"),
        w(104.3, 165.4, "Permit"), w(155.0, 165.4, "B26000127"),
        w(227.0, 164.6, "HOCK/BAVAR"), w(288.5, 164.6, "STAYTON"),
        w(371.0, 164.6, "COMPLETE"), w(497.0, 164.6, "BLDG"),
        w(686.0, 164.6, "6/11/2026"),
    ]
    lines = lines_from_words(words)
    assert len(lines) == 1  # 164.6 and 165.4 are the same visual line
    line = lines[0]
    assert line["type"] == "Commercial Addition Permit"
    assert line["permit"] == "B26000127"
    assert line["owner_addr"] == "HOCK/BAVAR STAYTON"
    assert line["contractor"] == "COMPLETE"
    assert line["desc"] == "BLDG"
    assert line["date"] == "6/11/2026"


def test_separate_lines_stay_separate():
    words = [w(20.0, 100.0, "Commercial"), w(20.0, 120.0, "Residential")]
    lines = lines_from_words(words)
    assert [l["type"] for l in lines] == ["Commercial", "Residential"]
```

**Step 2: Run test to verify it fails**

Run: `nix-shell --run "pytest pipeline/tests/test_parse.py -v"`
Expected: FAIL — `ModuleNotFoundError: No module named 'parse'`

**Step 3: Write the implementation**

`pipeline/parse.py`:

```python
"""Parse Howard County 'Marketing Analysis Report - Building' PDFs."""
import re

# Column buckets by word x0 (verified against the June 2026 report).
COLS = [
    ("type", 0, 150),        # Permit Type
    ("permit", 150, 222),    # Permit #
    ("owner_addr", 222, 366),  # Property Owner / Address of Site
    ("contractor", 366, 492),  # Name of Contractor / Contractor Phone
    ("desc", 492, 660),      # Description of Work / Subdivision
    ("date", 660, 800),      # Issue Date / Planning Area
]


def lines_from_words(words):
    """Group words into visual lines (3pt top tolerance), bucket by column."""
    rows = {}
    for word in words:
        rows.setdefault(round(word["top"] / 3), []).append(word)
    lines = []
    for key in sorted(rows):
        cols = {name: [] for name, _, _ in COLS}
        for word in sorted(rows[key], key=lambda w: w["x0"]):
            for name, lo, hi in COLS:
                if lo <= word["x0"] < hi:
                    cols[name].append(word["text"])
                    break
        lines.append({name: " ".join(texts) for name, texts in cols.items()})
    return lines
```

**Step 4: Run test to verify it passes**

Run: `nix-shell --run "pytest pipeline/tests/test_parse.py -v"`
Expected: 2 passed

**Step 5: Commit**

```bash
git add pipeline/parse.py pipeline/tests/test_parse.py
git commit -m "feat: parser line grouping and column bucketing"
```

---

### Task 3: Parser — full record extraction (integration test against real PDF)

**Files:**
- Modify: `pipeline/parse.py`
- Test: `pipeline/tests/test_parse.py`

**Step 1: Write the failing integration test** (append to `test_parse.py`)

```python
from pathlib import Path

import pytest

from parse import parse_pdf

PDF = Path(__file__).resolve().parent.parent / "pdfs" / "2026-06.pdf"


@pytest.fixture(scope="module")
def june():
    return parse_pdf(PDF)


def test_parses_every_record(june):
    assert len(june.records) == 320
    assert june.grand == (320, 222245719.52)
    assert june.subtotals == [(56, 201523989.00), (264, 20721730.52)]
    assert june.period == "2026-06"


def test_summed_costs_match_grand_total(june):
    assert round(sum(r["cost"] for r in june.records), 2) == 222245719.52


def test_first_record_fields(june):
    r = june.records[0]
    assert r["id"] == "B26000127"
    assert r["type"] == "Commercial Addition Permit"
    assert r["category"] == "Commercial"
    assert r["owner"] == "HOCK/BAVAR STAYTON JOINT"
    assert r["contractor"] == "COMPLETE CONVERSION SVS INC"
    assert r["phone"] == "4104933522"
    assert r["issued"] == "6/11/2026"
    assert r["address"] == ["10335 GUILFORD RD, BLDG A", "JESSUP, MD 20794"]
    assert r["tract"] == "606901"
    assert r["cost"] == 10000.0
    assert r["units"] == 0


def test_last_record_fields(june):
    r = june.records[-1]
    assert r["id"] == "B26002234"
    assert r["type"] == "Solar Express (Residential Only)"
    assert r["category"] == "Residential"
    assert r["cost"] == 17449.60
    assert r["tract"] == "602304"


def test_records_owned_by_howard_county_are_not_dropped(june):
    """Regression: header filter must not eat records containing 'HOWARD COUNTY'."""
    ids = {r["id"] for r in june.records}
    assert {"B25002340", "B25003428", "B26001195",
            "B26001853", "B26001969"} <= ids


def test_wrapped_owner_and_type_continuations(june):
    by_id = {r["id"]: r for r in june.records}
    assert by_id["B25002340"]["owner"] == "BOARD OF EDUCATION OF HO CO"
    assert by_id["B26001195"]["type"] == "Commercial Miscellaneous Permit"


def test_every_record_is_complete(june):
    for r in june.records:
        assert r["cost"] is not None, r["id"]
        assert r["issued"], r["id"]
        assert r["address"], r["id"]
        assert r["tract"], r["id"]
        assert r["category"] in ("Commercial", "Residential"), r["id"]
```

**Step 2: Run to verify failure**

Run: `nix-shell --run "pytest pipeline/tests/test_parse.py -v"`
Expected: FAIL — `ImportError: cannot import name 'parse_pdf'`

**Step 3: Implement record extraction** (append to `pipeline/parse.py`)

This state machine is validated against the real PDF — implement it as written.

```python
from dataclasses import dataclass

import pdfplumber

PERMIT_RE = re.compile(r"^[A-Z]\d{8}$")
COST_RE = re.compile(r"Est Construction Cost=\s*\$([\d,.]+)")
UNITS_RE = re.compile(r"# of Living Units\s*=\s*(\d+)")
TRACT_RE = re.compile(r"Census Tract\s+(\d+)")
SUBTOTAL_RE = re.compile(r"Sub Total\s*=\s*(\d+)\s+Totals\s*=\s*\$([\d,.]+)")
GRAND_RE = re.compile(
    r"Total Number of Permits\s*=\s*(\d+)\s+Grand Totals\s*=\s*\$([\d,.]+)")
PERIOD_RE = re.compile(r"From Date:\s*(\d{1,2})/\d{1,2}/(\d{4})")


class ParseError(Exception):
    pass


@dataclass
class ParseResult:
    records: list
    subtotals: list   # [(count, dollars), ...] per section
    grand: tuple      # (count, dollars)
    period: str       # "YYYY-MM"


def _money(s):
    return float(s.replace(",", ""))


def _is_header_or_footer(text, line):
    # Precise matches only — permit fields legitimately contain
    # "HOWARD COUNTY" as owner/contractor (see B25002340 et al.).
    return (text == "HOWARD COUNTY - DILP"
            or "MARKETING ANALYSIS REPORT" in text
            or ("Property Owner" in text and "Name of Contractor" in text)
            or line["type"] == "Permit Type"
            or text.startswith("Print Date:"))


def parse_pdf(path):
    records, subtotals = [], []
    grand = period = None
    cur = None
    category = None
    in_address = False  # once Census Tract seen, owner_addr col = address

    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for line in lines_from_words(page.extract_words()):
                text = " ".join(v for v in line.values() if v)
                if not text:
                    continue
                if text.startswith("From Date:"):
                    m = PERIOD_RE.search(text)
                    if m and not period:
                        period = f"{m.group(2)}-{int(m.group(1)):02d}"
                    continue
                if _is_header_or_footer(text, line):
                    continue
                m = GRAND_RE.search(text)
                if m:
                    grand = (int(m.group(1)), _money(m.group(2)))
                    continue
                m = SUBTOTAL_RE.search(text)
                if m:
                    subtotals.append((int(m.group(1)), _money(m.group(2))))
                    continue
                if text in ("Commercial", "Residential"):
                    category = text
                    continue
                if PERMIT_RE.match(line["permit"]):
                    if cur is not None:
                        raise ParseError(
                            f"record {cur['id']} never closed before "
                            f"{line['permit']} started")
                    cur = {
                        "category": category,
                        "type": line["type"],
                        "id": line["permit"],
                        "owner": line["owner_addr"],
                        "contractor": line["contractor"],
                        "phone": "",
                        "desc": line["desc"],
                        "issued": line["date"],
                        "address": [],
                        "tract": None,
                        "cost": None,
                        "units": None,
                    }
                    in_address = False
                    continue
                if cur is None:
                    continue
                m = TRACT_RE.search(text)
                if m:
                    cur["tract"] = m.group(1)
                    in_address = True
                    if line["owner_addr"]:
                        cur["address"].append(line["owner_addr"])
                    if line["contractor"]:
                        cur["phone"] += line["contractor"]
                    continue
                m = COST_RE.search(text)
                if m:
                    cur["cost"] = _money(m.group(1))
                    mu = UNITS_RE.search(text)
                    if mu:
                        cur["units"] = int(mu.group(1))
                    records.append(cur)
                    cur = None
                    continue
                # Continuation lines for an open record
                if line["type"] and cur["type"]:
                    cur["type"] += " " + line["type"]
                if in_address:
                    if line["owner_addr"]:
                        cur["address"].append(line["owner_addr"])
                    if line["contractor"]:
                        cur["phone"] += line["contractor"]
                else:
                    if line["owner_addr"]:
                        cur["owner"] += " " + line["owner_addr"]
                    if line["contractor"]:
                        cur["contractor"] += " " + line["contractor"]
                if line["desc"]:
                    cur["desc"] += " " + line["desc"]
                if line["date"] and not cur["issued"]:
                    cur["issued"] = line["date"]

    if cur is not None:
        raise ParseError(f"record {cur['id']} still open at end of document")
    if grand is None or period is None:
        raise ParseError("missing grand totals or From Date header")
    return ParseResult(records, subtotals, grand, period)
```

**Step 4: Run to verify it passes**

Run: `nix-shell --run "pytest pipeline/tests/test_parse.py -v"`
Expected: all pass (integration takes ~30s; that's fine)

**Step 5: Commit**

```bash
git add pipeline/parse.py pipeline/tests/test_parse.py
git commit -m "feat: full permit record extraction, verified against June 2026 report"
```

---

### Task 4: Parser — reconciliation gate

**Files:**
- Modify: `pipeline/parse.py`
- Test: `pipeline/tests/test_parse.py`

**Step 1: Write the failing tests** (append)

```python
from parse import ParseError, ParseResult, reconcile


def _result(records, subtotals, grand):
    return ParseResult(records, subtotals, grand, "2026-06")


def _rec(cost):
    return {"id": "B00000000", "cost": cost}


def test_reconcile_passes_when_totals_match():
    reconcile(_result([_rec(100.0), _rec(50.5)], [(2, 150.5)], (2, 150.5)))


def test_reconcile_fails_on_count_mismatch():
    with pytest.raises(ParseError, match="count"):
        reconcile(_result([_rec(100.0)], [(2, 100.0)], (2, 100.0)))


def test_reconcile_fails_on_cost_mismatch():
    with pytest.raises(ParseError, match="cost"):
        reconcile(_result([_rec(100.0)], [(1, 999.0)], (1, 999.0)))


def test_reconcile_fails_on_subtotal_count_mismatch():
    with pytest.raises(ParseError, match="subtotal"):
        reconcile(_result([_rec(100.0)], [(2, 100.0)], (1, 100.0)))


def test_june_reconciles(june):
    reconcile(june)
```

**Step 2: Run to verify failure**

Run: `nix-shell --run "pytest pipeline/tests/test_parse.py -k reconcile -v"`
Expected: FAIL — `ImportError: cannot import name 'reconcile'`

**Step 3: Implement** (append to `parse.py`)

```python
def reconcile(result):
    """Fail loudly if parsed records don't match the report's own totals."""
    count, total = result.grand
    if len(result.records) != count:
        raise ParseError(
            f"count mismatch: parsed {len(result.records)} records, "
            f"report says {count}")
    parsed_cost = round(sum(r["cost"] for r in result.records), 2)
    if abs(parsed_cost - total) > 0.01:
        raise ParseError(
            f"cost mismatch: parsed ${parsed_cost:,.2f}, "
            f"report says ${total:,.2f}")
    sub_count = sum(c for c, _ in result.subtotals)
    if sub_count != count:
        raise ParseError(
            f"subtotal counts sum to {sub_count}, grand total says {count}")
```

**Step 4: Run to verify pass**

Run: `nix-shell --run "pytest pipeline/tests/test_parse.py -v"`
Expected: all pass

**Step 5: Commit**

```bash
git add pipeline/parse.py pipeline/tests/test_parse.py
git commit -m "feat: reconciliation gate against report's printed totals"
```

### Amendment (2026-07-12, after Task 4 review)

Gate strengthening authorized by the plan owner following code review
(the "never weaken the reconciliation gate" note below is upheld — these
changes only tighten it):

- **Strict cent equality.** The `abs(parsed_cost - total) > 0.01`
  tolerance was replaced with strict equality on rounded cents
  (`parsed_cost != round(total, 2)`). A record off by exactly $0.01 now
  fails reconciliation; previously it slipped through.
- **Category-tagged subtotals.** `ParseResult.subtotals` entries are now
  `(category, count, dollars)` triples (tagged with the section they
  close), and `ParseResult` gained a `sections` field listing each
  "Commercial"/"Residential" section header line seen, in order.
  `reconcile` additionally checks: subtotal dollars sum to the grand
  total (strict, rounded cents); the number of subtotal lines equals the
  number of section headers seen (catches a future PDF whose header line
  gains extra text and stops matching — records would silently inherit
  the stale category); and per-category record counts and summed costs
  match that category's subtotal(s) (strict, rounded cents,
  order-agnostic — Mar/Apr/May list Residential first).
- **Downstream note.** Task 8's `build.py` consumes `ParseResult`; it
  must use the new `(category, count, dollars)` subtotal shape (and may
  rely on `sections`).

All six months (Jan–Jun 2026) reconcile under the strict checks.

---

### Task 5: Parser — record normalization

**Files:**
- Modify: `pipeline/parse.py`
- Test: `pipeline/tests/test_parse.py`

**Step 1: Failing tests** (append)

```python
from parse import normalize


def test_normalize_shapes_final_record():
    raw = {
        "id": "B26000127", "type": "Commercial Addition Permit",
        "category": "Commercial", "owner": "HOCK/BAVAR STAYTON JOINT",
        "contractor": "COMPLETE CONVERSION SVS INC", "phone": "4104933522",
        "desc": "BLDG A/ THOR LABS", "issued": "6/11/2026",
        "address": ["10335 GUILFORD RD, BLDG A", "JESSUP, MD 20794"],
        "tract": "606901", "cost": 10000.0, "units": 0,
    }
    n = normalize(raw, "2026-06")
    assert n["issued"] == "2026-06-11"
    assert n["address"] == "10335 GUILFORD RD, BLDG A, JESSUP, MD 20794"
    assert n["description"] == "BLDG A/ THOR LABS"
    assert n["source"] == "2026-06"
    assert n["cost"] == 10000.0
    assert "desc" not in n


def test_normalize_joins_wrapped_street_lines_with_spaces():
    raw = {
        "id": "B26002234", "type": "T", "category": "Residential",
        "owner": "O", "contractor": "", "phone": "", "desc": "D",
        "issued": "6/30/2026",
        "address": ["9891 BALTIMORE NATIONAL", "PIKE",
                    "ELLICOTT CITY, MD 21042"],
        "tract": "602304", "cost": 1.0, "units": 0,
    }
    n = normalize(raw, "2026-06")
    assert n["address"] == "9891 BALTIMORE NATIONAL PIKE, ELLICOTT CITY, MD 21042"
```

**Step 2: Run to verify failure**

Run: `nix-shell --run "pytest pipeline/tests/test_parse.py -k normalize -v"`
Expected: FAIL — ImportError

**Step 3: Implement** (append to `parse.py`)

```python
def normalize(raw, period):
    """Shape a parsed record for the site data file."""
    month, day, year = raw["issued"].split("/")
    lines = raw["address"]
    street = " ".join(lines[:-1]) if len(lines) > 1 else lines[0]
    address = f"{street}, {lines[-1]}" if len(lines) > 1 else street
    return {
        "id": raw["id"],
        "type": raw["type"],
        "category": raw["category"],
        "owner": raw["owner"],
        "contractor": raw["contractor"],
        "phone": raw["phone"],
        "description": raw["desc"],
        "issued": f"{year}-{int(month):02d}-{int(day):02d}",
        "address": address,
        "tract": raw["tract"],
        "cost": raw["cost"],
        "units": raw["units"],
        "source": period,
    }
```

**Step 4: Run to verify pass**

Run: `nix-shell --run "pytest pipeline/tests/test_parse.py -v"`
Expected: all pass

**Step 5: Commit**

```bash
git add pipeline/parse.py pipeline/tests/test_parse.py
git commit -m "feat: record normalization (ISO dates, joined addresses)"
```

---

### Task 6: Geocoder — address splitting

**Files:**
- Create: `pipeline/geocode.py`
- Test: `pipeline/tests/test_geocode.py`

**Step 1: Failing tests**

```python
from geocode import split_address


def test_splits_simple_address():
    assert split_address("9660 BASKET RING RD, COLUMBIA, MD 21045") == \
        ("9660 BASKET RING RD", "COLUMBIA", "21045")


def test_street_may_itself_contain_commas():
    assert split_address("10335 GUILFORD RD, BLDG A, JESSUP, MD 20794") == \
        ("10335 GUILFORD RD, BLDG A", "JESSUP", "20794")


def test_zip_plus_four():
    assert split_address("1 MAIN ST, LAUREL, MD 20723-1234") == \
        ("1 MAIN ST", "LAUREL", "20723")


def test_unsplittable_returns_none():
    assert split_address("NO ZIP HERE") is None
```

**Step 2: Run to verify failure**

Run: `nix-shell --run "pytest pipeline/tests/test_geocode.py -v"`
Expected: FAIL — ModuleNotFoundError

**Step 3: Implement**

`pipeline/geocode.py`:

```python
"""Geocode permit addresses: Census batch API, Nominatim fallback, JSON cache."""
import re

ADDR_RE = re.compile(
    r"^(?P<street>.+),\s*(?P<city>[^,]+),\s*MD\s*(?P<zip>\d{5})(-\d{4})?$")


def split_address(address):
    m = ADDR_RE.match(address)
    if not m:
        return None
    return m.group("street"), m.group("city"), m.group("zip")
```

**Step 4: Run to verify pass** — same command, 4 passed.

**Step 5: Commit**

```bash
git add pipeline/geocode.py pipeline/tests/test_geocode.py
git commit -m "feat: geocoder address splitting"
```

---

### Task 7: Geocoder — Census batch + cache

**Files:**
- Modify: `pipeline/geocode.py`
- Test: `pipeline/tests/test_geocode.py`

The Census batch endpoint: POST to
`https://geocoding.geo.census.gov/geocoder/geographies/addressbatch` with
form data `benchmark=Public_AR_Current`, `vintage=Current_Current` and a CSV
file field `addressFile` of rows `id,street,city,state,zip`. The response is
CSV; matched rows carry `Match`, `Exact|Non_Exact`, the matched address,
`"lng,lat"` as one field, then tiger id, side, state FIPS, county FIPS,
**tract**, block.

**Step 1: Failing tests** (append to `test_geocode.py`)

```python
import json

from geocode import geocode_all

CENSUS_ROW = ('"0","10335 GUILFORD RD, JESSUP, MD, 20794","Match","Exact",'
              '"10335 GUILFORD RD, JESSUP, MD, 20794","-76.79123,39.16456",'
              '"647266","L","24","027","606901","2004"')
NO_MATCH_ROW = '"1","1 NOWHERE LN, X, MD, 00000","No_Match"'


class FakeResponse:
    def __init__(self, text="", payload=None):
        self.text = text
        self._payload = payload or []

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


def test_census_match_is_cached_with_quality(tmp_path, monkeypatch):
    cache = tmp_path / "geocode.json"
    posts = []

    def fake_post(url, data=None, files=None, timeout=None):
        posts.append(url)
        return FakeResponse(text=CENSUS_ROW)

    monkeypatch.setattr("geocode.requests.post", fake_post)
    result = geocode_all(["10335 GUILFORD RD, JESSUP, MD 20794"], cache)
    entry = result["10335 GUILFORD RD, JESSUP, MD 20794"]
    assert entry["quality"] == "exact"
    assert entry["lat"] == 39.16456
    assert entry["lng"] == -76.79123
    assert entry["tract"] == "606901"
    assert len(posts) == 1
    assert json.loads(cache.read_text())  # persisted


def test_cached_addresses_skip_the_network(tmp_path, monkeypatch):
    cache = tmp_path / "geocode.json"
    cache.write_text(json.dumps({
        "10335 GUILFORD RD, JESSUP, MD 20794":
            {"lat": 1.0, "lng": 2.0, "quality": "exact", "tract": "606901"}}))

    def boom(*a, **k):
        raise AssertionError("network hit for cached address")

    monkeypatch.setattr("geocode.requests.post", boom)
    result = geocode_all(["10335 GUILFORD RD, JESSUP, MD 20794"], cache)
    assert result["10335 GUILFORD RD, JESSUP, MD 20794"]["lat"] == 1.0


def test_no_match_falls_back_to_nominatim(tmp_path, monkeypatch):
    cache = tmp_path / "geocode.json"
    monkeypatch.setattr("geocode.requests.post",
                        lambda *a, **k: FakeResponse(text=NO_MATCH_ROW))
    monkeypatch.setattr("geocode.requests.get",
                        lambda *a, **k: FakeResponse(
                            payload=[{"lat": "39.2", "lon": "-76.8"}]))
    monkeypatch.setattr("geocode.time.sleep", lambda s: None)
    result = geocode_all(["1 NOWHERE LN, X, MD 00000"], cache)
    entry = result["1 NOWHERE LN, X, MD 00000"]
    assert entry["quality"] == "approx"
    assert entry["lat"] == 39.2


def test_total_failure_is_cached_as_failed(tmp_path, monkeypatch):
    cache = tmp_path / "geocode.json"
    monkeypatch.setattr("geocode.requests.post",
                        lambda *a, **k: FakeResponse(text=NO_MATCH_ROW))
    monkeypatch.setattr("geocode.requests.get",
                        lambda *a, **k: FakeResponse(payload=[]))
    monkeypatch.setattr("geocode.time.sleep", lambda s: None)
    result = geocode_all(["1 NOWHERE LN, X, MD 00000"], cache)
    assert result["1 NOWHERE LN, X, MD 00000"] == {"quality": "failed"}


def test_unsplittable_address_fails_without_network(tmp_path, monkeypatch):
    cache = tmp_path / "geocode.json"
    monkeypatch.setattr("geocode.requests.get",
                        lambda *a, **k: FakeResponse(payload=[]))
    monkeypatch.setattr("geocode.time.sleep", lambda s: None)
    result = geocode_all(["GIBBERISH"], cache)
    assert result["GIBBERISH"]["quality"] == "failed"
```

**Step 2: Run to verify failure** — ImportError on `geocode_all`.

**Step 3: Implement** (append to `geocode.py`)

```python
import csv
import io
import json
import time

import requests

CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/geographies/addressbatch"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "howard-county-permit-map/1.0"}
BATCH_SIZE = 5000


def _census_batch(addresses):
    """One batch call. Returns {address: entry} for matches only."""
    rows = io.StringIO()
    writer = csv.writer(rows)
    indexed = []
    for addr in addresses:
        parts = split_address(addr)
        if parts:
            writer.writerow([len(indexed), *parts[:2], "MD", parts[2]])
            indexed.append(addr)
    if not indexed:
        return {}
    resp = requests.post(
        CENSUS_URL,
        data={"benchmark": "Public_AR_Current", "vintage": "Current_Current"},
        files={"addressFile": ("addresses.csv", rows.getvalue())},
        timeout=300)
    resp.raise_for_status()
    out = {}
    for row in csv.reader(io.StringIO(resp.text)):
        if len(row) < 12 or row[2] != "Match":
            continue
        lng, lat = (float(v) for v in row[5].split(","))
        out[indexed[int(row[0])]] = {
            "lat": lat, "lng": lng,
            "quality": "exact" if row[3] == "Exact" else "approx",
            "tract": row[10],
        }
    return out


def _nominatim(address):
    resp = requests.get(
        NOMINATIM_URL,
        params={"q": address, "format": "json", "limit": 1},
        headers=HEADERS, timeout=30)
    resp.raise_for_status()
    hits = resp.json()
    if not hits:
        return None
    return {"lat": float(hits[0]["lat"]), "lng": float(hits[0]["lon"]),
            "quality": "approx", "tract": None}


def geocode_all(addresses, cache_path):
    """Geocode every address, using and updating the JSON cache."""
    cache = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text())
    todo = sorted({a for a in addresses if a not in cache})

    for i in range(0, len(todo), BATCH_SIZE):
        batch = todo[i:i + BATCH_SIZE]
        matched = _census_batch(batch)
        for addr in batch:
            if addr in matched:
                cache[addr] = matched[addr]
        for addr in batch:
            if addr in cache:
                continue
            time.sleep(1.1)  # Nominatim usage policy: max 1 req/sec
            hit = _nominatim(addr)
            cache[addr] = hit if hit else {"quality": "failed"}

    if todo:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, indent=1, sort_keys=True))
    return cache
```

**Step 4: Run to verify pass**

Run: `nix-shell --run "pytest pipeline/tests/test_geocode.py -v"`
Expected: all pass

**Step 5: Commit**

```bash
git add pipeline/geocode.py pipeline/tests/test_geocode.py
git commit -m "feat: Census batch geocoding with cache and Nominatim fallback"
```

---

### Task 8: build.py — orchestrate and emit permits.js

**Files:**
- Create: `pipeline/build.py`
- Test: `pipeline/tests/test_build.py`

**Step 1: Failing tests**

```python
import json

from build import assemble, emit


def _permit(id_, issued, address, tract="606901"):
    return {"id": id_, "type": "T", "category": "Commercial", "owner": "O",
            "contractor": "C", "phone": "", "description": "D",
            "issued": issued, "address": address, "tract": tract,
            "cost": 1.0, "units": 0, "source": issued[:7]}


GEO = {"A ST, X, MD 11111": {"lat": 39.1, "lng": -76.9,
                             "quality": "exact", "tract": "606901"},
       "B ST, X, MD 11111": {"quality": "failed"}}


def test_assemble_attaches_coordinates_and_sorts_by_date():
    records = assemble(
        [_permit("B2", "2026-06-15", "B ST, X, MD 11111"),
         _permit("B1", "2026-06-02", "A ST, X, MD 11111")], GEO)
    assert [r["id"] for r in records] == ["B1", "B2"]
    assert records[0]["lat"] == 39.1
    assert records[0]["geoq"] == "exact"
    assert "lat" not in records[1]
    assert records[1]["geoq"] == "failed"


def test_tract_disagreement_downgrades_quality():
    records = assemble(
        [_permit("B1", "2026-06-02", "A ST, X, MD 11111", tract="999999")],
        GEO)
    assert records[0]["geoq"] == "approx"


def test_emit_writes_loadable_js(tmp_path):
    out = tmp_path / "permits.js"
    emit([{"id": "B1"}], out)
    text = out.read_text()
    assert text.startswith("window.PERMITS=")
    assert json.loads(text.removeprefix("window.PERMITS=").rstrip(";\n")) == \
        [{"id": "B1"}]
```

**Step 2: Run to verify failure**

Run: `nix-shell --run "pytest pipeline/tests/test_build.py -v"`
Expected: FAIL — ModuleNotFoundError

**Step 3: Implement**

`pipeline/build.py`:

```python
"""Build site/data/permits.js from every PDF in pipeline/pdfs/."""
import json
import sys
from collections import Counter
from pathlib import Path

from geocode import geocode_all
from parse import normalize, parse_pdf, reconcile

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache" / "geocode.json"
OUT = ROOT.parent / "site" / "data" / "permits.js"


def assemble(records, geo):
    """Attach lat/lng/geoq to normalized records; sort by issue date."""
    out = []
    for r in sorted(records, key=lambda r: (r["issued"], r["id"])):
        r = dict(r)
        entry = geo.get(r["address"], {"quality": "failed"})
        quality = entry["quality"]
        if quality != "failed":
            r["lat"] = entry["lat"]
            r["lng"] = entry["lng"]
            if entry.get("tract") and entry["tract"] != r["tract"]:
                quality = "approx"
        r["geoq"] = quality
        out.append(r)
    return out


def emit(records, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(records, separators=(",", ":"), ensure_ascii=False)
    path.write_text(f"window.PERMITS={body};\n")


def main():
    pdfs = sorted((ROOT / "pdfs").glob("*.pdf"))
    if not pdfs:
        sys.exit("no PDFs in pipeline/pdfs/")
    records = []
    for pdf in pdfs:
        result = parse_pdf(pdf)
        reconcile(result)
        records.extend(normalize(r, result.period) for r in result.records)
        print(f"{pdf.name}: {len(result.records)} permits "
              f"({result.period}), reconciled OK")
    geo = geocode_all([r["address"] for r in records], CACHE)
    final = assemble(records, geo)
    emit(final, OUT)
    counts = Counter(r["geoq"] for r in final)
    print(f"wrote {OUT.relative_to(ROOT.parent)}: {len(final)} permits — "
          f"{counts.get('exact', 0)} exact / {counts.get('approx', 0)} approx"
          f" / {counts.get('failed', 0)} failed")


if __name__ == "__main__":
    main()
```

**Step 4: Run to verify pass**

Run: `nix-shell --run "pytest pipeline/tests -v"`
Expected: all pass

**Step 5: Commit**

```bash
git add pipeline/build.py pipeline/tests/test_build.py
git commit -m "feat: build orchestrator emitting site/data/permits.js"
```

---

### Task 9: Run the real pipeline

**Files:**
- Create (generated): `site/data/permits.js`, `pipeline/cache/geocode.json`

**Step 1: Run the pipeline** (network: Census + possibly Nominatim; June alone is ~300 unique addresses, one batch call)

Run: `nix-shell --run "python3 pipeline/build.py"`
Expected output shape:
```
2026-06.pdf: 320 permits (2026-06), reconciled OK
wrote site/data/permits.js: 320 permits — ~300 exact / ~15 approx / ~5 failed
```
If more month PDFs are in `pipeline/pdfs/` by now (the user is downloading them), each appears as its own reconciled line. **If any PDF fails reconciliation, stop and investigate the parser — do not relax the gate.**

**Step 2: Sanity-check the output**

Run: `nix-shell --run "python3 -c \"import json; d=json.loads(open('site/data/permits.js').read().removeprefix('window.PERMITS=').rstrip(';\\n')); print(len(d), d[0]['id'], d[0].get('geoq'))\""`
Expected: record count, an id, a geoq value.

**Step 3: Commit**

```bash
git add site/data/permits.js pipeline/cache/geocode.json
git commit -m "data: build permits dataset from available reports"
```

---

### Task 10: Vendor Leaflet and markercluster

**Files:**
- Create: `site/vendor/leaflet.js`, `site/vendor/leaflet.css`, `site/vendor/leaflet.markercluster.js`, `site/vendor/MarkerCluster.css`, `site/vendor/MarkerCluster.Default.css`

**Step 1: Download pinned versions**

```bash
mkdir -p site/vendor
curl -fsSL -o site/vendor/leaflet.js  https://unpkg.com/leaflet@1.9.4/dist/leaflet.js
curl -fsSL -o site/vendor/leaflet.css https://unpkg.com/leaflet@1.9.4/dist/leaflet.css
curl -fsSL -o site/vendor/leaflet.markercluster.js https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js
curl -fsSL -o site/vendor/MarkerCluster.css https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css
curl -fsSL -o site/vendor/MarkerCluster.Default.css https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css
```

(No marker image assets needed — pins are `L.circleMarker`, clusters are CSS div icons.)

**Step 2: Verify**

Run: `ls -la site/vendor/ && head -c 100 site/vendor/leaflet.js`
Expected: five non-empty files; leaflet.js starts with its license banner.

**Step 3: Commit**

```bash
git add site/vendor
git commit -m "chore: vendor leaflet 1.9.4 and markercluster 1.5.3"
```

---

### Task 11: filter.js — pure filter/hash module (node:test)

**Files:**
- Create: `site/filter.js`
- Test: `site/filter.test.js`

**Step 1: Failing tests**

`site/filter.test.js`:

```js
"use strict";
const test = require("node:test");
const assert = require("node:assert");
const Filters = require("./filter.js");

const permit = (over) => Object.assign({
  id: "B26000127", type: "Commercial Addition Permit",
  category: "Commercial", owner: "HOCK/BAVAR", contractor: "COMPLETE SVS",
  description: "EXTERIOR STAIRCASE", address: "10335 GUILFORD RD, JESSUP, MD 20794",
  issued: "2026-06-11",
}, over);

const EMPTY = { q: "", from: "", to: "", cat: "All", types: [] };

test("empty state matches everything", () => {
  assert.ok(Filters.matches(permit(), EMPTY));
});

test("query matches across fields, case-insensitive", () => {
  assert.ok(Filters.matches(permit(), { ...EMPTY, q: "staircase" }));
  assert.ok(Filters.matches(permit(), { ...EMPTY, q: "guilford" }));
  assert.ok(Filters.matches(permit(), { ...EMPTY, q: "b26000127" }));
  assert.ok(!Filters.matches(permit(), { ...EMPTY, q: "zebra" }));
});

test("date range is inclusive by month", () => {
  assert.ok(Filters.matches(permit(), { ...EMPTY, from: "2026-06", to: "2026-06" }));
  assert.ok(!Filters.matches(permit(), { ...EMPTY, to: "2026-05" }));
  assert.ok(!Filters.matches(permit(), { ...EMPTY, from: "2026-07" }));
});

test("category and type filters", () => {
  assert.ok(!Filters.matches(permit(), { ...EMPTY, cat: "Residential" }));
  assert.ok(Filters.matches(permit(), { ...EMPTY, types: ["Commercial Addition Permit"] }));
  assert.ok(!Filters.matches(permit(), { ...EMPTY, types: ["Porch Permit"] }));
});

test("apply filters a list", () => {
  const list = [permit(), permit({ id: "X", category: "Residential" })];
  assert.strictEqual(Filters.apply(list, { ...EMPTY, cat: "Residential" }).length, 1);
});

test("hash round-trips state", () => {
  const state = { q: "solar panels", from: "2026-01", to: "2026-06",
                  cat: "Residential", types: ["Porch Permit", "Deck"] };
  assert.deepStrictEqual(Filters.fromHash(Filters.toHash(state)), state);
});

test("empty state serializes to empty hash", () => {
  assert.strictEqual(Filters.toHash(EMPTY), "");
  assert.deepStrictEqual(Filters.fromHash(""), EMPTY);
});
```

**Step 2: Run to verify failure**

Run: `nix-shell --run "node --test site/"`
Expected: FAIL — Cannot find module './filter.js'

**Step 3: Implement**

`site/filter.js`:

```js
"use strict";
// Pure filter + URL-hash logic. Loaded as a plain script in the browser
// (window.Filters) and via require() in node tests. No ES modules — the
// site must work over file://.
(function (global) {
  const Filters = {
    searchText(p) {
      return [p.id, p.type, p.owner, p.contractor, p.description, p.address]
        .join(" ").toLowerCase();
    },

    matches(p, s) {
      if (s.q && !(p._search || Filters.searchText(p)).includes(s.q.toLowerCase())) {
        return false;
      }
      const month = p.issued.slice(0, 7);
      if (s.from && month < s.from) return false;
      if (s.to && month > s.to) return false;
      if (s.cat !== "All" && p.category !== s.cat) return false;
      if (s.types.length && !s.types.includes(p.type)) return false;
      return true;
    },

    apply(permits, s) {
      return permits.filter((p) => Filters.matches(p, s));
    },

    toHash(s) {
      const params = new URLSearchParams();
      if (s.q) params.set("q", s.q);
      if (s.from) params.set("from", s.from);
      if (s.to) params.set("to", s.to);
      if (s.cat !== "All") params.set("cat", s.cat);
      if (s.types.length) params.set("types", s.types.join("|"));
      const str = params.toString();
      return str ? "#" + str : "";
    },

    fromHash(hash) {
      const params = new URLSearchParams((hash || "").replace(/^#/, ""));
      const types = params.get("types");
      return {
        q: params.get("q") || "",
        from: params.get("from") || "",
        to: params.get("to") || "",
        cat: params.get("cat") || "All",
        types: types ? types.split("|") : [],
      };
    },
  };

  if (typeof module !== "undefined") module.exports = Filters;
  else global.Filters = Filters;
})(this);
```

**Step 4: Run to verify pass**

Run: `nix-shell --run "node --test site/"`
Expected: all pass

**Step 5: Commit**

```bash
git add site/filter.js site/filter.test.js
git commit -m "feat: pure filter and hash-state module with node tests"
```

---

### Task 12: index.html + style.css

**Files:**
- Create: `site/index.html`, `site/style.css`

No automated test — verified by the smoke test in Task 14. Keep markup exactly in sync with the ids used by `app.js` (Task 13).

**Step 1: Write `site/index.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Howard County Building Permits Map</title>
<link rel="stylesheet" href="vendor/leaflet.css">
<link rel="stylesheet" href="vendor/MarkerCluster.css">
<link rel="stylesheet" href="vendor/MarkerCluster.Default.css">
<link rel="stylesheet" href="style.css">
</head>
<body>
<div id="app">
  <aside id="sidebar">
    <header>
      <h1>Howard County Building Permits</h1>
      <p class="subtitle">From the county's monthly Marketing Analysis Reports</p>
    </header>
    <div class="controls">
      <input id="search" type="search" placeholder="Search owner, contractor, address, description…" autocomplete="off">
      <div class="dates">
        <label>From <input id="from" type="month"></label>
        <label>To <input id="to" type="month"></label>
      </div>
      <div class="cats" id="cats">
        <button data-cat="All" class="active">All</button>
        <button data-cat="Commercial">Commercial</button>
        <button data-cat="Residential">Residential</button>
      </div>
      <details id="types-details">
        <summary>Permit types</summary>
        <div id="types"></div>
      </details>
    </div>
    <div id="summary"></div>
    <div id="results"></div>
  </aside>
  <button id="sidebar-toggle" aria-label="Toggle list">☰ List</button>
  <div id="map"></div>
  <div id="error" hidden>
    <p>Permit data failed to load. Run <code>python3 pipeline/build.py</code>
    to generate <code>site/data/permits.js</code>.</p>
  </div>
</div>
<script src="vendor/leaflet.js"></script>
<script src="vendor/leaflet.markercluster.js"></script>
<script src="data/permits.js"></script>
<script src="filter.js"></script>
<script src="app.js"></script>
</body>
</html>
```

**Step 2: Write `site/style.css`**

```css
* { box-sizing: border-box; }
html, body, #app { height: 100%; margin: 0; }
body { font: 14px/1.45 system-ui, sans-serif; color: #1a202c; }
#app { display: flex; }

#sidebar {
  width: 380px; min-width: 380px; height: 100%;
  display: flex; flex-direction: column;
  border-right: 1px solid #e2e8f0; background: #fff; z-index: 1000;
}
#sidebar header { padding: 14px 16px 6px; }
#sidebar h1 { font-size: 17px; margin: 0; }
.subtitle { margin: 2px 0 0; color: #718096; font-size: 12px; }

.controls { padding: 8px 16px; display: grid; gap: 8px; }
#search { width: 100%; padding: 8px 10px; border: 1px solid #cbd5e0;
  border-radius: 6px; font-size: 14px; }
.dates { display: flex; gap: 8px; }
.dates label { flex: 1; font-size: 12px; color: #4a5568; }
.dates input { width: 100%; padding: 4px 6px; border: 1px solid #cbd5e0;
  border-radius: 6px; }
.cats { display: flex; gap: 6px; }
.cats button { flex: 1; padding: 6px 0; border: 1px solid #cbd5e0;
  background: #fff; border-radius: 6px; cursor: pointer; }
.cats button.active { background: #2b6cb0; color: #fff; border-color: #2b6cb0; }
#types-details summary { cursor: pointer; font-size: 12px; color: #4a5568; }
#types { max-height: 160px; overflow-y: auto; font-size: 12px;
  padding: 6px 0; display: grid; gap: 2px; }
#types label { display: flex; gap: 6px; align-items: baseline; }

#summary { padding: 6px 16px; font-size: 12px; color: #4a5568;
  border-top: 1px solid #e2e8f0; }
#results { flex: 1; overflow-y: auto; }
.card { padding: 10px 16px; border-top: 1px solid #edf2f7; cursor: pointer; }
.card:hover { background: #f7fafc; }
.card.selected { background: #ebf8ff; }
.card .type { font-weight: 600; font-size: 13px; }
.card .type.res { color: #276749; }
.card .type.com { color: #9c4221; }
.card .addr { font-size: 13px; }
.card .meta { font-size: 12px; color: #718096; }
.badge { display: inline-block; font-size: 10px; padding: 1px 6px;
  border-radius: 8px; background: #fed7d7; color: #822727; }
.truncated-note { padding: 10px 16px; font-size: 12px; color: #718096;
  font-style: italic; }

#map { flex: 1; height: 100%; }
#sidebar-toggle { display: none; }
#error { position: absolute; inset: 0; display: flex; align-items: center;
  justify-content: center; background: #fff; z-index: 2000; }

.popup { max-width: 280px; }
.popup h3 { margin: 0 0 4px; font-size: 14px; }
.popup .desc { max-height: 120px; overflow-y: auto; font-size: 12px; }
.popup dl { margin: 6px 0 0; font-size: 12px; }
.popup dt { font-weight: 600; float: left; clear: left; margin-right: 4px; }
.popup dd { margin: 0; }

@media (max-width: 700px) {
  #app { flex-direction: column; }
  #sidebar { position: fixed; bottom: 0; left: 0; right: 0; top: 40%;
    width: 100%; min-width: 0; transform: translateY(calc(100% - 0px));
    transition: transform .2s; border-top: 1px solid #e2e8f0; }
  #sidebar.open { transform: none; }
  #sidebar-toggle { display: block; position: fixed; bottom: 12px;
    left: 50%; transform: translateX(-50%); z-index: 1100;
    padding: 8px 18px; border-radius: 20px; border: 1px solid #cbd5e0;
    background: #fff; box-shadow: 0 2px 8px rgba(0,0,0,.15); }
}
```

**Step 3: Commit**

```bash
git add site/index.html site/style.css
git commit -m "feat: site layout — sidebar, map container, mobile sheet"
```

---

### Task 13: app.js — wire map, list, and filters

**Files:**
- Create: `site/app.js`

**Step 1: Write `site/app.js`**

```js
"use strict";
(function () {
  if (!window.PERMITS || !Array.isArray(window.PERMITS)) {
    document.getElementById("error").hidden = false;
    return;
  }
  const permits = window.PERMITS;
  permits.forEach((p) => { p._search = Filters.searchText(p); });

  const CARD_LIMIT = 400;
  const COLORS = { Commercial: "#dd6b20", Residential: "#2f855a" };

  // --- map ---
  const map = L.map("map").setView([39.25, -76.93], 11);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);
  const cluster = L.markerClusterGroup({ chunkedLoading: true });
  map.addLayer(cluster);

  const money = (n) => "$" + Math.round(n).toLocaleString("en-US");

  function popupHtml(p) {
    const el = document.createElement("div");
    el.className = "popup";
    el.innerHTML = `<h3></h3><dl>
      <dt>Permit</dt><dd class="pid"></dd>
      <dt>Issued</dt><dd class="pissued"></dd>
      <dt>Owner</dt><dd class="powner"></dd>
      <dt>Contractor</dt><dd class="pcontractor"></dd>
      <dt>Est. cost</dt><dd class="pcost"></dd>
      <dt>Source</dt><dd class="psource"></dd>
      </dl><div class="desc"></div>`;
    el.querySelector("h3").textContent = `${p.type} — ${p.address}`;
    el.querySelector(".pid").textContent = p.id;
    el.querySelector(".pissued").textContent = p.issued;
    el.querySelector(".powner").textContent = p.owner || "—";
    el.querySelector(".pcontractor").textContent = p.contractor || "—";
    el.querySelector(".pcost").textContent = money(p.cost);
    el.querySelector(".psource").textContent = `${p.source} report`;
    el.querySelector(".desc").textContent = p.description;
    return el;
  }

  // --- state ---
  let state = Filters.fromHash(location.hash);
  const $ = (id) => document.getElementById(id);
  const searchEl = $("search"), fromEl = $("from"), toEl = $("to");

  const months = permits.map((p) => p.issued.slice(0, 7));
  const minMonth = months.reduce((a, b) => (a < b ? a : b));
  const maxMonth = months.reduce((a, b) => (a > b ? a : b));
  fromEl.min = toEl.min = minMonth;
  fromEl.max = toEl.max = maxMonth;

  // permit-type checklist, grouped by category
  const typesByCat = new Map();
  permits.forEach((p) => {
    if (!typesByCat.has(p.category)) typesByCat.set(p.category, new Set());
    typesByCat.get(p.category).add(p.type);
  });
  const typesEl = $("types");
  [...typesByCat.keys()].sort().forEach((cat) => {
    [...typesByCat.get(cat)].sort().forEach((t) => {
      const label = document.createElement("label");
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.value = t;
      cb.dataset.cat = cat;
      cb.addEventListener("change", onTypesChange);
      label.append(cb, document.createTextNode(t));
      typesEl.append(label);
    });
  });

  function syncControls() {
    searchEl.value = state.q;
    fromEl.value = state.from;
    toEl.value = state.to;
    document.querySelectorAll("#cats button").forEach((b) =>
      b.classList.toggle("active", b.dataset.cat === state.cat));
    document.querySelectorAll("#types input").forEach((cb) => {
      cb.checked = state.types.includes(cb.value);
    });
  }

  // --- rendering ---
  let markers = new Map(); // permit -> marker (for card→pin linking)
  let selectedCard = null;

  function render() {
    const filtered = Filters.apply(permits, state);

    cluster.clearLayers();
    markers = new Map();
    const layerList = [];
    filtered.forEach((p) => {
      if (p.geoq === "failed") return;
      const m = L.circleMarker([p.lat, p.lng], {
        radius: 7, weight: 1.5, color: "#fff", fillOpacity: 0.85,
        fillColor: COLORS[p.category] || "#4a5568",
      });
      m.bindPopup(() => popupHtml(p));
      m.on("click", () => highlightCard(p));
      markers.set(p, m);
      layerList.push(m);
    });
    cluster.addLayers(layerList);

    const total = filtered.reduce((s, p) => s + p.cost, 0);
    $("summary").textContent =
      `${filtered.length.toLocaleString()} permits · ${money(total)} total est. cost`;

    const results = $("results");
    results.replaceChildren();
    const frag = document.createDocumentFragment();
    filtered.slice(0, CARD_LIMIT).forEach((p) => {
      const card = document.createElement("div");
      card.className = "card";
      const badge = p.geoq === "failed"
        ? ' <span class="badge">no map location</span>' : "";
      card.innerHTML =
        `<div class="type ${p.category === "Residential" ? "res" : "com"}"></div>
         <div class="addr"></div><div class="meta"></div>`;
      card.querySelector(".type").textContent = p.type;
      card.querySelector(".addr").textContent = p.address;
      card.querySelector(".meta").innerHTML =
        `${p.issued} · ${money(p.cost)}${badge}`;
      card.addEventListener("click", () => focusPermit(p, card));
      frag.append(card);
    });
    if (filtered.length > CARD_LIMIT) {
      const note = document.createElement("div");
      note.className = "truncated-note";
      note.textContent =
        `Showing first ${CARD_LIMIT} of ${filtered.length} — refine filters to see the rest. All pins are on the map.`;
      frag.append(note);
    }
    results.append(frag);

    const hash = Filters.toHash(state);
    history.replaceState(null, "", hash || location.pathname + location.search);
  }

  function focusPermit(p, card) {
    if (selectedCard) selectedCard.classList.remove("selected");
    selectedCard = card;
    card.classList.add("selected");
    const m = markers.get(p);
    if (!m) return;
    map.setView(m.getLatLng(), Math.max(map.getZoom(), 16));
    cluster.zoomToShowLayer(m, () => m.openPopup());
  }

  function highlightCard(p) {
    // find card by index in current filtered order — cheap approach:
    // re-query cards and match by displayed permit address+type
    document.querySelectorAll(".card").forEach((c) => c.classList.remove("selected"));
    const cards = document.querySelectorAll(".card");
    const filtered = Filters.apply(permits, state).slice(0, cards.length);
    const i = filtered.indexOf(p);
    if (i >= 0) {
      cards[i].classList.add("selected");
      cards[i].scrollIntoView({ block: "nearest" });
      selectedCard = cards[i];
    }
  }

  // --- events ---
  let debounce;
  searchEl.addEventListener("input", () => {
    clearTimeout(debounce);
    debounce = setTimeout(() => { state.q = searchEl.value.trim(); render(); }, 150);
  });
  fromEl.addEventListener("change", () => { state.from = fromEl.value; render(); });
  toEl.addEventListener("change", () => { state.to = toEl.value; render(); });
  $("cats").addEventListener("click", (e) => {
    const btn = e.target.closest("button");
    if (!btn) return;
    state.cat = btn.dataset.cat;
    state.types = [];
    syncControls();
    render();
  });
  function onTypesChange() {
    state.types = [...document.querySelectorAll("#types input:checked")]
      .map((cb) => cb.value);
    render();
  }
  window.addEventListener("hashchange", () => {
    state = Filters.fromHash(location.hash);
    syncControls();
    render();
  });
  $("sidebar-toggle").addEventListener("click", () =>
    $("sidebar").classList.toggle("open"));

  syncControls();
  render();
})();
```

**Step 2: Run the node tests still pass (filter.js untouched, but be safe)**

Run: `nix-shell --run "node --test site/"`
Expected: all pass

**Step 3: Commit**

```bash
git add site/app.js
git commit -m "feat: map/list/filter wiring with clustered pins and hash state"
```

---

### Task 14: Browser smoke test

Serve the site (tiles need http for referer policies to behave; file:// also works but test http):

Run: `nix-shell --run "python3 -m http.server 8788 -d site"` (background)

Using chrome-devtools MCP tools (or manually if unavailable):
1. Open `http://localhost:8788` — map renders, clustered pins visible over Howard County, no console errors (`list_console_messages`).
2. Type `solar` in search — list shrinks to solar permits; pin count visibly drops; URL hash becomes `#q=solar`.
3. Click **Commercial** chip — only commercial permits remain.
4. Reload with the hash present — filters restore from URL.
5. Click a cluster → zooms; click a pin → popup opens and the matching card highlights in the sidebar.
6. Click a card → map pans/zooms to its pin and opens the popup.
7. Resize to 500px wide — sidebar becomes bottom sheet; toggle button shows/hides it.
8. Take a screenshot for the record.

Fix anything broken (systematic-debugging skill if non-obvious), then:

```bash
git add -A
git commit -m "fix: smoke-test findings"   # only if changes were needed
```

Kill the server when done.

---

### Task 15: README and wrap-up

**Files:**
- Create: `README.md`

**Step 1: Write `README.md`**

```markdown
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
- Frontend filter tests: `nix-shell --run "node --test site/"`
- Design: `docs/plans/2026-07-12-marketing-report-map-design.md`
```

**Step 2: Full test suite one last time**

Run: `nix-shell --run "pytest pipeline/tests -v && node --test site/"`
Expected: everything passes.

**Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README with update and deploy instructions"
```

**Step 4:** Use superpowers:finishing-a-development-branch (note: this repo works directly on `main` — just confirm final state is committed and tests pass).

---

## Notes for the executor

- **Never weaken the reconciliation gate to make a month pass.** A mismatch means the parser missed something real — debug with the systematic-debugging skill. The June 2026 numbers above are ground truth.
- New month PDFs may reveal permit types or layouts June doesn't have. If a new PDF fails, extract the offending page's words (`page.extract_words()`), find the pattern, add a regression test, then fix.
- Nominatim fallback must keep the 1.1s sleep and the User-Agent header (usage policy).
- Descriptions in the source are ALL-CAPS-ish and long; do not "clean them up" in the pipeline — display them verbatim.
- `site/data/permits.js` and `pipeline/cache/geocode.json` are generated but **committed** — they are the deployable artifact and the cache respectively.
```

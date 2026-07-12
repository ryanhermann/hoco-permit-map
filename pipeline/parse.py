"""Parse Howard County 'Marketing Analysis Report - Building' PDFs."""
import re
from dataclasses import dataclass

import pdfplumber

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
    """Group words into visual lines (3pt bins), bucket by column."""
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
    subtotals: list   # [(category, count, dollars), ...] per section
    grand: tuple      # (count, dollars)
    period: str       # "YYYY-MM"
    sections: list    # section header lines seen ("Commercial"/...), in order


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
    records, subtotals, sections = [], [], []
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
                    subtotals.append(
                        (category, int(m.group(1)), _money(m.group(2))))
                    continue
                if text in ("Commercial", "Residential"):
                    category = text
                    sections.append(text)
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
    return ParseResult(records, subtotals, grand, period, sections)


def reconcile(result):
    """Fail loudly if parsed records don't match the report's own totals.

    Every dollar comparison is strict equality on rounded cents — no
    tolerance. A mismatch means the parser missed something real.
    """
    count, total = result.grand
    total = round(total, 2)
    if len(result.records) != count:
        raise ParseError(
            f"count mismatch: parsed {len(result.records)} records, "
            f"report says {count}")
    parsed_cost = round(sum(r["cost"] for r in result.records), 2)
    if parsed_cost != total:
        raise ParseError(
            f"cost mismatch: parsed ${parsed_cost:,.2f}, "
            f"report says ${total:,.2f}")
    sub_count = sum(c for _, c, _ in result.subtotals)
    if sub_count != count:
        raise ParseError(
            f"subtotal counts sum to {sub_count}, grand total says {count}")
    sub_dollars = round(sum(d for _, _, d in result.subtotals), 2)
    if sub_dollars != total:
        raise ParseError(
            f"subtotal dollars sum to ${sub_dollars:,.2f}, "
            f"grand total says ${total:,.2f}")
    if len(result.subtotals) != len(result.sections):
        raise ParseError(
            f"{len(result.subtotals)} subtotal lines but "
            f"{len(result.sections)} section headers seen — a header line "
            f"may have stopped matching, leaving records mis-categorized")
    by_cat = {}
    for r in result.records:
        c, d = by_cat.get(r["category"], (0, 0.0))
        by_cat[r["category"]] = (c + 1, d + r["cost"])
    sub_by_cat = {}
    for cat, c, d in result.subtotals:
        pc, pd = sub_by_cat.get(cat, (0, 0.0))
        sub_by_cat[cat] = (pc + c, pd + d)
    for cat in sorted(set(by_cat) | set(sub_by_cat), key=str):
        pc, pd = by_cat.get(cat, (0, 0.0))
        sc, sd = sub_by_cat.get(cat, (0, 0.0))
        if pc != sc or round(pd, 2) != round(sd, 2):
            raise ParseError(
                f"category {cat}: parsed {pc} records / ${round(pd, 2):,.2f}, "
                f"subtotal says {sc} / ${round(sd, 2):,.2f}")

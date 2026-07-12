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

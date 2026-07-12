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

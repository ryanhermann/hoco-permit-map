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

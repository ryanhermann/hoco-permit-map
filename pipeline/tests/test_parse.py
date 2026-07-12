from pathlib import Path

import pytest

from parse import (
    ParseError, ParseResult, lines_from_words, parse_pdf, reconcile)


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


def test_lines_stay_top_down_even_if_words_arrive_out_of_order():
    """Input word order (e.g. reverse top order) must not affect output order."""
    words = [w(20.0, 120.0, "Residential"), w(20.0, 100.0, "Commercial")]
    lines = lines_from_words(words)
    assert [l["type"] for l in lines] == ["Commercial", "Residential"]


def test_column_boundary_is_half_open_at_150():
    words = [w(150.0, 100.0, "B26000127")]
    lines = lines_from_words(words)
    assert lines[0]["permit"] == "B26000127"
    assert lines[0]["type"] == ""


def test_every_line_has_all_six_columns_with_empty_string_default():
    words = [w(20.0, 100.0, "Commercial")]
    lines = lines_from_words(words)
    line = lines[0]
    assert set(line.keys()) == {
        "type", "permit", "owner_addr", "contractor", "desc", "date"}
    assert line["permit"] == ""
    assert line["owner_addr"] == ""
    assert line["contractor"] == ""
    assert line["desc"] == ""
    assert line["date"] == ""


PDF = Path(__file__).resolve().parent.parent / "pdfs" / "2026-06.pdf"


@pytest.fixture(scope="module")
def june():
    return parse_pdf(PDF)


def test_parses_every_record(june):
    assert len(june.records) == 320
    assert june.grand == (320, 222245719.52)
    assert june.subtotals == [("Commercial", 56, 201523989.00),
                              ("Residential", 264, 20721730.52)]
    assert june.sections == ["Commercial", "Residential"]
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


class _FakePage:
    def __init__(self, words):
        self._words = words

    def extract_words(self):
        return self._words


class _FakePdf:
    def __init__(self, pages_words):
        self.pages = [_FakePage(words) for words in pages_words]

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _from_date_line():
    return [w(20, 40, "From"), w(50, 40, "Date:"), w(90, 40, "6/1/2026")]


def _opener_line(top, permit_id):
    return [w(20, top, "Commercial"), w(155, top, permit_id)]


def _cost_closer_line(top, dollars):
    return [
        w(20, top, "Est"), w(50, top, "Construction"),
        w(90, top, "Cost="), w(130, top, f"${dollars:,.2f}"),
    ]


def test_parse_pdf_raises_when_record_never_closed(monkeypatch):
    words = (
        _from_date_line()
        + _opener_line(100, "B26000001")
        + _opener_line(130, "B26000002")
    )
    monkeypatch.setattr("parse.pdfplumber.open", lambda path: _FakePdf([words]))
    with pytest.raises(ParseError, match="never closed"):
        parse_pdf("fake.pdf")


def test_parse_pdf_raises_when_record_still_open_at_eof(monkeypatch):
    words = _from_date_line() + _opener_line(100, "B26000001")
    monkeypatch.setattr("parse.pdfplumber.open", lambda path: _FakePdf([words]))
    with pytest.raises(ParseError, match="still open"):
        parse_pdf("fake.pdf")


def test_parse_pdf_raises_when_grand_totals_missing(monkeypatch):
    # A complete, properly-closed record, but no grand-totals/From-Date lines.
    words = _opener_line(100, "B26000001") + _cost_closer_line(140, 1000.00)
    monkeypatch.setattr("parse.pdfplumber.open", lambda path: _FakePdf([words]))
    with pytest.raises(ParseError, match="missing grand totals"):
        parse_pdf("fake.pdf")


def _result(records, subtotals, grand, sections=None):
    if sections is None:
        sections = [cat for cat, _, _ in subtotals]
    return ParseResult(records, subtotals, grand, "2026-06", sections)


def _rec(cost, category="Commercial"):
    return {"id": "B00000000", "cost": cost, "category": category}


def test_reconcile_passes_when_totals_match():
    reconcile(_result([_rec(100.0), _rec(50.5)],
                      [("Commercial", 2, 150.5)], (2, 150.5)))


def test_reconcile_fails_on_count_mismatch():
    with pytest.raises(ParseError, match="count"):
        reconcile(_result([_rec(100.0)],
                          [("Commercial", 2, 100.0)], (2, 100.0)))


def test_reconcile_fails_on_cost_mismatch():
    with pytest.raises(ParseError, match="cost"):
        reconcile(_result([_rec(100.0)],
                          [("Commercial", 1, 999.0)], (1, 999.0)))


def test_reconcile_fails_on_one_cent_cost_discrepancy():
    """Strict cents: a single-cent drift must fail, not slip under a tolerance."""
    with pytest.raises(ParseError, match="cost"):
        reconcile(_result([_rec(100.0)],
                          [("Commercial", 1, 100.01)], (1, 100.01)))


def test_reconcile_fails_on_subtotal_count_mismatch():
    with pytest.raises(ParseError, match="subtotal"):
        reconcile(_result([_rec(100.0)],
                          [("Commercial", 2, 100.0)], (1, 100.0)))


def test_reconcile_fails_when_subtotal_dollars_dont_sum_to_grand():
    with pytest.raises(ParseError, match="subtotal dollars"):
        reconcile(_result(
            [_rec(100.0), _rec(50.0, "Residential")],
            [("Commercial", 1, 100.0), ("Residential", 1, 49.0)],
            (2, 150.0)))


def test_reconcile_fails_when_subtotal_lines_outnumber_section_headers():
    """A header line that stops matching would leave records with a stale
    category; catching subtotal-lines > headers-seen makes that loud."""
    with pytest.raises(ParseError, match="section header"):
        reconcile(_result(
            [_rec(100.0), _rec(50.0, "Residential")],
            [("Commercial", 1, 100.0), ("Residential", 1, 50.0)],
            (2, 150.0),
            sections=["Commercial"]))


def test_reconcile_fails_on_per_category_count_mismatch():
    with pytest.raises(ParseError, match="Commercial"):
        reconcile(_result(
            [_rec(100.0), _rec(50.0, "Residential")],
            [("Commercial", 2, 100.0), ("Residential", 0, 50.0)],
            (2, 150.0)))


def test_reconcile_fails_on_per_category_cost_mismatch():
    with pytest.raises(ParseError, match="Commercial"):
        reconcile(_result(
            [_rec(100.0), _rec(50.0, "Residential")],
            [("Commercial", 1, 50.0), ("Residential", 1, 100.0)],
            (2, 150.0)))


def test_reconcile_is_agnostic_to_section_order():
    """Mar/Apr/May reports list Residential first — must still reconcile."""
    reconcile(_result(
        [_rec(100.0), _rec(50.0, "Residential")],
        [("Residential", 1, 50.0), ("Commercial", 1, 100.0)],
        (2, 150.0)))


def test_june_reconciles(june):
    reconcile(june)


ALL_PDFS = sorted((Path(__file__).resolve().parent.parent / "pdfs").glob("*.pdf"))


def test_pdf_fixtures_present():
    """A broken glob must fail loudly, not silently skip the all-months test."""
    assert ALL_PDFS


@pytest.mark.parametrize("pdf", ALL_PDFS, ids=lambda p: p.stem)
def test_all_reports_parse_reconcile_and_are_complete(pdf):
    result = parse_pdf(pdf)
    reconcile(result)
    for r in result.records:
        assert r["cost"] is not None, r["id"]
        assert r["issued"], r["id"]
        assert r["address"], r["id"]
        assert r["tract"], r["id"]
        assert r["category"] in ("Commercial", "Residential"), r["id"]

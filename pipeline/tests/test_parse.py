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

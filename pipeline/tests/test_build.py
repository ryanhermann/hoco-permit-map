import json

import pytest

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


def test_tract_suffix_difference_keeps_exact():
    # County PDFs carry older-vintage tract codes; Census Current codes
    # often differ only in the suffix (tract splits). Same 4-digit base
    # (6069) must not downgrade the geocode quality.
    records = assemble(
        [_permit("B1", "2026-06-02", "A ST, X, MD 11111", tract="606906")],
        GEO)
    assert records[0]["geoq"] == "exact"


def test_assemble_raises_on_missing_geocode_entry():
    with pytest.raises(KeyError, match="MISSING"):
        assemble([_permit("B1", "2026-06-02", "MISSING ST, X, MD 11111")],
                 GEO)


def test_emit_writes_loadable_js(tmp_path):
    out = tmp_path / "permits.js"
    emit([{"id": "B1"}], out)
    text = out.read_text()
    assert text.startswith("window.PERMITS=")
    assert json.loads(text.removeprefix("window.PERMITS=").rstrip(";\n")) == \
        [{"id": "B1"}]


def test_emit_round_trips_non_ascii_utf8(tmp_path):
    out = tmp_path / "permits.js"
    records = [{"id": "B1", "description": "“shed” 10×12"}]
    emit(records, out)
    text = out.read_text(encoding="utf-8")
    assert "“shed” 10×12" in text
    assert json.loads(text.removeprefix("window.PERMITS=").rstrip(";\n")) == \
        records

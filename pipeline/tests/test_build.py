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

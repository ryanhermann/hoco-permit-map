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


def test_multi_word_city():
    assert split_address("11030 GUILFORD RD, ANNAPOLIS JUNCTION, MD 20701") == \
        ("11030 GUILFORD RD", "ANNAPOLIS JUNCTION", "20701")


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

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

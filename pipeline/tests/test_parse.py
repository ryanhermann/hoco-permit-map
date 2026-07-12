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

"""pdf_splitter 页码解析测试。"""

from mineru_parser.pdf_splitter import parse_pages_spec


def test_parse_pages_spec_ranges():
    # 1-based: pages 1-2 and 4 -> indices 0,1,3
    out, _ = parse_pages_spec("1-2,4", 5)
    assert out == [0, 1, 3]


def test_parse_pages_spec_single():
    out, _ = parse_pages_spec("3", 10)
    assert out == [2]


def test_parse_pages_spec_swap_reversed_range():
    out, _ = parse_pages_spec("5-3", 10)
    assert out == [2, 3, 4]


def test_parse_pages_spec_clamp_high():
    out, warns = parse_pages_spec("8-12", 10)
    assert out == [7, 8, 9]
    assert any("裁剪" in w for w in warns)


def test_parse_pages_spec_fully_out_of_range():
    out, warns = parse_pages_spec("50-60", 10)
    assert out == []
    assert warns


def test_parse_pages_spec_whitespace():
    out, _ = parse_pages_spec(" 1-3 , 5 ", 10)
    assert out == [0, 1, 2, 4]


def test_parse_pages_spec_dedup_sort():
    out, _ = parse_pages_spec("5,3,5-7", 10)
    assert out == [2, 4, 5, 6]

"""pdf_splitter 页码解析与切分测试。"""

import pytest

from mineru_parser.pdf_splitter import (
    extract_pages_to_pdf,
    get_pdf_info,
    parse_pages_spec,
    split_pdf_adaptive,
    split_pdf_by_limits,
)

# 用 pymupdf (fitz) 生成测试 PDF 并校验切分输出；fitz 为必装依赖，
# 缺失时跳过本模块的切分相关测试（不阻断页码解析纯逻辑测试）。
fitz = pytest.importorskip("fitz")

_SIZE_100MB = 100 * 1024 * 1024


def _make_pdf(path, num_pages: int) -> None:
    """生成 num_pages 页 PDF，每页含唯一文本 ``Page {i}``，便于切分校验。"""
    doc = fitz.open()
    for i in range(num_pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {i}")
    doc.save(str(path))
    doc.close()


def _page_texts(path) -> list[str]:
    """返回 PDF 每页文本（去首尾空白），按页顺序。"""
    doc = fitz.open(str(path))
    try:
        return [doc[i].get_text().strip() for i in range(doc.page_count)]
    finally:
        doc.close()


# ---------- parse_pages_spec（纯逻辑，原有测试）----------


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


# ---------- get_pdf_info ----------


def test_get_pdf_info(tmp_path):
    p = tmp_path / "a.pdf"
    _make_pdf(p, 7)
    num_pages, size_bytes = get_pdf_info(p)
    assert num_pages == 7
    assert size_bytes == p.stat().st_size


# ---------- extract_pages_to_pdf ----------


def test_extract_pages_noncontiguous(tmp_path):
    """非连续页索引，按给定顺序输出。"""
    src = tmp_path / "src.pdf"
    _make_pdf(src, 6)
    dest = tmp_path / "out.pdf"
    extract_pages_to_pdf(src, [0, 2, 4], dest)
    assert _page_texts(dest) == ["Page 0", "Page 2", "Page 4"]


def test_extract_pages_empty_raises(tmp_path):
    src = tmp_path / "src.pdf"
    _make_pdf(src, 3)
    with pytest.raises(ValueError):
        extract_pages_to_pdf(src, [], tmp_path / "out.pdf")


def test_extract_pages_out_of_range_raises(tmp_path):
    src = tmp_path / "src.pdf"
    _make_pdf(src, 3)
    with pytest.raises(ValueError):
        extract_pages_to_pdf(src, [5], tmp_path / "out.pdf")


# ---------- split_pdf_by_limits ----------


def test_split_no_need(tmp_path):
    """页数与大小均在限制内，返回原路径列表。"""
    src = tmp_path / "src.pdf"
    _make_pdf(src, 5)
    out = split_pdf_by_limits(
        src, page_limit=10, size_limit_bytes=_SIZE_100MB, temp_dir=tmp_path / "t"
    )
    assert out == [src]


def test_split_by_page_limit(tmp_path):
    """按页数限制切分，片段内容连续且顺序正确。"""
    src = tmp_path / "src.pdf"
    _make_pdf(src, 12)
    out = split_pdf_by_limits(
        src, page_limit=5, size_limit_bytes=_SIZE_100MB, temp_dir=tmp_path / "t"
    )
    assert len(out) == 3  # 5 + 5 + 2
    assert _page_texts(out[0]) == [f"Page {i}" for i in range(5)]
    assert _page_texts(out[2]) == ["Page 10", "Page 11"]
    # 拼接后应与原文档一一对应
    all_texts = [t for p in out for t in _page_texts(p)]
    assert all_texts == [f"Page {i}" for i in range(12)]


def test_split_by_size_limit(tmp_path):
    """单页均摊大小超限时，按大小进一步切分（每片收敛到 1 页）。"""
    src = tmp_path / "src.pdf"
    _make_pdf(src, 10)
    out = split_pdf_by_limits(
        src, page_limit=10, size_limit_bytes=1, temp_dir=tmp_path / "t"
    )
    assert len(out) == 10  # size_limit 极小 -> pages_per_chunk=1


# ---------- split_pdf_adaptive ----------


def test_adaptive_disabled_delegates(tmp_path):
    """target_chunk_pages<=0 时委托 split_pdf_by_limits（未超限则原样返回）。"""
    src = tmp_path / "src.pdf"
    _make_pdf(src, 5)
    out = split_pdf_adaptive(
        src,
        target_chunk_pages=0,
        page_limit=10,
        size_limit_bytes=_SIZE_100MB,
        temp_dir=tmp_path / "t",
    )
    assert out == [src]


def test_adaptive_within_target_no_split(tmp_path):
    """页数不超过 target_chunk_pages 时不切分。"""
    src = tmp_path / "src.pdf"
    _make_pdf(src, 3)
    out = split_pdf_adaptive(
        src,
        target_chunk_pages=5,
        page_limit=10,
        size_limit_bytes=_SIZE_100MB,
        temp_dir=tmp_path / "t",
    )
    assert out == [src]


def test_adaptive_splits(tmp_path):
    """页数超过 target_chunk_pages 时按目标大小切分。"""
    src = tmp_path / "src.pdf"
    _make_pdf(src, 10)
    out = split_pdf_adaptive(
        src,
        target_chunk_pages=3,
        page_limit=10,
        size_limit_bytes=_SIZE_100MB,
        temp_dir=tmp_path / "t",
    )
    assert len(out) == 4  # 3 + 3 + 3 + 1
    all_texts = [t for p in out for t in _page_texts(p)]
    assert all_texts == [f"Page {i}" for i in range(10)]

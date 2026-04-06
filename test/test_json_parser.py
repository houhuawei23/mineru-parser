"""JSON 解析模块单元测试。"""

import json
import tempfile
from pathlib import Path

import pytest

from mineru_parser.json_parser import (
    find_content_list_json,
    content_list_json_to_markdown,
    content_list_v2_to_markdown,
    _extract_text_from_content_list_item,
)


def test_find_content_list_json_empty_dir() -> None:
    """空目录应返回 None。"""
    with tempfile.TemporaryDirectory() as d:
        assert find_content_list_json(Path(d)) is None


def test_find_content_list_json_finds_file() -> None:
    """应找到 *_content_list.json。"""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "uuid_content_list.json"
        p.write_text("[]")
        assert find_content_list_json(Path(d)) == p


def test_extract_text_from_content_list_item() -> None:
    """测试文本提取。"""
    assert _extract_text_from_content_list_item({"type": "text", "text": " hello "}) == "hello"
    assert _extract_text_from_content_list_item({"type": "header", "text": "Header"}) == "Header"
    assert _extract_text_from_content_list_item({"type": "list", "list_items": ["a", "b"]}) == "- a\n- b"


def test_content_list_json_to_markdown_empty() -> None:
    """空列表应返回空字符串。"""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        f.write(b"[]")
        f.flush()
        try:
            assert content_list_json_to_markdown(Path(f.name)) == ""
        finally:
            Path(f.name).unlink()


def test_content_list_json_to_markdown_basic() -> None:
    """基本内容应正确转换。"""
    data = [
        {"type": "text", "text": "Title", "text_level": 1, "page_idx": 0},
        {"type": "text", "text": "Body", "page_idx": 0},
    ]
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        json.dump(data, f, ensure_ascii=False)
        f.flush()
        try:
            md = content_list_json_to_markdown(Path(f.name))
            assert "# Title" in md
            assert "Body" in md
        finally:
            Path(f.name).unlink()


def test_content_list_json_to_markdown_footnote_format() -> None:
    """脚注应无 [xx] 前缀，格式为 - 内容。"""
    data = [
        {"type": "page_footnote", "text": "1Note: 注释内容", "page_idx": 0},
    ]
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        json.dump(data, f, ensure_ascii=False)
        f.flush()
        try:
            md = content_list_json_to_markdown(Path(f.name))
            assert "<!-- 脚注 -->" in md
            assert "- Note: 注释内容" in md
            # 脚注内容不应包含 [1] 前缀（旧格式为 - [1] xxx）
            assert "- [1] Note" not in md
        finally:
            Path(f.name).unlink()

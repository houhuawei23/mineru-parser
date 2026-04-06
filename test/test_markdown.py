"""Markdown 生成模块单元测试。"""

import pytest

from mineru_parser.markdown import remove_line_number_blocks


def test_remove_line_number_blocks_removes_number_blocks() -> None:
    """应移除仅含数字行的段落（页边行号）。"""
    md = """First paragraph.

*1   
2   
3   
16*

Second paragraph."""
    result = remove_line_number_blocks(md)
    assert "*1" not in result
    assert "2   " not in result
    assert "First paragraph." in result
    assert "Second paragraph." in result


def test_remove_line_number_blocks_preserves_normal_content() -> None:
    """应保留正常段落。"""
    md = """# Title

Body with numbers 1 and 2 and 3.

More text."""
    result = remove_line_number_blocks(md)
    assert result == md


def test_remove_line_number_blocks_multiple_blocks() -> None:
    """应移除多个行号块。"""
    md = """A

*1
2*

B

*3
4
5*

C"""
    result = remove_line_number_blocks(md)
    assert "A" in result
    assert "B" in result
    assert "C" in result
    assert "*1" not in result
    assert "*3" not in result

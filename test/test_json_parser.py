"""JSON 解析模块单元测试。"""

import json
import tempfile
from pathlib import Path


from mineru_parser.json_parser import (
    find_content_list_json,
    content_list_json_to_markdown,
    _extract_text_from_content_list_item,
    _merge_paragraphs,
    sanitize_text,
    ContentBlock,
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


def test_extract_text_from_image_with_mermaid() -> None:
    """测试图片包含 mermaid 内容时直接输出 mermaid 代码块。"""
    item = {
        "type": "image",
        "img_path": "images/abc.jpg",
        "image_caption": ["Figure 1"],
        "content": "```mermaid\ngraph TD\n  A --> B\n```",
    }
    md = _extract_text_from_content_list_item(item)
    assert "![Figure 1](images/abc.jpg)" in md
    assert "```mermaid" in md
    assert "graph TD" in md
    assert "<details>" not in md
    assert "</details>" not in md


def test_extract_text_from_image_without_mermaid() -> None:
    """测试普通图片不包含 mermaid 时保持原格式。"""
    item = {
        "type": "image",
        "img_path": "images/abc.jpg",
        "image_caption": ["Figure 1"],
    }
    md = _extract_text_from_content_list_item(item)
    assert md == "![Figure 1](images/abc.jpg)"


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


def test_merge_paragraphs_preserves_same_page_spacing() -> None:
    """同一页中的相邻段落不应被合并，应保留段落间距。"""
    blocks = [
        ContentBlock(page_idx=0, markdown="First paragraph ends here.", is_plain_paragraph=True),
        ContentBlock(page_idx=0, markdown="Second paragraph starts here.", is_plain_paragraph=True),
    ]
    merged = _merge_paragraphs(blocks, merge_paragraphs=True)
    assert len(merged) == 2
    assert merged[0].markdown == "First paragraph ends here."
    assert merged[1].markdown == "Second paragraph starts here."


def test_merge_paragraphs_merges_cross_page_continuation() -> None:
    """跨页且前一段未以句末标点结尾时，应合并为一段。"""
    blocks = [
        ContentBlock(page_idx=0, markdown="This sentence continues", is_plain_paragraph=True),
        ContentBlock(page_idx=1, markdown="on the next page without break", is_plain_paragraph=True),
    ]
    merged = _merge_paragraphs(blocks, merge_paragraphs=True)
    assert len(merged) == 1
    assert "continues" in merged[0].markdown
    assert "next page" in merged[0].markdown


def test_merge_paragraphs_respects_sentence_end_cross_page() -> None:
    """跨页但前一段以英文句号结尾时，不应合并。"""
    blocks = [
        ContentBlock(page_idx=0, markdown="This paragraph ends with a period.", is_plain_paragraph=True),
        ContentBlock(page_idx=1, markdown="Another paragraph starts here.", is_plain_paragraph=True),
    ]
    merged = _merge_paragraphs(blocks, merge_paragraphs=True)
    assert len(merged) == 2


def test_content_list_json_to_markdown_paragraph_spacing() -> None:
    """普通文本段落之间应保留空行，不应粘连。"""
    data = [
        {"type": "text", "text": "Paragraph one ends here.", "page_idx": 0},
        {"type": "text", "text": "Paragraph two starts here.", "page_idx": 0},
    ]
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        json.dump(data, f, ensure_ascii=False)
        f.flush()
        try:
            md = content_list_json_to_markdown(Path(f.name))
            # 两个段落之间应有两个换行（空行）分隔
            assert "Paragraph one ends here.\n\nParagraph two starts here." in md
            # 不应出现粘连
            assert "here.Paragraph" not in md
        finally:
            Path(f.name).unlink()


def test_sanitize_text_removes_control_chars() -> None:
    """sanitize_text 应移除 C0/C1 控制字符与零宽字符。"""
    raw = "hello\x00\x11world\x7f\x85\u200b"
    cleaned = sanitize_text(raw)
    assert cleaned == "helloworld"
    assert "\x00" not in cleaned
    assert "\x11" not in cleaned
    assert "\u200b" not in cleaned


def test_sanitize_text_keeps_whitespace_and_markdown() -> None:
    """sanitize_text 应保留换行、制表符与 Markdown 语法字符。"""
    raw = "# Title\n\n**bold** and $x = 1$\n\n- item 1\n- item 2"
    assert sanitize_text(raw) == raw


def test_extract_text_from_content_list_item_sanitizes_text() -> None:
    """从 content_list 项提取文本时应自动清理控制字符。"""
    item = {"type": "text", "text": "Paragraph with \x11\x04garbage\x00."}
    result = _extract_text_from_content_list_item(item)
    assert result == "Paragraph with garbage."


def test_content_list_json_to_markdown_sanitizes_control_chars() -> None:
    """生成的 Markdown 中不应包含控制字符。"""
    data = [
        {
            "type": "text",
            "text": "an edge between X and $Z$ that $G _ { 1 } { ' }$ -\x11\x04\x08\x10-\x0e\x04\x06 graph from",
            "page_idx": 0,
        },
    ]
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        json.dump(data, f, ensure_ascii=False)
        f.flush()
        try:
            md = content_list_json_to_markdown(Path(f.name))
            assert "\x11" not in md
            assert "\x04" not in md
            assert "\x0e" not in md
            assert "an edge between X" in md
            assert "graph from" in md
        finally:
            Path(f.name).unlink()

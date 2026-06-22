"""JSON 解析模块单元测试。"""

import json
import tempfile
from pathlib import Path


from mineru_parser.json_parser import (
    find_content_list_json,
    content_list_json_to_markdown,
    content_list_v2_to_markdown,
    _extract_text_from_content_list_item,
    _item_to_content_md,
    _list_items_to_markdown,
    _merge_paragraphs,
    sanitize_text,
    convert_html_tables_to_markdown,
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
    # image 类型仅返回图片路径，完整 Markdown 由 _item_to_content_md 组装
    assert _extract_text_from_content_list_item(
        {"type": "image", "img_path": "images/abc.jpg", "image_caption": ["Figure 1"]}
    ) == "images/abc.jpg"


def test_list_items_to_markdown_bullet() -> None:
    """已带 Markdown 列表标记的项应保留为无序列表。"""
    md = _list_items_to_markdown(["- apple", "- banana"])
    assert md == "- apple\n- banana"


def test_list_items_to_markdown_numbered() -> None:
    """编号项应按普通段落输出，保留硬换行。"""
    md = _list_items_to_markdown(["(1) first", "If sub-condition", "(2) second"])
    assert md == "(1) first  \nIf sub-condition  \n(2) second"


def test_list_items_to_markdown_plain_text() -> None:
    """无列表标记的文本项应按普通段落输出。"""
    md = _list_items_to_markdown(["apple", "banana"])
    assert md == "apple  \nbanana"


def test_list_items_to_markdown_references() -> None:
    """参考文献应按普通段落输出。"""
    md = _list_items_to_markdown(
        ["[A] ref one", "[B] ref two"], sub_type="ref_text"
    )
    assert md == "[A] ref one  \n[B] ref two"


def test_item_to_content_md_image_with_mermaid() -> None:
    """测试图片包含 mermaid 内容时直接输出 mermaid 代码块，caption 作为正文。"""
    item = {
        "type": "image",
        "img_path": "images/abc.jpg",
        "image_caption": ["Figure 1"],
        "content": "```mermaid\ngraph TD\n  A --> B\n```",
    }
    md = _item_to_content_md(item, _extract_text_from_content_list_item(item))
    assert "![](images/abc.jpg)" in md
    assert "Figure 1" in md
    assert "```mermaid" in md
    assert "graph TD" in md
    assert "<details>" not in md
    assert "</details>" not in md


def test_item_to_content_md_image_without_mermaid() -> None:
    """测试普通图片 caption 作为正文段落。"""
    item = {
        "type": "image",
        "img_path": "images/abc.jpg",
        "image_caption": ["Figure 1"],
    }
    md = _item_to_content_md(item, _extract_text_from_content_list_item(item))
    assert md == "![](images/abc.jpg)\n\nFigure 1"


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


def test_equation_not_double_wrapped() -> None:
    """行间公式已带 $$ 时不应重复包裹。"""
    data = [
        {
            "type": "equation",
            "text": "$$\nx = 1\n$$",
            "page_idx": 0,
        },
    ]
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        json.dump(data, f, ensure_ascii=False)
        f.flush()
        try:
            md = content_list_json_to_markdown(Path(f.name))
            assert "$$\nx = 1\n$$" in md
            assert "$$$$" not in md
        finally:
            Path(f.name).unlink()


def test_vlm_pseudo_text_filtered() -> None:
    """VLM/OCR 自我修正说明应被过滤。"""
    data = [
        {
            "type": "text",
            "text": "The image contains a single line. According to Rule 2, [Empty String]",
            "page_idx": 0,
        },
        {"type": "text", "text": "Real paragraph text.", "page_idx": 0},
    ]
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        json.dump(data, f, ensure_ascii=False)
        f.flush()
        try:
            md = content_list_json_to_markdown(Path(f.name))
            assert "The image contains" not in md
            assert "[Empty String]" not in md
            assert "Real paragraph text." in md
        finally:
            Path(f.name).unlink()


def test_image_caption_as_body_paragraph() -> None:
    """图片 caption 应作为正文段落，而非 alt text。"""
    data = [
        {
            "type": "image",
            "img_path": "images/fig.jpg",
            "image_caption": ["Figure 1: caption"],
            "page_idx": 0,
        },
    ]
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        json.dump(data, f, ensure_ascii=False)
        f.flush()
        try:
            md = content_list_json_to_markdown(Path(f.name))
            assert "![](images/fig.jpg)" in md
            assert "Figure 1: caption" in md
            assert "![Figure 1: caption](images/fig.jpg)" not in md
        finally:
            Path(f.name).unlink()


def test_plain_text_list_not_bulleted() -> None:
    """普通文本列表不应被强制转为无序列表。"""
    data = [
        {
            "type": "list",
            "sub_type": "text",
            "list_items": ["(1) first", "If condition", "(2) second"],
            "page_idx": 0,
        },
    ]
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        json.dump(data, f, ensure_ascii=False)
        f.flush()
        try:
            md = content_list_json_to_markdown(Path(f.name))
            assert "- (1) first" not in md
            assert "(1) first" in md
            assert "(2) second" in md
        finally:
            Path(f.name).unlink()


def test_footnote_not_inline_by_default() -> None:
    """默认情况下脚注应输出在文档末尾，而非引用段落后内联。"""
    data = [
        {"type": "text", "text": "Text with reference $^{1}$.", "page_idx": 0},
        {"type": "text", "text": "Another paragraph.", "page_idx": 0},
        {"type": "page_footnote", "text": "1 footnote content", "page_idx": 0},
    ]
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        json.dump(data, f, ensure_ascii=False)
        f.flush()
        try:
            md = content_list_json_to_markdown(Path(f.name))
            # 引用段落后不应紧跟 footnote 块
            assert "Text with reference $^{1}$.\n\n<!-- footnote -->" not in md
            # footnote 应出现在文档末尾
            assert md.strip().endswith("<!-- footnote end -->")
            assert "footnote content" in md
            # 另一个段落应位于引用段落和脚注之间
            assert "Another paragraph." in md
        finally:
            Path(f.name).unlink()


def test_multi_line_footnote_format() -> None:
    """多行脚注每项都应带 - 前缀。"""
    data = [
        {"type": "page_footnote", "text": "*First line.\n†Second line.", "page_idx": 0},
    ]
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        json.dump(data, f, ensure_ascii=False)
        f.flush()
        try:
            md = content_list_json_to_markdown(Path(f.name))
            assert "- *First line." in md
            assert "- †Second line." in md
        finally:
            Path(f.name).unlink()


def test_content_list_v2_equation_interline() -> None:
    """content_list_v2 应正确输出行间公式。"""
    data = [
        [
            {
                "type": "equation_interline",
                "content": {
                    "math_content": "x = 1",
                    "math_type": "latex",
                },
            }
        ]
    ]
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        json.dump(data, f, ensure_ascii=False)
        f.flush()
        try:
            md = content_list_v2_to_markdown(Path(f.name))
            assert "$$x = 1$$" in md
            assert "$$$$" not in md
        finally:
            Path(f.name).unlink()


def test_content_list_v2_image_caption() -> None:
    """content_list_v2 图片 caption 应作为正文段落。"""
    data = [
        [
            {
                "type": "image",
                "content": {
                    "image_source": {"path": "images/fig.jpg"},
                    "image_caption": [{"type": "text", "content": "Figure 1: caption"}],
                    "content": "",
                },
            }
        ]
    ]
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        json.dump(data, f, ensure_ascii=False)
        f.flush()
        try:
            md = content_list_v2_to_markdown(Path(f.name))
            assert "![](images/fig.jpg)" in md
            assert "Figure 1: caption" in md
            assert "![Figure 1: caption](images/fig.jpg)" not in md
        finally:
            Path(f.name).unlink()


def test_convert_html_tables_to_markdown_simple() -> None:
    """简单 HTML 表格应转为 Markdown 表格，默认首行为表头。"""
    html = (
        "<table><tr><td>A</td><td>B</td></tr>"
        "<tr><td>1</td><td>2</td></tr></table>"
    )
    md = convert_html_tables_to_markdown(html)
    assert "<table>" not in md
    assert "| A | B |" in md
    assert "| --- | --- |" in md
    assert "| 1 | 2 |" in md


def test_convert_html_tables_to_markdown_with_th() -> None:
    """包含 <th> 时，表头行应正确识别。"""
    html = (
        "<table><tr><th>Name</th><th>Value</th></tr>"
        "<tr><td>foo</td><td>bar</td></tr></table>"
    )
    md = convert_html_tables_to_markdown(html)
    assert "| Name | Value |" in md
    assert "| foo | bar |" in md


def test_convert_html_tables_to_markdown_escapes_pipe() -> None:
    """单元格中的管道符应被转义。"""
    html = "<table><tr><td>a | b</td><td>c</td></tr></table>"
    md = convert_html_tables_to_markdown(html)
    assert "a \\| b" in md


def test_convert_html_tables_to_markdown_colspan() -> None:
    """colspan 应被展开为多个相同内容的单元格。"""
    html = (
        "<table><tr><td>A</td><td>B</td></tr>"
        "<tr><td colspan=\"2\">X</td></tr></table>"
    )
    md = convert_html_tables_to_markdown(html)
    assert "| X | X |" in md


def test_convert_html_tables_to_markdown_rowspan() -> None:
    """rowspan 应被展开到后续行。"""
    html = (
        "<table><tr><td>A</td><td>B</td></tr>"
        "<tr><td rowspan=\"2\">X</td><td>Y</td></tr>"
        "<tr><td>Z</td></tr></table>"
    )
    md = convert_html_tables_to_markdown(html)
    lines = [ln.strip() for ln in md.splitlines() if ln.strip()]
    assert "| X | Y |" in lines
    assert "| X | Z |" in lines


def test_convert_html_tables_to_markdown_leaves_text_unchanged() -> None:
    """无 HTML 表格时文本应保持不变。"""
    text = "Some text with <b>tag</b> but no table."
    assert convert_html_tables_to_markdown(text) == text


def test_content_list_json_to_markdown_converts_html_table() -> None:
    """content_list JSON 中的 table_body HTML 应被转换为 Markdown 表格。"""
    data = [
        {
            "type": "table",
            "page_idx": 0,
            "table_body": "<table><tr><td>X</td><td>Y</td></tr><tr><td>1</td><td>2</td></tr></table>",
            "table_caption": ["Table 1"],
        }
    ]
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        json.dump(data, f, ensure_ascii=False)
        f.flush()
        try:
            md = content_list_json_to_markdown(Path(f.name))
            assert "<table>" not in md
            assert "| X | Y |" in md
            assert "| 1 | 2 |" in md
            assert "**Table 1**" in md
        finally:
            Path(f.name).unlink()

"""JSON 解析模块：查找并解析 MinerU content_list JSON。"""

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

# 脚注引用符号（①②③④⑤⑥⑦⑧⑨⑩）
FOOTNOTE_REFS = "①②③④⑤⑥⑦⑧⑨⑩"
FOOTNOTE_REF_PATTERN = re.compile(f"[{FOOTNOTE_REFS}]")
# LaTeX 上标脚注引用格式：$^{1}$, $^{2}$ 等
LATEX_FOOTNOTE_REF_PATTERN = re.compile(r"\$\^\{(\d+)\}\$")
# 句末标点：用于判断段落是否可在跨页时合并
# 包含中英文句号、问号、感叹号、引号、分号、冒号以及 proof end 符号 □
SENTENCE_END_CHARS = "。！？；：」\".?!□"
# 需要保留的空白字符
_ALLOWED_WHITESPACE = {"\t", "\n", "\r"}
# 零宽字符
_ZERO_WIDTH_CHARS = "\u200B\u200C\u200D\uFEFF\u2060"


def sanitize_text(text: str) -> str:
    """
    清理文本中的非法控制字符、C1 控制字符与零宽字符。

    保留普通空白（\t、\n、\r）与可见字符，将 \r\n 与单独 \r 统一为 \n。
    用于消除 MinerU OCR/图表识别偶尔混入的乱码控制字符。
    """
    if not isinstance(text, str):
        return ""
    # 保留可见字符与允许的空白，移除 C0 控制字符
    cleaned = "".join(
        c for c in text if ord(c) >= 32 or c in _ALLOWED_WHITESPACE
    )
    # 移除 DEL (U+007F) 与 C1 控制字符 (U+0080-U+009F)
    cleaned = "".join(c for c in cleaned if not 0x7F <= ord(c) <= 0x9F)
    # 移除零宽字符
    cleaned = "".join(c for c in cleaned if c not in _ZERO_WIDTH_CHARS)
    # 统一换行
    return cleaned.replace("\r\n", "\n").replace("\r", "\n")


@dataclass
class PageMeta:
    """页面元信息。"""
    headers: list[str] = field(default_factory=list)
    footers: list[str] = field(default_factory=list)
    page_num: str | None = None


@dataclass
class ContentBlock:
    """统一的内容块表示。"""
    page_idx: int
    markdown: str
    is_plain_paragraph: bool
    footnote_pairs: list[tuple[int, int]] = field(default_factory=list)


@dataclass
class ParsedPage:
    """解析后的页面数据。"""
    content_blocks: list[ContentBlock] = field(default_factory=list)
    footnotes: list[str] = field(default_factory=list)
    meta: PageMeta = field(default_factory=PageMeta)


def find_content_list_json(extract_dir: Path) -> Path | None:
    """
    在解压目录中查找 content_list JSON 文件。
    支持格式：*_content_list.json 或 content_list.json
    """
    candidates = list(extract_dir.rglob("*_content_list.json")) + list(
        extract_dir.rglob("content_list.json")
    )
    for p in candidates:
        if "content_list_v2" not in p.name:
            return p
    return candidates[0] if candidates else None


def _extract_text_from_content_list_item(item: dict) -> str:
    """从 content_list 单项中提取并清理文本内容。"""
    t = item.get("type", "")
    if t in ("text", "header", "footer", "page_number", "page_footnote", "aside_text", "title", "ref_text"):
        return sanitize_text((item.get("text") or "").strip())
    if t == "list":
        items = item.get("list_items", [])
        return "\n".join(sanitize_text(f"- {s.strip()}") for s in items if s)
    if t == "table":
        body = sanitize_text(item.get("table_body", ""))
        caption = item.get("table_caption", [])
        cap_text = sanitize_text(" ".join(caption).strip()) if caption else ""
        return f"**{cap_text}**\n\n{body}" if cap_text else body
    if t == "code":
        body = sanitize_text(item.get("code_body", ""))
        caption = item.get("code_caption", [])
        cap_text = sanitize_text(" ".join(caption).strip()) if caption else ""
        # code_body 通常已包含 ```language\n...\n```，直接返回
        if cap_text:
            return f"{cap_text}\n\n{body}"
        return body
    if t == "image":
        img_path = sanitize_text(item.get("img_path", ""))
        captions = item.get("image_caption", [])
        cap_text = sanitize_text(" ".join(captions).strip()) if captions else ""
        md = f"![{cap_text}]({img_path})" if img_path else cap_text or ""
        # MinerU 对部分图表（如 flowchart）会生成 mermaid 代码，保留在 content 字段
        mermaid = sanitize_text((item.get("content") or "").strip())
        if mermaid:
            md = f"{md}\n\n{mermaid}"
        return md
    if t == "equation":
        return sanitize_text(item.get("latex", item.get("text", "")))
    return ""


def _item_to_content_md(item: dict, text: str) -> str:
    """将 content_list 单项转为 Markdown 内容块。"""
    t = item.get("type", "")
    if t == "text":
        level = item.get("text_level", 0)
        if level and level >= 1:
            return f"# {text}" if level == 1 else f"{'#' * min(level, 6)} {text}"
        return text
    if t == "title":
        level = item.get("text_level", 1)
        return f"{'#' * min(level, 6)} {text}"
    if t in ("list", "table", "code", "image"):
        return text
    if t == "equation":
        return f"$${text}$$"
    if t == "aside_text":
        return f"*{text}*"
    if t == "ref_text":
        return text
    return text if text else ""


def _is_plain_paragraph(item: dict) -> bool:
    """判断是否为普通段落（可参与跨页合并）。"""
    t = item.get("type", "")
    if t != "text":
        return False
    level = item.get("text_level", 0)
    return not level or level == 0


def _ends_with_sentence_end(text: str) -> bool:
    """判断文本是否以句末标点结尾。"""
    return bool(text.rstrip() and text.rstrip()[-1] in SENTENCE_END_CHARS)


def _sort_items_by_reading_order(items: list[dict]) -> list[dict]:
    """按 (page_idx, column, -bbox[1]) 排序：先左栏后右栏，栏内从上到下。"""
    def key_fn(x: dict) -> tuple[int, int, float]:
        page = x.get("page_idx", 0)
        bbox = x.get("bbox") or [0, 0, 0, 0]
        x_center = (bbox[0] + bbox[2]) / 2 if len(bbox) >= 4 else 0
        y_val = bbox[1] if len(bbox) > 1 else 0
        # 分栏：x < 500 为左栏，否则右栏
        column = 0 if x_center < 500 else 1
        return (page, column, -float(y_val))
    return sorted(items, key=key_fn)


def _detect_language(text: str) -> str:
    """检测文本主要语言，返回 'zh' 或 'en'。"""
    if not text:
        return "zh"
    # 统计中文字符数量
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    total_chars = len(re.findall(r'[\w]', text))
    if total_chars == 0:
        return "zh"
    # 中文字符占比超过 10% 视为中文内容
    return "zh" if chinese_chars / total_chars > 0.1 else "en"


def _extract_footnote_refs(text: str) -> list[str]:
    """从文本中按出现顺序提取脚注引用符号。支持 Unicode 圆圈数字和 LaTeX 上标格式。"""
    refs = FOOTNOTE_REF_PATTERN.findall(text)
    # 同时匹配 $^{N}$ 格式的 LaTeX 上标脚注
    latex_refs = LATEX_FOOTNOTE_REF_PATTERN.findall(text)
    refs.extend(latex_refs)
    return refs


def _format_footnote(text: str) -> str:
    """格式化脚注输出。保留 $^{N}$ 前缀，去除纯数字前缀。"""
    # 去除纯数字前缀（如 "1 Note content" -> "Note content"）
    m = re.match(r"^(\d+)\s*(.*)$", text.strip())
    if m:
        text = m.group(2)
    return f"- {text.strip()}"


def _merge_paragraphs(
    flat_blocks: list[ContentBlock],
    merge_paragraphs: bool = True,
) -> list[ContentBlock]:
    """
    合并跨页的普通段落。

    当上一段未以句末标点结尾时，尝试与后续段落合并（同页或跨一页）。
    """
    if not merge_paragraphs or not flat_blocks:
        return flat_blocks

    merged: list[ContentBlock] = []
    i = 0
    while i < len(flat_blocks):
        current = flat_blocks[i]

        if not current.is_plain_paragraph:
            merged.append(current)
            i += 1
            continue

        # 开始合并
        merged_md = current.markdown
        merged_fn_pairs = list(current.footnote_pairs)
        merged_page = current.page_idx
        j = i + 1

        while j < len(flat_blocks):
            next_block = flat_blocks[j]
            if next_block.page_idx > merged_page + 1:
                break
            if not next_block.is_plain_paragraph:
                break
            # 仅合并跨页的段落，避免同一页中相邻段落被错误拼接
            if next_block.page_idx <= merged_page:
                break
            if _ends_with_sentence_end(merged_md):
                break

            merged_md = merged_md + next_block.markdown
            merged_fn_pairs.extend(next_block.footnote_pairs)
            merged_page = next_block.page_idx
            j += 1

        merged.append(ContentBlock(
            page_idx=current.page_idx,
            markdown=merged_md,
            is_plain_paragraph=True,
            footnote_pairs=merged_fn_pairs,
        ))
        i = j

    return merged


def _generate_markdown_output(
    merged_blocks: list[ContentBlock],
    pages_meta: dict[int, PageMeta],
    pages_footnotes: dict[int, list[str]],
    include_header: bool = False,
    include_footer: bool = False,
    include_page_number: bool = False,
    include_footnote: bool = True,
    inline_footnotes: bool = True,
) -> str:
    """从合并后的内容块生成最终 Markdown。"""
    all_parts: list[str] = []
    pages_done: set[int] = set()

    for i, block in enumerate(merged_blocks):
        page_idx = block.page_idx

        # 输出页眉、页码（每页首次出现时）
        if page_idx not in pages_done:
            pages_done.add(page_idx)
            meta = pages_meta.get(page_idx, PageMeta())
            if include_header and meta.headers:
                all_parts.append("<!-- 页眉 -->")
                all_parts.extend(meta.headers)
            if include_page_number and meta.page_num is not None:
                all_parts.append(f"<!-- 页码 {meta.page_num} -->")

        all_parts.append(block.markdown)

        # 内联脚注
        if inline_footnotes and block.footnote_pairs:
            fn_lines = []
            for p, idx in block.footnote_pairs:
                fns = pages_footnotes.get(p, [])
                if idx < len(fns) and fns[idx]:
                    fn_lines.append(f"> {fns[idx]}")
            if fn_lines:
                # 根据脚注内容检测语言，使用对应的注释标签
                fn_text = " ".join(fn_lines)
                lang = _detect_language(fn_text)
                if lang == "zh":
                    all_parts.append("<!-- 脚注 -->\n\n" + "\n".join(fn_lines) + "\n\n<!-- 脚注结束 -->")
                else:
                    all_parts.append("<!-- footnote -->\n\n" + "\n".join(fn_lines) + "\n\n<!-- footnote end -->")

        # 输出页脚：仅对已完成的页输出页脚
        next_page = merged_blocks[i + 1].page_idx if i + 1 < len(merged_blocks) else page_idx + 1
        last_completed = min(
            max(block.page_idx, page_idx),
            next_page - 1
        ) if next_page > page_idx else page_idx

        for p in range(page_idx, last_completed + 1):
            meta = pages_meta.get(p, PageMeta())
            if include_footer and meta.footers:
                all_parts.append("<!-- 页脚 -->")
                all_parts.extend(meta.footers)

    # 兜底输出未内联的脚注
    if include_footnote:
        has_inline_refs = any(block.footnote_pairs for block in merged_blocks)
        if (not inline_footnotes) or (not has_inline_refs):
            trailing_notes: list[str] = []
            for p in sorted(pages_footnotes.keys()):
                notes = [n for n in pages_footnotes[p] if n]
                if notes:
                    # 根据脚注内容检测语言
                    fn_text = " ".join(notes)
                    lang = _detect_language(fn_text)
                    if lang == "zh":
                        trailing_notes.append("<!-- 脚注 -->\n\n" + "\n".join(notes) + "\n\n<!-- 脚注结束 -->")
                    else:
                        trailing_notes.append("<!-- footnote -->\n\n" + "\n".join(notes) + "\n\n<!-- footnote end -->")
            if trailing_notes:
                all_parts.extend(trailing_notes)

    result = "\n\n".join(p for p in all_parts if p)
    return result.replace("\n\n\n\n", "\n\n")


def content_list_json_to_markdown(
    json_path: Path,
    include_header: bool = False,
    include_footer: bool = False,
    include_page_number: bool = False,
    include_footnote: bool = True,
    merge_paragraphs: bool = True,
    inline_footnotes: bool = True,
) -> str:
    """
    从 MinerU content_list JSON 生成完整 Markdown。
    支持跨页段落合并与脚注内联到段落后。
    """
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        logger.warning("content_list JSON 格式异常：非列表")
        return ""

    # 使用原始顺序（MinerU 通常已按阅读顺序输出），避免多栏排版时排序错误
    sorted_items = data

    # 按页分组：内容块、脚注、元信息
    pages_data: dict[int, ParsedPage] = defaultdict(ParsedPage)

    for item in sorted_items:
        t = item.get("type", "")
        text = _extract_text_from_content_list_item(item)
        page_idx = item.get("page_idx", 0)
        page = pages_data[page_idx]

        if t == "header" and text:
            page.meta.headers.append(text)
        elif t == "footer" and text:
            page.meta.footers.append(text)
        elif t == "page_number":
            page.meta.page_num = text.strip() or str(page_idx + 1)
        elif t == "page_footnote" and text:
            page.footnotes.append(_format_footnote(text) if include_footnote else "")
        elif t not in ("header", "footer", "page_number", "page_footnote"):
            if text or t in ("image", "table", "code"):
                md = _item_to_content_md(item, text)
                if md:
                    is_plain = _is_plain_paragraph(item)
                    # 延迟计算 footnote_pairs，在构建 flat_blocks 时统一处理
                    page.content_blocks.append((md, item, is_plain))

    # 构建扁平内容流
    flat_blocks: list[ContentBlock] = []
    for page_idx in sorted(pages_data.keys()):
        page = pages_data[page_idx]
        footnotes = page.footnotes
        fn_idx = 0

        for md, item, is_plain in page.content_blocks:
            text = _extract_text_from_content_list_item(item)
            refs = _extract_footnote_refs(text)
            pairs = []
            for _ in refs:
                if fn_idx < len(footnotes):
                    pairs.append((page_idx, fn_idx))
                    fn_idx += 1

            flat_blocks.append(ContentBlock(
                page_idx=page_idx,
                markdown=md,
                is_plain_paragraph=is_plain,
                footnote_pairs=pairs,
            ))

    # 提取元信息和脚注字典用于输出
    pages_meta = {p: data.meta for p, data in pages_data.items()}
    pages_footnotes = {p: data.footnotes for p, data in pages_data.items()}

    # 合并段落并生成输出
    merged_blocks = _merge_paragraphs(flat_blocks, merge_paragraphs)
    return _generate_markdown_output(
        merged_blocks,
        pages_meta,
        pages_footnotes,
        include_header=include_header,
        include_footer=include_footer,
        include_page_number=include_page_number,
        include_footnote=include_footnote,
        inline_footnotes=inline_footnotes,
    )


def _get_text_from_content_v2(content: dict) -> str:
    """从 content_list_v2 的 content 中提取并清理文本。"""
    if not content:
        return ""
    parts: list[str] = []
    for key in ["paragraph_content", "title_content", "page_number_content", "page_footnote_content", "code_caption", "code_content"]:
        if key in content and isinstance(content[key], list):
            for c in content[key]:
                if isinstance(c, dict):
                    ct = c.get("type", "")
                    if ct == "text":
                        parts.append(sanitize_text(c.get("content", "")))
                    elif ct == "equation_inline":
                        parts.append(f"${sanitize_text(c.get('content', ''))}$")
                    else:
                        parts.append(sanitize_text(c.get("content", "")))
    return " ".join(parts).strip()


def _get_code_caption_from_content_v2(content: dict) -> str:
    """从 content_list_v2 的 content 中提取 code_caption 文本。"""
    if not content:
        return ""
    parts: list[str] = []
    for key in ["code_caption"]:
        if key in content and isinstance(content[key], list):
            for c in content[key]:
                if isinstance(c, dict):
                    ct = c.get("type", "")
                    if ct == "text":
                        parts.append(sanitize_text(c.get("content", "")))
                    else:
                        parts.append(sanitize_text(c.get("content", "")))
    return " ".join(parts).strip()


def _get_code_content_from_content_v2(content: dict) -> str:
    """从 content_list_v2 的 content 中提取 code_content 文本。"""
    if not content:
        return ""
    parts: list[str] = []
    for key in ["code_content"]:
        if key in content and isinstance(content[key], list):
            for c in content[key]:
                if isinstance(c, dict):
                    ct = c.get("type", "")
                    if ct == "text":
                        parts.append(sanitize_text(c.get("content", "")))
                    else:
                        parts.append(sanitize_text(c.get("content", "")))
    return "\n".join(parts)


def _is_plain_paragraph_v2(item: dict) -> bool:
    """判断 content_list_v2 的 paragraph 是否为普通段落（可合并）。"""
    return item.get("type") == "paragraph"


def _convert_v2_to_content_blocks(
    data: list,
    include_footnote: bool = True,
) -> tuple[dict[int, list[ContentBlock]], dict[int, PageMeta], dict[int, list[str]]]:
    """将 content_list_v2 数据转换为统一的内容块格式。"""
    pages_content: dict[int, list[ContentBlock]] = defaultdict(list)
    pages_footnotes: dict[int, list[str]] = defaultdict(list)
    pages_meta: dict[int, PageMeta] = defaultdict(PageMeta)

    for page_idx, page_items in enumerate(data):
        if not isinstance(page_items, list):
            continue

        page_blocks: list[tuple[str, dict, bool]] = []  # (md, item, is_plain)

        for item in page_items:
            t = item.get("type", "")
            content = item.get("content", {})
            text = _get_text_from_content_v2(content) if isinstance(content, dict) else ""

            if t == "header" and text:
                pages_meta[page_idx].headers.append(text)
            elif t == "footer" and text:
                pages_meta[page_idx].footers.append(text)
            elif t == "page_number":
                pages_meta[page_idx].page_num = text.strip() or str(page_idx + 1)
            elif t == "page_footnote" and text:
                pages_footnotes[page_idx].append(_format_footnote(text) if include_footnote else "")
            elif t == "title":
                level = content.get("level", 1)
                md = f"{'#' * min(level, 6)} {text}"
                page_blocks.append((md, item, False))
            elif t == "paragraph":
                page_blocks.append((text, item, True))
            elif t == "list":
                for li in content.get("list_items", []):
                    ic = li.get("item_content", []) if isinstance(li, dict) else []
                    line = " ".join(
                        c.get("content", "") if isinstance(c, dict) else "" for c in ic
                    ).strip()
                    if line:
                        page_blocks.append((f"- {line}", item, False))
            elif t == "code":
                caption = _get_code_caption_from_content_v2(content)
                code_body = _get_code_content_from_content_v2(content)
                lang = content.get("code_language", "") if isinstance(content, dict) else ""
                md_parts: list[str] = []
                if caption:
                    md_parts.append(caption)
                if code_body:
                    md_parts.append(f"```{lang}\n{code_body}\n```")
                if md_parts:
                    page_blocks.append(("\n\n".join(md_parts), item, False))
            elif t == "table" or text:
                page_blocks.append((text, item, False))

        # 为该页的所有内容块计算脚注引用
        footnotes = pages_footnotes[page_idx]
        fn_idx = 0
        for md, item, is_plain in page_blocks:
            text = _get_text_from_content_v2(item.get("content", {}))
            refs = _extract_footnote_refs(text)
            pairs = []
            for _ in refs:
                if fn_idx < len(footnotes):
                    pairs.append((page_idx, fn_idx))
                    fn_idx += 1

            pages_content[page_idx].append(ContentBlock(
                page_idx=page_idx,
                markdown=md,
                is_plain_paragraph=is_plain,
                footnote_pairs=pairs,
            ))

    return pages_content, pages_meta, pages_footnotes


def content_list_v2_to_markdown(
    json_path: Path,
    include_header: bool = False,
    include_footer: bool = False,
    include_page_number: bool = False,
    include_footnote: bool = True,
    merge_paragraphs: bool = True,
    inline_footnotes: bool = True,
) -> str:
    """从 MinerU content_list_v2.json 生成完整 Markdown，支持跨页合并与脚注内联。"""
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        logger.warning("content_list_v2 JSON 格式异常：非列表")
        return ""

    # 转换为统一格式
    pages_content, pages_meta, pages_footnotes = _convert_v2_to_content_blocks(
        data, include_footnote=include_footnote
    )

    # 构建扁平内容流
    flat_blocks: list[ContentBlock] = []
    for page_idx in sorted(pages_content.keys()):
        flat_blocks.extend(pages_content[page_idx])

    # 合并段落并生成输出
    merged_blocks = _merge_paragraphs(flat_blocks, merge_paragraphs)
    return _generate_markdown_output(
        merged_blocks,
        pages_meta,
        pages_footnotes,
        include_header=include_header,
        include_footer=include_footer,
        include_page_number=include_page_number,
        include_footnote=include_footnote,
        inline_footnotes=inline_footnotes,
    )

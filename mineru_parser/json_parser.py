"""JSON 解析模块：查找并解析 MinerU content_list JSON。"""

import json
import re
from collections import defaultdict
from pathlib import Path

from loguru import logger

# 脚注引用符号（①②③④⑤⑥⑦⑧⑨⑩）
FOOTNOTE_REFS = "①②③④⑤⑥⑦⑧⑨⑩"
FOOTNOTE_REF_PATTERN = re.compile(f"[{FOOTNOTE_REFS}]")
# 句末标点：用于判断段落是否可在跨页时合并
SENTENCE_END_CHARS = "。！？；：」\""


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
    """从 content_list 单项中提取文本内容。"""
    t = item.get("type", "")
    if t in ("text", "header", "footer", "page_number", "page_footnote", "aside_text", "title", "ref_text"):
        return (item.get("text") or "").strip()
    if t == "list":
        items = item.get("list_items", [])
        return "\n".join(f"- {s.strip()}" for s in items if s)
    if t == "table":
        body = item.get("table_body", "")
        caption = item.get("table_caption", [])
        cap_text = " ".join(caption).strip() if caption else ""
        return f"**{cap_text}**\n\n{body}" if cap_text else body
    if t == "code":
        body = item.get("code_body", "")
        return f"```\n{body}\n```"
    if t == "image":
        img_path = item.get("img_path", "")
        captions = item.get("image_caption", [])
        cap_text = " ".join(captions).strip() if captions else ""
        return f"![{cap_text}]({img_path})" if img_path else cap_text or ""
    if t == "equation":
        return item.get("latex", item.get("text", ""))
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


def _extract_footnote_refs(text: str) -> list[str]:
    """从文本中按出现顺序提取脚注引用符号。"""
    return FOOTNOTE_REF_PATTERN.findall(text)


def _format_footnote(text: str) -> str:
    """格式化脚注输出。"""
    m = re.match(r"^(\d+)\s*(.*)$", text.strip())
    return f"- {m.group(2)}" if m else f"- {text}"


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
    pages_content: dict[int, list[dict]] = defaultdict(list)
    pages_footnotes: dict[int, list[str]] = defaultdict(list)
    pages_meta: dict[int, dict] = defaultdict(lambda: {"headers": [], "footers": [], "page_num": None})

    for item in sorted_items:
        t = item.get("type", "")
        text = _extract_text_from_content_list_item(item)
        page_idx = item.get("page_idx", 0)

        if t == "header" and text:
            pages_meta[page_idx]["headers"].append(text)
        elif t == "footer" and text:
            pages_meta[page_idx]["footers"].append(text)
        elif t == "page_number":
            pages_meta[page_idx]["page_num"] = text.strip() or str(page_idx + 1)
        elif t == "page_footnote" and text:
            pages_footnotes[page_idx].append(_format_footnote(text) if include_footnote else "")
        elif t not in ("header", "footer", "page_number", "page_footnote"):
            if text or t in ("image", "table", "code"):
                pages_content[page_idx].append(item)

    # 构建扁平内容流：(page_idx, item, footnote_pairs)，footnote_pairs 为 (page_idx, fn_idx) 列表
    flat_blocks: list[tuple[int, dict, list[tuple[int, int]]]] = []
    for page_idx in sorted(pages_content.keys()):
        items = pages_content[page_idx]
        footnotes = pages_footnotes.get(page_idx, [])
        fn_idx = 0
        for item in items:
            text = _extract_text_from_content_list_item(item)
            refs = _extract_footnote_refs(text)
            pairs = []
            for _ in refs:
                if fn_idx < len(footnotes):
                    pairs.append((page_idx, fn_idx))
                    fn_idx += 1
            flat_blocks.append((page_idx, item, pairs))

    # 合并跨页段落并输出
    all_parts: list[str] = []
    pages_done: set[int] = set()
    i = 0
    while i < len(flat_blocks):
        page_idx, item, fn_indices = flat_blocks[i]
        text = _extract_text_from_content_list_item(item)
        md = _item_to_content_md(item, text)
        if not md:
            i += 1
            continue

        # 输出页眉、页码（每页首次出现时）
        if page_idx not in pages_done:
            pages_done.add(page_idx)
            meta = pages_meta[page_idx]
            if include_header and meta["headers"]:
                all_parts.append("<!-- 页眉 -->")
                all_parts.extend(meta["headers"])
            if include_page_number and meta["page_num"] is not None:
                all_parts.append(f"<!-- 页码 {meta['page_num']} -->")

        merged_md = md
        merged_fn_pairs = list(fn_indices)
        merged_page = page_idx

        # 尝试合并后续普通段落（同页或跨页，当上一段未以句末标点结尾时）
        if merge_paragraphs and _is_plain_paragraph(item):
            j = i + 1
            while j < len(flat_blocks):
                next_page, next_item, next_fn = flat_blocks[j]
                if next_page > merged_page + 1:
                    break
                if not _is_plain_paragraph(next_item):
                    break
                if _ends_with_sentence_end(merged_md):
                    break
                next_text = _extract_text_from_content_list_item(next_item)
                next_md = _item_to_content_md(next_item, next_text)
                merged_md = merged_md + next_md
                merged_fn_pairs.extend(next_fn)
                merged_page = next_page
                j += 1
            i = j
        else:
            i += 1

        all_parts.append(merged_md)
        if inline_footnotes and merged_fn_pairs:
            fn_lines = []
            for p, idx in merged_fn_pairs:
                fns = pages_footnotes.get(p, [])
                if idx < len(fns) and fns[idx]:
                    fn_lines.append(f"> {fns[idx]}")
            if fn_lines:
                all_parts.append("\n".join(fn_lines))

        # 输出页脚：仅对已完成的页（下一块来自更高页或已结束）输出页脚
        next_page = flat_blocks[i][0] if i < len(flat_blocks) else merged_page + 1
        last_completed = min(merged_page, next_page - 1) if next_page > page_idx else merged_page
        for p in range(page_idx, last_completed + 1):
            if include_footer and pages_meta[p]["footers"]:
                all_parts.append("<!-- 页脚 -->")
                all_parts.extend(pages_meta[p]["footers"])

    # 兜底输出未内联的脚注（或无正文时仅有脚注）。
    if include_footnote:
        has_inline_refs = any(pairs for _, _, pairs in flat_blocks)
        if (not inline_footnotes) or (not has_inline_refs):
            trailing_notes: list[str] = []
            for p in sorted(pages_footnotes.keys()):
                notes = [n for n in pages_footnotes[p] if n]
                if notes:
                    trailing_notes.append("<!-- 脚注 -->")
                    trailing_notes.extend(notes)
            if trailing_notes:
                all_parts.extend(trailing_notes)

    result = "\n\n".join(p for p in all_parts if p)
    return result.replace("\n\n\n\n", "\n\n")


def _get_text_from_content_v2(content: dict) -> str:
    """从 content_list_v2 的 content 中提取文本。"""
    if not content:
        return ""
    parts: list[str] = []
    for key in ["paragraph_content", "title_content", "page_number_content", "page_footnote_content"]:
        if key in content and isinstance(content[key], list):
            for c in content[key]:
                if isinstance(c, dict):
                    ct = c.get("type", "")
                    if ct == "text":
                        parts.append(c.get("content", ""))
                    elif ct == "equation_inline":
                        parts.append(f"${c.get('content', '')}$")
                    else:
                        parts.append(c.get("content", ""))
    return " ".join(parts).strip()


def _is_plain_paragraph_v2(item: dict) -> bool:
    """判断 content_list_v2 的 paragraph 是否为普通段落（可合并）。"""
    return item.get("type") == "paragraph"


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

    # 按页分组：内容块与脚注
    pages_content: dict[int, list[tuple[str, dict]]] = defaultdict(list)  # (md, item)
    pages_footnotes: dict[int, list[str]] = defaultdict(list)
    pages_meta: dict[int, dict] = defaultdict(lambda: {"headers": [], "footers": [], "page_num": None})

    for page_idx, page_items in enumerate(data):
        if not isinstance(page_items, list):
            continue
        for item in page_items:
            t = item.get("type", "")
            content = item.get("content", {})
            text = _get_text_from_content_v2(content) if isinstance(content, dict) else ""

            if t == "header" and text:
                pages_meta[page_idx]["headers"].append(text)
            elif t == "footer" and text:
                pages_meta[page_idx]["footers"].append(text)
            elif t == "page_number":
                pages_meta[page_idx]["page_num"] = text.strip() or str(page_idx + 1)
            elif t == "page_footnote" and text:
                pages_footnotes[page_idx].append(_format_footnote(text) if include_footnote else "")
            elif t == "title":
                level = content.get("level", 1)
                pages_content[page_idx].append((f"{'#' * min(level, 6)} {text}", item))
            elif t == "paragraph":
                pages_content[page_idx].append((text, item))
            elif t == "list":
                for li in content.get("list_items", []):
                    ic = li.get("item_content", []) if isinstance(li, dict) else []
                    line = " ".join(
                        c.get("content", "") if isinstance(c, dict) else "" for c in ic
                    ).strip()
                    if line:
                        pages_content[page_idx].append((f"- {line}", item))
            elif t == "table" or text:
                pages_content[page_idx].append((text, item))

    # 构建扁平内容流：(page_idx, md, item, footnote_pairs)
    flat_blocks: list[tuple[int, str, dict, list[tuple[int, int]]]] = []
    for page_idx in sorted(pages_content.keys()):
        items = pages_content[page_idx]
        footnotes = pages_footnotes.get(page_idx, [])
        fn_idx = 0
        for md, item in items:
            text = _get_text_from_content_v2(item.get("content", {}))
            refs = _extract_footnote_refs(text)
            pairs = []
            for _ in refs:
                if fn_idx < len(footnotes):
                    pairs.append((page_idx, fn_idx))
                    fn_idx += 1
            flat_blocks.append((page_idx, md, item, pairs))

    # 合并跨页段落并输出
    all_parts: list[str] = []
    pages_done: set[int] = set()
    i = 0
    while i < len(flat_blocks):
        page_idx, md, item, fn_indices = flat_blocks[i]
        meta = pages_meta[page_idx]
        footnotes = pages_footnotes.get(page_idx, [])

        if page_idx not in pages_done:
            pages_done.add(page_idx)
            if include_header and meta["headers"]:
                all_parts.append("<!-- 页眉 -->")
                all_parts.extend(meta["headers"])
            if include_page_number and meta["page_num"] is not None:
                all_parts.append(f"<!-- 页码 {meta['page_num']} -->")

        merged_md = md
        merged_fn_pairs = list(fn_indices)
        merged_page = page_idx

        if merge_paragraphs and _is_plain_paragraph_v2(item):
            j = i + 1
            while j < len(flat_blocks):
                next_page, next_md, next_item, next_fn = flat_blocks[j]
                if next_page > merged_page + 1:
                    break
                if not _is_plain_paragraph_v2(next_item):
                    break
                if _ends_with_sentence_end(merged_md):
                    break
                merged_md = merged_md + next_md
                merged_fn_pairs.extend(next_fn)
                merged_page = next_page
                j += 1
            i = j
        else:
            i += 1

        all_parts.append(merged_md)
        if inline_footnotes and merged_fn_pairs:
            fn_lines = []
            for p, idx in merged_fn_pairs:
                fns = pages_footnotes.get(p, [])
                if idx < len(fns) and fns[idx]:
                    fn_lines.append(f"> {fns[idx]}")
            if fn_lines:
                all_parts.append("\n".join(fn_lines))

        next_page = flat_blocks[i][0] if i < len(flat_blocks) else merged_page + 1
        last_completed = min(merged_page, next_page - 1) if next_page > page_idx else merged_page
        for p in range(page_idx, last_completed + 1):
            if include_footer and pages_meta[p]["footers"]:
                all_parts.append("<!-- 页脚 -->")
                all_parts.extend(pages_meta[p]["footers"])

    if include_footnote:
        has_inline_refs = any(pairs for _, _, _, pairs in flat_blocks)
        if (not inline_footnotes) or (not has_inline_refs):
            trailing_notes: list[str] = []
            for p in sorted(pages_footnotes.keys()):
                notes = [n for n in pages_footnotes[p] if n]
                if notes:
                    trailing_notes.append("<!-- 脚注 -->")
                    trailing_notes.extend(notes)
            if trailing_notes:
                all_parts.extend(trailing_notes)

    result = "\n\n".join(p for p in all_parts if p)
    return result.replace("\n\n\n\n", "\n\n")

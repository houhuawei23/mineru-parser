"""Markdown 生成模块：从 JSON 或 zip 提取并生成 Markdown。"""

import io
import re
import shutil
import zipfile
from pathlib import Path

from loguru import logger

from mineru_parser.engines.image_processor import process_images
from mineru_parser.engines.json_parser import (
    content_list_json_to_markdown,
    content_list_v2_to_markdown,
    convert_html_tables_to_markdown,
    find_content_list_json,
    sanitize_text,
)


def regenerate_markdown_from_json(
    parsed_dir: Path,
    output_md: Path | None = None,
    include_header: bool = False,
    include_footer: bool = False,
    include_page_number: bool = False,
    include_footnote: bool = True,
    merge_paragraphs: bool = True,
    inline_footnotes: bool = False,
) -> str | None:
    """
    从已解压的 MinerU 解析目录中的 JSON 重新生成完整 Markdown。

    :param parsed_dir: 解析输出目录（含 layout.json、*_content_list.json 等）
    :param output_md: 可选，输出 md 路径，默认 parsed_dir/full.md
    :return: markdown 字符串，失败返回 None
    """
    content_list_json = find_content_list_json(parsed_dir)
    content_list_v2 = list(parsed_dir.rglob("content_list_v2.json"))
    markdown: str | None = None

    if content_list_json:
        try:
            markdown = content_list_json_to_markdown(
                content_list_json,
                include_header=include_header,
                include_footer=include_footer,
                include_page_number=include_page_number,
                include_footnote=include_footnote,
                merge_paragraphs=merge_paragraphs,
                inline_footnotes=inline_footnotes,
            )
            logger.debug("已从 content_list JSON 生成 Markdown")
        except Exception as e:
            logger.warning(f"从 content_list JSON 生成失败: {e}")

    if not markdown and content_list_v2:
        try:
            markdown = content_list_v2_to_markdown(
                content_list_v2[0],
                include_header=include_header,
                include_footer=include_footer,
                include_page_number=include_page_number,
                include_footnote=include_footnote,
                merge_paragraphs=merge_paragraphs,
                inline_footnotes=inline_footnotes,
            )
            logger.debug("已从 content_list_v2 JSON 生成 Markdown")
        except Exception as e:
            logger.warning(f"从 content_list_v2 生成失败: {e}")

    if not markdown:
        logger.error("未找到有效的 content_list JSON 文件")
        return None

    markdown = remove_line_number_blocks(markdown)
    markdown = sanitize_text(markdown)
    markdown = convert_html_tables_to_markdown(markdown)
    out_path = output_md or (parsed_dir / "full.md")
    out_path.write_text(markdown, encoding="utf-8")
    logger.info(f"已生成 Markdown: {out_path}")
    return markdown


# 行号块正则：匹配仅含数字的行（论文页边行号），如 *1, 2, 3, 58*
_LINE_NUM_LINE_RE = re.compile(r"^\s*\*?\d+\*?\s*$")


def _is_line_number_block(block: str) -> bool:
    """判断段落是否为页边行号块（仅含数字行）。"""
    lines = [ln for ln in block.strip().split("\n") if ln.strip()]
    if not lines:
        return False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if not _LINE_NUM_LINE_RE.match(stripped):
            return False
    return True


def remove_line_number_blocks(markdown: str) -> str:
    """
    移除论文页边行号块。这些块由 OCR 误识别为正文，格式为 *1, 2, 3, ... 58* 等。
    """
    blocks = markdown.split("\n\n")
    kept = [b for b in blocks if not _is_line_number_block(b)]
    return "\n\n".join(kept)


def extract_markdown_from_zip(z: zipfile.ZipFile) -> str | None:
    """从已打开的 zip 中提取并合并 markdown 内容。"""
    md_files = [
        n for n in z.namelist() if n.endswith(".md") and not n.startswith("__MACOSX")
    ]
    if not md_files:
        return None
    md_files.sort()
    parts: list[str] = []
    for name in md_files:
        try:
            parts.append(z.read(name).decode("utf-8", errors="replace"))
        except Exception as e:
            logger.warning(f"读取 {name} 失败: {e}")
    return "\n\n".join(parts) if parts else None


def build_markdown_from_zip(
    zip_content: bytes,
    extract_dir: Path,
    output_dir: Path,
    include_header: bool = False,
    include_footer: bool = False,
    include_page_number: bool = False,
    include_footnote: bool = True,
    merge_paragraphs: bool = True,
    inline_footnotes: bool = False,
    output_md_name: str = "full.md",
) -> str | None:
    """
    从 zip 内容解压、提取 Markdown、复制图片。优先从 JSON 生成完整 Markdown。

    :return: markdown 字符串，失败返回 None
    """
    temp_extract_dir = extract_dir / "_temp_extract"
    try:
        with zipfile.ZipFile(io.BytesIO(zip_content), "r") as z:
            z.extractall(temp_extract_dir)

        # 优先从 JSON 生成
        content_list_json = find_content_list_json(temp_extract_dir)
        content_list_v2 = list(temp_extract_dir.rglob("content_list_v2.json"))
        markdown: str | None = None

        if content_list_json:
            try:
                markdown = content_list_json_to_markdown(
                    content_list_json,
                    include_header=include_header,
                    include_footer=include_footer,
                    include_page_number=include_page_number,
                    include_footnote=include_footnote,
                    merge_paragraphs=merge_paragraphs,
                    inline_footnotes=inline_footnotes,
                )
            except Exception as e:
                logger.warning(f"从 JSON 生成 Markdown 失败: {e}")

        if not markdown and content_list_v2:
            try:
                markdown = content_list_v2_to_markdown(
                    content_list_v2[0],
                    include_header=include_header,
                    include_footer=include_footer,
                    include_page_number=include_page_number,
                    include_footnote=include_footnote,
                    merge_paragraphs=merge_paragraphs,
                    inline_footnotes=inline_footnotes,
                )
            except Exception as e:
                logger.warning(f"从 content_list_v2 生成失败: {e}")

        if not markdown:
            md_files = list(temp_extract_dir.rglob("*.md"))
            preferred = next((f for f in md_files if f.name == "full.md"), None)
            preferred = preferred or next(
                (f for f in md_files if f.name == "merged.md"), None
            )
            preferred = preferred or (md_files[0] if md_files else None)
            if preferred:
                markdown = preferred.read_text(encoding="utf-8", errors="replace")
                logger.info("使用 zip 内 .md 文件")

        if not markdown:
            logger.error("zip 中未找到 .md 文件或有效 JSON")
            return None

        # 图片后处理：仅保留被引用图片，重命名为 image_xx.png，转 PNG，更新引用格式
        markdown = process_images(markdown, temp_extract_dir, output_dir)

        # 修正行间公式：$$$$ -> $$
        markdown = re.sub(r"\$\$\$\$", "$$", markdown)

        # 移除论文页边行号块
        markdown = remove_line_number_blocks(markdown)

        # 兜底清理：移除所有来源可能混入的控制字符
        markdown = sanitize_text(markdown)

        # 将 HTML 表格转换为 Markdown 表格
        markdown = convert_html_tables_to_markdown(markdown)

        md_path = output_dir / output_md_name
        md_path.write_text(markdown, encoding="utf-8")
        logger.info(f"已保存 Markdown: {md_path}")
        return markdown
    finally:
        shutil.rmtree(temp_extract_dir, ignore_errors=True)


def merge_markdown_parts(
    part_dirs: list[Path],
    output_dir: Path,
    output_md_name: str = "full.md",
    images_dir_name: str = "images",
    part_md_name: str = "full.md",
) -> str:
    """
    合并多个解析片段的 Markdown 与图片。
    将各片段的 md 按顺序拼接，并统一重命名图片引用，复制到 output_dir/{images_dir_name}/。
    仅在存在图片时创建图片目录。

    :param part_dirs: 各片段输出目录（含 part_md_name 与 images_dir_name/）
    :param output_dir: 最终输出目录
    :param output_md_name: 输出 Markdown 文件名，如 xx.md
    :param images_dir_name: 图片子目录名
    :param part_md_name: 片段中的 md 文件名
    :return: 合并后的 Markdown 字符串
    """
    import re
    import shutil
    from mineru_parser.engines.image_processor import IMAGE_REF_PATTERN

    # 匹配 {images_dir_name}/image_xx.png
    esc = re.escape(images_dir_name)
    img_path_re = re.compile(rf"{esc}/(image_\d+\.png)", re.IGNORECASE)
    parts_md: list[str] = []
    total_img_idx = 0
    images_dir = output_dir / images_dir_name
    images_dir_created = False

    for part_dir in part_dirs:
        md_path = part_dir / part_md_name
        if not md_path.exists():
            logger.warning(f"片段缺少 {part_md_name}: {part_dir}")
            continue

        md = md_path.read_text(encoding="utf-8", errors="replace")
        part_images = part_dir / images_dir_name

        # 按出现顺序收集该片段中的图片引用
        refs = IMAGE_REF_PATTERN.findall(md)
        name_map: dict[str, str] = {}  # 旧名 -> 新名
        for _cap, path in refs:
            m = img_path_re.search(path)
            if m:
                old_name = m.group(1)
                if old_name not in name_map:
                    total_img_idx += 1
                    new_name = f"image_{total_img_idx:02d}.png"
                    name_map[old_name] = new_name

        # 替换 Markdown 中的引用
        def replacer(m: re.Match[str]) -> str:
            path = m.group(2)
            mm = img_path_re.search(path)
            if mm:
                old_name = mm.group(1)
                new_name = name_map.get(old_name)
                if new_name:
                    new_path = f"{images_dir_name}/{new_name}"
                    new_cap = Path(new_name).stem
                    return f"![{new_cap}]({new_path})"
            return m.group(0)

        md = IMAGE_REF_PATTERN.sub(replacer, md)

        # 复制图片（仅在存在图片时创建 images 目录）
        for old_name, new_name in name_map.items():
            if not images_dir_created:
                images_dir.mkdir(parents=True, exist_ok=True)
                images_dir_created = True
            src = part_images / old_name
            if src.exists():
                dest = images_dir / new_name
                shutil.copy2(src, dest)
            else:
                # 尝试无扩展名匹配
                stem = Path(old_name).stem
                for f in part_images.glob(f"{stem}.*"):
                    dest = images_dir / new_name
                    shutil.copy2(f, dest)
                    break

        parts_md.append(md)

    merged = "\n\n".join(parts_md)
    md_path = output_dir / output_md_name
    md_path.write_text(merged, encoding="utf-8")
    logger.info(f"已合并 {len(part_dirs)} 个片段，共 {total_img_idx} 张图片")
    return merged

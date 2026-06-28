"""PDF 拆分模块：按页数/大小限制切分 PDF。"""

from __future__ import annotations

import re
from pathlib import Path

from loguru import logger
from pypdf import PdfReader, PdfWriter

# 允许的页码片段：单页 "12" 或区间 "10-20"
_PAGE_SEGMENT = re.compile(r"^\s*(\d+)\s*(?:-\s*(\d+))?\s*$")


def parse_pages_spec(spec: str, num_pages: int) -> tuple[list[int], list[str]]:
    """
    解析 CLI 页码字符串（1-based），返回 0-based 索引列表（去重、升序）及警告信息。

    格式示例：``10-20,30-40``、``5``、``1-3, 7``。空白会被忽略。

    若某区间上下界颠倒，会自动交换。超出 ``[1, num_pages]`` 的端点会裁剪到文档范围内；
    与文档无交集的片段会跳过并记入警告。

    :param spec: 用户输入，如 ``"10-20,30-40"``
    :param num_pages: PDF 总页数（至少为 1 时才有有效页）
    :return: (page_indices_0based, warning_messages)
    """
    warnings: list[str] = []
    if not spec or not spec.strip():
        return [], ["页码范围为空"]
    if num_pages < 1:
        return [], [f"PDF 无有效页面（总页数 {num_pages}）"]

    pages_1based: set[int] = set()

    for raw in spec.split(","):
        part = raw.strip()
        if not part:
            continue
        m = _PAGE_SEGMENT.match(part)
        if not m:
            warnings.append(f"无法解析的片段，已忽略: {part!r}")
            continue
        a_str, b_str = m.group(1), m.group(2)
        a = int(a_str)
        if b_str is None:
            lo = hi = a
        else:
            b = int(b_str)
            lo, hi = (a, b) if a <= b else (b, a)
            if a > b:
                warnings.append(f"区间 {a}-{b} 上下界已自动调整为 {lo}-{hi}")

        # 与 [1, num_pages] 求交
        eff_lo = max(1, lo)
        eff_hi = min(num_pages, hi)
        if eff_lo > eff_hi:
            warnings.append(
                f"片段 {part} 与文档无交集（文档共 {num_pages} 页），已跳过"
            )
            continue
        if lo < 1 or hi > num_pages:
            warnings.append(
                f"片段 {part} 已裁剪为 {eff_lo}-{eff_hi}（文档共 {num_pages} 页）"
            )
        for p in range(eff_lo, eff_hi + 1):
            pages_1based.add(p)

    sorted_pages = sorted(pages_1based)
    indices = [p - 1 for p in sorted_pages]
    for w in warnings:
        logger.warning(w)
    return indices, warnings


def extract_pages_to_pdf(
    src: Path,
    page_indices_0based: list[int],
    dest: Path,
) -> None:
    """
    将指定页按顺序写入新 PDF（索引为 0-based，须已在调用方校验范围）。
    """
    if not page_indices_0based:
        raise ValueError("page_indices_0based 不能为空")
    reader = PdfReader(str(src))
    n = len(reader.pages)
    writer = PdfWriter()
    for i in page_indices_0based:
        if i < 0 or i >= n:
            raise ValueError(f"页索引越界: {i}（PDF 共 {n} 页）")
        writer.add_page(reader.pages[i])
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as f:
        writer.write(f)


def get_pdf_info(pdf_path: Path) -> tuple[int, int]:
    """
    获取 PDF 页数和文件大小。

    :return: (num_pages, size_bytes)
    """
    size_bytes = pdf_path.stat().st_size
    reader = PdfReader(str(pdf_path))
    num_pages = len(reader.pages)
    return num_pages, size_bytes


def split_pdf_by_limits(
    pdf_path: Path,
    page_limit: int,
    size_limit_bytes: int,
    temp_dir: Path,
) -> list[Path]:
    """
    若 PDF 超出页数或大小限制，按页数切分为多个子 PDF。
    每个子 PDF 不超过 page_limit 页，且尽量不超过 size_limit_bytes（按页均分估算）。

    :param pdf_path: 源 PDF 路径
    :param page_limit: 每片最大页数
    :param size_limit_bytes: 每片最大字节数（200MB ≈ 209715200）
    :param temp_dir: 临时目录，用于存放切分后的 PDF
    :return: 切分后的 PDF 路径列表，若无需切分则返回 [pdf_path]
    """
    num_pages, size_bytes = get_pdf_info(pdf_path)

    # 无需切分：页数和大小均在限制内
    if num_pages <= page_limit and size_bytes <= size_limit_bytes:
        return [pdf_path]

    logger.info(
        f"PDF 超出限制（{num_pages} 页、{size_bytes / 1024 / 1024:.1f} MB），将自动切分"
    )

    temp_dir.mkdir(parents=True, exist_ok=True)
    stem = pdf_path.stem
    reader = PdfReader(str(pdf_path))

    # 计算每片页数：优先满足页数限制，若单页均摊大小仍超限则进一步切分
    pages_per_chunk = page_limit
    avg_bytes_per_page = size_bytes / num_pages if num_pages else 0
    if (
        avg_bytes_per_page > 0
        and pages_per_chunk * avg_bytes_per_page > size_limit_bytes
    ):
        pages_per_chunk = max(1, int(size_limit_bytes / avg_bytes_per_page))

    output_paths: list[Path] = []
    start = 0
    chunk_idx = 0

    while start < num_pages:
        end = min(start + pages_per_chunk, num_pages)
        writer = PdfWriter()
        for i in range(start, end):
            writer.add_page(reader.pages[i])

        out_path = temp_dir / f"{stem}_part{chunk_idx}.pdf"
        writer.write(str(out_path))
        output_paths.append(out_path)
        logger.debug(f"已切分: {out_path.name} (页 {start + 1}-{end})")

        start = end
        chunk_idx += 1

    logger.info(f"已切分为 {len(output_paths)} 个片段")
    return output_paths


def split_pdf_adaptive(
    pdf_path: Path,
    target_chunk_pages: int,
    page_limit: int,
    size_limit_bytes: int,
    temp_dir: Path,
) -> list[Path]:
    """
    自适应分片：当 PDF 页数超过 ``target_chunk_pages`` 时切分为该大小的片段，
    即使未超出硬限制（page_limit / file_size_limit_mb），从而并发调用 API 加速解析。

    若 ``target_chunk_pages <= 0`` 或 PDF 页数不超过该值，委托给
    :func:`split_pdf_by_limits`（传统行为）。

    :param pdf_path: 源 PDF 路径
    :param target_chunk_pages: 自适应分片目标页数（>0 时启用）
    :param page_limit: 每片最大页数（硬限制）
    :param size_limit_bytes: 每片最大字节数（硬限制）
    :param temp_dir: 临时目录，用于存放切分后的 PDF
    :return: 切分后的 PDF 路径列表
    """
    num_pages, size_bytes = get_pdf_info(pdf_path)

    # 未启用自适应分片，或 PDF 页数不超过目标值：走传统逻辑
    if target_chunk_pages <= 0 or num_pages <= target_chunk_pages:
        return split_pdf_by_limits(pdf_path, page_limit, size_limit_bytes, temp_dir)

    # 未超限且不需要自适应分片的情况已在上面处理
    logger.info(f"自适应分片：{num_pages} 页，目标每片 {target_chunk_pages} 页")

    temp_dir.mkdir(parents=True, exist_ok=True)
    stem = pdf_path.stem
    reader = PdfReader(str(pdf_path))

    # 计算每片页数：优先使用 target_chunk_pages，再检查大小限制
    pages_per_chunk = target_chunk_pages
    avg_bytes_per_page = size_bytes / num_pages if num_pages else 0
    if (
        avg_bytes_per_page > 0
        and pages_per_chunk * avg_bytes_per_page > size_limit_bytes
    ):
        pages_per_chunk = max(1, int(size_limit_bytes / avg_bytes_per_page))
        logger.info(f"按大小限制调整每片页数为 {pages_per_chunk}")

    # 同时也不能超过 page_limit
    pages_per_chunk = min(pages_per_chunk, page_limit)

    output_paths: list[Path] = []
    start = 0
    chunk_idx = 0

    while start < num_pages:
        end = min(start + pages_per_chunk, num_pages)
        writer = PdfWriter()
        for i in range(start, end):
            writer.add_page(reader.pages[i])

        out_path = temp_dir / f"{stem}_part{chunk_idx}.pdf"
        writer.write(str(out_path))
        output_paths.append(out_path)
        logger.debug(f"已切分: {out_path.name} (页 {start + 1}-{end})")

        start = end
        chunk_idx += 1

    logger.info(f"自适应分片完成：{len(output_paths)} 个片段")
    return output_paths

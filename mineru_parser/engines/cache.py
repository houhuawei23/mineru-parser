"""解析结果缓存模块。

缓存身份 = ``源 PDF 内容哈希 + 该单元覆盖的源页码集合``，**与切分/提取产出的
派生 PDF 字节无关**。这样即便 PyMuPDF 的 ``save()`` 每次写入都嵌入随机 ``/ID``
与时间戳（导致派生文件字节不确定），只要源 PDF 与所选页码不变，缓存键就稳定。

目录布局（同一源 PDF 的所有结果归入同一组目录，便于查看管理）::

    <cache_dir>/<model>/<safe_stem>_<hash8>/
        full.zip          # 整篇、未切分
        p1-50.zip         # 切分片段（连续区间，人类可读）
        p10-20.zip        # --pages 提取的连续子集
        h<12hex>.zip      # 非连续页码集合
        source.txt        # 记录源 PDF 文件名，便于人眼辨认
"""

import hashlib
import re
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from mineru_parser.models.config import RootConfig

# 组目录短哈希长度（源 SHA256 的前缀），用于区分同名不同内容的 PDF
_SHORT_HASH_LEN = 8
# 非连续页码集合兜底 token 的哈希前缀长度
_TOKEN_HASH_LEN = 12
# 组目录中源文件名 stem 的最大长度（清洗后）
_MAX_STEM_LEN = 40
# 合法 stem 字符（其余替换为下划线）
_STEM_OK = re.compile(r"[^A-Za-z0-9._-]")


# 用于缓存的内部函数，基于文件路径和修改时间
@lru_cache(maxsize=128)
def _compute_pdf_hash_cached(
    path_str: str, mtime: float, size: int, chunk_size: int
) -> str:
    """
    计算 PDF 文件的 SHA256 哈希（带缓存版本）。

    缓存键包括：文件路径、修改时间、文件大小、块大小
    如果文件被修改，mtime 会改变，自动使缓存失效。

    :param path_str: PDF 文件路径（字符串）
    :param mtime: 文件修改时间
    :param size: 文件大小（用于验证）
    :param chunk_size: 读块大小
    :return: SHA256 十六进制哈希字符串
    """
    pdf_path = Path(path_str)
    h = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def _compute_pdf_hash(pdf_path: Path, config: "RootConfig") -> str:
    """
    计算 PDF 文件的 SHA256 哈希，用于缓存键。

    使用 LRU 缓存避免对同一文件的重复哈希计算。
    缓存基于文件路径、修改时间和大小自动失效。

    :param pdf_path: PDF 文件路径
    :param config: 配置对象，包含 cache_hash_chunk_size
    :return: SHA256 十六进制哈希字符串
    """
    # 获取文件统计信息用于缓存键
    stat = pdf_path.stat()
    mtime = stat.st_mtime
    size = stat.st_size
    chunk_size = config.cache_hash_chunk_size

    # 调用带缓存的版本
    return _compute_pdf_hash_cached(str(pdf_path), mtime, size, chunk_size)


def compute_source_hash(source_pdf: Path, config: "RootConfig") -> str:
    """
    计算**源** PDF 的内容 SHA256，作为缓存身份的稳定基础。

    始终对原始输入 PDF 取哈希（而非切分/提取后的派生文件），从而规避 PyMuPDF
    写出字节的随机性。复用 :func:`_compute_pdf_hash` 的 mtime/size LRU 缓存。

    :param source_pdf: 源 PDF 路径
    :param config: 配置对象
    :return: SHA256 十六进制哈希字符串
    :raises FileNotFoundError: 源 PDF 不存在
    """
    if not source_pdf.exists():
        raise FileNotFoundError(f"源 PDF 不存在，无法计算缓存键: {source_pdf}")
    return _compute_pdf_hash(source_pdf, config)


def describe_page_token(source_indices_0based: list[int]) -> str:
    """
    将一组**源页码**（0-based）转为稳定且人类可读的缓存 token。

    - 单页 → ``p{n+1}``
    - 连续区间 → ``p{a+1}-{b+1}``
    - 非连续（如 ``--pages 1-3,7``）→ ``h<sha256[:12]>``（确定性、避免特殊字符）

    :param source_indices_0based: 该解析单元覆盖的源页码（0-based，可乱序/重复）
    :return: 稳定的页码描述 token
    """
    if not source_indices_0based:
        return "p0"
    pages = sorted(set(source_indices_0based))
    if len(pages) == 1:
        return f"p{pages[0] + 1}"
    if pages == list(range(pages[0], pages[-1] + 1)):
        return f"p{pages[0] + 1}-{pages[-1] + 1}"
    key = ",".join(str(p) for p in pages)
    short = hashlib.sha256(key.encode()).hexdigest()[:_TOKEN_HASH_LEN]
    return f"h{short}"


def _sanitize_stem(stem: str, max_len: int = _MAX_STEM_LEN) -> str:
    """清洗文件名 stem：仅保留 ``[A-Za-z0-9._-]``，其余替换为 ``_``，并截断长度。

    空结果兜底为 ``pdf``，保证目录名非空。
    """
    cleaned = _STEM_OK.sub("_", stem).strip("._-")[:max_len]
    return cleaned or "pdf"


def cache_group_dir(
    cache_dir: Path,
    model_version: str,
    source_pdf: Path,
    source_hash: str,
) -> Path:
    """
    计算源 PDF 对应的**缓存组目录**：``<cache_dir>/<model>/<safe_stem>_<hash8>``。

    同一源 PDF 的所有结果（整篇/片段/页码子集）都落在同一组目录下；
    目录名含可读文件名前缀与内容短哈希，既好辨认又能区分同名不同内容。

    目录名由 ``(source_pdf, source_hash)`` 确定性重建 → 查找与写入路径一致。
    """
    safe_stem = _sanitize_stem(source_pdf.stem)
    short = source_hash[:_SHORT_HASH_LEN]
    return cache_dir / model_version / f"{safe_stem}_{short}"


def cache_zip_path(
    cache_dir: Path,
    model_version: str,
    source_pdf: Path,
    source_hash: str,
    page_token: str,
) -> Path:
    """计算单个缓存 zip 的完整路径：``cache_group_dir(...) / f"{page_token}.zip"``。"""
    return (
        cache_group_dir(cache_dir, model_version, source_pdf, source_hash)
        / f"{page_token}.zip"
    )


def write_source_marker(group_dir: Path, source_pdf: Path) -> None:
    """在缓存组目录写入 ``source.txt``，记录源 PDF 文件名（best-effort，便于人眼辨认）。"""
    try:
        group_dir.mkdir(parents=True, exist_ok=True)
        marker = group_dir / "source.txt"
        # 仅在内容变化时写入，避免无谓 IO
        new_text = str(source_pdf)
        if not marker.exists() or marker.read_text(encoding="utf-8") != new_text:
            marker.write_text(new_text, encoding="utf-8")
    except OSError as e:
        logger.debug(f"写入 source.txt 失败（忽略）: {e}")


def get_cached_zip(cache_file: Path) -> bytes | None:
    """
    从给定缓存文件读取已解析的 zip 内容。

    :param cache_file: 缓存 zip 的完整路径（由 :func:`cache_zip_path` 计算）
    :return: zip 字节内容，未命中返回 None
    """
    if cache_file.exists():
        try:
            content = cache_file.read_bytes()
            logger.info(f"命中缓存，复用已解析结果: {cache_file}")
            return content
        except OSError as e:
            logger.warning(f"读取缓存失败: {e}")
    return None


def save_to_cache(cache_file: Path, zip_content: bytes) -> Path | None:
    """
    将解析结果写入给定缓存文件。

    :param cache_file: 缓存 zip 的完整路径（由 :func:`cache_zip_path` 计算）
    :param zip_content: zip 字节内容
    :return: 缓存文件路径，失败返回 None
    """
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(zip_content)
        logger.debug(f"已写入缓存: {cache_file}")
        return cache_file
    except OSError as e:
        logger.warning(f"写入缓存失败: {e}")
        return None

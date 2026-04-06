"""解析结果缓存模块：基于 PDF 内容哈希缓存 zip，避免重复调用 API。"""

import hashlib
import os
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from mineru_parser.config import Config


# 用于缓存的内部函数，基于文件路径和修改时间
@lru_cache(maxsize=128)
def _compute_pdf_hash_cached(path_str: str, mtime: float, size: int, chunk_size: int) -> str:
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


def _compute_pdf_hash(pdf_path: Path, config: "Config") -> str:
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


def get_cached_zip(
    pdf_path: Path,
    cache_dir: Path,
    config: "Config",
    model_version: str = "vlm",
) -> bytes | None:
    """
    从缓存获取已解析的 zip 内容。

    :param pdf_path: PDF 文件路径
    :param cache_dir: 缓存目录
    :param config: 配置对象，包含 cache_key_prefix_len
    :param model_version: 模型版本（不同版本结果可能不同，需区分缓存）
    :return: zip 字节内容，未命中返回 None
    """
    if not pdf_path.exists():
        return None

    prefix_len = config.cache_key_prefix_len
    cache_key = _compute_pdf_hash(pdf_path, config)
    cache_file = cache_dir / model_version / cache_key[:prefix_len] / f"{cache_key}.zip"
    if cache_file.exists():
        try:
            content = cache_file.read_bytes()
            logger.info(f"命中缓存，使用已解析结果: {cache_file}")
            return content
        except OSError as e:
            logger.warning(f"读取缓存失败: {e}")
    return None


def save_to_cache(
    pdf_path: Path,
    zip_content: bytes,
    cache_dir: Path,
    config: "Config",
    model_version: str = "vlm",
) -> Path | None:
    """
    将解析结果保存到缓存。

    :param pdf_path: PDF 文件路径
    :param zip_content: zip 字节内容
    :param cache_dir: 缓存目录
    :param config: 配置对象，包含 cache_key_prefix_len
    :param model_version: 模型版本
    :return: 缓存文件路径，失败返回 None
    """
    if not pdf_path.exists():
        return None

    prefix_len = config.cache_key_prefix_len
    cache_key = _compute_pdf_hash(pdf_path, config)
    cache_file = cache_dir / model_version / cache_key[:prefix_len] / f"{cache_key}.zip"
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(zip_content)
        logger.debug(f"已写入缓存: {cache_file}")
        return cache_file
    except OSError as e:
        logger.warning(f"写入缓存失败: {e}")
        return None


def get_default_cache_dir(config: "Config") -> Path:
    """从配置获取默认缓存目录。

    :param config: 配置对象
    :return: 缓存目录路径
    """
    return config.cache_dir

"""解析结果缓存模块：基于 PDF 内容哈希缓存 zip，避免重复调用 API。"""

import hashlib
from pathlib import Path

from loguru import logger


def _compute_pdf_hash(pdf_path: Path, chunk_size: int | None = None) -> str:
    """计算 PDF 文件的 SHA256 哈希，用于缓存键。"""
    if chunk_size is None:
        from mineru_parser.config import load_config
        cfg = load_config(None)
        chunk_size = cfg.cache_hash_chunk_size
    h = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def get_cached_zip(
    pdf_path: Path,
    cache_dir: Path,
    model_version: str = "vlm",
) -> bytes | None:
    """
    从缓存获取已解析的 zip 内容。

    :param pdf_path: PDF 文件路径
    :param cache_dir: 缓存目录
    :param model_version: 模型版本（不同版本结果可能不同，需区分缓存）
    :return: zip 字节内容，未命中返回 None
    """
    if not pdf_path.exists():
        return None

    from mineru_parser.config import load_config
    cfg = load_config(None)
    prefix_len = cfg.cache_key_prefix_len
    cache_key = _compute_pdf_hash(pdf_path)
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
    model_version: str = "vlm",
) -> Path | None:
    """
    将解析结果保存到缓存。

    :param pdf_path: PDF 文件路径
    :param zip_content: zip 字节内容
    :param cache_dir: 缓存目录
    :param model_version: 模型版本
    :return: 缓存文件路径，失败返回 None
    """
    if not pdf_path.exists():
        return None

    from mineru_parser.config import load_config
    cfg = load_config(None)
    prefix_len = cfg.cache_key_prefix_len
    cache_key = _compute_pdf_hash(pdf_path)
    cache_file = cache_dir / model_version / cache_key[:prefix_len] / f"{cache_key}.zip"
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(zip_content)
        logger.debug(f"已写入缓存: {cache_file}")
        return cache_file
    except OSError as e:
        logger.warning(f"写入缓存失败: {e}")
        return None


def get_default_cache_dir() -> Path:
    """从 default_config.yml 获取默认缓存目录。"""
    from mineru_parser.config import load_config
    return load_config(None).cache_dir

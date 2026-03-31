"""工具函数：URL 解析、PDF 下载等。"""

import re
from pathlib import Path
from typing import Tuple
from urllib.parse import urlparse

import requests
from loguru import logger

ARXIV_ABS_PATTERN = re.compile(
    r"https?://(?:www\.)?arxiv\.org/abs/([\d]+\.[\d]+(?:v\d+)?)",
    re.IGNORECASE,
)


def arxiv_abs_to_pdf_url(arxiv_url: str) -> str | None:
    """将 arXiv 摘要页 URL 转为 PDF 直链。"""
    m = ARXIV_ABS_PATTERN.match(arxiv_url.strip())
    if not m:
        return None
    arxiv_id = m.group(1)
    base_id = re.sub(r"v\d+$", "", arxiv_id, flags=re.IGNORECASE)
    return f"https://arxiv.org/pdf/{base_id}.pdf"


def download_pdf_from_url(url: str, save_path: Path, timeout: int = 120) -> bool:
    """
    从 URL 下载 PDF 到本地。
    支持 arXiv 摘要链接（自动转为 PDF 链接）及直接 PDF 链接。
    """
    pdf_url = url.strip()
    if ARXIV_ABS_PATTERN.match(pdf_url):
        pdf_url = arxiv_abs_to_pdf_url(pdf_url) or pdf_url
        logger.info(f"已解析 arXiv 链接，PDF 地址: {pdf_url}")

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    try:
        resp = requests.get(pdf_url, headers=headers, timeout=timeout, stream=True)
        resp.raise_for_status()
        content = resp.content
        if len(content) < 100:
            logger.warning("下载内容过短，可能不是有效 PDF")
            return False
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_bytes(content)
        logger.info(f"已下载 PDF: {save_path} ({len(content) / 1024:.1f} KB)")
        return True
    except requests.RequestException as e:
        logger.error(f"下载失败: {e}")
        return False


def resolve_input_to_pdf(
    input_or_url: str,
    output_dir: Path | None = None,
) -> Tuple[Path | None, str | None]:
    """
    将输入（本地路径或 URL）解析为可用的 PDF 路径及输出 stem。

    :return: (pdf_path, output_stem)
    """
    s = input_or_url.strip()
    if s.startswith("http://") or s.startswith("https://"):
        m = ARXIV_ABS_PATTERN.match(s)
        if m:
            base_id = re.sub(r"v\d+$", "", m.group(1), flags=re.IGNORECASE)
            output_stem = f"arxiv_{base_id}"
        else:
            parsed = urlparse(s)
            name = Path(parsed.path).stem or "downloaded"
            output_stem = f"url_{name}"[:80]

        out_dir = output_dir or Path.cwd()
        save_path = out_dir / f"{output_stem}.pdf"
        if not download_pdf_from_url(s, save_path):
            return None, None
        return save_path, output_stem

    path = Path(s)
    if not path.exists():
        logger.error(f"文件不存在: {path}")
        return None, None
    return path, path.stem


def collect_pdf_paths(
    input_path: Path,
    recursive: bool = False,
    include: str = "*.pdf",
    exclude: str = "",
) -> list[Path]:
    """
    收集 PDF 文件路径。
    :param input_path: 输入文件或目录
    :param recursive: 是否递归子目录
    :param include: 包含模式（如 *.pdf）
    :param exclude: 排除模式（正则）
    """
    if input_path.is_file():
        return [input_path] if input_path.suffix.lower() == ".pdf" else []

    pattern = include if include else "*.pdf"
    paths: list[Path] = []
    iterator = input_path.rglob(pattern) if recursive else input_path.glob(pattern)
    for p in iterator:
        if p.is_file() and p.suffix.lower() == ".pdf":
            if exclude and re.search(exclude, str(p)):
                continue
            paths.append(p)
    return sorted(set(paths))

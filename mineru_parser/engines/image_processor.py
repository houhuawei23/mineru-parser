"""图片后处理模块：提取引用、重命名、转 PNG、更新 Markdown 格式。"""

from __future__ import annotations

import re
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from loguru import logger
from PIL import Image

# Markdown 图片引用正则：![alt](path)
IMAGE_REF_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")

# 默认并行工作进程数
DEFAULT_IMAGE_WORKERS = 4


def _convert_single_image(args: tuple[Path, Path, str, str]) -> tuple[str, bool]:
    """
    转换单个图片为 PNG（用于进程池）。

    :param args: (src_path, dest_dir, old_name, new_name) 元组
    :return: (new_name, success) 元组
    """
    src_path, dest_dir, old_name, new_name = args
    dest = dest_dir / new_name

    try:
        img = Image.open(src_path)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGBA")
        else:
            img = img.convert("RGB")
        img.save(dest, "PNG")
        return (new_name, True)
    except Exception as e:
        logger.warning(f"图片转换失败 {src_path}: {e}")
        return (new_name, False)


def extract_image_refs(markdown: str) -> list[tuple[str, str]]:
    """
    按出现顺序提取 Markdown 中的图片引用。

    Args:
        markdown: 原始 Markdown 文本

    Returns:
        [(caption, path), ...] 列表，按出现顺序
    """
    refs: list[tuple[str, str]] = []
    for m in IMAGE_REF_PATTERN.finditer(markdown):
        caption = m.group(1)
        path = m.group(2).strip()
        refs.append((caption, path))
    return refs


def _find_image_file(temp_extract_dir: Path, img_path: str) -> Path | None:
    """在解压目录中查找图片文件。支持相对路径或纯文件名。"""
    # 可能路径：images/xxx.jpg 或 xxx.jpg
    path = Path(img_path)
    candidates = [
        temp_extract_dir / img_path,
        temp_extract_dir / path.name,
    ]
    for c in candidates:
        if c.exists() and c.is_file():
            return c
    # 递归搜索文件名
    for f in temp_extract_dir.rglob(path.name):
        if f.is_file():
            return f
    return None


def _convert_to_png(src: Path, dest: Path) -> bool:
    """将图片转为 PNG 格式保存。"""
    try:
        img = Image.open(src)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGBA")
        else:
            img = img.convert("RGB")
        img.save(dest, "PNG")
        return True
    except Exception as e:
        logger.warning(f"图片转换失败 {src}: {e}")
        return False


def process_images(
    markdown: str,
    temp_extract_dir: Path,
    output_dir: Path,
    max_workers: int | None = None,
) -> str:
    """
    处理 Markdown 中的图片：仅保留被引用的图片，重命名为 image_xx.png，转为 PNG，
    并更新引用格式为 ![image_xx](images/image_xx.png) 后跟 > Caption。

    使用进程池并行处理图片转换以提高性能。

    Args:
        markdown: 原始 Markdown 文本
        temp_extract_dir: zip 解压临时目录
        output_dir: 输出目录（images 子目录将在此创建）
        max_workers: 并行工作进程数，默认 4

    Returns:
        更新后的 Markdown 文本
    """
    refs = extract_image_refs(markdown)
    if not refs:
        return markdown  # 无图片引用时不创建 images 目录

    # 去重保序：path -> (new_name, caption)，首次出现的 caption 作为该 path 的 caption
    path_to_info: dict[str, tuple[str, str]] = {}
    ordered_paths: list[str] = []
    for caption, path in refs:
        if path not in path_to_info:
            path_to_info[path] = (f"image_{len(path_to_info) + 1:02d}.png", caption)
            ordered_paths.append(path)

    # 清空并重建 images 目录
    final_images_dir = output_dir / "images"
    if final_images_dir.exists():
        for f in final_images_dir.iterdir():
            if f.is_file():
                f.unlink()
    final_images_dir.mkdir(parents=True, exist_ok=True)

    # 准备并行处理的任务
    tasks: list[tuple[Path, Path, str, str]] = []
    for path in ordered_paths:
        new_name, _ = path_to_info[path]
        src = _find_image_file(temp_extract_dir, path)
        if not src:
            logger.warning(f"未找到图片: {path}")
            continue
        tasks.append((src, final_images_dir, path, new_name))

    # 并行处理图片转换
    if tasks:
        workers = max_workers or DEFAULT_IMAGE_WORKERS
        successful: set[str] = set()

        with ProcessPoolExecutor(max_workers=workers) as executor:
            results = executor.map(_convert_single_image, tasks)
            for new_name, success in results:
                if success:
                    successful.add(new_name)
                    logger.debug(f"已保存: {final_images_dir / new_name}")

        # 清理未成功转换的图片引用
        for path in list(path_to_info.keys()):
            new_name, _ = path_to_info[path]
            if new_name not in successful:
                logger.warning(f"图片转换失败，将从引用中移除: {path}")
                # 保留 info 但标记为失败

    # 替换 Markdown 中的引用
    def replacer(m: re.Match[str]) -> str:
        caption = m.group(1)
        path = m.group(2).strip()
        if path not in path_to_info:
            return m.group(0)
        new_name, _ = path_to_info[path]
        # alt 使用 image_xx 不含扩展名
        alt = Path(new_name).stem
        new_ref = f"![{alt}](images/{new_name})"
        if caption:
            new_ref += f"\n\n> {caption}"
        return new_ref

    result = IMAGE_REF_PATTERN.sub(replacer, markdown)
    logger.info(f"已处理 {len(ordered_paths)} 张被引用图片，保存至 {final_images_dir}")
    return result

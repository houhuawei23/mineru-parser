"""可复用引擎：与 CLI/编排无关的纯业务能力。

包含 PDF 切分、JSON 解析、Markdown 生成、图片后处理、缓存、批量状态管理与工具函数。
这些模块可独立于 Typer/Rich/日志系统使用，便于单测与复用。
"""

from mineru_parser.engines.cache import get_cached_zip, save_to_cache
from mineru_parser.engines.json_parser import (
    content_list_json_to_markdown,
    content_list_v2_to_markdown,
)
from mineru_parser.engines.markdown import (
    build_markdown_from_zip,
    merge_markdown_parts,
    regenerate_markdown_from_json,
)

__all__ = [
    "get_cached_zip",
    "save_to_cache",
    "content_list_json_to_markdown",
    "content_list_v2_to_markdown",
    "build_markdown_from_zip",
    "merge_markdown_parts",
    "regenerate_markdown_from_json",
]

"""
MinerU PDF 解析器：将 PDF 解析为 Markdown，支持页眉、页脚、页码、脚注。

主要模块：
- api: MinerU API 调用（上传、轮询、下载）
- json_parser: 解析 content_list JSON
- markdown: 生成 Markdown 文本
- config: 配置加载
"""

__version__ = "1.1.0"

from mineru_parser.config import Config, ConfigError, load_config
from mineru_parser.api import parse_pdf_via_api, parse_pdf_via_api_with_auto_split
from mineru_parser.markdown import regenerate_markdown_from_json

__all__ = [
    "__version__",
    "load_config",
    "Config",
    "ConfigError",
    "parse_pdf_via_api",
    "parse_pdf_via_api_with_auto_split",
    "regenerate_markdown_from_json",
]

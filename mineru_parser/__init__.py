"""
MinerU PDF 解析器：将 PDF 解析为 Markdown，支持页眉、页脚、页码、脚注。

主要模块：
- api: MinerU API 调用（上传、轮询、下载）
- json_parser: 解析 content_list JSON
- markdown: 生成 Markdown 文本
- config: 配置加载
"""

__version__ = "2.0.0"

from mineru_parser.models.config import ConfigError, RootConfig as Config, load_config
from mineru_parser.models.params import ParseParams, RunContext
from mineru_parser.core.orchestrator import orchestrate_parse, parse_pdf_via_api
from mineru_parser.core.batch import run_batch
from mineru_parser.core.result import ParseResult
from mineru_parser.engines.markdown import regenerate_markdown_from_json

__all__ = [
    "__version__",
    "load_config",
    "Config",
    "ConfigError",
    "ParseParams",
    "RunContext",
    "ParseResult",
    "orchestrate_parse",
    "run_batch",
    "parse_pdf_via_api",
    "regenerate_markdown_from_json",
]

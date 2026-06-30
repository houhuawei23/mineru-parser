"""核心业务层：HTTP 传输、解析编排与批量并发。

本层使用 loguru 记录日志；不直接产生 Rich 终端 UI（由命令层负责）。
"""

from mineru_parser.core.batch import run_batch
from mineru_parser.core.http import close_session, get_session
from mineru_parser.core.orchestrator import orchestrate_parse, parse_pdf_via_api
from mineru_parser.core.result import ParseResult

__all__ = [
    "run_batch",
    "close_session",
    "get_session",
    "orchestrate_parse",
    "parse_pdf_via_api",
    "ParseResult",
]

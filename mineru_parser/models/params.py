"""命令层与编排层之间的数据传输对象（DTO）。

将 ``api.py`` 旧版 ~25 个位置参数收拢为 :class:`ParseParams`，
运行期共享状态（速率限制器、日志路径等）封装为 :class:`RunContext`。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from mineru_parser.models.config import RootConfig


@dataclass(frozen=True, slots=True)
class ParseParams:
    """单 PDF 解析的全部输入参数。

    ``base_url`` / ``model_version`` / ``poll_interval`` / ``max_wait`` /
    ``file_size_limit_mb`` / ``page_limit`` / ``max_workers`` 为空/None 时，
    由编排层从 ``config`` 取默认值（与旧行为一致）。
    """

    pdf_path: Path
    token: str
    output_dir: Path
    config: RootConfig

    base_url: str = ""
    model_version: str = ""
    poll_interval: int = 0
    max_wait: int = 0
    file_size_limit_mb: float | None = None
    page_limit: int | None = None
    max_workers: int | None = None
    target_chunk_pages: int = 0

    cache_enabled: bool = True
    cache_dir: Path | None = None
    use_cache: bool = True

    pages_spec: str | None = None
    output_md_name: str | None = None

    # Markdown 输出选项
    include_header: bool = False
    include_footer: bool = False
    include_page_number: bool = False
    include_footnote: bool = True
    merge_paragraphs: bool = True
    inline_footnotes: bool = False


@dataclass
class RunContext:
    """一次 CLI 运行的共享上下文。

    ``rate_limiter`` 是由命令层一次性构造的 API 并发信号量，在分片片段与
    批量文件之间共享，确保总在途 API 调用受 ``api_rate_limit`` 约束（取代旧的全局单例）。
    """

    config: RootConfig
    rate_limiter: threading.Semaphore
    log_path: Path
    run_started_at: datetime
    force: bool = False
    no_cache: bool = False
    no_merge_paragraphs: bool = False
    no_inline_footnotes: bool = False
    dry_run: bool = False
    quiet: bool = False
    extra: dict = field(default_factory=dict)

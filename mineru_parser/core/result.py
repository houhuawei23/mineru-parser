"""解析结果数据结构。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ParseResult:
    """单文件解析结果（命令层据此渲染与记录日志）。"""

    success: bool
    pdf_path: Path
    markdown: str | None = None
    md_path: Path | None = None
    elapsed: float = 0.0
    error: str | None = None

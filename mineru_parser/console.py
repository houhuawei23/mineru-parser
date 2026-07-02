"""Rich 终端 UI 层：统一命令层的人机输出。

仅在此模块（与 ``commands/``）使用 Rich。``core/`` 与 ``engines/`` 一律使用 loguru
记录日志；Rich 进度条由 :class:`RichProgressReporter` 承担，复用编排层的阶段事件词表，
故 ``core/orchestrator.py`` 无需为展示改动回调。
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.theme import Theme

_THEME = Theme(
    {
        "ok": "bold green",
        "fail": "bold red",
        "warn": "yellow",
        "muted": "dim",
        "accent": "cyan",
        "phase": "bold blue",
        "info": "green",
    }
)

# 主控制台：命令层渲染面板/表格/进度
console = Console(theme=_THEME, highlight=False)
# 静默控制台：-q 模式下不输出
quiet_console = Console(quiet=True)


# ==================== 渲染助手 ====================


def render_run_header(
    *,
    input_path: str,
    model: str,
    output_dir: Path,
    pages: str | None,
    target_chunk_pages: int,
    dry_run: bool,
    log_path: Path,
    cache_dir: Path | None = None,
) -> Panel:
    """运行参数面板：输入、模型、输出、页码、分片、缓存、dry-run、日志路径。"""
    lines = [
        f"[bold]输入[/]: [accent]{input_path}[/]",
        f"[bold]模型[/]: {model}",
        f"[bold]输出[/]: {output_dir}",
        f"[bold]页码[/]: {pages or '全部'}",
        f"[bold]自适应分片[/]: {target_chunk_pages or '仅超限切分'}",
        f"[bold]日志[/]: [muted]{log_path}[/]",
    ]
    if cache_dir is not None:
        lines.append(f"[bold]缓存[/]: [muted]{cache_dir}[/]")
    if dry_run:
        lines.append("[fail][DRY RUN] 模拟模式，不会实际调用 API[/]")
    return Panel(
        "\n".join(lines),
        title="[phase]mineru-parse[/]",
        border_style="phase",
        expand=False,
    )


def render_result_panel(
    *,
    success: bool,
    md_path: Path | None,
    md_len: int,
    elapsed: float,
    cache_dir: Path | None = None,
) -> Panel:
    """单次解析结果面板。"""
    if success:
        body = (
            f"[ok]✔ 解析成功[/]\n"
            f"Markdown: [accent]{md_path}[/]（{md_len} 字符）\n"
            f"耗时: {elapsed:.1f}s"
        )
        if cache_dir is not None:
            body += f"\n缓存: [muted]{cache_dir}[/]"
        return Panel(body, title="[ok]结果[/]", border_style="ok", expand=False)
    body = "[fail]✘ 解析失败[/]"
    return Panel(body, title="[fail]结果[/]", border_style="fail", expand=False)


def render_error(msg: str) -> Panel:
    """错误面板。"""
    return Panel(msg, title="[fail]错误[/]", border_style="fail", expand=False)


def render_dry_run_table(
    rows: list[tuple[str, int | str, float | str]],
    total_pages: int,
    total_size_mb: float,
    model: str,
    out_base: Path,
) -> Table:
    """dry-run 文件清单表。每行 ``(name, num_pages, size_mb)``。"""
    table = Table(title="[phase]DRY RUN 将要处理的文件[/]", expand=True)
    table.add_column("文件", style="accent", overflow="fold")
    table.add_column("页数", justify="right")
    table.add_column("大小(MB)", justify="right")
    for name, pages, size in rows:
        table.add_row(
            str(name),
            str(pages),
            f"{size:.1f}" if isinstance(size, float) else str(size),
        )
    table.add_row(
        "[bold]汇总[/]", f"[bold]{total_pages}[/]", f"[bold]{total_size_mb:.1f}[/]"
    )
    table.caption = (
        f"文件数 {len(rows)} | 模型 {model} | 输出目录 {out_base} | 未实际调用 API"
    )
    return table


def render_batch_summary(
    summary: dict[str, int], elapsed: float, cache_root: Path | None = None
) -> Table:
    """批次状态汇总表。"""
    table = Table(title="[phase]批次结果[/]", expand=False)
    table.add_column("状态", style="accent")
    table.add_column("数量", justify="right")
    for status in ("completed", "failed", "pending", "running"):
        table.add_row(status, str(summary.get(status, 0)))
    caption = f"耗时 {elapsed:.1f}s"
    if cache_root is not None:
        caption += f" | 缓存 {cache_root}"
    table.caption = caption
    return table


def render_resume_state(summary: dict[str, int]) -> Panel:
    """断点续传状态面板。"""
    lines = [
        f"已完成: [ok]{summary.get('completed', 0)}[/]",
        f"失败: [fail]{summary.get('failed', 0)}[/]",
        f"待处理: [accent]{summary.get('pending', 0)}[/]",
    ]
    return Panel(
        "\n".join(lines), title="[phase]断点续传[/]", border_style="phase", expand=False
    )


# ==================== 进度报告器 ====================


class RichProgressReporter:
    """基于 Rich.Progress 的进度报告器，取代旧的手写进度回调。

    单 PDF 解析使用一个主任务（spinner + 阶段文本 + 进度条 + 耗时）；
    切分片段在主任务上按 ``total_parts`` 推进。所有对 ``Progress`` 的写操作
    在 ``self._lock`` 内进行，确保多线程分片并发下渲染安全。
    """

    def __init__(
        self,
        desc: str = "解析",
        quiet: bool = False,
        out_console: Console | None = None,
    ) -> None:
        self.desc = desc
        self.quiet = quiet
        self._out_console = out_console or console
        self._lock = threading.Lock()
        self._progress: Progress | None = None
        self._task_id: Any = None
        self._part_total: int = 0
        self._part_done: int = 0

    def _ensure(self) -> None:
        if self._progress is None:
            self._progress = Progress(
                SpinnerColumn(),
                TextColumn("[phase]{task.description}[/]"),
                BarColumn(bar_width=None),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                console=self._out_console,
                transient=False,
            )
            self._progress.start()
            self._task_id = self._progress.add_task(self.desc, total=None)

    def update(self, phase: str, info: dict[str, Any] | None = None) -> None:
        """接收阶段事件并更新终端展示。"""
        if self.quiet:
            return
        info = info or {}
        with self._lock:
            self._ensure()
            p = self._progress
            assert p is not None and self._task_id is not None

            if phase == "start":
                pdf = info.get("pdf_path", "")
                name = Path(pdf).name if pdf else "输入"
                num = info.get("num_pages") or "?"
                mb = info.get("size_mb", 0.0)
                p.update(
                    self._task_id,
                    description=f"解析 {name} ({num} 页, {mb:.1f} MB)",
                )
            elif phase == "cache_hit":
                p.console.print("命中缓存，跳过 API 调用", style="accent")
            elif phase == "upload":
                bid = info.get("batch_id")
                p.update(
                    self._task_id,
                    description=f"申请上传链接… batch_id={bid}"
                    if bid
                    else "申请上传链接…",
                )
            elif phase == "upload_done":
                p.update(self._task_id, description="上传成功，等待解析…")
            elif phase == "poll":
                state = info.get("state", "")
                extracted = info.get("extracted_pages")
                total = info.get("total_pages")
                if extracted is not None and total is not None:
                    p.update(
                        self._task_id,
                        description=f"解析中… {state}".strip(),
                        completed=min(extracted, total),
                        total=total,
                    )
                else:
                    p.update(self._task_id, description=f"解析中… {state}".strip())
            elif phase == "download":
                p.update(self._task_id, description="下载解析结果…")
            elif phase == "build":
                p.update(self._task_id, description="生成 Markdown…")
            elif phase == "split_start":
                p.update(self._task_id, description="PDF 较大，切分中…")
            elif phase in ("split", "split_done"):
                total = info.get("total_parts", 0)
                self._part_total = total
                self._part_done = 0
                p.update(
                    self._task_id,
                    description=f"解析 {total} 个片段…",
                    total=total or None,
                    completed=0,
                )
                if total:
                    p.console.print(f"PDF 需要切分，共 {total} 个片段", style="phase")
            elif phase == "part_start":
                idx = info.get("idx", 0)
                tot = info.get("total", 0)
                p.console.print(f"解析片段 {idx + 1}/{tot}…", style="muted")
            elif phase == "part_complete":
                idx = info.get("idx", 0)
                tot = info.get("total", 0)
                self._part_done += 1
                p.update(self._task_id, completed=self._part_done)
                p.console.print(f"片段 {idx + 1}/{tot} 解析完成", style="muted")
            elif phase == "merge":
                p.update(self._task_id, description="合并解析结果…")
            elif phase == "complete":
                self._close_locked()
                elapsed = info.get("elapsed", 0.0)
                md_len = info.get("markdown_length", 0)
                self._out_console.print(
                    f"解析完成，耗时 {elapsed:.1f}s，Markdown 长度 {md_len} 字符",
                    style="ok",
                )
            elif phase == "error":
                self._close_locked()
                self._out_console.print(
                    render_error(str(info.get("error", "未知错误")))
                )

    def _close_locked(self) -> None:
        if self._progress is not None:
            self._progress.stop()
            self._progress = None
            self._task_id = None

    def close(self) -> None:
        """关闭进度条。"""
        with self._lock:
            self._close_locked()


def make_progress_callback(
    reporter: RichProgressReporter,
) -> Callable[[str, dict[str, Any] | None], None]:
    """生成兼容 API 进度回调的闭包。"""
    return lambda phase, info=None: reporter.update(phase, info or {})

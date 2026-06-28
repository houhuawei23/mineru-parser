"""进度报告模块：为 CLI 提供可交互的解析进度展示。"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

import typer
from tqdm import tqdm


class ProgressReporter:
    """
    基于 tqdm 与 typer.echo 的进度报告器。

    支持阶段文本输出、轮询进度条（已知总页数时）或动态计数（未知时），
    并自动累计耗时。
    """

    def __init__(self, desc: str = "解析", quiet: bool = False) -> None:
        self.desc = desc
        self.quiet = quiet
        self.start_time = time.time()
        self.pbar: tqdm | None = None
        self._last_poll_state: str | None = None

    def elapsed(self) -> float:
        """返回已运行秒数。"""
        return time.time() - self.start_time

    def _ensure_pbar(self, total: int | None = None) -> tqdm | None:
        if self.quiet:
            return None
        if self.pbar is None:
            self.pbar = tqdm(
                total=total,
                desc=self.desc,
                unit="step",
                leave=False,
                bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}{postfix}]",
            )
        elif total is not None and (
            self.pbar.total is None or self.pbar.total != total
        ):
            self.pbar.total = total
        return self.pbar

    def update(self, phase: str, info: dict[str, Any] | None = None) -> None:
        """接收阶段事件并更新终端展示。"""
        if self.quiet:
            return
        info = info or {}

        if phase == "start":
            pdf = info.get("pdf_path", "")
            name = Path(pdf).name if pdf else "输入"
            num_pages = info.get("num_pages") or "?"
            size_mb = info.get("size_mb", 0.0)
            typer.echo(f"开始解析: {name} ({num_pages} 页, {size_mb:.1f} MB)")

        elif phase == "cache_hit":
            typer.echo("命中缓存，跳过 API 调用")

        elif phase == "upload":
            batch_id = info.get("batch_id")
            if batch_id:
                typer.echo(f"已申请上传链接，batch_id: {batch_id}")
            else:
                typer.echo("正在申请上传链接...")

        elif phase == "upload_done":
            typer.echo("上传成功，等待解析...")

        elif phase == "poll":
            state = info.get("state", "")
            extracted = info.get("extracted_pages")
            total = info.get("total_pages")
            pbar = self._ensure_pbar(total)
            if pbar is None:
                return
            if extracted is not None and total is not None:
                pbar.n = min(extracted, total)
                pbar.set_postfix_str(f"状态: {state}")
                pbar.update(0)
            else:
                pbar.set_postfix_str(f"状态: {state}")
                pbar.update(1)
            self._last_poll_state = state

        elif phase == "download":
            typer.echo("正在下载解析结果...")

        elif phase == "build":
            typer.echo("正在生成 Markdown...")

        elif phase == "split":
            total = info.get("total_parts", 0)
            typer.echo(f"PDF 需要切分，共 {total} 个片段")

        elif phase == "part_start":
            idx = info.get("idx", 0) + 1
            total = info.get("total", 0)
            typer.echo(f"解析片段 {idx}/{total}...")

        elif phase == "part_complete":
            idx = info.get("idx", 0) + 1
            total = info.get("total", 0)
            typer.echo(f"片段 {idx}/{total} 解析完成")

        elif phase == "merge":
            typer.echo("合并解析结果...")

        elif phase == "complete":
            self.close()
            elapsed = info.get("elapsed", self.elapsed())
            md_len = info.get("markdown_length", 0)
            typer.echo(f"解析完成，耗时: {elapsed:.1f}s，Markdown 长度: {md_len} 字符")

        elif phase == "error":
            self.close()
            err = info.get("error", "未知错误")
            typer.echo(f"解析失败: {err}")

    def close(self) -> None:
        """关闭进度条。"""
        if self.pbar is not None:
            self.pbar.close()
            self.pbar = None


def make_progress_callback(
    reporter: ProgressReporter,
) -> Callable[[str, dict[str, Any] | None], None]:
    """生成兼容 API 进度回调的闭包。"""
    return lambda phase, info=None: reporter.update(phase, info or {})

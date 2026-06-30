"""``batch`` 子命令：批量解析 PDF，支持递归、dry-run、断点续传与并发。"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import typer
from loguru import logger
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from mineru_parser.commands._shared import (
    build_md_options,
    resolve_subcommand_config,
    validate_token,
)
from mineru_parser.console import (
    console,
    render_batch_summary,
    render_dry_run_table,
    render_resume_state,
)
from mineru_parser.core.batch import run_batch
from mineru_parser.core.result import ParseResult
from mineru_parser.engines.pdf_splitter import get_pdf_info
from mineru_parser.engines.state import BatchStateManager, JobStatus, get_state_file
from mineru_parser.engines.utils import collect_pdf_paths
from mineru_parser.logging_setup import log_run_result
from mineru_parser.models.params import ParseParams, RunContext


def _collect_dry_run_info(
    paths: list[Path],
) -> tuple[list[tuple[str, int | str, float | str]], int, float]:
    """收集每个文件的名/页数/大小，汇总总页数与总大小（MB）。"""
    rows: list[tuple[str, int | str, float | str]] = []
    total_pages = 0
    total_size = 0
    for pdf_path in paths:
        try:
            num_pages, size_bytes = get_pdf_info(pdf_path)
            total_pages += num_pages
            total_size += size_bytes
            rows.append((str(pdf_path), num_pages, size_bytes / 1024 / 1024))
        except Exception as e:  # noqa: BLE001 — 单文件信息获取失败不应中断预览
            rows.append((str(pdf_path), f"无法获取: {e}", "-"))
    return rows, total_pages, total_size / 1024 / 1024


def batch_cmd(
    ctx: typer.Context,
    input_path: Path = typer.Option(
        ..., "-i", "--input", path_type=Path, help="输入 PDF 文件或目录"
    ),
    output_dir: Path | None = typer.Option(
        None, "-o", "--output", path_type=Path, help="输出目录（默认与输入同目录）"
    ),
    recursive: bool = typer.Option(False, "-r", "--recursive", help="递归处理子目录"),
    include: str = typer.Option(
        None, "-I", "--include", help="包含的文件模式（默认 *.pdf）"
    ),
    exclude: str = typer.Option(None, "-E", "--exclude", help="排除的文件模式（正则）"),
    token: str | None = typer.Option(None, "-t", "--token", help="MinerU API Token"),
    model: str | None = typer.Option(
        None, "-m", "--model", help="解析模型：vlm 或 pipeline"
    ),
    config_path: Path | None = typer.Option(
        None, "-c", "--config", path_type=Path, help="覆盖配置（YAML）"
    ),
    resume: bool = typer.Option(
        False, "--resume", help="断点续传：跳过已完成，继续中断的批次"
    ),
    reset_failed: bool = typer.Option(
        False, "--reset-failed", help="重置失败任务并重试"
    ),
    concurrency: int = typer.Option(
        None, "--concurrency", help="并发处理文件数（1=顺序，默认从配置读取）"
    ),
    target_chunk_pages: int = typer.Option(
        None, "--target-chunk-pages", help="自适应分片目标页数"
    ),
) -> None:
    """批量解析 PDF。"""
    rc: RunContext = ctx.obj
    resolve_subcommand_config(rc, config_path)
    cfg = rc.config
    validate_token(token or cfg.token)

    include_pattern = include if include is not None else cfg.batch_include_pattern
    exclude_pattern = exclude if exclude is not None else cfg.batch_exclude_pattern
    if input_path.is_file():
        paths = [input_path] if input_path.suffix.lower() == ".pdf" else []
    else:
        paths = collect_pdf_paths(
            input_path,
            recursive=recursive,
            include=include_pattern,
            exclude=exclude_pattern,
        )

    if not paths:
        console.print("[muted]未找到 PDF 文件[/]")
        log_run_result(False, elapsed=0.0, files_done=0, files_failed=0)
        raise typer.Exit(0)

    out_base = output_dir or (input_path if input_path.is_dir() else input_path.parent)
    md_opts = build_md_options(rc, cfg)
    model_version = model or cfg.model_version
    chunk_pages = (
        target_chunk_pages if target_chunk_pages is not None else cfg.target_chunk_pages
    )

    # Dry-run 预览
    if rc.dry_run:
        rows, total_pages, total_size_mb = _collect_dry_run_info(paths)
        console.print(
            render_dry_run_table(
                rows, total_pages, total_size_mb, model_version, out_base
            )
        )
        raise typer.Exit(0)

    state_file = get_state_file(input_path, out_base)
    batch_conc = concurrency if concurrency is not None else cfg.batch_concurrency
    tok = token or cfg.token
    start = time.perf_counter()

    with BatchStateManager(state_file) as state:
        if reset_failed:
            n = state.reset_failed()
            console.print(f"[accent]已重置 {n} 个失败任务[/]")

        if resume:
            summary = state.get_summary()
            if summary.get(JobStatus.COMPLETED.value, 0) or summary.get(
                JobStatus.FAILED.value, 0
            ):
                console.print(render_resume_state(summary))

        for pdf_path in paths:
            state.create_job(str(pdf_path))

        # 原子认领任务（resume 感知），构造 ParseParams
        claimed: list[tuple[Path, ParseParams]] = []
        for pdf_path in paths:
            if not state.try_start_job(str(pdf_path), resume=resume):
                continue
            out_dir = out_base / f"{pdf_path.stem}{cfg.output_parsed_suffix}"
            out_dir.mkdir(parents=True, exist_ok=True)
            params = ParseParams(
                pdf_path=pdf_path,
                token=tok,
                output_dir=out_dir,
                config=cfg,
                base_url=cfg.base_url,
                model_version=model_version,
                poll_interval=cfg.poll_interval,
                max_wait=cfg.max_wait,
                cache_enabled=cfg.cache_enabled,
                cache_dir=cfg.cache_dir,
                use_cache=not rc.no_cache,
                target_chunk_pages=chunk_pages,
                **md_opts,
            )
            claimed.append((pdf_path, params))

        if not claimed:
            console.print("[muted]没有需要处理的文件[/]")
            raise typer.Exit(0)

        console.print(
            f"[phase]批量处理[/] {len(claimed)} 个文件 | 并发 {batch_conc} | API 限制 {cfg.api_rate_limit}"
        )

        # 批次级文件计数进度（quiet 时跳过）
        progress: Progress | None = None
        task_id = None
        lock = threading.Lock()
        if not rc.quiet:
            progress = Progress(
                SpinnerColumn(),
                TextColumn("[phase]{task.description}[/]"),
                BarColumn(bar_width=None),
                TimeElapsedColumn(),
                console=console,
                transient=False,
            )
            progress.start()
            task_id = progress.add_task("解析 PDF", total=len(claimed))

        def on_complete(idx: int, result: ParseResult) -> None:
            if progress is None or task_id is None:
                return
            with lock:
                name = result.pdf_path.name[:30]
                tag = "OK" if result.success else "FAIL"
                progress.advance(task_id)
                progress.update(task_id, description=f"解析 PDF（{tag}: {name}）")

        try:
            results = run_batch(
                [params for _, params in claimed],
                rc,
                batch_concurrency=batch_conc,
                on_complete=on_complete,
            )
        finally:
            if progress is not None:
                progress.stop()

        failed = 0
        for (pdf_path, _), result in zip(claimed, results, strict=True):
            if result.success:
                state.update_job(str(pdf_path), JobStatus.COMPLETED)
            else:
                state.update_job(
                    str(pdf_path), JobStatus.FAILED, result.error or "解析返回空结果"
                )
                failed += 1

        final_summary = state.get_summary()

    elapsed = time.perf_counter() - start
    console.print(render_batch_summary(final_summary, elapsed))
    log_run_result(
        success=failed == 0,
        elapsed=elapsed,
        files_done=len(claimed) - failed,
        files_failed=failed,
    )
    if failed:
        logger.warning(f"失败 {failed}/{len(claimed)} 个文件")
        raise typer.Exit(1)

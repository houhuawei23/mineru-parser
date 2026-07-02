"""``parse`` 子命令：解析单个 PDF 或 URL。"""

from __future__ import annotations

import time
from pathlib import Path

import typer
from loguru import logger

from mineru_parser.commands._shared import (
    build_md_options,
    resolve_subcommand_config,
    validate_token,
)
from mineru_parser.console import (
    console,
    make_progress_callback,
    render_error,
    render_result_panel,
    render_run_header,
    RichProgressReporter,
)
from mineru_parser.core.orchestrator import orchestrate_parse
from mineru_parser.engines.cache import cache_group_dir, compute_source_hash
from mineru_parser.engines.utils import resolve_input_to_pdf
from mineru_parser.logging_setup import log_run_result
from mineru_parser.models.params import ParseParams, RunContext


def parse_cmd(
    ctx: typer.Context,
    input_path: Path = typer.Argument(
        ..., path_type=Path, help="PDF 文件路径或 arXiv 链接"
    ),
    output: Path | None = typer.Option(
        None,
        "-o",
        "--output",
        path_type=Path,
        help="输出目录或 Markdown 路径（默认：{stem}/full.md）",
    ),
    token: str | None = typer.Option(
        None, "-t", "--token", help="MinerU API Token（覆盖配置文件）"
    ),
    model: str | None = typer.Option(
        None,
        "-m",
        "--model",
        help="解析模型：vlm（默认，可能切分大图）或 pipeline（不切分大图）",
    ),
    header: bool = typer.Option(False, "--header", help="添加页眉"),
    footer: bool = typer.Option(False, "--footer", help="添加页脚"),
    page_number: bool = typer.Option(False, "--page-number", help="添加页码"),
    no_footnote: bool = typer.Option(False, "--no-footnote", help="关闭脚注"),
    pages: str | None = typer.Option(
        None,
        "--pages",
        help="仅解析指定页码（从 1 计数），多个区间用逗号分隔，例如 10-20,30-40；超出总页数会自动裁剪并告警",
    ),
    target_chunk_pages: int = typer.Option(
        None,
        "--target-chunk-pages",
        help="自适应分片目标页数（0=仅超限切分，默认从配置读取；>0=始终切分到此大小以并发加速）",
    ),
    config_path: Path | None = typer.Option(
        None,
        "-c",
        "--config",
        path_type=Path,
        help="覆盖配置（YAML）；优先级高于主命令 -c",
    ),
    force: bool = typer.Option(False, "-f", "--force", help="强制覆盖已存在的输出目录"),
) -> None:
    """解析单个 PDF 或 URL。"""
    rc: RunContext = ctx.obj
    resolve_subcommand_config(rc, config_path)
    cfg = rc.config
    validate_token(token or cfg.token)

    # 判断 URL 还是本地文件，并推导输出目录与 md 文件名
    s = str(input_path)
    if s.startswith(("http://", "https://")):
        out_dir = output or Path.cwd()
        result = resolve_input_to_pdf(s, out_dir)
        if not result[0]:
            console.print(render_error(f"下载失败: {s}"))
            log_run_result(False, None, 0.0)
            raise typer.Exit(1)
        pdf_path, stem = result
        if output:
            output_dir = out_dir / f"{stem}{cfg.output_parsed_suffix}"
            md_name = f"{stem}.md"
        else:
            output_dir = out_dir / stem
            md_name = "full.md"
    else:
        p = Path(input_path)
        if not p.exists():
            console.print(render_error(f"文件不存在: {p}"))
            log_run_result(False, None, 0.0)
            raise typer.Exit(1)
        if p.suffix.lower() != ".pdf":
            console.print(render_error("输入不是 PDF 文件"))
            log_run_result(False, None, 0.0)
            raise typer.Exit(1)
        pdf_path = p
        if output:
            if output.suffix == ".md":
                output_dir = output.parent / f"{p.stem}{cfg.output_parsed_suffix}"
            else:
                output_dir = output
            md_name = f"{p.stem}.md"
        else:
            output_dir = p.parent / p.stem
            md_name = "full.md"

    if output_dir.exists() and not (force or rc.force):
        logger.warning(f"输出目录已存在: {output_dir}，使用 -f 强制覆盖")
    output_dir.mkdir(parents=True, exist_ok=True)

    md_opts = build_md_options(
        rc,
        cfg,
        header=header,
        footer=footer,
        page_number=page_number,
        no_footnote=no_footnote,
    )
    model_version = model or cfg.model_version
    chunk_pages = (
        target_chunk_pages if target_chunk_pages is not None else cfg.target_chunk_pages
    )

    # 计算该 PDF 的缓存组目录路径（用于在运行头/结果面板展示，便于用户进入查看）。
    # 仅在启用缓存时计算；compute_source_hash 按 mtime/size 复用，开销可忽略。
    cache_group: Path | None = None
    if cfg.cache_enabled and not rc.no_cache:
        try:
            source_hash = compute_source_hash(pdf_path, cfg)
            cache_group = cache_group_dir(
                cfg.cache_dir, model_version, pdf_path, source_hash
            )
        except FileNotFoundError:
            cache_group = None

    params = ParseParams(
        pdf_path=pdf_path,
        token=token or cfg.token,
        output_dir=output_dir,
        config=cfg,
        base_url=cfg.base_url,
        model_version=model_version,
        poll_interval=cfg.poll_interval,
        max_wait=cfg.max_wait,
        cache_enabled=cfg.cache_enabled,
        cache_dir=cfg.cache_dir,
        use_cache=not rc.no_cache,
        pages_spec=pages,
        target_chunk_pages=chunk_pages,
        output_md_name=md_name,
        **md_opts,
    )

    console.print(
        render_run_header(
            input_path=str(input_path),
            model=model_version,
            output_dir=output_dir,
            pages=pages,
            target_chunk_pages=chunk_pages,
            dry_run=rc.dry_run,
            log_path=rc.log_path,
            cache_dir=cache_group,
        )
    )

    reporter = RichProgressReporter(desc=f"解析 {pdf_path.name}", quiet=rc.quiet)
    progress_callback = make_progress_callback(reporter)
    start = time.perf_counter()
    try:
        markdown = orchestrate_parse(params, rc, progress_callback=progress_callback)
    finally:
        reporter.close()

    elapsed = time.perf_counter() - start
    md_path = output_dir / md_name
    if markdown:
        console.print(
            render_result_panel(
                success=True,
                md_path=md_path,
                md_len=len(markdown),
                elapsed=elapsed,
                cache_dir=cache_group,
            )
        )
        log_run_result(True, md_path, elapsed)
    else:
        console.print(
            render_result_panel(success=False, md_path=None, md_len=0, elapsed=elapsed)
        )
        log_run_result(False, None, elapsed)
        raise typer.Exit(1)

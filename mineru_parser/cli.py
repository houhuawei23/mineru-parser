#!/usr/bin/env python3
"""
MinerU PDF 解析器 CLI 入口。
使用 Typer 提供命令行交互，支持批量处理、进度显示。
"""

import sys
from pathlib import Path

import typer
from loguru import logger
from tqdm import tqdm

from mineru_parser import __version__
from mineru_parser.api import parse_pdf_via_api_with_auto_split, parse_pdfs_concurrent, reset_api_semaphore
from mineru_parser.config import ConfigError, load_config
from mineru_parser.markdown import regenerate_markdown_from_json
from mineru_parser.pdf_splitter import get_pdf_info
from mineru_parser.state import BatchStateManager, JobStatus, get_state_file
from mineru_parser.utils import collect_pdf_paths, resolve_input_to_pdf

app = typer.Typer(
    name="mineru-parse",
    help="使用 MinerU API 解析 PDF 为 Markdown，支持页眉、页脚、页码、脚注",
    add_completion=False,
)


def setup_logging(quiet: bool = False, debug: bool = False) -> None:
    """配置 loguru 日志级别。"""
    logger.remove()
    if quiet:
        logger.add(sys.stderr, level="WARNING")
    elif debug:
        logger.add(sys.stderr, level="DEBUG")
    else:
        logger.add(sys.stderr, level="INFO")


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"mineru-parse {__version__}")
        raise typer.Exit()


@app.callback()
def main_callback(
    ctx: typer.Context,
    version: bool = typer.Option(
        False, "-v", "--version", callback=version_callback, is_eager=True,
        help="显示版本信息",
    ),
    config_path: Path | None = typer.Option(
        None, "-c", "--config", path_type=Path,
        help="用户配置文件（YAML）；也可写在子命令后，如 parse file -c config.yml。"
        " 优先级：本参数/子命令 -c > 环境变量 > 当前目录 config.yml > 包内 default",
    ),
    force: bool = typer.Option(
        False, "-f", "--force",
        help="强制覆盖已存在的输出文件",
    ),
    no_cache: bool = typer.Option(
        False, "--no-cache",
        help="禁用缓存，强制重新调用 API 解析",
    ),
    no_merge_paragraphs: bool = typer.Option(
        False, "--no-merge-paragraphs",
        help="禁用跨页段落合并",
    ),
    no_inline_footnotes: bool = typer.Option(
        False, "--no-inline-footnotes",
        help="脚注放在页末而非段落后",
    ),
    quiet: bool = typer.Option(
        False, "-q", "--quiet",
        help="静默模式，减少输出",
    ),
    debug: bool = typer.Option(
        False, "-d", "--debug",
        help="调试模式，输出详细日志",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="模拟运行，不实际调用 API，仅显示将要处理的内容",
    ),
) -> None:
    """MinerU PDF 解析器。"""
    setup_logging(quiet=quiet, debug=debug)
    try:
        cfg = load_config(config_path)
    except ConfigError as e:
        logger.error(str(e))
        raise typer.Exit(1) from e
    ctx.obj = {
        "config": cfg,
        "force": force,
        "no_cache": no_cache,
        "no_merge_paragraphs": no_merge_paragraphs,
        "no_inline_footnotes": no_inline_footnotes,
        "dry_run": dry_run,
    }
    if dry_run:
        typer.echo("[DRY RUN] 模拟模式 - 不会实际调用 API")


def _apply_subcommand_config(ctx: typer.Context, config_path: Path | None) -> None:
    """子命令上的 ``-c`` 重新加载配置（见 load_config 合并顺序）。"""
    if config_path is None:
        return
    try:
        ctx.obj["config"] = load_config(config_path)
    except ConfigError as e:
        logger.error(str(e))
        raise typer.Exit(1) from e


def _get_md_options(ctx: typer.Context) -> dict:
    cfg = ctx.obj["config"]
    return {
        "include_header": cfg.markdown.include_header,
        "include_footer": cfg.markdown.include_footer,
        "include_page_number": cfg.markdown.include_page_number,
        "include_footnote": cfg.markdown.include_footnote,
        "merge_paragraphs": cfg.markdown.merge_paragraphs and not ctx.obj.get("no_merge_paragraphs", False),
        "inline_footnotes": cfg.markdown.inline_footnotes and not ctx.obj.get("no_inline_footnotes", False),
    }


@app.command("parse")
def parse_cmd(
    ctx: typer.Context,
    input_path: Path = typer.Argument(
        ...,
        path_type=Path,
        help="PDF 文件路径或 arXiv 链接",
    ),
    output: Path | None = typer.Option(
        None, "-o", "--output", path_type=Path,
        help="输出目录或 Markdown 路径",
    ),
    token: str | None = typer.Option(
        None, "-t", "--token",
        help="MinerU API Token（覆盖配置文件）",
    ),
    model: str | None = typer.Option(
        None, "-m", "--model",
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
        help="覆盖配置（YAML）；优先级高于主命令 -c、环境变量与当前目录 config.yml",
    ),
    force: bool = typer.Option(
        False,
        "-f",
        "--force",
        help="强制覆盖已存在的输出目录",
    ),
) -> None:
    """解析单个 PDF 或 URL。"""
    _apply_subcommand_config(ctx, config_path)
    cfg = ctx.obj["config"]
    tok = token or cfg.token
    if not tok:
        logger.error(
            "未配置 API Token。请通过以下方式之一设置：\n"
            "  1) 在当前目录 config.yml、default_config.yml 或 -c 指定的配置中设置 api.token\n"
            "  2) 设置环境变量 MINERU_TOKEN\n"
            "  3) 使用 -t/--token 传入"
        )
        raise typer.Exit(1)

    # 判断是 URL 还是本地文件
    s = str(input_path)
    if s.startswith("http://") or s.startswith("https://"):
        out_dir = output or Path.cwd()
        result = resolve_input_to_pdf(s, out_dir)
        if not result[0]:
            raise typer.Exit(1)
        pdf_path, stem = result
        output_dir = out_dir / f"{stem}{cfg.output_parsed_suffix}"
    else:
        p = Path(input_path)
        if not p.exists():
            logger.error(f"文件不存在: {p}")
            raise typer.Exit(1)
        if p.suffix.lower() != ".pdf":
            logger.error("输入不是 PDF 文件")
            raise typer.Exit(1)
        pdf_path = p
        output_dir = output or (p.parent / f"{p.stem}{cfg.output_parsed_suffix}")
        if output and output.suffix == ".md":
            output_dir = output.parent / f"{p.stem}{cfg.output_parsed_suffix}"

    force_overwrite = force or ctx.obj.get("force", False)
    if output_dir.exists() and not force_overwrite:
        logger.warning(f"输出目录已存在: {output_dir}，使用 -f 强制覆盖")

    base_md = _get_md_options(ctx)
    md_opts = {
        **base_md,
        "include_header": header or cfg.markdown.include_header,
        "include_footer": footer or cfg.markdown.include_footer,
        "include_page_number": page_number or cfg.markdown.include_page_number,
        "include_footnote": not no_footnote and cfg.markdown.include_footnote,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    model_version = model or cfg.model_version
    chunk_pages = target_chunk_pages if target_chunk_pages is not None else cfg.target_chunk_pages
    markdown = parse_pdf_via_api_with_auto_split(
        pdf_path,
        tok,
        output_dir,
        cfg,
        base_url=cfg.base_url,
        model_version=model_version,
        poll_interval=cfg.poll_interval,
        max_wait=cfg.max_wait,
        cache_enabled=cfg.cache_enabled,
        cache_dir=cfg.cache_dir,
        use_cache=not ctx.obj["no_cache"],
        pages_spec=pages,
        target_chunk_pages=chunk_pages,
        api_rate_limit=cfg.api_rate_limit,
        **md_opts,
    )
    if markdown:
        md_path = output_dir / f"{pdf_path.stem}.md"
        typer.echo(f"解析成功，Markdown 长度: {len(markdown)} 字符，已保存: {md_path}")
    else:
        raise typer.Exit(1)


@app.command("from-json")
def from_json_cmd(
    ctx: typer.Context,
    input_dir: Path = typer.Argument(
        ...,
        path_type=Path,
        help="已解析目录（含 *_content_list.json）",
    ),
    output: Path | None = typer.Option(
        None, "-o", "--output", path_type=Path,
        help="输出 Markdown 路径",
    ),
    header: bool = typer.Option(False, "--header", help="添加页眉"),
    footer: bool = typer.Option(False, "--footer", help="添加页脚"),
    page_number: bool = typer.Option(False, "--page-number", help="添加页码"),
    no_footnote: bool = typer.Option(False, "--no-footnote", help="关闭脚注"),
    config_path: Path | None = typer.Option(
        None,
        "-c",
        "--config",
        path_type=Path,
        help="覆盖配置（YAML）；优先级见主命令 --help",
    ),
) -> None:
    """从已解压目录的 JSON 重新生成 Markdown。"""
    _apply_subcommand_config(ctx, config_path)
    if not input_dir.is_dir():
        logger.error(f"目录不存在: {input_dir}")
        raise typer.Exit(1)

    cfg = ctx.obj["config"]
    base_md = _get_md_options(ctx)
    md_opts = {
        **base_md,
        "include_header": header or cfg.markdown.include_header,
        "include_footer": footer or cfg.markdown.include_footer,
        "include_page_number": page_number or cfg.markdown.include_page_number,
        "include_footnote": not no_footnote and cfg.markdown.include_footnote,
    }

    output_md = output if output and str(output).endswith(".md") else None
    result = regenerate_markdown_from_json(
        input_dir,
        output_md=output_md,
        **md_opts,
    )
    if result:
        typer.echo("重新生成成功")
    else:
        raise typer.Exit(1)


@app.command("batch")
def batch_cmd(
    ctx: typer.Context,
    input_path: Path = typer.Option(
        ..., "-i", "--input", path_type=Path,
        help="输入 PDF 文件或目录",
    ),
    output_dir: Path | None = typer.Option(
        None, "-o", "--output", path_type=Path,
        help="输出目录（默认与输入同目录）",
    ),
    recursive: bool = typer.Option(
        False, "-r", "--recursive",
        help="递归处理子目录",
    ),
    include: str = typer.Option(
        None, "-I", "--include",
        help="包含的文件模式（默认从 default_config.yml 读取）",
    ),
    exclude: str = typer.Option(
        None, "-E", "--exclude",
        help="排除的文件模式（正则，默认从 default_config.yml 读取）",
    ),
    token: str | None = typer.Option(
        None, "-t", "--token",
        help="MinerU API Token",
    ),
    model: str | None = typer.Option(
        None, "-m", "--model",
        help="解析模型：vlm 或 pipeline（不切分大图）",
    ),
    config_path: Path | None = typer.Option(
        None,
        "-c",
        "--config",
        path_type=Path,
        help="覆盖配置（YAML）；优先级见主命令 --help",
    ),
    resume: bool = typer.Option(
        False,
        "--resume",
        help="断点续传模式：跳过已完成的文件，继续处理上次中断的批次",
    ),
    reset_failed: bool = typer.Option(
        False,
        "--reset-failed",
        help="重置失败任务状态，重新尝试处理失败的文件",
    ),
    concurrency: int = typer.Option(
        None,
        "--concurrency",
        help="并发处理文件数（默认从配置读取，1 为顺序处理）",
    ),
    target_chunk_pages: int = typer.Option(
        None,
        "--target-chunk-pages",
        help="自适应分片目标页数（0=仅超限切分，默认从配置读取；>0=始终切分到此大小以并发加速）",
    ),
) -> None:
    """批量解析 PDF。"""
    _apply_subcommand_config(ctx, config_path)
    cfg = ctx.obj["config"]
    tok = token or cfg.token
    if not tok:
        logger.error(
            "未配置 API Token。请通过 default_config.yml、-c 配置、环境变量 MINERU_TOKEN 或 -t/--token 设置"
        )
        raise typer.Exit(1)

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
        logger.warning("未找到 PDF 文件")
        raise typer.Exit(0)

    out_base = output_dir or (input_path if input_path.is_dir() else input_path.parent)
    md_opts = _get_md_options(ctx)
    model_version = model or cfg.model_version

    # Dry run mode
    if ctx.obj.get("dry_run", False):
        typer.echo(f"\n[DRY RUN] 将要处理的文件 ({len(paths)} 个):")
        total_pages = 0
        total_size = 0
        for pdf_path in paths:
            try:
                num_pages, size_bytes = get_pdf_info(pdf_path)
                total_pages += num_pages
                total_size += size_bytes
                size_mb = size_bytes / 1024 / 1024
                typer.echo(f"  - {pdf_path} ({num_pages} 页, {size_mb:.1f} MB)")
            except Exception as e:
                typer.echo(f"  - {pdf_path} (无法获取信息: {e})")
        typer.echo("\n汇总:")
        typer.echo(f"  文件数: {len(paths)}")
        typer.echo(f"  总页数: {total_pages}")
        typer.echo(f"  总大小: {total_size / 1024 / 1024:.1f} MB")
        typer.echo(f"  模型: {model_version}")
        typer.echo(f"  输出目录: {out_base}")
        typer.echo("\n[DRY RUN] 未实际调用 API，以上仅为预览")
        raise typer.Exit(0)

    # Initialize state manager for resume capability
    state_file = get_state_file(input_path, out_base)
    batch_conc = concurrency if concurrency is not None else cfg.batch_concurrency
    chunk_pages = target_chunk_pages if target_chunk_pages is not None else cfg.target_chunk_pages

    with BatchStateManager(state_file) as state:
        if reset_failed:
            reset_count = state.reset_failed()
            logger.info(f"已重置 {reset_count} 个失败任务")

        if resume:
            summary = state.get_summary()
            completed = summary.get(JobStatus.COMPLETED.value, 0)
            failed = summary.get(JobStatus.FAILED.value, 0)
            if completed > 0 or failed > 0:
                logger.info(f"断点续传模式: 已完成 {completed} 个, 失败 {failed} 个, 待处理 {summary.get(JobStatus.PENDING.value, 0)} 个")

        # Create/update job records
        for pdf_path in paths:
            state.create_job(str(pdf_path))

        # Filter paths based on resume mode
        if resume:
            original_count = len(paths)
            paths = [p for p in paths if state.should_process(str(p), resume=True)]
            skipped = original_count - len(paths)
            if skipped > 0:
                logger.info(f"跳过 {skipped} 个已处理/处理中的文件")

        if not paths:
            logger.info("没有需要处理的文件")
            raise typer.Exit(0)

        failed = 0

        if batch_conc <= 1:
            # 顺序模式（传统行为）
            for pdf_path in tqdm(paths, desc="解析 PDF"):
                pdf_str = str(pdf_path)
                state.update_job(pdf_str, JobStatus.RUNNING)
                out_dir = out_base / f"{pdf_path.stem}{cfg.output_parsed_suffix}"
                out_dir.mkdir(parents=True, exist_ok=True)

                try:
                    result = parse_pdf_via_api_with_auto_split(
                        pdf_path,
                        tok,
                        out_dir,
                        cfg,
                        base_url=cfg.base_url,
                        model_version=model_version,
                        poll_interval=cfg.poll_interval,
                        max_wait=cfg.max_wait,
                        cache_enabled=cfg.cache_enabled,
                        cache_dir=cfg.cache_dir,
                        use_cache=not ctx.obj["no_cache"],
                        target_chunk_pages=chunk_pages,
                        api_rate_limit=cfg.api_rate_limit,
                        **md_opts,
                    )
                    if result:
                        state.update_job(pdf_str, JobStatus.COMPLETED)
                    else:
                        state.update_job(pdf_str, JobStatus.FAILED, "解析返回空结果")
                        failed += 1
                except Exception as e:
                    logger.error(f"处理失败 {pdf_path}: {e}")
                    state.update_job(pdf_str, JobStatus.FAILED, str(e))
                    failed += 1
        else:
            # 并发模式
            reset_api_semaphore()

            # 使用 try_start_job 原子化认领任务
            pdf_tasks = []
            task_paths = []
            for pdf_path in paths:
                pdf_str = str(pdf_path)
                if state.try_start_job(pdf_str, resume=resume):
                    out_dir = out_base / f"{pdf_path.stem}{cfg.output_parsed_suffix}"
                    out_dir.mkdir(parents=True, exist_ok=True)
                    task_paths.append(pdf_path)
                    pdf_tasks.append({
                        "pdf_path": pdf_path,
                        "token": tok,
                        "output_dir": out_dir,
                        "config": cfg,
                        "target_chunk_pages": chunk_pages,
                        "api_rate_limit": cfg.api_rate_limit,
                        "base_url": cfg.base_url,
                        "model_version": model_version,
                        "poll_interval": cfg.poll_interval,
                        "max_wait": cfg.max_wait,
                        "cache_enabled": cfg.cache_enabled,
                        "cache_dir": cfg.cache_dir,
                        "use_cache": not ctx.obj["no_cache"],
                        **md_opts,
                    })

            if not pdf_tasks:
                logger.info("没有需要处理的文件")
                raise typer.Exit(0)

            logger.info(f"并发模式: {batch_conc} 个文件同时处理, API 并发限制 {cfg.api_rate_limit}")

            with tqdm(total=len(pdf_tasks), desc="解析 PDF") as pbar:
                def on_file_complete(idx, result):
                    pbar.update(1)
                    status = "OK" if result["success"] else "FAIL"
                    name = Path(str(result["pdf_path"])).name[:30]
                    pbar.set_postfix_str(f"{status}: {name}")

                results = parse_pdfs_concurrent(
                    pdf_tasks,
                    batch_concurrency=batch_conc,
                    api_rate_limit=cfg.api_rate_limit,
                    on_complete=on_file_complete,
                )

            # 更新任务状态
            for r in results:
                pdf_str = str(r["pdf_path"])
                if r["success"]:
                    state.update_job(pdf_str, JobStatus.COMPLETED)
                else:
                    err = r.get("error") or "解析返回空结果"
                    state.update_job(pdf_str, JobStatus.FAILED, err)
                    failed += 1

    if failed:
        logger.warning(f"失败 {failed}/{len(paths)} 个文件")
        raise typer.Exit(1)
    typer.echo(f"成功解析 {len(paths)} 个 PDF")


if __name__ == "__main__":
    app()

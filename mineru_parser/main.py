"""MinerU PDF 解析器 CLI 入口（Typer app + 全局回调 + bootstrap）。

分层职责：
- 此模块（与 ``commands/``）使用 **Typer + Rich** 处理人机交互；
- ``core/`` 承载业务编排并用 **loguru** 记录日志；
- ``engines/`` 为可复用纯逻辑。
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import typer

from mineru_parser import __version__
from mineru_parser.commands.batch import batch_cmd
from mineru_parser.commands.from_json import from_json_cmd
from mineru_parser.commands.parse import parse_cmd
from mineru_parser.console import console, render_error
from mineru_parser.errors import ConfigError
from mineru_parser.logging_setup import (
    build_run_log_path,
    configure_logging,
    resolve_console_level,
)
from mineru_parser.models.config import load_config
from mineru_parser.models.params import RunContext

app = typer.Typer(
    name="mineru-parse",
    help="使用 MinerU API 解析 PDF 为 Markdown，支持页眉、页脚、页码、脚注",
    add_completion=False,
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"mineru-parse {__version__}")
        raise typer.Exit()


@app.callback()
def main_callback(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="显示版本信息",
    ),
    config_path: Path | None = typer.Option(
        None,
        "-c",
        "--config",
        path_type=Path,
        help="用户配置文件（YAML）；优先级：本参数/子命令 -c > 环境变量 > 当前目录 config.yml > 包内 default",
    ),
    force: bool = typer.Option(False, "-f", "--force", help="强制覆盖已存在的输出文件"),
    no_cache: bool = typer.Option(
        False, "--no-cache", help="禁用缓存，强制重新调用 API 解析"
    ),
    no_merge_paragraphs: bool = typer.Option(
        False, "--no-merge-paragraphs", help="禁用跨页段落合并"
    ),
    no_inline_footnotes: bool = typer.Option(
        False, "--no-inline-footnotes", help="脚注放在页末而非段落后"
    ),
    quiet: bool = typer.Option(False, "-q", "--quiet", help="静默模式，减少输出"),
    debug: bool = typer.Option(False, "-d", "--debug", help="调试模式，输出详细日志"),
    verbose: bool = typer.Option(False, "--verbose", help="在终端显示 INFO 级日志"),
    dry_run: bool = typer.Option(False, "--dry-run", help="模拟运行，不实际调用 API"),
) -> None:
    """MinerU PDF 解析器。"""
    try:
        cfg = load_config(config_path)
    except ConfigError as e:
        console.print(render_error(str(e)))
        raise typer.Exit(1) from e

    log_path, started = build_run_log_path(cfg.cache_dir / "logs")
    console_level = resolve_console_level(quiet=quiet, debug=debug, verbose=verbose)
    configure_logging(log_path, started, list(sys.argv), console_level)

    ctx.obj = RunContext(
        config=cfg,
        rate_limiter=threading.Semaphore(cfg.api_rate_limit),
        log_path=log_path,
        run_started_at=started,
        force=force,
        no_cache=no_cache,
        no_merge_paragraphs=no_merge_paragraphs,
        no_inline_footnotes=no_inline_footnotes,
        dry_run=dry_run,
        quiet=quiet,
    )


# 注册子命令
app.command(name="parse")(parse_cmd)
app.command(name="batch")(batch_cmd)
app.command(name="from-json")(from_json_cmd)


if __name__ == "__main__":
    app()

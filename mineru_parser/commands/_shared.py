"""命令层共享助手：配置解析、输出目录推导、Markdown 选项与 token 校验。

这些函数从旧 ``cli.py`` 的各命令中抽取，消除重复逻辑，使命令函数保持「瘦」。
"""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import typer

from mineru_parser.console import print_error
from mineru_parser.logging_setup import log_run_result
from mineru_parser.models.config import RootConfig
from mineru_parser.models.params import RunContext


def resolve_subcommand_config(rc: RunContext, config_path: Path | None) -> RunContext:
    """子命令上的 ``-c`` 重新加载配置（优先级见 :func:`load_config`）。"""
    if config_path is None:
        return rc
    # 延迟导入避免循环
    from mineru_parser.models.config import load_config

    try:
        rc.config = load_config(config_path)
    except Exception as e:  # ConfigError
        print_error(str(e), quiet=rc.quiet)
        raise typer.Exit(1) from e
    return rc


def validate_token(token: str, *, quiet: bool = False) -> None:
    """校验 API Token，缺失或空白时输出错误并退出。"""
    if not token or not token.strip():
        print_error(
            "未配置 API Token。请通过以下方式之一设置：\n"
            "  1) 在 config.yml / default_config.yml / -c 配置中设置 api.token\n"
            "  2) 设置环境变量 MINERU_TOKEN\n"
            "  3) 使用 -t/--token 传入",
            quiet=quiet,
        )
        raise typer.Exit(1)


def fail_run(msg: str, rc: RunContext, elapsed: float = 0.0) -> NoReturn:
    """输出失败原因（stderr，quiet 感知）、记录运行结果并以退出码 1 终止。"""
    print_error(msg, quiet=rc.quiet)
    log_run_result(False, None, elapsed)
    raise typer.Exit(1)


def build_md_options(
    rc: RunContext,
    cfg: RootConfig,
    *,
    header: bool = False,
    footer: bool = False,
    page_number: bool = False,
    no_footnote: bool = False,
) -> dict[str, bool]:
    """合并配置默认与 CLI 覆盖的 Markdown 选项。"""
    return {
        "include_header": header or cfg.markdown.include_header,
        "include_footer": footer or cfg.markdown.include_footer,
        "include_page_number": page_number or cfg.markdown.include_page_number,
        "include_footnote": not no_footnote and cfg.markdown.include_footnote,
        "merge_paragraphs": cfg.markdown.merge_paragraphs
        and not rc.no_merge_paragraphs,
        "inline_footnotes": cfg.markdown.inline_footnotes
        and not rc.no_inline_footnotes,
    }

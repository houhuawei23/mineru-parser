"""命令层共享助手：配置解析、输出目录推导、Markdown 选项与 token 校验。

这些函数从旧 ``cli.py`` 的各命令中抽取，消除重复逻辑，使命令函数保持「瘦」。
"""

from __future__ import annotations

from pathlib import Path

import typer

from mineru_parser.console import console, render_error
from mineru_parser.errors import TokenError
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
        console.print(render_error(str(e)))
        raise typer.Exit(1) from e
    return rc


def validate_token(token: str) -> None:
    """校验 API Token，缺失时渲染错误并退出。"""
    if not token:
        console.print(
            render_error(
                "未配置 API Token。请通过以下方式之一设置：\n"
                "  1) 在 config.yml / default_config.yml / -c 配置中设置 api.token\n"
                "  2) 设置环境变量 MINERU_TOKEN\n"
                "  3) 使用 -t/--token 传入"
            )
        )
        raise typer.Exit(1)
    if not token.strip():
        raise TokenError("token 为空白")


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

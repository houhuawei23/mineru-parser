"""``from-json`` 子命令：从已解析目录的 JSON 重新生成 Markdown。"""

from __future__ import annotations

from pathlib import Path

import typer

from mineru_parser.commands._shared import build_md_options, resolve_subcommand_config
from mineru_parser.console import console, render_error, render_result_panel
from mineru_parser.engines.markdown import regenerate_markdown_from_json
from mineru_parser.logging_setup import log_run_result
from mineru_parser.models.params import RunContext


def from_json_cmd(
    ctx: typer.Context,
    input_dir: Path = typer.Argument(
        ..., path_type=Path, help="已解析目录（含 *_content_list.json）"
    ),
    output: Path | None = typer.Option(
        None, "-o", "--output", path_type=Path, help="输出 Markdown 路径"
    ),
    header: bool = typer.Option(False, "--header", help="添加页眉"),
    footer: bool = typer.Option(False, "--footer", help="添加页脚"),
    page_number: bool = typer.Option(False, "--page-number", help="添加页码"),
    no_footnote: bool = typer.Option(False, "--no-footnote", help="关闭脚注"),
    config_path: Path | None = typer.Option(
        None, "-c", "--config", path_type=Path, help="覆盖配置（YAML）"
    ),
) -> None:
    """从已解压目录的 JSON 重新生成 Markdown。"""
    rc: RunContext = ctx.obj
    resolve_subcommand_config(rc, config_path)
    if not input_dir.is_dir():
        console.print(render_error(f"目录不存在: {input_dir}"))
        log_run_result(False, None, 0.0)
        raise typer.Exit(1)

    cfg = rc.config
    md_opts = build_md_options(
        rc,
        cfg,
        header=header,
        footer=footer,
        page_number=page_number,
        no_footnote=no_footnote,
    )
    output_md = output if output and str(output).endswith(".md") else None
    result = regenerate_markdown_from_json(input_dir, output_md=output_md, **md_opts)
    if result:
        out_path = output_md or (input_dir / "full.md")
        console.print(
            render_result_panel(
                success=True, md_path=out_path, md_len=len(result), elapsed=0.0
            )
        )
        log_run_result(True, out_path, 0.0)
    else:
        console.print(render_error("未找到有效的 content_list JSON 文件"))
        log_run_result(False, None, 0.0)
        raise typer.Exit(1)

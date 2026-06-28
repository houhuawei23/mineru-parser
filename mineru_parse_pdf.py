#!/usr/bin/env python3
"""
MinerU PDF 解析器 - 兼容旧版入口。

推荐使用新 CLI：python -m mineru_parser.cli 或 mineru-parse
"""

import os
import sys
from pathlib import Path

from loguru import logger

# 确保可导入 mineru_parser
sys.path.insert(0, str(Path(__file__).parent))

from mineru_parser.api import parse_pdf_via_api_with_auto_split
from mineru_parser.config import ConfigError, load_config
from mineru_parser.markdown import regenerate_markdown_from_json
from mineru_parser.utils import resolve_input_to_pdf


def _setup_logging(log_file: Path) -> None:
    """配置日志：文件记录详细日志，终端仅显示警告及以上。"""
    logger.remove()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger.add(
        str(log_file),
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
        rotation="10 MB",
        retention="1 week",
        encoding="utf-8",
    )
    logger.add(sys.stderr, level="WARNING", format="{level}: {message}")


def main() -> None:
    """兼容旧版 argparse 入口。"""
    import argparse

    parser = argparse.ArgumentParser(
        description="使用 MinerU API 解析 PDF 并输出 Markdown。支持本地 PDF 或 arXiv 链接"
    )
    parser.add_argument(
        "pdf_or_url",
        nargs="?",
        help="PDF 路径、arXiv 链接，或已解析目录（配合 --from-json）",
    )
    parser.add_argument(
        "--from-json", action="store_true", help="从已解压目录的 JSON 重新生成 Markdown"
    )
    parser.add_argument("-o", "--output", help="输出目录或 Markdown 路径")
    parser.add_argument("-t", "--token", default="", help="MinerU API Token")
    parser.add_argument("-c", "--config", type=Path, help="配置文件路径")
    parser.add_argument("--model", default="vlm", choices=["vlm", "pipeline"])
    parser.add_argument("--poll-interval", type=int, default=10)
    parser.add_argument("--max-wait", type=int, default=1200)
    parser.add_argument("--header", action="store_true")
    parser.add_argument("--footer", action="store_true")
    parser.add_argument("--page-number", action="store_true")
    parser.add_argument("--no-footnote", action="store_true")
    parser.add_argument(
        "--no-cache", action="store_true", help="禁用缓存，强制重新调用 API 解析"
    )
    parser.add_argument(
        "--no-merge-paragraphs", action="store_true", help="禁用跨页段落合并"
    )
    parser.add_argument(
        "--no-inline-footnotes", action="store_true", help="脚注放在页末而非段落后"
    )
    args = parser.parse_args()

    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        print(f"配置加载失败: {e}", file=sys.stderr)
        sys.exit(1)

    log_file = cfg.cache_dir / "logs" / "mineru-parse.log"
    _setup_logging(log_file)
    print(f"详细日志: {log_file}")

    token = (args.token or os.environ.get("MINERU_TOKEN", "") or cfg.token).strip()

    if args.from_json:
        if not args.pdf_or_url:
            print("请提供已解析目录路径")
            sys.exit(1)
        parsed_dir = Path(args.pdf_or_url)
        if not parsed_dir.is_dir():
            print(f"目录不存在: {parsed_dir}")
            sys.exit(1)
        output_md = (
            Path(args.output) if args.output and args.output.endswith(".md") else None
        )
        if regenerate_markdown_from_json(
            parsed_dir,
            output_md,
            include_header=args.header or cfg.markdown.include_header,
            include_footer=args.footer or cfg.markdown.include_footer,
            include_page_number=args.page_number or cfg.markdown.include_page_number,
            include_footnote=not args.no_footnote and cfg.markdown.include_footnote,
            merge_paragraphs=cfg.markdown.merge_paragraphs
            and not args.no_merge_paragraphs,
            inline_footnotes=cfg.markdown.inline_footnotes
            and not args.no_inline_footnotes,
        ):
            print("重新生成成功")
        else:
            sys.exit(1)
        return

    if not token:
        print("请提供 -t/--token 或设置环境变量 MINERU_TOKEN")
        sys.exit(1)

    input_arg = args.pdf_or_url
    if not input_arg:
        default = (
            Path(__file__).parent
            / "2021-ICLR-ALFWorld-Aligning-Text-and-Embodied-Environments-for-Interactive-Learning-2010.03768v2.pdf"
        )
        input_arg = str(default) if default.exists() else ""

    if not input_arg:
        print("请提供 PDF 路径或 arXiv 链接")
        sys.exit(1)

    is_url = input_arg.strip().startswith(("http://", "https://"))
    if is_url:
        output_dir = Path(args.output) if args.output else Path.cwd()
        result = resolve_input_to_pdf(input_arg, output_dir)
        if not result[0]:
            sys.exit(1)
        pdf_path, stem = result
        output_dir = output_dir / f"{stem}{cfg.output_parsed_suffix}"
    else:
        pdf_path = Path(input_arg)
        if not pdf_path.exists():
            print(f"文件不存在: {pdf_path}")
            sys.exit(1)
        output_dir = Path(args.output) if args.output else pdf_path.parent
        if output_dir.suffix == ".md":
            output_dir = output_dir.parent
        output_dir = output_dir / f"{pdf_path.stem}{cfg.output_parsed_suffix}"

    output_dir.mkdir(parents=True, exist_ok=True)
    md_opts = {
        "include_header": args.header or cfg.markdown.include_header,
        "include_footer": args.footer or cfg.markdown.include_footer,
        "include_page_number": args.page_number or cfg.markdown.include_page_number,
        "include_footnote": not args.no_footnote and cfg.markdown.include_footnote,
        "merge_paragraphs": cfg.markdown.merge_paragraphs
        and not args.no_merge_paragraphs,
        "inline_footnotes": cfg.markdown.inline_footnotes
        and not args.no_inline_footnotes,
    }

    markdown = parse_pdf_via_api_with_auto_split(
        pdf_path,
        token,
        output_dir,
        cfg,
        base_url=cfg.base_url,
        model_version=args.model,
        poll_interval=args.poll_interval,
        max_wait=args.max_wait,
        cache_enabled=cfg.cache_enabled,
        cache_dir=cfg.cache_dir,
        use_cache=not args.no_cache,
        **md_opts,
    )
    if markdown:
        md_path = output_dir / f"{pdf_path.stem}.md"
        print(f"解析成功，Markdown 长度: {len(markdown)} 字符，已保存: {md_path}")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()

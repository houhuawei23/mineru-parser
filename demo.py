#!/usr/bin/env python3
"""
MinerU 解析器演示脚本。
演示从 JSON 生成 Markdown（无需 API Token）。
"""

from pathlib import Path

from mineru_parser.json_parser import (
    find_content_list_json,
    content_list_json_to_markdown,
    content_list_v2_to_markdown,
)
from mineru_parser.markdown import regenerate_markdown_from_json


def demo_from_json(parsed_dir: str | Path) -> None:
    """从已解析目录的 JSON 重新生成 Markdown。"""
    parsed_dir = Path(parsed_dir)
    if not parsed_dir.is_dir():
        print(f"目录不存在: {parsed_dir}")
        return

    content_list = find_content_list_json(parsed_dir)
    content_list_v2 = list(parsed_dir.rglob("content_list_v2.json"))

    if content_list:
        print(f"找到 content_list: {content_list}")
        md = content_list_json_to_markdown(content_list)
        print(f"生成 Markdown 长度: {len(md)} 字符")
        out = parsed_dir / "full.md"
        out.write_text(md, encoding="utf-8")
        print(f"已保存: {out}")
    elif content_list_v2:
        print(f"找到 content_list_v2: {content_list_v2[0]}")
        md = content_list_v2_to_markdown(content_list_v2[0])
        print(f"生成 Markdown 长度: {len(md)} 字符")
        out = parsed_dir / "full.md"
        out.write_text(md, encoding="utf-8")
        print(f"已保存: {out}")
    else:
        result = regenerate_markdown_from_json(parsed_dir)
        if result:
            print("已通过 regenerate_markdown_from_json 生成")
        else:
            print("未找到有效的 content_list JSON")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        demo_from_json(sys.argv[1])
    else:
        # 尝试 examples 目录
        examples = Path(__file__).parent / "examples"
        for d in examples.rglob("*_parsed"):
            if d.is_dir():
                print(f"演示: {d}")
                demo_from_json(d)
                break
        else:
            print("用法: python demo.py <parsed_dir>")
            print("示例: python demo.py examples/extracted_xxx_parsed")

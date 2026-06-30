"""命令层：Typer 子命令入口（parse / batch / from-json）。

命令函数只做参数解析、配置解析、调用编排与 Rich 渲染；业务逻辑在 ``core/``。
"""

from mineru_parser.commands.batch import batch_cmd
from mineru_parser.commands.from_json import from_json_cmd
from mineru_parser.commands.parse import parse_cmd

__all__ = ["batch_cmd", "from_json_cmd", "parse_cmd"]

"""统一异常体系。

所有命令层捕获的业务错误均派生自 :class:`MineruError`，便于在 Typer 命令中统一渲染与退出。
"""

from __future__ import annotations


class MineruError(Exception):
    """所有 mineru-parser 业务异常的基类。"""


class ConfigError(MineruError):
    """配置加载或校验失败。"""


class TokenError(MineruError):
    """未配置或无效的 API Token。"""


class ParseError(MineruError):
    """解析流程中的业务错误（上传 / 轮询 / 构建）。"""


class DownloadError(MineruError):
    """下载解析结果失败。"""

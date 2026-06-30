"""日志系统：每次运行一个独立日志文件，按天分子目录。

日志文件路径：``<cache_dir>/logs/YYYY-MM-DD/YYYY-MM-DD_HHMMSS.log``

日志记录包含：运行命令、运行起始时间、时间戳、级别、位置（模块:函数:行）、
日志内容、各阶段耗时、最终执行结果。

终端 sink 的级别由 ``-q`` / ``-d`` / ``--verbose`` 控制；详细日志仅写入文件，
不打扰默认用户输出（Rich 负责命令层的人机展示）。
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from loguru import logger

# 文件 sink：时间 | 级别 | 位置 | 内容
FILE_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
    "{name}:{function}:{line} | {message}"
)
# 终端 sink：精简（级别 + 内容）
CONSOLE_FORMAT = "{level:<8} | {message}"

DEFAULT_LOG_DIR = Path("~/.cache/mineru_parser/logs").expanduser()


def build_run_log_path(log_root: Path | None = None) -> tuple[Path, datetime]:
    """构造本次运行的日志文件路径并创建当日子目录。

    :return: ``(log_path, run_started_at)``。同一天多次运行靠时分秒区分，互不重名。
    """
    started = datetime.now()
    root = Path(log_root).expanduser() if log_root else DEFAULT_LOG_DIR
    day_dir = root / started.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    log_path = day_dir / started.strftime("%Y-%m-%d_%H%M%S.log")
    return log_path, started


def configure_logging(
    run_log_path: Path,
    run_started_at: datetime,
    run_command: list[str],
    console_level: str = "WARNING",
) -> Path:
    """配置 loguru：每次运行一个 DEBUG 级文件 sink + 一个可调级别的 stderr sink。

    文件起始注入运行命令与起始时间头；文件记录同步写入（loguru 线程安全），
    便于测试与排查时即时读取。
    """
    logger.remove()
    run_log_path.parent.mkdir(parents=True, exist_ok=True)

    # 文件 sink：完整运行日志（含时间、级别、位置、内容）
    logger.add(
        str(run_log_path),
        level="DEBUG",
        format=FILE_FORMAT,
        encoding="utf-8",
    )

    # 终端 sink：级别由 -q/-d/--verbose 控制
    logger.add(
        sys.stderr,
        level=console_level,
        format=CONSOLE_FORMAT,
        backtrace=True,
        diagnose=(console_level == "DEBUG"),
    )

    # 运行命令与起始时间作为文件开头标记
    cmd_text = " ".join(str(a) for a in run_command)
    logger.bind(run=True).info(f"=== RUN START === command: {cmd_text}")
    logger.bind(run=True).info(
        f"=== RUN START === started: {run_started_at.isoformat()}"
    )
    return run_log_path


def log_run_result(
    success: bool,
    md_path: Path | None = None,
    elapsed: float = 0.0,
    files_done: int | None = None,
    files_failed: int | None = None,
) -> None:
    """在命令退出前写入最终执行结果汇总行。"""
    result = "SUCCESS" if success else "FAILURE"
    parts = [f"result={result}", f"elapsed={elapsed:.2f}s"]
    if md_path is not None:
        parts.append(f"md={md_path}")
    if files_done is not None:
        parts.append(f"done={files_done}")
    if files_failed is not None:
        parts.append(f"failed={files_failed}")
    logger.bind(run=True).info("=== RUN END === " + " ".join(parts))


def resolve_console_level(
    quiet: bool = False, debug: bool = False, verbose: bool = False
) -> str:
    """根据 -q/-d/--verbose 解析终端 sink 级别。"""
    if debug:
        return "DEBUG"
    if verbose:
        return "INFO"
    if quiet:
        return "ERROR"
    return "WARNING"

"""日志系统单元测试：路径格式、运行命令头、结果汇总。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from loguru import logger

from mineru_parser.logging_setup import (
    build_run_log_path,
    configure_logging,
    log_run_result,
    resolve_console_level,
)


@pytest.fixture
def reset_logger():
    """测试后恢复 loguru 默认 sink，避免影响其他测试。"""
    yield
    logger.remove()
    logger.add(sys.stderr)


_PATH_RE = re.compile(r"logs/\d{4}-\d{2}-\d{2}/\d{4}-\d{2}-\d{2}_\d{6}\.log$")


def test_build_run_log_path_format(tmp_path: Path) -> None:
    """日志路径应为 logs/YYYY-MM-DD/YYYY-MM-DD_HHMMSS.log。"""
    log_path, started = build_run_log_path(tmp_path / "logs")
    assert _PATH_RE.search(str(log_path))
    assert log_path.parent.is_dir()  # 当日子目录已创建
    assert log_path.parent.name == started.strftime("%Y-%m-%d")


def test_configure_logging_writes_run_start_and_result(
    tmp_path: Path, reset_logger
) -> None:
    """文件应含运行命令头、起始时间，并能同步读取。"""
    log_path, started = build_run_log_path(tmp_path / "logs")
    configure_logging(log_path, started, ["mineru-parse", "parse", "paper.pdf"])
    log_run_result(success=True, md_path=Path("out/full.md"), elapsed=3.21)

    content = log_path.read_text(encoding="utf-8")
    assert "=== RUN START === command: mineru-parse parse paper.pdf" in content
    assert "=== RUN START === started:" in content
    assert "=== RUN END === result=SUCCESS elapsed=3.21s md=out/full.md" in content
    # 每条记录含级别与位置（模块:函数:行）分隔
    assert "INFO" in content
    assert "logging_setup:" in content


def test_log_run_result_failure_includes_counts(tmp_path: Path, reset_logger) -> None:
    log_path, started = build_run_log_path(tmp_path / "logs")
    configure_logging(log_path, started, ["mineru-parse", "batch"])
    log_run_result(success=False, elapsed=10.0, files_done=7, files_failed=2)
    content = log_path.read_text(encoding="utf-8")
    assert "result=FAILURE" in content
    assert "done=7" in content and "failed=2" in content


def test_resolve_console_level() -> None:
    assert resolve_console_level() == "WARNING"
    assert resolve_console_level(quiet=True) == "ERROR"
    assert resolve_console_level(debug=True) == "DEBUG"
    assert resolve_console_level(verbose=True) == "INFO"
    # debug 优先于 verbose
    assert resolve_console_level(debug=True, verbose=True) == "DEBUG"

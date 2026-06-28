"""进度报告模块单元测试。"""

from mineru_parser.progress import ProgressReporter, make_progress_callback


def test_progress_reporter_quiet_no_output(capsys) -> None:
    """静默模式下不应产生终端输出。"""
    reporter = ProgressReporter(desc="test", quiet=True)
    reporter.update(
        "start", {"pdf_path": "/tmp/a.pdf", "num_pages": 10, "size_mb": 1.5}
    )
    reporter.update("complete", {"markdown_length": 100})
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_progress_reporter_start_output(capsys) -> None:
    """start 阶段应输出解析文件信息。"""
    reporter = ProgressReporter(desc="test", quiet=False)
    reporter.update(
        "start", {"pdf_path": "/tmp/a.pdf", "num_pages": 10, "size_mb": 1.5}
    )
    reporter.close()
    captured = capsys.readouterr()
    assert "开始解析" in captured.out
    assert "a.pdf" in captured.out
    assert "10 页" in captured.out


def test_progress_reporter_complete_output(capsys) -> None:
    """complete 阶段应输出耗时与 Markdown 长度。"""
    reporter = ProgressReporter(desc="test", quiet=False)
    reporter.update("complete", {"elapsed": 3.5, "markdown_length": 1234})
    captured = capsys.readouterr()
    assert "解析完成" in captured.out
    assert "3.5s" in captured.out
    assert "1234" in captured.out


def test_make_progress_callback() -> None:
    """make_progress_callback 应正确代理到 reporter。"""
    reporter = ProgressReporter(desc="test", quiet=True)
    cb = make_progress_callback(reporter)
    cb("start", {"pdf_path": "/tmp/b.pdf", "num_pages": 5, "size_mb": 0.5})
    # 静默模式下无异常即可

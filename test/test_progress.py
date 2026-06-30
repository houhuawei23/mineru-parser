"""Rich 进度报告器与渲染助手单元测试。"""

from __future__ import annotations

from pathlib import Path

from mineru_parser.console import (
    RichProgressReporter,
    console,
    make_progress_callback,
    render_dry_run_table,
    render_error,
    render_result_panel,
    render_run_header,
)


def test_reporter_quiet_produces_no_output(capsys) -> None:
    """静默模式下不应产生终端输出。"""
    reporter = RichProgressReporter(desc="test", quiet=True)
    reporter.update(
        "start", {"pdf_path": "/tmp/a.pdf", "num_pages": 10, "size_mb": 1.5}
    )
    reporter.update("split_done", {"total_parts": 3})
    reporter.update("complete", {"elapsed": 1.0, "markdown_length": 10})
    reporter.close()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_reporter_full_phase_flow_no_raise(capsys) -> None:
    """完整阶段流转不应抛异常，并输出切分提示。"""
    reporter = RichProgressReporter(desc="解析")
    phases = [
        ("start", {"pdf_path": "/tmp/a.pdf", "num_pages": 10, "size_mb": 1.5}),
        ("upload", {"batch_id": "bid-123"}),
        ("upload_done", {}),
        ("split_done", {"total_parts": 3}),
        ("part_complete", {"idx": 0, "total": 3}),
        ("part_complete", {"idx": 1, "total": 3}),
        ("merge", {}),
        ("complete", {"elapsed": 3.5, "markdown_length": 1234}),
    ]
    for phase, info in phases:
        reporter.update(phase, info)
    reporter.close()
    out = capsys.readouterr().out
    assert "3 个片段" in out


def test_reporter_error_phase_renders_error(capsys) -> None:
    """error 阶段应渲染错误面板并关闭进度条。"""
    reporter = RichProgressReporter(desc="解析")
    reporter.update("error", {"error": "boom"})
    reporter.close()  # 幂等
    out = capsys.readouterr().out
    assert "boom" in out


def test_make_progress_callback_proxies() -> None:
    """make_progress_callback 应代理到 reporter（静默下无异常）。"""
    reporter = RichProgressReporter(desc="test", quiet=True)
    cb = make_progress_callback(reporter)
    cb("start", {"pdf_path": "/tmp/b.pdf", "num_pages": 5, "size_mb": 0.5})
    cb("poll")  # info 默认为空 dict


def test_render_run_header() -> None:
    """运行参数面板应包含输入、模型、日志路径。"""
    with console.capture() as cap:
        console.print(
            render_run_header(
                input_path="paper.pdf",
                model="vlm",
                output_dir=Path("out"),
                pages="1-3",
                target_chunk_pages=0,
                dry_run=False,
                log_path=Path("/tmp/x.log"),
            )
        )
    text = cap.get()
    assert "paper.pdf" in text
    assert "vlm" in text
    assert "/tmp/x.log" in text


def test_render_result_panel_success_and_failure() -> None:
    """结果面板区分成功/失败。"""
    with console.capture() as cap:
        console.print(
            render_result_panel(
                success=True, md_path=Path("out/full.md"), md_len=1234, elapsed=3.5
            )
        )
    assert "解析成功" in cap.get()
    with console.capture() as cap:
        console.print(
            render_result_panel(success=False, md_path=None, md_len=0, elapsed=0.0)
        )
    assert "解析失败" in cap.get()


def test_render_dry_run_table() -> None:
    with console.capture() as cap:
        console.print(
            render_dry_run_table(
                rows=[("a.pdf", 10, 1.5), ("b.pdf", 20, 2.5)],
                total_pages=30,
                total_size_mb=4.0,
                model="vlm",
                out_base=Path("out"),
            )
        )
    text = cap.get()
    assert "a.pdf" in text and "b.pdf" in text and "30" in text


def test_render_error_panel() -> None:
    with console.capture() as cap:
        console.print(render_error("something broke"))
    assert "something broke" in cap.get()

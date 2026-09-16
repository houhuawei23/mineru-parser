"""CLI（main + commands）单元测试。

使用真实 :class:`RootConfig`（pydantic）构造测试配置，patch ``main.load_config``
与 ``main.configure_logging`` 注入；patch 编排函数避免真实 API 调用。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

import mineru_parser
from mineru_parser.core.result import ParseResult
from mineru_parser.main import app
from mineru_parser.models.config import ApiConfig, CacheConfig, RootConfig
from mineru_parser.models.params import ParseParams

runner = CliRunner()

# 预检（validate_pdf）要求真实可解析的 PDF，用 fitz 生成
fitz = pytest.importorskip("fitz")


def _make_pdf(path: Path, num_pages: int = 1) -> None:
    doc = fitz.open()
    for i in range(num_pages):
        doc.new_page().insert_text((72, 72), f"Page {i}")
    doc.save(str(path))
    doc.close()


def _cfg(cache_dir: Path, *, token: str = "test_token") -> RootConfig:
    """构造带 token 与临时缓存目录的真实配置。"""
    return RootConfig(api=ApiConfig(token=token), cache=CacheConfig(dir=cache_dir))


def _invoke(args: list[str], cache_dir: Path, *, token: str = "test_token"):
    """以 patched 配置与日志注入运行 CLI。"""
    cfg = _cfg(cache_dir, token=token)
    with (
        patch("mineru_parser.main.load_config", return_value=cfg),
        patch("mineru_parser.main.configure_logging"),
    ):
        return runner.invoke(app, args, catch_exceptions=False)


# ==================== 主回调与全局选项 ====================


class TestMainCallback:
    def test_version_flag(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "mineru-parse" in result.output
        assert mineru_parser.__version__ in result.output

    def test_help_shows_commands(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "parse" in result.output
        assert "batch" in result.output
        assert "from-json" in result.output

    def test_parse_help(self) -> None:
        result = runner.invoke(app, ["parse", "--help"])
        assert result.exit_code == 0
        assert "解析单个 PDF 或 URL" in result.output
        for flag in ("--output", "--token", "--model", "--pages", "--force"):
            assert flag in result.output

    def test_console_level_resolved(self, tmp_path: Path) -> None:
        """--debug/--quiet/--verbose 解析为对应终端日志级别。"""
        cfg = _cfg(tmp_path)
        for args, expected in [
            (["--debug", "parse", "--help"], "DEBUG"),
            (["--quiet", "parse", "--help"], "ERROR"),
            (["--verbose", "parse", "--help"], "INFO"),
        ]:
            with (
                patch("mineru_parser.main.load_config", return_value=cfg),
                patch("mineru_parser.main.configure_logging") as mock_log,
            ):
                runner.invoke(app, args)
            assert mock_log.call_args.args[3] == expected  # console_level 位置参数

    def test_configure_logging_receives_run_command(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path)
        with (
            patch("mineru_parser.main.load_config", return_value=cfg),
            patch("mineru_parser.main.configure_logging") as mock_log,
            patch(
                "mineru_parser.main.sys.argv", ["mineru-parse", "parse", "paper.pdf"]
            ),
        ):
            runner.invoke(app, ["parse", "--help"])
        # run_command 来自 sys.argv，应包含实际命令
        run_command = mock_log.call_args.args[2]
        assert "parse" in run_command and "paper.pdf" in run_command


# ==================== parse ====================


class TestParseCommand:
    def test_parse_missing_file_exits_error(self, tmp_path: Path) -> None:
        result = _invoke(["parse", "/nonexistent/file.pdf"], tmp_path)
        assert result.exit_code == 1
        assert "不存在" in result.output

    def test_parse_non_pdf_exits_error(self, tmp_path: Path) -> None:
        txt = tmp_path / "test.txt"
        txt.write_text("not a pdf")
        result = _invoke(["parse", str(txt)], tmp_path)
        assert result.exit_code == 1
        assert "PDF" in result.output

    def test_parse_missing_token_exits_error(self, tmp_path: Path) -> None:
        pdf = tmp_path / "x.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        result = _invoke(["parse", str(pdf)], tmp_path, token="")
        assert result.exit_code == 1
        assert "Token" in result.output

    def test_parse_whitespace_token_exits_error(self, tmp_path: Path) -> None:
        """纯空白 token 与缺失 token 同样处理，且不抛裸 traceback。"""
        pdf = tmp_path / "x.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        result = _invoke(["parse", str(pdf)], tmp_path, token="   ")
        assert result.exit_code == 1
        assert "Token" in result.output

    def test_parse_fake_pdf_preflight_exits_error(self, tmp_path: Path) -> None:
        """HTML 伪装 .pdf：预检拦截，orchestrate_parse 不被调用。"""
        pdf = tmp_path / "fake.pdf"
        pdf.write_bytes(b"<html>captcha</html>")
        with patch("mineru_parser.commands.parse.orchestrate_parse") as mock_orch:
            result = _invoke(["parse", str(pdf)], tmp_path)
        assert result.exit_code == 1
        assert "不是有效的 PDF" in result.output
        mock_orch.assert_not_called()

    def test_parse_success(self, tmp_path: Path) -> None:
        pdf = tmp_path / "paper.pdf"
        _make_pdf(pdf)
        with patch(
            "mineru_parser.commands.parse.orchestrate_parse", return_value="# Markdown"
        ):
            result = _invoke(["parse", str(pdf)], tmp_path)
        assert result.exit_code == 0
        assert "解析成功" in result.output

    def test_parse_no_cache_disables_cache(self, tmp_path: Path) -> None:
        """parse --no-cache 应传入 use_cache=False。"""
        pdf = tmp_path / "paper.pdf"
        _make_pdf(pdf)
        with patch(
            "mineru_parser.commands.parse.orchestrate_parse", return_value="# Markdown"
        ) as mock_orch:
            result = _invoke(["parse", "--no-cache", str(pdf)], tmp_path)
        assert result.exit_code == 0
        params = mock_orch.call_args.args[0]
        assert isinstance(params, ParseParams)
        assert params.use_cache is False

    def test_parse_global_no_cache_still_works(self, tmp_path: Path) -> None:
        """全局 --no-cache parse 仍保持向后兼容。"""
        pdf = tmp_path / "paper.pdf"
        _make_pdf(pdf)
        with patch(
            "mineru_parser.commands.parse.orchestrate_parse", return_value="# Markdown"
        ) as mock_orch:
            result = _invoke(["--no-cache", "parse", str(pdf)], tmp_path)
        assert result.exit_code == 0
        params = mock_orch.call_args.args[0]
        assert isinstance(params, ParseParams)
        assert params.use_cache is False

    def test_parse_help_shows_no_cache(self, tmp_path: Path) -> None:
        result = _invoke(["parse", "--help"], tmp_path)
        assert result.exit_code == 0
        assert "--no-cache" in result.output

    def test_parse_failure_exits_error(self, tmp_path: Path) -> None:
        pdf = tmp_path / "paper.pdf"
        _make_pdf(pdf)
        with patch("mineru_parser.commands.parse.orchestrate_parse", return_value=None):
            result = _invoke(["parse", str(pdf)], tmp_path)
        assert result.exit_code == 1
        assert "解析失败" in result.output


# ==================== batch ====================


class TestBatchCommand:
    def test_batch_no_pdfs_exits_zero(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        result = _invoke(["batch", "-i", str(empty)], tmp_path)
        assert result.exit_code == 0
        assert "未找到" in result.output

    def test_batch_dry_run(self, tmp_path: Path) -> None:
        pdfs_dir = tmp_path / "pdfs"
        pdfs_dir.mkdir()
        _make_pdf(pdfs_dir / "a.pdf")
        _make_pdf(pdfs_dir / "b.pdf")
        with patch(
            "mineru_parser.commands.batch.get_pdf_info", return_value=(10, 1024)
        ):
            result = _invoke(
                [
                    "--dry-run",
                    "batch",
                    "-i",
                    str(pdfs_dir),
                    "-o",
                    str(tmp_path / "out"),
                ],
                tmp_path,
            )
        assert result.exit_code == 0
        # 不依赖列宽折叠：caption 含文件数，汇总行含总页数 2*10
        assert "文件数 2" in result.output
        assert "20" in result.output

    def test_batch_no_cache_disables_cache(self, tmp_path: Path) -> None:
        """batch --no-cache 应传入 use_cache=False。"""
        pdfs_dir = tmp_path / "pdfs"
        pdfs_dir.mkdir()
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        _make_pdf(pdfs_dir / "a.pdf")
        with (
            patch("mineru_parser.commands.batch.get_pdf_info", return_value=(1, 1024)),
            patch(
                "mineru_parser.commands.batch.run_batch",
                return_value=[ParseResult(pdf_path=pdfs_dir / "a.pdf", success=True)],
            ) as mock_run,
        ):
            result = _invoke(
                ["batch", "--no-cache", "-i", str(pdfs_dir), "-o", str(out_dir)],
                tmp_path,
            )
        assert result.exit_code == 0
        params = mock_run.call_args.args[0][0]
        assert isinstance(params, ParseParams)
        assert params.use_cache is False

    def test_batch_help_shows_no_cache(self, tmp_path: Path) -> None:
        result = _invoke(["batch", "--help"], tmp_path)
        assert result.exit_code == 0
        assert "--no-cache" in result.output

    def test_batch_skips_invalid_preflight(self, tmp_path: Path) -> None:
        """1 个有效 + 1 个伪装 PDF：只处理有效者，无效者有警告。"""
        pdfs_dir = tmp_path / "pdfs"
        pdfs_dir.mkdir()
        _make_pdf(pdfs_dir / "good.pdf")
        (pdfs_dir / "bad.pdf").write_bytes(b"<html>blocked</html>")
        with patch(
            "mineru_parser.commands.batch.run_batch",
            return_value=[ParseResult(pdf_path=pdfs_dir / "good.pdf", success=True)],
        ) as mock_run:
            result = _invoke(
                ["batch", "-i", str(pdfs_dir), "-o", str(tmp_path / "out")],
                tmp_path,
            )
        assert result.exit_code == 0
        # 只有 good.pdf 进入处理队列
        assert len(mock_run.call_args.args[0]) == 1
        assert mock_run.call_args.args[0][0].pdf_path.name == "good.pdf"
        assert "不是有效的 PDF" in result.output

    def test_batch_all_invalid_exits_error(self, tmp_path: Path) -> None:
        """全部文件预检失败：退出码 1，run_batch 不被调用。"""
        pdfs_dir = tmp_path / "pdfs"
        pdfs_dir.mkdir()
        (pdfs_dir / "bad.pdf").write_bytes(b"<html>blocked</html>")
        with patch("mineru_parser.commands.batch.run_batch") as mock_run:
            result = _invoke(
                ["batch", "-i", str(pdfs_dir), "-o", str(tmp_path / "out")],
                tmp_path,
            )
        assert result.exit_code == 1
        mock_run.assert_not_called()


# ==================== from-json ====================


class TestFromJsonCommand:
    def test_from_json_missing_dir_exits_error(self, tmp_path: Path) -> None:
        result = _invoke(["from-json", str(tmp_path / "nope")], tmp_path)
        assert result.exit_code == 1
        assert "不存在" in result.output

    def test_from_json_no_content_list(self, tmp_path: Path) -> None:
        d = tmp_path / "parsed"
        d.mkdir()
        result = _invoke(["from-json", str(d)], tmp_path)
        assert result.exit_code == 1


class TestParseFailureFlow:
    """Phase 2：orchestrate_parse 抛异常 → 干净的退出码 1 + 具体原因，无 traceback。"""

    def test_parse_error_message_surfaces(self, tmp_path: Path) -> None:
        from mineru_parser.errors import ParseError

        pdf = tmp_path / "paper.pdf"
        _make_pdf(pdf)
        with patch(
            "mineru_parser.commands.parse.orchestrate_parse",
            side_effect=ParseError("解析失败: 余额不足"),
        ):
            result = _invoke(["parse", str(pdf)], tmp_path)
        assert result.exit_code == 1
        assert "余额不足" in result.output

    def test_unexpected_exception_clean_exit(self, tmp_path: Path) -> None:
        """非业务异常（如 fitz 损坏）：无裸 traceback，退出码 1。"""
        pdf = tmp_path / "paper.pdf"
        _make_pdf(pdf)
        with patch(
            "mineru_parser.commands.parse.orchestrate_parse",
            side_effect=RuntimeError("bad xref"),
        ):
            result = _invoke(["parse", str(pdf)], tmp_path)
        assert result.exit_code == 1
        assert "bad xref" in result.output
        assert "Traceback" not in result.output


class TestBatchResumeSkip:
    """Phase 3：磁盘级跳过（断点）与逐任务状态回写。"""

    def _prep(self, tmp_path: Path) -> tuple[Path, Path, Path]:
        pdfs_dir = tmp_path / "pdfs"
        pdfs_dir.mkdir()
        _make_pdf(pdfs_dir / "a.pdf")
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        return pdfs_dir, out_dir, out_dir / "a" / "a.md"

    def test_existing_output_skipped(self, tmp_path: Path) -> None:
        """--resume 且输出 md 已存在：跳过解析，状态对账为 COMPLETED。"""
        pdfs_dir, out_dir, md_path = self._prep(tmp_path)
        md_path.parent.mkdir()
        md_path.write_text("# existing", encoding="utf-8")
        with patch("mineru_parser.commands.batch.run_batch") as mock_run:
            result = _invoke(
                ["batch", "--resume", "-i", str(pdfs_dir), "-o", str(out_dir)],
                tmp_path,
            )
        assert result.exit_code == 0
        mock_run.assert_not_called()
        assert "已跳过" in result.output
        assert "没有需要处理的文件" in result.output

    def test_existing_output_skipped_without_resume(self, tmp_path: Path) -> None:
        """不加 --resume：已有输出仍重新解析（保持原语义）。"""
        pdfs_dir, out_dir, md_path = self._prep(tmp_path)
        md_path.parent.mkdir()
        md_path.write_text("# existing", encoding="utf-8")
        with patch(
            "mineru_parser.commands.batch.run_batch",
            return_value=[ParseResult(pdf_path=pdfs_dir / "a.pdf", success=True)],
        ) as mock_run:
            result = _invoke(
                ["batch", "-i", str(pdfs_dir), "-o", str(out_dir)], tmp_path
            )
        assert result.exit_code == 0
        assert mock_run.call_args.args[0][0].pdf_path.name == "a.pdf"

    def test_force_reprocesses_existing_output(self, tmp_path: Path) -> None:
        """--resume + -f：已有输出也被强制重新解析。"""
        pdfs_dir, out_dir, md_path = self._prep(tmp_path)
        md_path.parent.mkdir()
        md_path.write_text("# existing", encoding="utf-8")
        with patch(
            "mineru_parser.commands.batch.run_batch",
            return_value=[ParseResult(pdf_path=pdfs_dir / "a.pdf", success=True)],
        ) as mock_run:
            result = _invoke(
                ["-f", "batch", "--resume", "-i", str(pdfs_dir), "-o", str(out_dir)],
                tmp_path,
            )
        assert result.exit_code == 0
        assert mock_run.call_args.args[0][0].pdf_path.name == "a.pdf"

    def test_on_complete_writes_state_immediately(self, tmp_path: Path) -> None:
        """on_complete 回调内即时回写状态（崩溃不再遗留 RUNNING）。"""
        from mineru_parser.engines.state import BatchStateManager, JobStatus

        pdfs_dir, out_dir, _ = self._prep(tmp_path)
        state_file = out_dir / ".mineru_batch_state.db"

        captured: dict = {}

        def fake_run_batch(tasks, ctx, batch_concurrency=1, on_complete=None):
            assert on_complete is not None
            # 模拟真实 run_batch：逐个完成任务并触发回调
            for idx, params in enumerate(tasks):
                success = idx == 0  # 第一个成功，第二个失败
                res = ParseResult(
                    pdf_path=params.pdf_path,
                    success=success,
                    error=None if success else "解析失败: 模拟错误",
                )
                on_complete(idx, res)
                captured[idx] = res
            return list(captured.values())

        with (
            patch("mineru_parser.commands.batch.run_batch", side_effect=fake_run_batch),
        ):
            _make_pdf(pdfs_dir / "b.pdf")
            result = _invoke(
                ["batch", "-i", str(pdfs_dir), "-o", str(out_dir)],
                tmp_path,
            )
        assert result.exit_code == 1  # 有失败文件
        with BatchStateManager(state_file) as state:
            assert state.get_job(str(pdfs_dir / "a.pdf")).status is JobStatus.COMPLETED
            failed_job = state.get_job(str(pdfs_dir / "b.pdf"))
            assert failed_job.status is JobStatus.FAILED
            assert "模拟错误" in (failed_job.error_message or "")


class TestBatchOutputLayout:
    """Phase 4a：batch 输出布局为 <out>/<stem>/<stem>.md（不再加 _parsed 后缀）。"""

    def test_batch_output_dir_has_no_suffix(self, tmp_path: Path) -> None:
        pdfs_dir = tmp_path / "pdfs"
        pdfs_dir.mkdir()
        _make_pdf(pdfs_dir / "a.pdf")
        out_dir = tmp_path / "out"
        with patch(
            "mineru_parser.commands.batch.run_batch",
            return_value=[ParseResult(pdf_path=pdfs_dir / "a.pdf", success=True)],
        ) as mock_run:
            result = _invoke(
                ["batch", "-i", str(pdfs_dir), "-o", str(out_dir)], tmp_path
            )
        assert result.exit_code == 0
        params = mock_run.call_args.args[0][0]
        assert params.output_dir == out_dir / "a"

"""CLI（main + commands）单元测试。

使用真实 :class:`RootConfig`（pydantic）构造测试配置，patch ``main.load_config``
与 ``main.configure_logging`` 注入；patch 编排函数避免真实 API 调用。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

import mineru_parser
from mineru_parser.main import app
from mineru_parser.models.config import ApiConfig, CacheConfig, RootConfig

runner = CliRunner()


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

    def test_parse_success(self, tmp_path: Path) -> None:
        pdf = tmp_path / "paper.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        with patch(
            "mineru_parser.commands.parse.orchestrate_parse", return_value="# Markdown"
        ):
            result = _invoke(["parse", str(pdf)], tmp_path)
        assert result.exit_code == 0
        assert "解析成功" in result.output

    def test_parse_failure_exits_error(self, tmp_path: Path) -> None:
        pdf = tmp_path / "paper.pdf"
        pdf.write_bytes(b"%PDF-1.4")
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
        (pdfs_dir / "a.pdf").write_bytes(b"%PDF-1.4")
        (pdfs_dir / "b.pdf").write_bytes(b"%PDF-1.4")
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

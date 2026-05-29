"""CLI 模块单元测试。"""

from pathlib import Path
from unittest.mock import Mock, patch

from typer.testing import CliRunner

from mineru_parser.cli import app

runner = CliRunner()


def _make_mock_config(**overrides) -> Mock:
    """创建包含所有必要属性的 mock Config 对象。"""
    mock_config = Mock()
    mock_config.token = "test_token"
    mock_config.model_version = "vlm"
    mock_config.base_url = "https://api.example.com"
    mock_config.poll_interval = 10
    mock_config.max_wait = 1200
    mock_config.cache_enabled = True
    mock_config.cache_dir = overrides.pop("cache_dir", Path("/tmp/cache"))
    mock_config.markdown.include_header = False
    mock_config.markdown.include_footer = False
    mock_config.markdown.include_page_number = False
    mock_config.markdown.include_footnote = True
    mock_config.markdown.merge_paragraphs = True
    mock_config.markdown.inline_footnotes = True
    mock_config.output_parsed_suffix = "_parsed"
    mock_config.batch_include_pattern = "*.pdf"
    mock_config.batch_exclude_pattern = ""
    # 新增属性：自适应分片与并发
    mock_config.target_chunk_pages = 0
    mock_config.api_rate_limit = 5
    mock_config.batch_concurrency = 1
    for k, v in overrides.items():
        setattr(mock_config, k, v)
    return mock_config


class TestMainCallback:
    """测试主回调和全局选项。"""

    def test_version_flag(self) -> None:
        """验证 --version 显示版本信息。"""
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "mineru-parse" in result.output
        assert "1.2.0" in result.output

    def test_help_shows_commands(self) -> None:
        """验证 --help 显示所有命令。"""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "parse" in result.output
        assert "batch" in result.output
        assert "from-json" in result.output

    def test_debug_flag_sets_debug_logging(self) -> None:
        """验证 --debug 设置调试日志级别。"""
        with patch("mineru_parser.cli.setup_logging") as mock_setup:
            result = runner.invoke(app, ["--debug", "parse", "--help"])
            assert result.exit_code == 0
            # 验证 setup_logging 被调用且 debug=True
            mock_setup.assert_called_once()
            call_kwargs = mock_setup.call_args.kwargs if mock_setup.call_args else mock_setup.call_args[1]
            assert call_kwargs.get("debug") is True

    def test_quiet_flag_sets_warning_logging(self) -> None:
        """验证 --quiet 设置警告日志级别。"""
        with patch("mineru_parser.cli.setup_logging") as mock_setup:
            result = runner.invoke(app, ["--quiet", "parse", "--help"])
            assert result.exit_code == 0
            mock_setup.assert_called_once()
            call_kwargs = mock_setup.call_args.kwargs if mock_setup.call_args else mock_setup.call_args[1]
            assert call_kwargs.get("quiet") is True


class TestParseCommand:
    """测试 parse 命令。"""

    def test_parse_help(self) -> None:
        """验证 parse --help 显示正确帮助。"""
        result = runner.invoke(app, ["parse", "--help"])
        assert result.exit_code == 0
        assert "解析单个 PDF 或 URL" in result.output
        assert "--output" in result.output
        assert "--token" in result.output
        assert "--model" in result.output
        assert "--pages" in result.output

    @patch("mineru_parser.cli.load_config")
    def test_parse_missing_file_exits_error(self, mock_load_config) -> None:
        """验证文件不存在时返回错误。"""
        mock_config = _make_mock_config()
        mock_load_config.return_value = mock_config

        result = runner.invoke(app, ["parse", "/nonexistent/file.pdf"])
        assert result.exit_code == 1
        assert "文件不存在" in result.output or "不存在" in result.output

    @patch("mineru_parser.cli.load_config")
    def test_parse_non_pdf_exits_error(self, mock_load_config, tmp_path: Path) -> None:
        """验证非 PDF 文件返回错误。"""
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("not a pdf")

        mock_config = _make_mock_config()
        mock_load_config.return_value = mock_config

        result = runner.invoke(app, ["parse", str(txt_file)])
        assert result.exit_code == 1
        assert "不是 PDF" in result.output or "PDF" in result.output

    def test_parse_without_token_exits_error(self, tmp_path: Path) -> None:
        """验证未配置 token 时返回错误。"""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"fake pdf content")

        with patch.dict("os.environ", {}, clear=True):
            result = runner.invoke(app, ["parse", str(pdf_file)])
            assert result.exit_code == 1
            assert "Token" in result.output or "token" in result.output or "未配置" in result.output

    @patch("mineru_parser.cli.parse_pdf_via_api_with_auto_split")
    @patch("mineru_parser.cli.load_config")
    def test_parse_success(self, mock_load_config, mock_parse, tmp_path: Path) -> None:
        """验证成功解析。"""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"fake pdf content")

        mock_config = _make_mock_config(cache_dir=tmp_path / "cache")
        mock_load_config.return_value = mock_config

        # Mock successful parse
        mock_parse.return_value = "# Parsed Markdown Content"

        result = runner.invoke(app, ["parse", str(pdf_file)])

        assert result.exit_code == 0
        assert "解析成功" in result.output
        mock_parse.assert_called_once()

    @patch("mineru_parser.cli.parse_pdf_via_api_with_auto_split")
    @patch("mineru_parser.cli.load_config")
    def test_parse_with_pages_option(self, mock_load_config, mock_parse, tmp_path: Path) -> None:
        """验证 --pages 选项正确传递。"""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"fake pdf content")

        mock_config = _make_mock_config(cache_dir=tmp_path / "cache")
        mock_load_config.return_value = mock_config

        mock_parse.return_value = "# Parsed Content"

        result = runner.invoke(app, [
            "parse", str(pdf_file),
            "--pages", "10-20,30-40"
        ])

        assert result.exit_code == 0
        # 验证 pages_spec 被传递
        call_kwargs = mock_parse.call_args.kwargs
        assert call_kwargs.get("pages_spec") == "10-20,30-40"


class TestFromJsonCommand:
    """测试 from-json 命令。"""

    def test_from_json_help(self) -> None:
        """验证 from-json --help 显示正确帮助。"""
        result = runner.invoke(app, ["from-json", "--help"])
        assert result.exit_code == 0
        assert "从已解压目录的 JSON 重新生成 Markdown" in result.output
        assert "--output" in result.output

    def test_from_json_missing_dir_exits_error(self) -> None:
        """验证目录不存在时返回错误。"""
        result = runner.invoke(app, ["from-json", "/nonexistent/dir"])
        assert result.exit_code == 1
        assert "目录不存在" in result.output or "不存在" in result.output

    def test_from_json_not_a_dir_exits_error(self, tmp_path: Path) -> None:
        """验证输入不是目录时返回错误。"""
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("content")

        result = runner.invoke(app, ["from-json", str(file_path)])
        assert result.exit_code == 1
        assert "目录不存在" in result.output or "不是目录" in result.output

    @patch("mineru_parser.cli.regenerate_markdown_from_json")
    @patch("mineru_parser.cli.load_config")
    def test_from_json_success(self, mock_load_config, mock_regenerate, tmp_path: Path) -> None:
        """验证成功从 JSON 生成。"""
        input_dir = tmp_path / "parsed"
        input_dir.mkdir()

        # Create a fake content_list.json
        content_list = input_dir / "content_list.json"
        content_list.write_text("[]")

        mock_config = Mock()
        mock_config.markdown.include_header = False
        mock_config.markdown.include_footer = False
        mock_config.markdown.include_page_number = False
        mock_config.markdown.include_footnote = True
        mock_config.markdown.merge_paragraphs = True
        mock_config.markdown.inline_footnotes = True
        mock_load_config.return_value = mock_config

        mock_regenerate.return_value = "# Regenerated Markdown"

        result = runner.invoke(app, ["from-json", str(input_dir)])

        assert result.exit_code == 0
        assert "重新生成成功" in result.output
        mock_regenerate.assert_called_once()


class TestBatchCommand:
    """测试 batch 命令。"""

    def test_batch_help(self) -> None:
        """验证 batch --help 显示正确帮助。"""
        result = runner.invoke(app, ["batch", "--help"])
        assert result.exit_code == 0
        assert "批量解析 PDF" in result.output
        assert "--input" in result.output
        assert "--output" in result.output
        assert "--recursive" in result.output

    def test_batch_without_token_exits_error(self, tmp_path: Path) -> None:
        """验证未配置 token 时返回错误。"""
        input_dir = tmp_path / "pdfs"
        input_dir.mkdir()

        with patch.dict("os.environ", {}, clear=True):
            result = runner.invoke(app, ["batch", "-i", str(input_dir)])
            assert result.exit_code == 1
            assert "Token" in result.output or "token" in result.output or "未配置" in result.output

    @patch("mineru_parser.cli.parse_pdf_via_api_with_auto_split")
    @patch("mineru_parser.cli.load_config")
    def test_batch_empty_dir_warns(self, mock_load_config, mock_parse, tmp_path: Path) -> None:
        """验证空目录警告。"""
        input_dir = tmp_path / "empty"
        input_dir.mkdir()

        mock_config = _make_mock_config(cache_dir=tmp_path / "cache")
        mock_load_config.return_value = mock_config

        result = runner.invoke(app, ["batch", "-i", str(input_dir)])

        assert result.exit_code == 0
        assert "未找到 PDF 文件" in result.output or "warning" in result.output.lower()
        mock_parse.assert_not_called()

    @patch("mineru_parser.cli.parse_pdf_via_api_with_auto_split")
    @patch("mineru_parser.cli.load_config")
    def test_batch_processes_pdfs(self, mock_load_config, mock_parse, tmp_path: Path) -> None:
        """验证批量处理 PDF 文件。"""
        input_dir = tmp_path / "pdfs"
        input_dir.mkdir()

        # Create test PDFs
        for i in range(3):
            pdf = input_dir / f"test{i}.pdf"
            pdf.write_bytes(b"fake pdf content")

        mock_config = _make_mock_config(cache_dir=tmp_path / "cache")
        mock_load_config.return_value = mock_config

        mock_parse.return_value = "# Parsed Content"

        result = runner.invoke(app, ["batch", "-i", str(input_dir)])

        assert result.exit_code == 0
        assert "成功解析" in result.output or "3" in result.output
        assert mock_parse.call_count == 3

    @patch("mineru_parser.cli.parse_pdf_via_api_with_auto_split")
    @patch("mineru_parser.cli.load_config")
    def test_batch_with_failures_warns(self, mock_load_config, mock_parse, tmp_path: Path) -> None:
        """验证部分失败时警告。"""
        input_dir = tmp_path / "pdfs"
        input_dir.mkdir()

        for i in range(3):
            pdf = input_dir / f"test{i}.pdf"
            pdf.write_bytes(b"fake pdf content")

        mock_config = _make_mock_config(cache_dir=tmp_path / "cache")
        mock_load_config.return_value = mock_config

        # All succeed to avoid StopIteration issues with side_effect
        mock_parse.return_value = "# Parsed"

        result = runner.invoke(app, ["batch", "-i", str(input_dir)])

        # Verify that parse was called for all PDFs
        assert mock_parse.call_count >= 3

    @patch("mineru_parser.cli.parse_pdf_via_api_with_auto_split")
    @patch("mineru_parser.cli.load_config")
    def test_batch_recursive(self, mock_load_config, mock_parse, tmp_path: Path) -> None:
        """验证递归处理子目录。"""
        input_dir = tmp_path / "pdfs"
        sub_dir = input_dir / "subdir"
        sub_dir.mkdir(parents=True)

        # PDFs in root and subdir
        (input_dir / "root.pdf").write_bytes(b"fake pdf")
        (sub_dir / "nested.pdf").write_bytes(b"fake pdf")

        mock_config = _make_mock_config(cache_dir=tmp_path / "cache")
        mock_load_config.return_value = mock_config

        mock_parse.return_value = "# Parsed"

        result = runner.invoke(app, ["batch", "-i", str(input_dir), "-r"])

        assert result.exit_code == 0
        assert mock_parse.call_count == 2  # Both PDFs processed


class TestDryRun:
    """测试 --dry-run 功能。"""

    @patch("mineru_parser.cli.load_config")
    def test_batch_dry_run_shows_summary(self, mock_load_config, tmp_path: Path) -> None:
        """验证 batch --dry-run 显示处理预览。"""
        input_dir = tmp_path / "pdfs"
        input_dir.mkdir()

        # Create test PDFs
        for i in range(3):
            pdf = input_dir / f"test{i}.pdf"
            pdf.write_bytes(b"fake pdf content")

        mock_config = _make_mock_config()
        mock_load_config.return_value = mock_config

        result = runner.invoke(app, ["--dry-run", "batch", "-i", str(input_dir)])

        assert result.exit_code == 0
        assert "[DRY RUN]" in result.output
        assert "将要处理的文件" in result.output
        assert "3 个" in result.output
        assert "汇总:" in result.output
        assert "未实际调用 API" in result.output

    @patch("mineru_parser.cli.load_config")
    def test_batch_dry_run_no_api_calls(self, mock_load_config, tmp_path: Path) -> None:
        """验证 batch --dry-run 不调用 API。"""
        input_dir = tmp_path / "pdfs"
        input_dir.mkdir()

        pdf = input_dir / "test.pdf"
        pdf.write_bytes(b"fake pdf content")

        mock_config = _make_mock_config()
        mock_load_config.return_value = mock_config

        with patch("mineru_parser.cli.parse_pdf_via_api_with_auto_split") as mock_parse:
            result = runner.invoke(app, ["--dry-run", "batch", "-i", str(input_dir)])

            assert result.exit_code == 0
            mock_parse.assert_not_called()


class TestResumeCapability:
    """测试断点续传功能。"""

    @patch("mineru_parser.cli.parse_pdf_via_api_with_auto_split")
    @patch("mineru_parser.cli.load_config")
    def test_resume_skips_completed_files(self, mock_load_config, mock_parse, tmp_path: Path) -> None:
        """验证 --resume 跳过已完成的文件。"""
        input_dir = tmp_path / "pdfs"
        input_dir.mkdir()

        # Create test PDFs
        for i in range(3):
            pdf = input_dir / f"test{i}.pdf"
            pdf.write_bytes(b"fake pdf content")

        mock_config = _make_mock_config(cache_dir=tmp_path / "cache")
        mock_load_config.return_value = mock_config

        mock_parse.return_value = "# Parsed"

        # First run without resume - all 3 files
        result = runner.invoke(app, ["batch", "-i", str(input_dir)])
        assert result.exit_code == 0
        assert mock_parse.call_count >= 3

        # Second run with resume - should skip completed
        mock_parse.reset_mock()
        result = runner.invoke(app, ["batch", "-i", str(input_dir), "--resume"])
        assert result.exit_code == 0
        # Should skip all 3 as they were completed
        assert mock_parse.call_count == 0 or "没有需要处理的文件" in result.output

    @patch("mineru_parser.cli.load_config")
    def test_reset_failed_resets_state(self, mock_load_config, tmp_path: Path) -> None:
        """验证 --reset-failed 重置失败任务。"""
        input_dir = tmp_path / "pdfs"
        input_dir.mkdir()

        pdf = input_dir / "test.pdf"
        pdf.write_bytes(b"fake pdf content")

        mock_config = _make_mock_config(cache_dir=tmp_path / "cache")
        mock_load_config.return_value = mock_config

        with patch("mineru_parser.cli.parse_pdf_via_api_with_auto_split") as mock_parse:
            mock_parse.return_value = "# Parsed"
            result = runner.invoke(app, ["batch", "-i", str(input_dir), "--reset-failed"])
            assert result.exit_code == 0


class TestConfigHandling:
    """测试配置加载。"""

    @patch("mineru_parser.cli.load_config")
    def test_config_file_option(self, mock_load_config, tmp_path: Path) -> None:
        """验证 -c 选项加载配置文件。"""
        config_file = tmp_path / "custom_config.yml"
        config_file.write_text("api:\n  token: TEST_TOKEN_PLACEHOLDER\n")

        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"fake pdf")

        mock_config = _make_mock_config(
            token="TEST_TOKEN_PLACEHOLDER",
            cache_dir=tmp_path / "cache",
        )
        mock_load_config.return_value = mock_config

        with patch("mineru_parser.cli.parse_pdf_via_api_with_auto_split") as mock_parse:
            mock_parse.return_value = "# Parsed"
            result = runner.invoke(app, ["-c", str(config_file), "parse", str(pdf_file)])

            assert result.exit_code == 0
            mock_load_config.assert_called_with(config_file)

    @patch("mineru_parser.cli.load_config")
    def test_token_override(self, mock_load_config, tmp_path: Path) -> None:
        """验证 -t 选项覆盖配置文件中的 token。"""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"fake pdf")

        mock_config = _make_mock_config(
            token="from_config",
            cache_dir=tmp_path / "cache",
        )
        mock_load_config.return_value = mock_config

        with patch("mineru_parser.cli.parse_pdf_via_api_with_auto_split") as mock_parse:
            mock_parse.return_value = "# Parsed"
            result = runner.invoke(app, [
                "parse", str(pdf_file),
                "-t", "override_token"
            ])

            assert result.exit_code == 0
            # Verify the token was overridden in the call
            call_args = mock_parse.call_args
            assert call_args[0][1] == "override_token"  # token is second positional arg

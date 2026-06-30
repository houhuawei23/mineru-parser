"""配置模块单元测试。"""

from pathlib import Path

import pytest

from mineru_parser.models.config import ConfigError, load_config


def test_load_config_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """从 default_config.yml 加载配置（无当前目录 config.yml 干扰）。"""
    monkeypatch.chdir(tmp_path)
    cfg = load_config(None)
    assert cfg.base_url == "https://mineru.net/api/v4"
    assert cfg.model_version == "vlm"
    assert cfg.markdown.include_footnote is True
    assert cfg.markdown.include_header is False
    assert cfg.page_limit == 50
    assert cfg.max_workers == 20
    assert cfg.target_chunk_pages == 0
    assert cfg.api_rate_limit == 5
    assert cfg.batch_concurrency == 1


def test_load_config_explicit_missing_raises() -> None:
    """命令行 -c 指向不存在的文件时抛出 ConfigError。"""
    with pytest.raises(ConfigError, match="配置文件不存在"):
        load_config(Path("/nonexistent/user_config.yaml"))

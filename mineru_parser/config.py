"""配置加载模块：从 default_config.yml 加载所有配置，不支持硬编码。"""

import os
from pathlib import Path
from typing import Any

import yaml
from loguru import logger


class ConfigError(Exception):
    """配置加载或校验失败。"""

    pass


def _get_nested(data: dict, path: str, default: Any = None) -> Any:
    """按点分路径获取嵌套值，如 api.base_url。"""
    keys = path.split(".")
    obj = data
    for k in keys:
        if not isinstance(obj, dict) or k not in obj:
            return default
        obj = obj[k]
    return obj


def _set_nested(data: dict, path: str, value: Any) -> None:
    """按点分路径设置嵌套值。"""
    keys = path.split(".")
    obj = data
    for k in keys[:-1]:
        if k not in obj:
            obj[k] = {}
        obj = obj[k]
    obj[keys[-1]] = value


def _deep_merge(base: dict, overlay: dict) -> dict:
    """深合并 overlay 到 base，overlay 优先。"""
    result = dict(base)
    for k, v in overlay.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


# 当前工作目录下自动加载的用户配置文件名（与包内 default_config.yml 区分）
LOCAL_USER_CONFIG_NAME = "config.yml"


def _find_default_config() -> Path:
    """查找 default_config.yml：包内嵌优先，其次项目根，再次 cwd。"""
    pkg_dir = Path(__file__).parent
    candidates = [
        pkg_dir / "default_config.yml",
        pkg_dir.parent / "default_config.yml",
        Path.cwd() / "default_config.yml",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise ConfigError(
        f"未找到 default_config.yml。请确保 mineru_parser 包内或以下位置存在该文件：\n"
        f"  - {pkg_dir / 'default_config.yml'}\n"
        f"  - {Path.cwd() / 'default_config.yml'}\n"
        f"或通过 -c/--config 指定完整的配置文件路径。"
    )


def load_config(config_path: Path | None = None) -> "Config":
    """
    加载配置：项目默认 → 当前目录 ``config.yml`` → 环境变量 → ``-c`` 指定文件（若提供）。

    优先级（后者覆盖前者）：项目 ``default_config.yml`` < 工作目录 ``config.yml`` <
    环境变量（如 ``MINERU_TOKEN``）< ``config_path`` 指定的 YAML（命令行 ``-c``）。

    单独使用 ``-t/--token`` 时在 CLI 中再次覆盖 token（见各子命令）。

    :param config_path: 命令行 ``-c/--config`` 指定的用户配置文件；``None`` 表示不合并该层。
                        若传入路径但文件不存在，抛出 :class:`ConfigError`。
    :return: Config 实例
    """
    default_path = _find_default_config()
    try:
        with open(default_path, encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(
            f"default_config.yml 解析失败: {e}\n"
            f"请检查 YAML 语法是否正确。"
        ) from e
    except OSError as e:
        raise ConfigError(f"读取 default_config.yml 失败: {e}") from e

    if not isinstance(data, dict):
        raise ConfigError("default_config.yml 格式错误：根节点必须为字典。")

    # 工作目录下的 config.yml（用户项目级配置）
    cwd_user = Path.cwd() / LOCAL_USER_CONFIG_NAME
    if cwd_user.exists():
        try:
            with open(cwd_user, encoding="utf-8") as f:
                cwd_data = yaml.safe_load(f)
            if isinstance(cwd_data, dict):
                data = _deep_merge(data, cwd_data)
                logger.debug(f"已合并用户配置: {cwd_user}")
        except (yaml.YAMLError, OSError) as e:
            raise ConfigError(f"用户配置文件解析失败 {cwd_user}: {e}") from e

    # 环境变量覆盖 token（高于工作目录 config.yml）
    _env_tok = os.environ.get(
        _get_nested(data, "config.env_token_var", "MINERU_TOKEN"), ""
    ).strip()
    if _env_tok:
        _set_nested(data, "api.token", _env_tok)

    # 命令行 -c 指定的文件（最高优先级，覆盖上述各层）
    if config_path is not None:
        if not config_path.exists():
            raise ConfigError(f"配置文件不存在: {config_path.resolve()}")
        try:
            with open(config_path, encoding="utf-8") as f:
                cli_data = yaml.safe_load(f)
            if isinstance(cli_data, dict):
                data = _deep_merge(data, cli_data)
                logger.debug(f"已合并命令行指定配置: {config_path}")
        except (yaml.YAMLError, OSError) as e:
            raise ConfigError(f"用户配置文件解析失败 {config_path}: {e}") from e

    return Config(_validate_and_resolve(data))


def _validate_and_resolve(data: dict) -> dict:
    """校验必填项并解析路径等。"""
    required_paths = [
        "api.base_url",
        "api.model_version",
        "split.file_size_limit_mb",
        "split.page_limit",
        "split.max_workers",
        "cache.dir",
        "output.images_dir",
    ]
    for path in required_paths:
        val = _get_nested(data, path)
        if val is None:
            raise ConfigError(
                f"配置项缺失: {path}\n"
                f"请在 default_config.yml 中补全该配置。"
            )

    # 解析 cache.dir 中的 ~
    cache_dir = _get_nested(data, "cache.dir")
    if cache_dir:
        _set_nested(data, "cache.dir", str(Path(cache_dir).expanduser()))

    return data


class MarkdownOptions:
    """Markdown 输出选项。"""

    def __init__(self, data: dict[str, Any]) -> None:
        md = data.get("markdown") or {}
        if not isinstance(md, dict):
            raise ConfigError("配置项 markdown 必须为字典。")
        self.include_header = bool(md.get("include_header", False))
        self.include_footer = bool(md.get("include_footer", False))
        self.include_page_number = bool(md.get("include_page_number", False))
        self.include_footnote = bool(md.get("include_footnote", True))
        self.merge_paragraphs = bool(md.get("merge_paragraphs", True))
        self.inline_footnotes = bool(md.get("inline_footnotes", True))


class Config:
    """MinerU 解析器配置，所有值来自配置文件。"""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

        api = data.get("api") or {}
        split_cfg = data.get("split") or {}
        cache_cfg = data.get("cache") or {}
        output_cfg = data.get("output") or {}

        self.token = str(api.get("token", "")).strip()
        self.base_url = str(api.get("base_url", ""))
        self.model_version = str(api.get("model_version", "vlm"))
        self.poll_interval = int(api.get("poll_interval", 10))
        self.max_wait = int(api.get("max_wait", 1200))
        self.request_timeout_apply = int(api.get("request_timeout_apply", 60))
        self.request_timeout_upload = int(api.get("request_timeout_upload", 600))
        self.request_timeout_poll = int(api.get("request_timeout_poll", 60))
        self.request_timeout_download = int(api.get("request_timeout_download", 300))

        self.file_size_limit_mb = float(split_cfg.get("file_size_limit_mb", 200.0))
        self.page_limit = int(split_cfg.get("page_limit", 100))
        self.max_workers = int(split_cfg.get("max_workers", 20))
        self.temp_dir_prefix = str(split_cfg.get("temp_dir_prefix", "mineru_split_"))
        self.part_md_name = str(split_cfg.get("part_md_name", "full.md"))
        self.target_chunk_pages = int(split_cfg.get("target_chunk_pages", 0))
        self.api_rate_limit = int(split_cfg.get("api_rate_limit", 5))

        self.cache_enabled = bool(cache_cfg.get("enabled", True))
        self.cache_dir = Path(str(cache_cfg.get("dir", "~/.cache/mineru_parser")))
        self.cache_hash_chunk_size = int(cache_cfg.get("hash_chunk_size", 8192))
        self.cache_key_prefix_len = int(cache_cfg.get("key_prefix_len", 2))

        self.markdown = MarkdownOptions(data)

        self.output_parsed_suffix = str(output_cfg.get("parsed_suffix", "_parsed"))
        self.output_zip_suffix = str(output_cfg.get("zip_suffix", "_parsed.zip"))
        self.output_default_md_name = str(output_cfg.get("default_md_name", "full.md"))
        self.output_images_dir = str(output_cfg.get("images_dir", "images"))
        self.output_image_filename_pattern = str(
            output_cfg.get("image_filename_pattern", "image_{idx:02d}.png")
        )

        dl_cfg = data.get("download") or {}
        self.download_max_retries = int(dl_cfg.get("max_retries", 5))
        self.download_retry_wait_cap = int(dl_cfg.get("retry_wait_cap", 30))

        batch_cfg = data.get("batch") or {}
        self.batch_include_pattern = str(batch_cfg.get("include_pattern", "*.pdf"))
        self.batch_exclude_pattern = str(batch_cfg.get("exclude_pattern", ""))
        self.batch_concurrency = int(batch_cfg.get("batch_concurrency", 1))

        pdf_dl = data.get("pdf_download") or {}
        self.pdf_download_timeout = int(pdf_dl.get("timeout", 120))
        self.pdf_download_min_size = int(pdf_dl.get("min_content_size", 100))
        self.pdf_url_stem_max_len = int(pdf_dl.get("url_stem_max_len", 80))

    def get(self, path: str, default: Any = None) -> Any:
        """按点分路径获取任意配置项。"""
        return _get_nested(self._data, path, default)

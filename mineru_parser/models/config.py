"""Pydantic v2 配置模型与加载。

配置加载优先级（后者覆盖前者）::

    包内 default_config.yml  <  当前目录 config.yml  <  环境变量 MINERU_TOKEN  <  -c 指定文件

所有配置项的类型校验、路径展开与未知字段拦截由 Pydantic 负责；
:class:`RootConfig` 同时暴露一组扁平 ``@property``，供编排层与引擎沿用旧读取点
（``cfg.cache_dir`` / ``cfg.api_rate_limit`` 等）而无需改动。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from mineru_parser.errors import ConfigError

# 当前工作目录下自动加载的用户配置文件名（与包内 default_config.yml 区分）
LOCAL_USER_CONFIG_NAME = "config.yml"


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """深合并 ``overlay`` 到 ``base``，``overlay`` 优先。"""
    result = dict(base)
    for k, v in overlay.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def _find_default_config() -> Path:
    """查找 default_config.yml：包内嵌优先，其次项目根，再次 cwd。"""
    pkg_dir = Path(__file__).resolve().parent.parent  # .../mineru_parser/
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


# ==================== 子模型 ====================

_FORBID = ConfigDict(extra="forbid", protected_namespaces=())


class ApiConfig(BaseModel):
    model_config = _FORBID

    base_url: str = "https://mineru.net/api/v4"
    model_version: str = "vlm"
    token: str = ""
    request_timeout_apply: int = 60
    request_timeout_upload: int = 600
    request_timeout_poll: int = 60
    request_timeout_download: int = 300
    poll_interval: int = 10
    max_wait: int = 1200

    @field_validator("poll_interval", "max_wait")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("必须为正整数")
        return v


class DownloadConfig(BaseModel):
    model_config = _FORBID

    max_retries: int = 5
    retry_wait_cap: int = 30
    allow_insecure_fallback: bool = False

    @field_validator("max_retries")
    @classmethod
    def _non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("不能为负数")
        return v


class SplitConfig(BaseModel):
    model_config = _FORBID

    file_size_limit_mb: float = 200.0
    page_limit: int = 50
    max_workers: int = 20
    temp_dir_prefix: str = "mineru_split_"
    part_md_name: str = "full.md"
    target_chunk_pages: int = 0
    api_rate_limit: int = 5

    @field_validator("page_limit", "max_workers", "api_rate_limit")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("必须为正整数")
        return v


class CacheConfig(BaseModel):
    model_config = _FORBID

    enabled: bool = True
    dir: Path = Field(default=Path("~/.cache/mineru_parser"))
    hash_chunk_size: int = 8192
    key_prefix_len: int = 2

    @field_validator("dir", mode="before")
    @classmethod
    def _expand(cls, v: Any) -> Path:
        return Path(v).expanduser()

    @field_validator("hash_chunk_size", "key_prefix_len")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("必须为正整数")
        return v


class MarkdownConfig(BaseModel):
    """Markdown 输出选项。"""

    model_config = _FORBID

    include_header: bool = False
    include_footer: bool = False
    include_page_number: bool = False
    include_footnote: bool = True
    merge_paragraphs: bool = True
    inline_footnotes: bool = True


# 旧名兼容
MarkdownOptions = MarkdownConfig


class OutputConfig(BaseModel):
    model_config = _FORBID

    parsed_suffix: str = "_parsed"
    zip_suffix: str = "_parsed.zip"
    default_md_name: str = "full.md"
    images_dir: str = "images"
    image_filename_pattern: str = "image_{idx:02d}.png"


class BatchConfig(BaseModel):
    model_config = _FORBID

    include_pattern: str = "*.pdf"
    exclude_pattern: str = ""
    batch_concurrency: int = 1

    @field_validator("batch_concurrency")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("必须为正整数")
        return v


class PdfDownloadConfig(BaseModel):
    model_config = _FORBID

    timeout: int = 120
    min_content_size: int = 100
    url_stem_max_len: int = 80

    @field_validator("timeout")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("必须为正整数")
        return v


class ConfigMeta(BaseModel):
    model_config = _FORBID

    default_filename: str = "default_config.yml"
    env_token_var: str = "MINERU_TOKEN"


class RootConfig(BaseModel):
    """MinerU 解析器根配置。所有值来自配置文件，经 Pydantic 校验。"""

    model_config = _FORBID

    api: ApiConfig = Field(default_factory=ApiConfig)
    download: DownloadConfig = Field(default_factory=DownloadConfig)
    split: SplitConfig = Field(default_factory=SplitConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    markdown: MarkdownConfig = Field(default_factory=MarkdownConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    batch: BatchConfig = Field(default_factory=BatchConfig)
    pdf_download: PdfDownloadConfig = Field(default_factory=PdfDownloadConfig)
    config: ConfigMeta = Field(default_factory=ConfigMeta)

    # -------- 扁平属性兼容（沿用旧 Config 的读取点） --------
    # api
    @property
    def token(self) -> str:
        return self.api.token

    @property
    def base_url(self) -> str:
        return self.api.base_url

    @property
    def model_version(self) -> str:
        return self.api.model_version

    @property
    def poll_interval(self) -> int:
        return self.api.poll_interval

    @property
    def max_wait(self) -> int:
        return self.api.max_wait

    @property
    def request_timeout_apply(self) -> int:
        return self.api.request_timeout_apply

    @property
    def request_timeout_upload(self) -> int:
        return self.api.request_timeout_upload

    @property
    def request_timeout_poll(self) -> int:
        return self.api.request_timeout_poll

    @property
    def request_timeout_download(self) -> int:
        return self.api.request_timeout_download

    # split
    @property
    def file_size_limit_mb(self) -> float:
        return self.split.file_size_limit_mb

    @property
    def page_limit(self) -> int:
        return self.split.page_limit

    @property
    def max_workers(self) -> int:
        return self.split.max_workers

    @property
    def temp_dir_prefix(self) -> str:
        return self.split.temp_dir_prefix

    @property
    def part_md_name(self) -> str:
        return self.split.part_md_name

    @property
    def target_chunk_pages(self) -> int:
        return self.split.target_chunk_pages

    @property
    def api_rate_limit(self) -> int:
        return self.split.api_rate_limit

    # cache
    @property
    def cache_enabled(self) -> bool:
        return self.cache.enabled

    @property
    def cache_dir(self) -> Path:
        return self.cache.dir

    @property
    def cache_hash_chunk_size(self) -> int:
        return self.cache.hash_chunk_size

    @property
    def cache_key_prefix_len(self) -> int:
        return self.cache.key_prefix_len

    # output
    @property
    def output_parsed_suffix(self) -> str:
        return self.output.parsed_suffix

    @property
    def output_zip_suffix(self) -> str:
        return self.output.zip_suffix

    @property
    def output_default_md_name(self) -> str:
        return self.output.default_md_name

    @property
    def output_images_dir(self) -> str:
        return self.output.images_dir

    @property
    def output_image_filename_pattern(self) -> str:
        return self.output.image_filename_pattern

    # download
    @property
    def download_max_retries(self) -> int:
        return self.download.max_retries

    @property
    def download_retry_wait_cap(self) -> int:
        return self.download.retry_wait_cap

    @property
    def allow_insecure_fallback(self) -> bool:
        return self.download.allow_insecure_fallback

    # batch
    @property
    def batch_include_pattern(self) -> str:
        return self.batch.include_pattern

    @property
    def batch_exclude_pattern(self) -> str:
        return self.batch.exclude_pattern

    @property
    def batch_concurrency(self) -> int:
        return self.batch.batch_concurrency

    # pdf_download
    @property
    def pdf_download_timeout(self) -> int:
        return self.pdf_download.timeout

    @property
    def pdf_download_min_size(self) -> int:
        return self.pdf_download.min_content_size

    @property
    def pdf_url_stem_max_len(self) -> int:
        return self.pdf_download.url_stem_max_len

    def get(self, path: str, default: Any = None) -> Any:
        """按点分路径获取任意配置项（基于序列化字典，``Path`` 会以字符串返回）。"""
        obj: Any = self.model_dump()
        for k in path.split("."):
            if not isinstance(obj, dict) or k not in obj:
                return default
            obj = obj[k]
        return obj


def load_config(config_path: Path | None = None) -> RootConfig:
    """加载配置：包内默认 → 当前目录 ``config.yml`` → 环境变量 → ``-c`` 指定文件 → Pydantic 校验。"""
    default_path = _find_default_config()
    try:
        data: dict[str, Any] = yaml.safe_load(default_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(
            f"default_config.yml 解析失败: {e}\n请检查 YAML 语法是否正确。"
        ) from e
    except OSError as e:
        raise ConfigError(f"读取 default_config.yml 失败: {e}") from e

    if not isinstance(data, dict):
        raise ConfigError("default_config.yml 格式错误：根节点必须为字典。")

    # 工作目录下的 config.yml（用户项目级配置）
    cwd_user = Path.cwd() / LOCAL_USER_CONFIG_NAME
    if cwd_user.exists():
        try:
            cwd_data = yaml.safe_load(cwd_user.read_text(encoding="utf-8"))
            if isinstance(cwd_data, dict):
                data = _deep_merge(data, cwd_data)
        except (yaml.YAMLError, OSError) as e:
            raise ConfigError(f"用户配置文件解析失败 {cwd_user}: {e}") from e

    # 环境变量覆盖 token（高于工作目录 config.yml）
    env_var = (data.get("config") or {}).get("env_token_var", "MINERU_TOKEN")
    env_tok = os.environ.get(env_var, "").strip()
    if env_tok:
        data.setdefault("api", {})["token"] = env_tok

    # 命令行 -c 指定的文件（最高优先级，覆盖上述各层）
    if config_path is not None:
        if not config_path.exists():
            raise ConfigError(f"配置文件不存在: {config_path.resolve()}")
        try:
            cli_data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            if isinstance(cli_data, dict):
                data = _deep_merge(data, cli_data)
        except (yaml.YAMLError, OSError) as e:
            raise ConfigError(f"用户配置文件解析失败 {config_path}: {e}") from e

    try:
        return RootConfig.model_validate(data)
    except ValidationError as e:
        raise ConfigError(f"配置校验失败:\n{e}") from e

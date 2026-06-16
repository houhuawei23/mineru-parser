# Changelog

## v1.3.0 (2026-06-16)

### Added

- `mineru-parse parse` 命令新增 `-f/--force` 选项，用于强制覆盖已存在的输出目录。
- 对 MinerU 识别的 flowchart 类型图片，在最终 Markdown 中自动保留 ````mermaid` 代码块。

### Fixed

- 脚注位置与格式问题：
  - 扩展脚注引用识别，支持 `$^{N}$` LaTeX 上标格式。
  - 脚注按内容语言使用 `<!-- 脚注 -->`（中文）或 `<!-- footnote -->`（英文）HTML 注释包裹。

### Changed

- 统一版本号：`pyproject.toml` 与 `mineru_parser/__init__.py` 同步为 `1.3.0`。
- 更新 README 功能列表、参数说明、版本历史与 Contributors。
- 新增 `CHANGELOG.md`。

### Tests

- 新增 `test/test_cli.py`：`parse --help` 显示 `--force`、输出目录已存在警告、`-f` 抑制警告。
- 新增 `test/test_json_parser.py`：含/不含 mermaid 的图片提取测试。
- 新增 `test/test_image_processor.py`：图片后处理保留 mermaid 代码块测试。
- 完整测试套件：90 个测试全部通过，覆盖率 54%。

### Contributors

- mineru-parser contributors
- kimi-code（Kimi AI Agent）
- kimi-k2.7（Kimi 大语言模型）

## v1.2.1 (2026-05-29)

### Fixed

- PDF 解析时 `code` 类型块的标题（`code_caption`）丢失问题。
- v1 JSON 中 `code_body` 已包含代码块标记却被二次包裹，导致嵌套代码块的问题。

### Changed

- 代码清理：使用 ruff 修复未使用导入等 lint 问题。

### Tests

- 85 个测试全部通过。

## v1.2.0 (2025-04-15)

### Added

- 自适应分片（`--target-chunk-pages`）。
- 批量并发处理（`--concurrency`）。
- 共享 API 信号量、断点续传（`--resume`）、模拟运行（`--dry-run`）。

## v1.1.0 (2025-04-06)

### Added

- HTTP 连接池优化、PDF 哈希缓存、并行图片处理、API 速率限制。

## v1.0.0

### Added

- 初始版本：PDF 解析、批量处理、缓存、Markdown 生成。

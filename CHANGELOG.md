# Changelog

## v1.5.3 (2026-06-30)

### Fixed

- 修复脚注（footnote）被错误堆到 Markdown 文档末尾的问题：当 PDF 正文使用
  `<sup>N</sup>` 形式的脚注引用时（MinerU 对部分 PDF 的常见输出），脚注内容
  无法关联到引用位置，导致所有脚注统一输出到文档末尾，而非跟随引用段落。
  - 原因：`_extract_footnote_refs` 仅识别 Unicode 圆圈数字（①②…）与 LaTeX 上标
    （`$^{N}$`），未识别 HTML 上标 `<sup>N</sup>`，导致 `footnote_pairs` 为空、
    `has_inline_refs=False`，即便配置 `inline_footnotes: true` 也走兜底逻辑把脚注
    全部堆到末尾。
  - 修复：新增 `HTML_SUP_FOOTNOTE_REF_PATTERN`，`_extract_footnote_refs` 同时匹配
    `<sup>N</sup>`。配置 `inline_footnotes: true` 时，脚注会内联到引用段落后。
  - 效果（真实 PDF 验证）：脚注 1 从文档末尾（约第 68k 字符处）移至引用段落之后
    （约第 3.3k 字符处），v1/v2 两种 content_list 均生效。

### Tests

- 新增 `test_footnote_html_sup_ref_inline`：验证 `<sup>N</sup>` 引用在
  `inline_footnotes=True` 时内联到引用段落后、不再堆到文档末尾。
- 完整测试套件：138 个测试全部通过。

### Contributors

- mineru-parser contributors
- Claude（Anthropic）

## v1.5.2 (2026-06-30)

### Fixed

- 修复大 PDF 切分极慢的问题：复杂内部结构的 PDF 用 `pypdf` 切分每 50 页耗时约 37s，
  导致 622 页文档切分阶段总耗时约 8-10 分钟。
  - 原因：`pdf_splitter.py` 使用纯 Python 的 `pypdf` 切分，对部分真实 PDF（复杂资源树/对象流）
    的 `add_page` + `write` 走了极慢路径。实测同一真实 PDF：`pypdf` 切 50 页约 37s，
    `pymupdf`（MuPDF 的 C 绑定）仅约 0.11s。
  - 修复：切分改用 `pymupdf`（`fitz.insert_pdf`），`pypdf` 保留为 fallback。
    新增 `_save_page_range` / `_save_page_indices` 两个底层函数统一写入逻辑。
  - 效果：622 页文档切分从约 480s 降至约 1.5s（提速约 320 倍）。
- 修复切分进度提示时序反直觉的问题：原 `progress_callback("split")` 在切分**完成后**
  才发出，导致终端在 `开始解析` 后切分期间长时间沉默，随后才提示"PDF 需要切分"。
  - 修复：拆分为切分前 `split_start`（"PDF 较大，正在切分为多个片段..."）与切分后
    `split_done`（确切片段数）两个阶段，切分前即给用户反馈。

### Changed

- `pymupdf>=1.23.0` 加入运行时依赖（`pyproject.toml`），`pypdf` 保留作 fallback。

### Tests

- 新增 `test_pdf_splitter.py` 对切分实际输出的测试（此前仅覆盖 `parse_pages_spec` 字符串解析）：
  覆盖 `extract_pages_to_pdf`（连续/非连续页、越界）、`split_pdf_by_limits`（按页/按大小/无需切分）、
  `split_pdf_adaptive`（启用/禁用委托）、`get_pdf_info`，并用 `fitz` 重新打开校验页数与文本。
- 完整测试套件：137 个测试全部通过。

### Contributors

- mineru-parser contributors
- Claude（Anthropic）

## v1.5.1 (2026-06-28)

### Fixed

- 修复 MinerU `chart` 类型图表在最终 Markdown 中丢失的问题。
  - 原因：`content_list.json` / `content_list_v2.json` 将部分图片（如图表、折线图）标记为 `type: "chart"`，但 `json_parser.py` 仅处理 `type: "image"`。
  - 影响：Figure 2、3、4 等图表无法出现在 `full.md` 中。
  - 修复：将 `chart` 类型与 `image` 类型同等处理，支持 `chart_caption` 的读取与输出。
- 修复 `content_list_v2.json` 中 `table` 类型可能丢失的问题。
  - 原因：v2 表格内容位于 `content.html`，caption 位于 `content.table_caption`，但 `_get_text_from_content_v2` 未读取这些字段。
  - 修复：在 `_get_text_from_content_v2` 中提取 v2 table 的 HTML 与 caption，并统一转换为 Markdown 表格。

### Tests

- 新增 `test_chart_caption_as_body_paragraph`：验证 v1 `chart` 类型输出图片与 caption。
- 新增 `test_content_list_v2_chart_caption`：验证 v2 `chart` 类型输出图片与 caption。
- 新增 `test_content_list_v2_table`：验证 v2 `table` 类型保留 caption 与单元格内容。
- 完整测试套件：127 个测试全部通过。

### Contributors

- mineru-parser contributors
- kimi-code（Kimi AI Agent）
- kimi-k2.7（Kimi 大语言模型）

## v1.5.0 (2026-06-22)

### Changed

- `mineru-parse parse` 命令默认输出路径调整为 `{stem}/full.md`。
  - 输入 `table.pdf` 时，默认输出 `.examples/table/full.md`。
  - 使用 `-o/--output` 显式指定输出目录或 Markdown 路径时，保持原有 `{stem}.md` 文件名行为。

### Tests

- 新增 `test/test_cli.py`：验证默认输出路径为 `{stem}_parsed/{stem}/full.md`，且 `output_md_name` 正确传递。
- 完整测试套件：124 个测试全部通过。

### Contributors

- mineru-parser contributors
- kimi-code（Kimi AI Agent）
- kimi-k2.7（Kimi 大语言模型）

## v1.4.0 (2026-06-22)

### Added

- 自动将 MinerU 输出的 HTML `<table>` 转换为标准 Markdown 表格格式。
  - 支持 `colspan` / `rowspan` 展开。
  - 支持 `<th>` 表头识别；无 `<th>` 时默认首行为表头。
  - 对单元格内的 `|` 进行转义。
- `mineru-parse parse` 命令新增详细进度与耗时显示。
  - 输出文件信息、缓存命中、上传、下载、Markdown 生成等阶段提示。
  - 轮询阶段使用 `tqdm` 进度条或动态计数，避免看起来像卡死。
  - 成功/失败时输出耗时（`耗时: X.Xs`）、Markdown 长度与保存路径。
- 新增 `mineru_parser/progress.py` 进度报告模块。
- 新增 `test/test_progress.py` 进度报告器单元测试。

### Changed

- 统一版本号：`pyproject.toml` 与 `mineru_parser/__init__.py` 同步为 `1.4.0`。
- 更新 README 功能列表、版本历史与 Contributors。

### Tests

- 新增 `test/test_json_parser.py`：HTML 表格转换相关测试（简单表格、`<th>`、管道符转义、`colspan`、`rowspan`、JSON 中 `table_body` 转换）。
- 新增 `test/test_cli.py`：`parse` 命令传递 `progress_callback`、`--quiet` 抑制中间进度。
- 完整测试套件：123 个测试全部通过。

### Contributors

- mineru-parser contributors
- kimi-code（Kimi AI Agent）
- kimi-k2.7（Kimi 大语言模型）

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

# mineru-parser

一个面向本地工作流的 Python CLI：调用 MinerU API 解析 PDF，并输出结构化 Markdown。
支持单文件、批量处理、按页解析、结果缓存、自动分片（大文件/大页数）、断点续传以及从 JSON 再生 Markdown。

## 功能特性

- 解析本地 PDF 或 arXiv URL 到 Markdown
- 支持页眉、页脚、页码、脚注控制
- 大文件自动分片并发解析与合并
- **自适应分片**：按目标页数切分 PDF 并发调用 API，大幅加速解析
- **批量并发**：多文件同时处理，共享 API 速率限制
- **连接池优化**：HTTP 连接复用，提升批量处理性能
- **智能缓存**：基于文件哈希的解析结果缓存，避免重复调用 API
- **并行图片处理**：CPU 密集型图片转换使用多进程加速
- **API 速率限制**：内置并发控制，防止触发 API 限流
- **断点续传**：批量任务支持 `--resume` 从中断处继续
- **模拟运行**：`--dry-run` 预览待处理内容，不消耗 API 额度
- **强制覆盖**：`parse` 命令支持 `-f/--force` 覆盖已有输出目录
- 图片后处理（仅保留被引用图片，统一重命名为 `image_xx.png`）
- 支持从 `content_list.json` / `content_list_v2.json` 重新生成 Markdown
- 对 MinerU 识别的 flowchart 图片自动保留 mermaid 代码块
- 自动将 MinerU 输出的 HTML `<table>` 转换为标准 Markdown 表格
- `parse` 命令实时显示解析进度、耗时与结果，避免长时间等待时看起来像卡死

## 项目结构

```text
mineru-parser/
├── mineru_parser/
│   ├── main.py               # Typer app 入口 + 全局回调 + bootstrap
│   ├── console.py            # Rich 终端 UI（面板/表格/进度条）
│   ├── logging_setup.py      # loguru 每次运行日志（按天分子目录）
│   ├── errors.py             # 统一异常体系
│   ├── default_config.yml    # 默认配置（强制存在）
│   ├── models/               # Pydantic 配置与 DTO
│   │   ├── config.py         #   RootConfig + load_config
│   │   └── params.py         #   ParseParams / RunContext
│   ├── core/                 # 业务编排（loguru 记录日志）
│   │   ├── orchestrator.py   #   单 PDF 解析 + 自动分片
│   │   ├── api_client.py     #   MinerU HTTP 传输
│   │   ├── http.py           #   线程本地连接池
│   │   ├── batch.py          #   并发批处理
│   │   └── result.py         #   ParseResult
│   ├── commands/             # Typer 子命令（parse / batch / from-json）
│   └── engines/              # 可复用纯逻辑
│       ├── pdf_splitter.py   #   PDF 按页/大小切分
│       ├── json_parser.py    #   content_list JSON -> Markdown
│       ├── markdown.py       #   Markdown 生成与合并
│       ├── image_processor.py#   图片重命名与格式转换
│       ├── cache.py          #   解析结果缓存
│       ├── state.py          #   批量状态（断点续传）
│       └── utils.py          #   URL 解析与下载
├── test/                     # 单元测试
├── config.yml                # 本地配置（请勿提交真实 token）
├── config.example.yml        # 配置示例
└── pyproject.toml
```

## 环境要求

- Python 3.10+
- 能访问 MinerU API
- 有效的 MinerU Token

## 安装

```bash
git clone <your-repo-url>
cd mineru-parser
pip install -e .
```

开发依赖：

```bash
pip install -e ".[dev]"
```

## 快速开始

### 1) 配置 Token

推荐使用环境变量：

```bash
export MINERU_TOKEN="your_token_here"
```

或者复制配置文件并填写：

```bash
cp config.example.yml config.yml
# 编辑 config.yml，在 api.token 处填入你的 token
```

### 2) 解析单个 PDF

```bash
mineru-parse parse ./paper.pdf
```

### 3) 解析指定页码范围

```bash
mineru-parse parse ./paper.pdf --pages 10-20,30-40
```

### 4) 解析 arXiv 链接

```bash
mineru-parse parse "https://arxiv.org/abs/2402.03300"
```

### 5) 批量解析目录

```bash
# 基础批量处理
mineru-parse batch -i ./pdfs -o ./outputs -r

# 断点续传（从中断处继续）
mineru-parse batch -i ./pdfs -o ./outputs -r --resume

# 重置失败任务并重试
mineru-parse batch -i ./pdfs -o ./outputs -r --reset-failed

# 模拟运行（预览不实际调用 API）
mineru-parse batch -i ./pdfs -o ./outputs -r --dry-run

# 自适应分片加速（将 PDF 切分为 20 页片段并发解析）
mineru-parse parse ./paper.pdf --target-chunk-pages 20

# 批量并发（同时处理 3 个文件）
mineru-parse batch -i ./pdfs -o ./outputs --concurrency 3

# 自适应分片 + 批量并发组合使用
mineru-parse batch -i ./pdfs -o ./outputs --concurrency 3 --target-chunk-pages 20
```

### 6) 从 JSON 再生 Markdown

```bash
mineru-parse from-json ./paper_parsed -o ./paper_full.md
```

## CLI 用法

查看帮助：

```bash
mineru-parse --help
mineru-parse parse --help
mineru-parse batch --help
mineru-parse from-json --help
```

### 全局参数

| 参数 | 说明 |
|------|------|
| `-c, --config` | 指定用户配置（覆盖默认配置） |
| `-f, --force` | 强制覆盖输出 |
| `--no-cache` | 禁用缓存 |
| `--no-merge-paragraphs` | 禁用跨页段落合并 |
| `--no-inline-footnotes` | 脚注放在页末而非段落后 |
| `-q, --quiet` | 静默模式 |
| `-d, --debug` | 调试模式 |
| `--dry-run` | 模拟运行，不调用 API |

### parse 命令参数

| 参数 | 说明 |
|------|------|
| `-o, --output` | 输出目录或 Markdown 路径 |
| `-t, --token` | 临时覆盖 Token |
| `-m, --model` | 解析模型：`vlm`（默认）或 `pipeline` |
| `--header` | 添加页眉 |
| `--footer` | 添加页脚 |
| `--page-number` | 添加页码 |
| `--no-footnote` | 关闭脚注 |
| `--pages` | 仅解析指定页（如 `10-20,30-40`） |
| `--target-chunk-pages` | 自适应分片目标页数（0=仅超限切分，>0=始终切分到此大小） |
| `-f, --force` | 强制覆盖已存在的输出目录 |

### batch 命令参数

| 参数 | 说明 |
|------|------|
| `-i, --input` | 输入 PDF 文件或目录（必需） |
| `-o, --output` | 输出目录 |
| `-r, --recursive` | 递归处理子目录 |
| `-I, --include` | 包含的文件模式 |
| `-E, --exclude` | 排除的文件模式（正则） |
| `--resume` | 断点续传模式 |
| `--reset-failed` | 重置失败任务状态 |
| `--concurrency` | 并发处理文件数（默认从配置读取，1=顺序） |
| `--target-chunk-pages` | 自适应分片目标页数（0=仅超限切分，>0=始终切分到此大小） |

## 配置说明

配置加载优先级（后者覆盖前者）：

1. `mineru_parser/default_config.yml`
2. 当前目录 `config.yml`
3. 环境变量（如 `MINERU_TOKEN`）
4. 命令行 `-c/--config` 指定文件
5. 命令行 `-t/--token`（仅 token）

### 关键配置项

```yaml
api:
  token: ""                          # API Token
  base_url: "https://mineru.net/api" # API 地址
  model_version: "vlm"               # 默认模型
  poll_interval: 5                   # 轮询间隔（秒）
  max_wait: 3600                     # 最大等待时间（秒）

cache:
  enabled: true                      # 启用缓存
  dir: "~/.cache/mineru_parser"      # 缓存目录

split:
  page_limit: 50                     # 每片最大页数
  file_size_limit_mb: 200            # 文件大小限制（MB）
  max_workers: 20                    # 并发线程数
  api_rate_limit: 5                  # API 并发限制（跨文件/分片共享）
  target_chunk_pages: 0              # 自适应分片目标页数（0=仅超限切分）

batch:
  include_pattern: "*.pdf"
  exclude_pattern: ""
  batch_concurrency: 1               # 批量并发文件数（1=顺序，>1=并发）

markdown:
  include_header: false              # 包含页眉
  include_footer: false              # 包含页脚
  include_page_number: false         # 包含页码
  include_footnote: true             # 包含脚注
  merge_paragraphs: true             # 合并跨页段落
  inline_footnotes: true             # 脚注内联到段落
```

建议：

- 生产/共享环境优先使用环境变量管理 Token
- 不要在仓库里提交真实 Token

## 输出说明

默认输出路径：`<pdf_stem>/full.md`

即输入 `paper.pdf` 时，默认生成：

```
paper/
├── full.md      # 最终 Markdown
└── images/      # 被 Markdown 引用的图片（统一为 PNG）
```

使用 `-o/--output` 显式指定输出目录或 Markdown 路径时，保持原有行为：输出文件名为 `<pdf_stem>.md`，并位于指定的输出目录下。

## 测试

运行全部测试：

```bash
pytest -q
```

带覆盖率报告：

```bash
pytest --cov=mineru_parser --cov-report=html
```

## 性能优化说明

本版本包含多项性能优化：

1. **HTTP 连接池**：复用 TCP 连接，减少 SSL 握手开销
2. **哈希缓存**：PDF 文件哈希结果 LRU 缓存，避免重复计算
3. **并行图片处理**：图片格式转换使用多进程加速
4. **API 速率限制**：共享信号量控制跨文件/分片的总并发 API 调用数
5. **自适应分片**：按目标页数切分 PDF，多片段并发调用 API，单文件解析速度提升约 N 倍（N=min(分片数, api_rate_limit)）
6. **批量并发**：多文件同时处理，共享 API 信号量，批量处理速度提升约 batch_concurrency 倍
7. **高速切分**：PDF 切分使用 `pymupdf`（C 实现），复杂大 PDF 切分比纯 Python `pypdf` 快约数百倍

## 常见问题

- **提示未配置 Token**
  设置 `MINERU_TOKEN` 或在 `config.yml` / `-c` 中填入 `api.token`。

- **大图被切分**
  使用 `--model pipeline`，通常更适合保留完整图像。

- **解析很慢或超时**
  调整 `api.poll_interval`、`api.max_wait`，并检查网络连通性。

- **批量任务中断了如何恢复**
  使用 `--resume` 参数继续处理：`mineru-parse batch -i ./pdfs --resume`

- **如何预览批量任务不消耗 API 额度**
  使用 `--dry-run` 参数：`mineru-parse batch -i ./pdfs --dry-run`

## 安全与开源发布建议

- 发布前确认 `config.yml` 中 `api.token` 为空
- 确保没有将本地缓存、测试产物、解析结果上传到公开仓库
- 建议定期轮换 Token

## 版本历史

### v2.0.0 (2026-06-30)

破坏性分层重构：`core/`（业务+loguru）× `commands/`（Typer+Rich）× `models/`（Pydantic）× `engines/`。
专业日志系统（每次运行单独文件、按天分子目录、含运行命令/各阶段耗时/执行结果）；
Rich 统一终端 UI；移除 tqdm；Pydantic 配置校验；删除全局信号量单例与遗留文件。
详见 [CHANGELOG.md](CHANGELOG.md)。

### v1.5.3 (2026-06-30)

- **修复**：脚注（footnote）被错误堆到 Markdown 文档末尾
  - 现象：当正文使用 `<sup>N</sup>` 形式脚注引用时（MinerU 对部分 PDF 的常见输出），脚注内容无法关联到引用位置，全部被堆到文档末尾
  - 原因：`_extract_footnote_refs` 仅识别圆圈数字（①②…）与 LaTeX 上标（`$^{N}$`），未识别 HTML 上标 `<sup>N</sup>`，即便配置 `inline_footnotes: true` 也走兜底逻辑堆到末尾
  - 修复：新增 `<sup>N</sup>` 识别；配置 `inline_footnotes: true` 时脚注内联到引用段落后（真实 PDF 验证：脚注从文末约第 68k 字符处移至引用段落后约第 3.3k 字符处）
- **测试**：新增 `<sup>N</sup>` 脚注内联回归测试，完整测试套件 138 个全部通过
- **文档**：更新 CHANGELOG、README、版本号

### v1.5.2 (2026-06-30)

- **修复**：大 PDF 切分极慢的问题
  - 现象：复杂内部结构的 PDF 切分每 50 页约 37s，622 页文档切分阶段总耗时约 8-10 分钟
  - 原因：`pdf_splitter.py` 使用纯 Python 的 `pypdf` 切分，对部分真实 PDF 走了极慢路径（同文档 `pypdf` 切 50 页约 37s，`pymupdf` 仅约 0.11s）
  - 修复：切分改用 `pymupdf`（`fitz.insert_pdf`），`pypdf` 保留为 fallback；622 页切分从约 480s 降至约 1.5s（提速约 320 倍）
- **修复**：切分进度提示时序反直觉——原"PDF 需要切分"提示在切分完成后才发出，切分期间终端长时间沉默
  - 修复：拆分为切分前 `split_start`（"PDF 较大，正在切分..."）与切分后 `split_done`（片段数），切分前即反馈
- **变更**：新增 `pymupdf>=1.23.0` 运行时依赖，`pypdf` 保留作 fallback
- **测试**：补 `pdf_splitter` 切分实际输出测试（此前仅覆盖页码字符串解析），完整测试套件 137 个全部通过
- **文档**：更新 CHANGELOG、README、版本号

### v1.5.1 (2026-06-28)

- **修复**：MinerU `chart` 类型图表在最终 Markdown 中丢失的问题
  - 原因：`content_list.json` / `content_list_v2.json` 将部分图片（如图表、折线图）标记为 `type: "chart"`，但 `json_parser.py` 仅处理 `type: "image"`
  - 修复：将 `chart` 类型与 `image` 类型同等处理，支持 `chart_caption` 的读取与输出
- **修复**：`content_list_v2.json` 中 `table` 类型可能丢失的问题
  - 原因：v2 表格内容位于 `content.html`，caption 位于 `content.table_caption`，但 `_get_text_from_content_v2` 未读取这些字段
  - 修复：在 `_get_text_from_content_v2` 中提取 v2 table 的 HTML 与 caption，并统一转换为 Markdown 表格
- **工程化**：更新 `.githooks/pre-commit`，提交前自动使用 `ruff format` 格式化 Python、`prettier --write` 格式化 YAML
- **整理**：全仓库 Python 文件执行 `ruff format`，YAML 文件执行 `prettier --write`
- **文档**：更新 CHANGELOG、README、版本号
- **署名**：本版本由 kimi-code（kimi-k2.7）共同开发
- 测试：127 个测试全部通过

### v1.5.0 (2026-06-22)

- **变更**：`mineru-parse parse` 命令默认输出路径调整为 `{stem}/full.md`
- **文档**：更新 CHANGELOG、README、版本号
- **署名**：本版本由 kimi-code（kimi-k2.7）共同开发
- 测试：124 个测试全部通过

### v1.4.0 (2026-06-22)

- **新增**：自动将 MinerU 输出的 HTML `<table>` 转换为标准 Markdown 表格格式
  - 支持 `colspan` / `rowspan` 展开、`<th>` 表头识别、管道符转义
- **新增**：`mineru-parse parse` 命令实时显示解析进度、耗时与结果
  - 阶段提示：文件信息、缓存命中、上传、下载、Markdown 生成
  - 轮询阶段使用 `tqdm` 进度条或动态计数，避免看起来像卡死
- **新增**：`mineru_parser/progress.py` 进度报告模块与 `test/test_progress.py` 测试
- **文档**：更新 README、CHANGELOG、版本号
- **署名**：本版本由 kimi-code（kimi-k2.7）共同开发
- 测试：123 个测试全部通过

### v1.3.0 (2026-06-16)

- **新增**：`mineru-parse parse` 命令支持 `-f/--force`，强制覆盖已存在的输出目录
- **新增**：对 MinerU 识别的 flowchart 图片，在最终 Markdown 中自动保留 ````mermaid` 代码块
- **修复**：脚注位置与格式问题
  - 扩展脚注引用识别，支持 `$^{N}$` LaTeX 上标格式
  - 脚注按内容语言使用 `<!-- 脚注 -->`（中文）或 `<!-- footnote -->`（英文）包裹
- **文档**：更新 README 功能列表与参数说明
- **署名**：本版本由 kimi-code（kimi-k2.7）共同开发
- 测试：90 个测试全部通过，覆盖率 54%

### v1.2.1 (2026-05-29)

- **修复**：PDF 解析时 `code` 类型块的标题（`code_caption`）丢失问题
  - v1 JSON (`content_list.json`)：`_extract_text_from_content_list_item` 现在会提取 `code_caption` 并与 `code_body` 一起输出
  - v2 JSON (`content_list_v2.json`)：新增 `_get_code_caption_from_content_v2` 和 `_get_code_content_from_content_v2`，`_convert_v2_to_content_blocks` 增加对 `type == "code"` 的专门处理
- **修复**：v1 JSON 中 `code_body` 已包含 ` ``` ` 标记却被二次包裹，导致输出中出现嵌套代码块的问题
- **代码清理**：使用 ruff 修复未使用导入（`F401`、`F841`）等 lint 问题
- 测试：85 个测试全部通过
- Wrapped up by kimi-cli (kimi-k2.6)

### v1.2.0 (2025-04-15)

- 新增：自适应分片（`--target-chunk-pages`），按目标页数切分 PDF 并发调用 API 加速解析
- 新增：批量并发处理（`--concurrency`），多文件同时处理共享 API 速率限制
- 新增：`parse_pdfs_concurrent()` 并发批量处理函数
- 新增：共享 API 信号量（`get_api_semaphore`），跨文件/分片统一控制并发数
- 新增：`split_pdf_adaptive()` 自适应分片函数
- 新增：`try_start_job()` 原子化任务认领，防止并发批处理竞争
- 改进：状态管理启用 WAL 模式，提升并发写入性能
- 修复：移除 batch 命令中 L453-471 的死代码（引用失效变量并重复调用 API）
- 测试：85 个测试全部通过

### v1.1.0 (2025-04-06)

- 新增：HTTP 连接池优化
- 新增：PDF 哈希缓存（带自动失效）
- 新增：并行图片处理
- 新增：API 速率限制
- 新增：断点续传（`--resume`）
- 新增：模拟运行（`--dry-run`）
- 新增：批量任务状态管理
- 重构：JSON 解析器共享逻辑提取
- 重构：缓存模块接收 Config 参数
- 测试：覆盖率提升至 58%（85 个测试）

### v1.0.0

- 初始版本：PDF 解析、批量处理、缓存、Markdown 生成

## 贡献

欢迎提交 Issue / PR，具体见 `CONTRIBUTING.md`。

### Contributors

- [mineru-parser contributors](https://github.com/houhuawei23/mineru-parser)
- [kimi-code](https://github.com/kimi-code) — AI 协作 agent（共同开发者）
- GLM-5.2 — AI 协作模型（共同开发者）
- kimi-code（Kimi AI Agent）
- kimi-k2.7（Kimi 大语言模型）

## License

MIT，见 `LICENSE`。

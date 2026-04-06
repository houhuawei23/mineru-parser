# mineru-parser

一个面向本地工作流的 Python CLI：调用 MinerU API 解析 PDF，并输出结构化 Markdown。
支持单文件、批量处理、按页解析、结果缓存、自动分片（大文件/大页数）、断点续传以及从 JSON 再生 Markdown。

## 功能特性

- 解析本地 PDF 或 arXiv URL 到 Markdown
- 支持页眉、页脚、页码、脚注控制
- 大文件自动分片并发解析与合并
- **连接池优化**：HTTP 连接复用，提升批量处理性能
- **智能缓存**：基于文件哈希的解析结果缓存，避免重复调用 API
- **并行图片处理**：CPU 密集型图片转换使用多进程加速
- **API 速率限制**：内置并发控制，防止触发 API 限流
- **断点续传**：批量任务支持 `--resume` 从中断处继续
- **模拟运行**：`--dry-run` 预览待处理内容，不消耗 API 额度
- 图片后处理（仅保留被引用图片，统一重命名为 `image_xx.png`）
- 支持从 `content_list.json` / `content_list_v2.json` 重新生成 Markdown

## 项目结构

```text
mineru-parser/
├── mineru_parser/
│   ├── api.py                # MinerU API 调用与自动分片
│   ├── cache.py              # 解析结果缓存管理
│   ├── cli.py                # Typer CLI 入口
│   ├── config.py             # 配置加载与校验
│   ├── default_config.yml    # 默认配置（强制存在）
│   ├── image_processor.py    # 图片重命名与格式转换
│   ├── json_parser.py        # content_list JSON -> Markdown
│   ├── markdown.py           # Markdown 生成与合并
│   ├── pdf_splitter.py       # PDF 按页/大小切分
│   ├── state.py              # 批量任务状态管理（断点续传）
│   └── utils.py              # URL 解析与下载等工具
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
  page_limit: 100                    # 每片最大页数
  file_size_limit_mb: 200            # 文件大小限制（MB）
  max_workers: 20                    # 并发线程数
  api_rate_limit: 5                  # API 并发限制

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

默认输出目录：`<pdf_stem>_parsed/`

典型内容：

- `<pdf_stem>.md`：最终 Markdown
- `images/`：被 Markdown 引用的图片（统一为 PNG）

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
4. **API 速率限制**：内置信号量控制并发，避免触发服务端限流

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

## License

MIT，见 `LICENSE`。

# mineru-parser

一个面向本地工作流的 Python CLI：调用 MinerU API 解析 PDF，并输出结构化 Markdown。  
支持单文件、批量处理、按页解析、结果缓存、自动分片（大文件/大页数）以及从 JSON 再生 Markdown。

## 功能特性

- 解析本地 PDF 或 arXiv URL 到 Markdown
- 支持页眉、页脚、页码、脚注控制
- 大文件自动分片并发解析与合并
- 解析结果缓存，避免重复请求 API
- 图片后处理（仅保留被引用图片，统一重命名为 `image_xx.png`）
- 支持从 `content_list.json` / `content_list_v2.json` 重新生成 Markdown

## 项目结构

```text
mineru-parser/
├── mineru_parser/
│   ├── api.py                # MinerU API 调用与自动分片
│   ├── cli.py                # Typer CLI 入口
│   ├── config.py             # 配置加载与校验
│   ├── default_config.yml    # 默认配置（强制存在）
│   ├── image_processor.py    # 图片重命名与格式转换
│   ├── json_parser.py        # content_list JSON -> Markdown
│   ├── markdown.py           # Markdown 生成与合并
│   ├── pdf_splitter.py       # PDF 按页/大小切分
│   └── utils.py              # URL 解析与下载等工具
├── test/                     # 单元测试
├── config.yml                # 本地配置（请勿提交真实 token）
├── config.example.yml        # 配置示例
├── mineru_parse_pdf.py       # 兼容旧入口
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
```

### 2) 解析单个 PDF

```bash
mineru-parse parse ./paper.pdf
```

### 3) 解析 arXiv 链接

```bash
mineru-parse parse "https://arxiv.org/abs/2402.03300"
```

### 4) 批量解析目录

```bash
mineru-parse batch -i ./pdfs -o ./outputs -r
```

### 5) 从 JSON 再生 Markdown

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

常用参数：

- `-c, --config`: 指定用户配置（覆盖默认配置）
- `-t, --token`: 临时覆盖 Token
- `-m, --model`: `vlm` 或 `pipeline`
- `-f, --force`: 强制覆盖输出
- `--no-cache`: 禁用缓存
- `--pages`: 仅解析指定页（如 `10-20,30-40`）
- `--header --footer --page-number --no-footnote`: Markdown 内容控制

## 配置说明

配置加载优先级（后者覆盖前者）：

1. `mineru_parser/default_config.yml`
2. 当前目录 `config.yml`
3. 环境变量（如 `MINERU_TOKEN`）
4. 命令行 `-c/--config` 指定文件
5. 命令行 `-t/--token`（仅 token）

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

## 常见问题

- **提示未配置 Token**  
  设置 `MINERU_TOKEN` 或在 `config.yml` / `-c` 中填入 `api.token`。

- **大图被切分**  
  使用 `--model pipeline`，通常更适合保留完整图像。

- **解析很慢或超时**  
  调整 `api.poll_interval`、`api.max_wait`，并检查网络连通性。

## 安全与开源发布建议

- 发布前确认 `config.yml` 中 `api.token` 为空
- 确保没有将本地缓存、测试产物、解析结果上传到公开仓库
- 建议定期轮换 Token

## 贡献

欢迎提交 Issue / PR，具体见 `CONTRIBUTING.md`。

## License

MIT，见 `LICENSE`。


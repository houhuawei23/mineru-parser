# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MinerU PDF Parser is a Python CLI tool that converts PDFs to Markdown using the MinerU API. It supports batch processing, automatic PDF splitting for large files, caching, and various Markdown output options.

## Development Commands

### Setup
```bash
# Install in development mode
pip install -e ".[dev]"
```

### Testing
```bash
# Run all tests
pytest -q

# Run with coverage
pytest --cov=mineru_parser
```

### Running the CLI
```bash
# Parse a single PDF
mineru-parse parse ./paper.pdf

# Parse with specific pages
mineru-parse parse ./paper.pdf --pages 10-20,30-40

# Parse arXiv URL
mineru-parse parse "https://arxiv.org/abs/2402.03300"

# Batch processing
mineru-parse batch -i ./pdfs -o ./outputs -r

# Regenerate Markdown from existing JSON
mineru-parse from-json ./paper_parsed -o ./output.md
```

## Architecture

The package is **layered** (v2.0.0+). Each layer has a single concern:

- `main.py` + `commands/` — **Typer + Rich** (human I/O only). Command functions stay thin: parse args → resolve config → call orchestrator → render via Rich → log result.
- `core/` — **business orchestration** (uses loguru, never Rich). HTTP transport, single-PDF parse + auto-split, concurrent batch.
- `models/` — **Pydantic v2** config + DTOs (`ParseParams`, `RunContext`, `ParseResult`).
- `engines/` — **reusable pure logic** (splitter, JSON parser, markdown, images, cache, state, utils). No CLI/Rich/logging coupling.
- `console.py` — Rich `Console` singleton, render helpers (`render_run_header`, `render_result_panel`, `render_dry_run_table`, `render_batch_summary`, …) and `RichProgressReporter` (replaces tqdm).
- `logging_setup.py` — loguru per-run file sink (`~/.cache/mineru_parser/logs/YYYY-MM-DD/YYYY-MM-DD_HHMMSS.log`) with `=== RUN START ===`/`=== RUN END ===` markers + per-stage timing.
- `errors.py` — `MineruError` hierarchy.

### Configuration System (models/config.py)

Pydantic v2 models (`RootConfig` aggregating `ApiConfig`/`SplitConfig`/`CacheConfig`/`MarkdownConfig`/`OutputConfig`/`BatchConfig`/`PdfDownloadConfig`/`DownloadConfig`/`ConfigMeta`). Loaded in strict priority order (later overrides earlier):
1. `mineru_parser/default_config.yml` (package defaults, required)
2. Current directory `config.yml` (user project config)
3. Environment variable `MINERU_TOKEN`
4. Command-line `-c/--config` specified file
5. Command-line `-t/--token` for token only

Pydantic validates types/positive-ints, expands `~` in `cache.dir`, and forbids unknown keys (`extra="forbid"`). `RootConfig` also exposes ~30 flat `@property` accessors (e.g. `cfg.cache_dir`, `cfg.api_rate_limit`) so engines/orchestrator read sites stay simple.

### Core Processing Flow

```
CLI command (commands/parse.py)
    ↓  builds ParseParams + RunContext(ctx.obj)
orchestrate_parse(params, ctx) (core/orchestrator.py)
    ↓
[If adaptive split enabled or PDF exceeds limits] → split_pdf_adaptive() / split_pdf_by_limits() (engines/pdf_splitter.py)
    ↓
parse_pdf_via_api() (core/orchestrator.py) - handles caching
    ↓
core/api_client.py: apply_upload_urls → upload_file_to_url → poll_batch_result → download_zip
    ↓
build_markdown_from_zip() (engines/markdown.py)
    ↓
[If split] merge_markdown_parts() (engines/markdown.py)

Batch mode (concurrency > 1):
commands/batch.py → run_batch(list[ParseParams], ctx) (core/batch.py)
    ↓
ThreadPoolExecutor(batch_concurrency) → N × orchestrate_parse()
    ↓
[Shared ctx.rate_limiter limits total concurrent API calls across files + fragments]
```

### Key Components

**Core orchestration (core/orchestrator.py)**
- `orchestrate_parse(params, ctx)`: Single PDF with auto-split (collapsed from the old 25-positional-arg signature into `ParseParams`); uses `ctx.rate_limiter` for fragment concurrency.
- `parse_pdf_via_api()`: Single fragment upload→poll→download→build with caching (unchanged signature).
- `_clean_output_dir()`: Keeps only `*.md` + `images/`.

**Core transport (core/api_client.py + core/http.py)**
- `apply_upload_urls`, `upload_file_to_url`, `poll_batch_result`, `download_zip` (download has `allow_insecure_fallback`, no global warning suppression).
- `get_session()`/`close_session()`: thread-local `requests.Session()` with `HTTPAdapter` pooling; `atexit`-registered cleanup.

**Core batch (core/batch.py)**
- `run_batch(tasks, ctx, batch_concurrency, on_complete)`: returns `list[ParseResult]`; shares `ctx.rate_limiter`.

**PDF Splitter (engines/pdf_splitter.py)** — `split_pdf_by_limits()`, `split_pdf_adaptive()`, `parse_pages_spec()` (returns warnings only — no longer logs inside), `extract_pages_to_pdf()`.

**Markdown (engines/markdown.py)** — `build_markdown_from_zip()`, `regenerate_markdown_from_json()`, `merge_markdown_parts()`.

**Image / Cache / State / JSON** (engines/) — engines; cache is keyed on source-PDF SHA256 + source page set (`compute_source_hash`/`describe_page_token`/`cache_zip_path`, grouped per source PDF), state is SQLite (WAL) with `try_start_job()` atomic claim.

**Concurrency note**: there is NO global semaphore anymore. `RunContext.rate_limiter` (a `threading.Semaphore(cfg.api_rate_limit)`) is constructed once in `main_callback` and shared by `orchestrate_parse` (fragments) and `run_batch` (files).

### CLI Structure (main.py + commands/)

Typer app in `main.py`; three commands in `commands/{parse,batch,from_json}.py`. Global options in `main_callback()` build a `RunContext` stored on `ctx.obj` (config, rate_limiter, log_path, force/no_cache/dry_run/quiet flags). Shared helpers (`build_parse_params`, `resolve_output_dir`, `build_md_options`, `validate_token`) live in `commands/_shared.py`. Console-level flags: `-q/--quiet`, `-d/--debug`, `--verbose` control the loguru stderr sink level.

## Important Implementation Details

### HTTP Connection Pooling
The API module uses `requests.Session()` with connection pooling for better performance:
- Sessions are stored in thread-local storage (`threading.local()`) for thread safety
- `get_session()` returns a pooled session with `HTTPAdapter` (pool_size=10, max_pool=20)
- `close_session()` cleans up the current thread's session
- All HTTP functions accept an optional `session` parameter for connection reuse
- Retry strategy with exponential backoff and jitter for transient errors

### Token Management
- Token can be provided via config file, environment variable `MINERU_TOKEN`, or CLI `-t`
- Never commit real tokens to the repository

### Rate Limiting
- API concurrency is controlled by `api_rate_limit` (default 5) via `RunContext.rate_limiter` (a `threading.Semaphore`)
- Limits total concurrent API calls across all files and their split fragments
- Constructed once per CLI invocation in `main_callback()` and injected via `RunContext` — **no global singleton** (the old `_api_semaphore`/`get_api_semaphore`/`reset_api_semaphore` were removed)
- Separate from `max_workers` which controls thread pool size for fragment I/O
- Applies to both split PDF fragment processing (`orchestrate_parse`) and concurrent batch file processing (`run_batch`)

### Parallel Image Processing
- Image conversion uses `ProcessPoolExecutor` (default 4 workers) for CPU-bound PIL operations
- Configurable via `max_workers` parameter in `process_images()`
- Preserves image order for correct Markdown reference mapping
- Failed conversions are logged and removed from references

### Large File Handling
- Files exceeding `split.file_size_limit_mb` (default 200MB) or `split.page_limit` (default 50 pages) are automatically split
- **Adaptive splitting**: When `split.target_chunk_pages > 0`, PDFs with more pages than this value are always split, even if within hard limits — enabling concurrent API calls for faster processing
- Each fragment is processed concurrently with `max_workers` (default 20) threads
- Results are merged with image renumbering to avoid conflicts

### Batch Concurrency
- `batch.batch_concurrency` (default 1) controls how many PDF files are processed concurrently
- When `batch_concurrency > 1`, uses `parse_pdfs_concurrent()` with a shared API semaphore
- The shared semaphore ensures total in-flight API calls across all files/chunks is bounded by `api_rate_limit`
- `--concurrency` CLI option overrides config; `--target-chunk-pages` enables adaptive splitting per run
- State manager uses `try_start_job()` for atomic claim-and-mark-RUNNING to prevent race conditions

### Caching
- Enabled by default, disable with `--no-cache`
- **Cache identity = SHA256 of the *source* PDF content + the source page set** (not the bytes of split/extracted temp files — PyMuPDF `save()` embeds a random `/ID` each write, so fragment bytes are non-deterministic and would bust the cache). See `engines/cache.py:compute_source_hash` / `describe_page_token`.
- All fragments of one source PDF are grouped under a single directory so they're easy to browse/manage:
  ```
  <cache_dir>/<model>/<safe_stem>_<hash8>/
      full.zip        # whole doc, unsplit
      p1-50.zip       # split fragment (contiguous)
      p10-20.zip      # --pages subset (contiguous)
      h<12hex>.zip    # non-contiguous page set (--pages 1-3,7)
      source.txt      # records the source filename for human inspection
  ```
  Layout helpers: `cache_group_dir`, `cache_zip_path`. The orchestrator computes the per-fragment cache path from `(source_pdf, source_hash, page_token)` and passes it as `cache_file` into `parse_pdf_via_api`.
- `compute_source_hash` is memoized via LRU (auto-invalidates on file mtime/size change)
- Cached results skip API calls entirely
- The per-PDF cache group dir is shown in the `parse` run header and result panel (Problem 3: easy to `cd` in and inspect the raw zips)

### Page Range Selection
- The `--pages` option uses 1-based indexing in CLI, converted to 0-based internally
- Out-of-range pages are automatically clipped with warnings
- Extracted pages are written to a temp file for processing

### Dry-Run Mode
- Use `--dry-run` to preview what would be processed without calling API
- Shows file count, total pages, total size, model, and output directory
- Useful for testing batch configurations and estimating costs

### Batch Resume Capability
- Use `--resume` to continue an interrupted batch job
- Tracks job state in SQLite database (`.mineru_batch_state.db`)
- Skips completed files, retries failed files (up to 3 attempts)
- Use `--reset-failed` to reset failed jobs and retry them

### Image Handling
- Only images referenced in Markdown are kept
- All images are renamed to `image_XX.png` format
- Images are stored in `{output_dir}/images/`

## Testing Structure

Tests are in the `test/` directory using pytest:
- `test_config.py`: Pydantic configuration loading & validation
- `test_pdf_splitter.py`: PDF splitting and page spec parsing
- `test_markdown.py`: Markdown generation
- `test_json_parser.py`: JSON parsing
- `test_image_processor.py`: Image processing
- `test_api.py`: Core HTTP transport (api_client) + connection pooling (http) + retries
- `test_orchestrator.py`: `orchestrate_parse` split-cache round-trip (write→hit, `--no-cache`, source marker)
- `test_cli.py`: CLI commands via `main.app` (parse, batch, from-json; real `RootConfig`)
- `test_cache.py`: Cache and hash memoization tests
- `test_state.py`: Batch state management (resume, atomic claim) tests
- `test_progress.py`: Rich `RichProgressReporter` + render helpers
- `test_logging.py`: Per-run log path format + RUN START/END markers

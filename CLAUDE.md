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

### Configuration System (config.py)

Configuration is loaded in a strict priority order (later overrides earlier):
1. `mineru_parser/default_config.yml` (package defaults, required)
2. Current directory `config.yml` (user project config)
3. Environment variable `MINERU_TOKEN`
4. Command-line `-c/--config` specified file
5. Command-line `-t/--token` for token only

The `Config` class exposes all settings as typed attributes. All configuration must come from YAML files; there are no hardcoded defaults in the code.

### Core Processing Flow

```
CLI (cli.py)
    ↓
parse_pdf_via_api_with_auto_split() (api.py)
    ↓
[If PDF exceeds limits] → split_pdf_by_limits() (pdf_splitter.py)
    ↓
parse_pdf_via_api() (api.py) - handles caching
    ↓
[Upload → Poll → Download] MinerU API
    ↓
build_markdown_from_zip() (markdown.py)
    ↓
[If split] merge_markdown_parts() (markdown.py)
```

### Key Components

**API Module (api.py)**
- `parse_pdf_via_api()`: Core function for single PDF processing with caching support
- `parse_pdf_via_api_with_auto_split()`: Handles large PDFs by splitting and concurrent processing
- Uses `ThreadPoolExecutor` for concurrent fragment processing
- **Connection Pooling**: Uses `requests.Session()` with `HTTPAdapter` for connection reuse. Sessions are stored in thread-local storage (`_thread_local`) for thread safety.
- **Session Management**: `get_session()` returns a pooled session; `close_session()` cleans up the current thread's session

**PDF Splitter (pdf_splitter.py)**
- `split_pdf_by_limits()`: Splits PDFs by page count and file size
- `parse_pages_spec()`: Parses CLI page range syntax (e.g., "10-20,30-40")
- `extract_pages_to_pdf()`: Extracts specific pages to a new PDF

**Markdown Generation (markdown.py)**
- `build_markdown_from_zip()`: Extracts zip, processes images, generates Markdown
- `regenerate_markdown_from_json()`: Re-creates Markdown from existing JSON output
- `merge_markdown_parts()`: Merges split PDF results with image renumbering

**Image Processing (image_processor.py)**
- Filters to only referenced images
- Renames to `image_xx.png` format
- Converts formats to PNG
- Updates Markdown references

**Cache (cache.py)**
- Content-addressable storage using PDF hash
- Cache key uses first N chars of hash as subdir prefix
- Default location: `~/.cache/mineru_parser/`

**JSON Parser (json_parser.py)**
- Converts `content_list.json` and `content_list_v2.json` to Markdown
- Handles text, images, tables, equations, and footnotes

### CLI Structure (cli.py)

Uses Typer with three main commands:
- `parse`: Single PDF/URL processing
- `batch`: Directory processing with glob patterns
- `from-json`: Regenerate Markdown from JSON

Global options in `main_callback()` are stored in `ctx.obj` and inherited by subcommands.

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
- API concurrency is controlled by `api_rate_limit` (default 5) using `threading.Semaphore`
- Limits concurrent API calls to prevent overwhelming the MinerU API
- Separate from `max_workers` which controls thread pool size for I/O operations
- Only applies to split PDF processing; single PDF processing is naturally sequential

### Parallel Image Processing
- Image conversion uses `ProcessPoolExecutor` (default 4 workers) for CPU-bound PIL operations
- Configurable via `max_workers` parameter in `process_images()`
- Preserves image order for correct Markdown reference mapping
- Failed conversions are logged and removed from references

### Large File Handling
- Files exceeding `split.file_size_limit_mb` (default 200MB) or `split.page_limit` (default 100 pages) are automatically split
- Each fragment is processed concurrently with `max_workers` (default 20) threads
- Results are merged with image renumbering to avoid conflicts

### Caching
- Enabled by default, disable with `--no-cache`
- Uses MD5 hash of PDF content as cache key
- Hash results are memoized with LRU cache (auto-invalidates on file modification)
- Cached results skip API calls entirely

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
- `test_config.py`: Configuration loading
- `test_pdf_splitter.py`: PDF splitting and page spec parsing
- `test_markdown.py`: Markdown generation
- `test_json_parser.py`: JSON parsing
- `test_image_processor.py`: Image processing
- `test_api.py`: API module tests (connection pooling, HTTP requests, retries)
- `test_cli.py`: CLI command tests (parse, batch, from-json commands)
- `test_cache.py`: Cache and hash memoization tests
- `test_state.py`: Batch state management tests

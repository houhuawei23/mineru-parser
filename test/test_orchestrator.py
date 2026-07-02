"""orchestrate_parse 缓存路径集成测试。

验证修复点：切分场景下，首次解析写入缓存后，第二次解析应直接命中缓存、不调用 API。
全程 mock 传输层与 Markdown 构建，避免网络与真实 zip 依赖。
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from mineru_parser.engines.cache import (
    cache_zip_path,
    compute_source_hash,
    describe_page_token,
)
from mineru_parser.engines.pdf_splitter import chunk_ranges, compute_pages_per_chunk
from mineru_parser.models.config import ApiConfig, CacheConfig, RootConfig
from mineru_parser.models.params import ParseParams, RunContext

fitz = pytest.importorskip("fitz")

_ORCH = "mineru_parser.core.orchestrator"


def _make_pdf(path: Path, num_pages: int) -> None:
    doc = fitz.open()
    for i in range(num_pages):
        doc.new_page().insert_text((72, 72), f"Page {i}")
    doc.save(str(path))
    doc.close()


def _build_params_and_ctx(pdf_path: Path, cache_dir: Path, output_dir: Path):
    cfg = RootConfig(
        api=ApiConfig(token="t"),
        cache=CacheConfig(dir=cache_dir),
    )
    params = ParseParams(
        pdf_path=pdf_path,
        token="t",
        output_dir=output_dir,
        config=cfg,
    )
    ctx = RunContext(
        config=cfg,
        rate_limiter=threading.Semaphore(5),
        log_path=output_dir / "run.log",
        run_started_at=datetime(2026, 7, 2, 0, 0, 0),
    )
    return params, ctx


def _fragment_cache_files(
    pdf_path: Path, cfg: RootConfig, num_pages: int
) -> list[Path]:
    """复刻编排层的片段缓存路径计算，供测试预置/校验。"""
    sh = compute_source_hash(pdf_path, cfg)
    ppc = compute_pages_per_chunk(
        num_pages,
        pdf_path.stat().st_size,
        cfg.page_limit,
        int(cfg.file_size_limit_mb * 1024 * 1024),
    )
    source_map = list(range(num_pages))
    return [
        cache_zip_path(
            cfg.cache_dir,
            cfg.model_version,
            pdf_path,
            sh,
            describe_page_token(source_map[s:e]),
        )
        for s, e in chunk_ranges(num_pages, ppc)
    ]


def test_split_pdf_cache_roundtrip(tmp_path: Path) -> None:
    """60 页 PDF（page_limit=50）切 2 片：首次走 API 写缓存，二次命中缓存不调 API。"""
    pdf_path = tmp_path / "big.pdf"
    _make_pdf(pdf_path, 60)
    cache_dir = tmp_path / "cache"
    output_dir = tmp_path / "out"
    params, ctx = _build_params_and_ctx(pdf_path, cache_dir, output_dir)

    fragment_files = _fragment_cache_files(pdf_path, ctx.config, 60)
    assert len(fragment_files) == 2  # [1-50], [51-60]
    assert [f.name for f in fragment_files] == ["p1-50.zip", "p51-60.zip"]

    api_calls = {"apply": 0, "download": 0}

    def fake_apply(*a, **kw):
        api_calls["apply"] += 1
        return {"batch_id": "bid", "file_urls": ["http://upload"]}

    def fake_download(*a, **kw):
        api_calls["download"] += 1
        return b"zip-bytes"

    # 首次：缓存为空 -> 走 API，写缓存
    with (
        patch(f"{_ORCH}.apply_upload_urls", side_effect=fake_apply),
        patch(f"{_ORCH}.upload_file_to_url", return_value=True),
        patch(f"{_ORCH}.poll_batch_result", return_value={"full_zip_url": "http://x"}),
        patch(f"{_ORCH}.download_zip", side_effect=fake_download),
        patch(f"{_ORCH}.build_markdown_from_zip", return_value="# part"),
        patch(f"{_ORCH}.merge_markdown_parts", return_value="# merged"),
    ):
        from mineru_parser.core.orchestrator import orchestrate_parse

        md1 = orchestrate_parse(params, ctx)

    assert md1 == "# merged"
    assert api_calls["apply"] == 2  # 两个片段各申请一次
    assert api_calls["download"] == 2
    for f in fragment_files:
        assert f.exists() and f.read_bytes() == b"zip-bytes"

    # 二次：应命中缓存 -> 不再调用 apply / download
    with (
        patch(f"{_ORCH}.apply_upload_urls", side_effect=fake_apply),
        patch(f"{_ORCH}.download_zip", side_effect=fake_download),
        patch(f"{_ORCH}.build_markdown_from_zip", return_value="# part"),
        patch(f"{_ORCH}.merge_markdown_parts", return_value="# merged"),
    ):
        md2 = orchestrate_parse(params, ctx)

    assert md2 == "# merged"
    assert api_calls["apply"] == 2  # 未增加 -> 缓存命中
    assert api_calls["download"] == 2  # 未增加


def test_no_cache_disables_writes(tmp_path: Path) -> None:
    """--no-cache：不读不写缓存，始终走 API。"""
    pdf_path = tmp_path / "big.pdf"
    _make_pdf(pdf_path, 60)
    cache_dir = tmp_path / "cache"
    output_dir = tmp_path / "out"
    params, ctx = _build_params_and_ctx(pdf_path, cache_dir, output_dir)
    params = ParseParams(
        pdf_path=pdf_path,
        token="t",
        output_dir=output_dir,
        config=ctx.config,
        cache_enabled=False,
        use_cache=False,
    )

    with (
        patch(
            f"{_ORCH}.apply_upload_urls",
            return_value={"batch_id": "b", "file_urls": ["u"]},
        ),
        patch(f"{_ORCH}.upload_file_to_url", return_value=True),
        patch(f"{_ORCH}.poll_batch_result", return_value={"full_zip_url": "x"}),
        patch(f"{_ORCH}.download_zip", return_value=b"zip"),
        patch(f"{_ORCH}.build_markdown_from_zip", return_value="# part"),
        patch(f"{_ORCH}.merge_markdown_parts", return_value="# merged"),
    ):
        from mineru_parser.core.orchestrator import orchestrate_parse

        md = orchestrate_parse(params, ctx)

    assert md == "# merged"
    # 缓存目录不应被创建
    assert not cache_dir.exists() or not any(cache_dir.rglob("*.zip"))


def test_source_marker_written(tmp_path: Path) -> None:
    """命中/写入缓存时，组目录下应生成 source.txt 记录源文件名。"""
    pdf_path = tmp_path / "doc.pdf"
    _make_pdf(pdf_path, 60)
    cache_dir = tmp_path / "cache"
    output_dir = tmp_path / "out"
    params, ctx = _build_params_and_ctx(pdf_path, cache_dir, output_dir)

    with (
        patch(
            f"{_ORCH}.apply_upload_urls",
            return_value={"batch_id": "b", "file_urls": ["u"]},
        ),
        patch(f"{_ORCH}.upload_file_to_url", return_value=True),
        patch(f"{_ORCH}.poll_batch_result", return_value={"full_zip_url": "x"}),
        patch(f"{_ORCH}.download_zip", return_value=b"zip"),
        patch(f"{_ORCH}.build_markdown_from_zip", return_value="# part"),
        patch(f"{_ORCH}.merge_markdown_parts", return_value="# merged"),
    ):
        from mineru_parser.core.orchestrator import orchestrate_parse

        orchestrate_parse(params, ctx)

    markers = list(cache_dir.rglob("source.txt"))
    assert len(markers) == 1
    assert markers[0].read_text(encoding="utf-8") == str(pdf_path)

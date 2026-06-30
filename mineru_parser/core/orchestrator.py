"""解析编排：单 PDF 上传→轮询→下载→构建，含自动分片与并发合并。

- :func:`parse_pdf_via_api` 处理单个 PDF 片段（上传/轮询/下载/构建），含缓存。
- :func:`orchestrate_parse` 在其上叠加页码提取、自适应分片、并发片段处理与合并，
  使用 :class:`RunContext.rate_limiter` 控制总在途 API 调用（取代旧的全局信号量单例）。
"""

from __future__ import annotations

import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from loguru import logger

from mineru_parser.core.api_client import (
    apply_upload_urls,
    download_zip,
    poll_batch_result,
    upload_file_to_url,
)
from mineru_parser.core.http import get_session
from mineru_parser.engines.cache import get_cached_zip, save_to_cache
from mineru_parser.engines.markdown import build_markdown_from_zip, merge_markdown_parts
from mineru_parser.engines.pdf_splitter import (
    extract_pages_to_pdf,
    get_pdf_info,
    parse_pages_spec,
    split_pdf_adaptive,
    split_pdf_by_limits,
)
from mineru_parser.models.config import RootConfig
from mineru_parser.models.params import ParseParams, RunContext


def parse_pdf_via_api(
    pdf_path: Path,
    token: str,
    output_dir: Path,
    config: RootConfig,
    base_url: str = "",
    model_version: str = "",
    poll_interval: int = 0,
    max_wait: int = 0,
    include_header: bool = False,
    include_footer: bool = False,
    include_page_number: bool = False,
    include_footnote: bool = True,
    merge_paragraphs: bool = True,
    inline_footnotes: bool = False,
    cache_enabled: bool = True,
    cache_dir: Path | None = None,
    use_cache: bool = True,
    save_zip_to_output: bool = False,
    output_md_name: str | None = None,
    session: requests.Session | None = None,
    progress_callback=None,
) -> str | None:
    """上传单个 PDF 到 MinerU API 解析、下载 zip、解压并生成 Markdown。

    支持缓存：相同 PDF 命中缓存时直接复用，跳过 API 调用。
    """
    _session = session or get_session()
    base_url = base_url or config.base_url
    model_version = model_version or config.model_version
    poll_interval = poll_interval or config.poll_interval
    max_wait = max_wait or config.max_wait
    md_name = output_md_name or f"{pdf_path.stem}.md"
    _cache_dir = cache_dir or config.cache_dir
    zip_suffix = config.output_zip_suffix

    if not pdf_path.exists():
        logger.error(f"文件不存在: {pdf_path}")
        if progress_callback is not None:
            progress_callback("error", {"error": f"文件不存在: {pdf_path}"})
        return None

    md_opts = dict(
        include_header=include_header,
        include_footer=include_footer,
        include_page_number=include_page_number,
        include_footnote=include_footnote,
        merge_paragraphs=merge_paragraphs,
        inline_footnotes=inline_footnotes,
        output_md_name=md_name,
    )

    # 尝试从缓存获取
    if cache_enabled and use_cache:
        zip_content = get_cached_zip(pdf_path, _cache_dir, config, model_version)
        if zip_content is not None:
            if progress_callback is not None:
                progress_callback("cache_hit", {})
            output_dir.mkdir(parents=True, exist_ok=True)
            if save_zip_to_output:
                zip_path = output_dir.parent / f"{pdf_path.stem}{zip_suffix}"
                zip_path.write_bytes(zip_content)
                logger.info(f"已保存 zip: {zip_path}")
            if progress_callback is not None:
                progress_callback("build", {})
            t0 = time.perf_counter()
            markdown = build_markdown_from_zip(
                zip_content, output_dir, output_dir, **md_opts
            )
            logger.info(f"build (cache) done in {time.perf_counter() - t0:.2f}s")
            return markdown

    # 申请上传链接
    if progress_callback is not None:
        progress_callback("upload", {})
    t0 = time.perf_counter()
    apply_result = apply_upload_urls(
        token,
        base_url,
        pdf_path.name,
        model_version,
        config.request_timeout_apply,
        session=_session,
    )
    logger.info(f"apply_upload_urls done in {time.perf_counter() - t0:.2f}s")
    if not apply_result:
        if progress_callback is not None:
            progress_callback("error", {"error": "申请上传链接失败"})
        return None
    batch_id = apply_result["batch_id"]
    file_urls = apply_result["file_urls"]
    logger.info(f"batch_id: {batch_id}")
    if progress_callback is not None:
        progress_callback("upload", {"batch_id": batch_id})

    # 上传
    t0 = time.perf_counter()
    if not upload_file_to_url(
        pdf_path, file_urls[0], config.request_timeout_upload, session=_session
    ):
        if progress_callback is not None:
            progress_callback("error", {"error": "上传文件失败"})
        return None
    logger.info(f"upload done in {time.perf_counter() - t0:.2f}s")
    if progress_callback is not None:
        progress_callback("upload_done", {})

    # 轮询
    t0 = time.perf_counter()
    result = poll_batch_result(
        token,
        base_url,
        batch_id,
        poll_interval,
        max_wait,
        config.request_timeout_poll,
        session=_session,
        progress_callback=progress_callback,
    )
    logger.info(f"poll done in {time.perf_counter() - t0:.2f}s")
    if not result:
        if progress_callback is not None:
            progress_callback("error", {"error": "解析失败或超时"})
        return None
    zip_url = result.get("full_zip_url")
    if not zip_url:
        if progress_callback is not None:
            progress_callback("error", {"error": "state=done 但无 full_zip_url"})
        return None

    # 下载
    if progress_callback is not None:
        progress_callback("download", {})
    t0 = time.perf_counter()
    zip_content = download_zip(
        zip_url,
        token,
        config.request_timeout_download,
        config.download_max_retries,
        config.download_retry_wait_cap,
        session=_session,
        allow_insecure_fallback=config.allow_insecure_fallback,
    )
    logger.info(f"download done in {time.perf_counter() - t0:.2f}s")
    if not zip_content:
        if progress_callback is not None:
            progress_callback("error", {"error": "下载解析结果失败"})
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    if save_zip_to_output:
        zip_path = output_dir.parent / f"{pdf_path.stem}{zip_suffix}"
        zip_path.write_bytes(zip_content)
        logger.info(f"已保存 zip: {zip_path}")

    # 写入缓存
    if cache_enabled and use_cache:
        save_to_cache(pdf_path, zip_content, _cache_dir, config, model_version)

    # 构建 Markdown
    if progress_callback is not None:
        progress_callback("build", {})
    t0 = time.perf_counter()
    markdown = build_markdown_from_zip(zip_content, output_dir, output_dir, **md_opts)
    logger.info(f"build done in {time.perf_counter() - t0:.2f}s")
    return markdown


def _clean_output_dir(
    output_dir: Path, md_filename: str, images_dir_name: str = "images"
) -> None:
    """仅保留 ``xx.md`` 和 ``images/``，移除其他文件与目录。"""
    keep = {md_filename, images_dir_name}
    for item in output_dir.iterdir():
        if item.name in keep:
            continue
        try:
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)
        except OSError as e:
            logger.debug(f"清理输出目录时跳过 {item}: {e}")


def orchestrate_parse(
    params: ParseParams,
    ctx: RunContext,
    progress_callback=None,
) -> str | None:
    """解析 PDF，若超出页数/大小限制或开启自适应分片则切分、并发处理、合并结果。"""
    config = params.config
    pdf_path = params.pdf_path
    base_url = params.base_url or config.base_url
    model_version = params.model_version or config.model_version
    poll_interval = params.poll_interval or config.poll_interval
    max_wait = params.max_wait or config.max_wait
    file_size_limit_mb = params.file_size_limit_mb or config.file_size_limit_mb
    page_limit = params.page_limit or config.page_limit
    max_workers = params.max_workers or config.max_workers
    target_chunk_pages = params.target_chunk_pages or config.target_chunk_pages
    cache_dir = params.cache_dir or config.cache_dir
    md_stem = pdf_path.stem
    md_name = params.output_md_name or f"{md_stem}.md"

    if not pdf_path.exists():
        logger.error(f"文件不存在: {pdf_path}")
        if progress_callback is not None:
            progress_callback("error", {"error": f"文件不存在: {pdf_path}"})
        return None

    # 页码提取（--pages）
    working_pdf = pdf_path
    temp_extracted: Path | None = None
    if params.pages_spec and params.pages_spec.strip():
        total_pages, _ = get_pdf_info(pdf_path)
        indices, warns = parse_pages_spec(params.pages_spec, total_pages)
        for w in warns:
            logger.warning(w)
        if not indices:
            logger.error(
                "页码范围未选中任何有效页面（可能全部超出 PDF 页数），请检查 --pages"
            )
            if progress_callback is not None:
                progress_callback("error", {"error": "页码范围未选中任何有效页面"})
            return None
        try:
            tf = tempfile.NamedTemporaryFile(
                suffix=".pdf", delete=False, prefix=f"{pdf_path.stem}_pages_"
            )
            tf.close()
            temp_extracted = Path(tf.name)
            extract_pages_to_pdf(pdf_path, indices, temp_extracted)
        except Exception as e:  # noqa: BLE001 — 提取失败需兜底清理临时文件
            logger.exception(f"按页码提取 PDF 失败: {e}")
            if temp_extracted is not None:
                temp_extracted.unlink(missing_ok=True)
            if progress_callback is not None:
                progress_callback("error", {"error": f"按页码提取 PDF 失败: {e}"})
            return None
        working_pdf = temp_extracted
        logger.info(f"已按 --pages 提取 {len(indices)} 页用于解析")

    size_limit_bytes = int(file_size_limit_mb * 1024 * 1024)
    num_pages, size_bytes = get_pdf_info(working_pdf)

    if progress_callback is not None:
        progress_callback(
            "start",
            {
                "pdf_path": str(pdf_path),
                "num_pages": num_pages,
                "size_bytes": size_bytes,
                "size_mb": size_bytes / 1024 / 1024,
            },
        )

    try:
        return _orchestrate_body(
            working_pdf=working_pdf,
            md_name=md_name,
            token=params.token,
            output_dir=params.output_dir,
            config=config,
            page_limit=page_limit,
            max_workers=max_workers,
            size_limit_bytes=size_limit_bytes,
            num_pages=num_pages,
            size_bytes=size_bytes,
            base_url=base_url,
            model_version=model_version,
            poll_interval=poll_interval,
            max_wait=max_wait,
            include_header=params.include_header,
            include_footer=params.include_footer,
            include_page_number=params.include_page_number,
            include_footnote=params.include_footnote,
            merge_paragraphs=params.merge_paragraphs,
            inline_footnotes=params.inline_footnotes,
            cache_enabled=params.cache_enabled,
            cache_dir=cache_dir,
            use_cache=params.use_cache,
            rate_limiter=ctx.rate_limiter,
            target_chunk_pages=target_chunk_pages,
            progress_callback=progress_callback,
        )
    finally:
        if temp_extracted is not None:
            temp_extracted.unlink(missing_ok=True)


def _orchestrate_body(
    *,
    working_pdf: Path,
    md_name: str,
    token: str,
    output_dir: Path,
    config: RootConfig,
    page_limit: int,
    max_workers: int,
    size_limit_bytes: int,
    num_pages: int,
    size_bytes: int,
    base_url: str,
    model_version: str,
    poll_interval: int,
    max_wait: int,
    include_header: bool,
    include_footer: bool,
    include_page_number: bool,
    include_footnote: bool,
    merge_paragraphs: bool,
    inline_footnotes: bool,
    cache_enabled: bool,
    cache_dir: Path | None,
    use_cache: bool,
    rate_limiter,
    target_chunk_pages: int = 0,
    progress_callback=None,
) -> str | None:
    needs_split = (
        (target_chunk_pages > 0 and num_pages > target_chunk_pages)
        or num_pages > page_limit
        or size_bytes > size_limit_bytes
    )

    common_md = dict(
        include_header=include_header,
        include_footer=include_footer,
        include_page_number=include_page_number,
        include_footnote=include_footnote,
        merge_paragraphs=merge_paragraphs,
        inline_footnotes=inline_footnotes,
    )

    if not needs_split:
        return parse_pdf_via_api(
            working_pdf,
            token,
            output_dir,
            config,
            base_url=base_url,
            model_version=model_version,
            poll_interval=poll_interval,
            max_wait=max_wait,
            cache_enabled=cache_enabled,
            cache_dir=cache_dir,
            use_cache=use_cache,
            save_zip_to_output=False,
            output_md_name=md_name,
            progress_callback=progress_callback,
            **common_md,
        )

    # 需要切分：片段输出到临时目录，合并后仅保留 xx.md 和 images/
    with tempfile.TemporaryDirectory(prefix=config.temp_dir_prefix) as tmp:
        temp_dir = Path(tmp)

        if progress_callback is not None:
            progress_callback("split_start", {})

        if target_chunk_pages > 0 and num_pages > target_chunk_pages:
            split_paths = split_pdf_adaptive(
                working_pdf,
                target_chunk_pages=target_chunk_pages,
                page_limit=page_limit,
                size_limit_bytes=size_limit_bytes,
                temp_dir=temp_dir,
            )
        else:
            split_paths = split_pdf_by_limits(
                working_pdf,
                page_limit=page_limit,
                size_limit_bytes=size_limit_bytes,
                temp_dir=temp_dir,
            )

        if progress_callback is not None:
            progress_callback("split_done", {"total_parts": len(split_paths)})

        part_results: dict[int, Path] = {}

        def parse_one(idx: int, part_path: Path) -> tuple[int, Path | None]:
            with rate_limiter:
                part_out = temp_dir / f"_part{idx}"
                part_out.mkdir(parents=True, exist_ok=True)
                ok = parse_pdf_via_api(
                    part_path,
                    token,
                    part_out,
                    config,
                    output_md_name=config.part_md_name,
                    base_url=base_url,
                    model_version=model_version,
                    poll_interval=poll_interval,
                    max_wait=max_wait,
                    cache_enabled=cache_enabled,
                    cache_dir=cache_dir,
                    use_cache=use_cache,
                    save_zip_to_output=False,
                    **common_md,
                )
                return (idx, part_out if ok else None)

        failed = 0
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = [ex.submit(parse_one, i, p) for i, p in enumerate(split_paths)]
            for fut in as_completed(futures):
                idx, result = fut.result()
                if result:
                    part_results[idx] = result
                    if progress_callback is not None:
                        progress_callback(
                            "part_complete", {"idx": idx, "total": len(split_paths)}
                        )
                else:
                    failed += 1

        if failed > 0:
            logger.error(f"有 {failed}/{len(split_paths)} 个片段解析失败")
            if progress_callback is not None:
                progress_callback(
                    "error",
                    {"error": f"有 {failed}/{len(split_paths)} 个片段解析失败"},
                )
            return None

        part_output_dirs = [part_results[i] for i in range(len(split_paths))]

        output_dir.mkdir(parents=True, exist_ok=True)
        if progress_callback is not None:
            progress_callback("merge", {})
        merged = merge_markdown_parts(
            part_output_dirs,
            output_dir,
            output_md_name=md_name,
            images_dir_name=config.output_images_dir,
            part_md_name=config.part_md_name,
        )
        _clean_output_dir(output_dir, md_name, config.output_images_dir)
        return merged

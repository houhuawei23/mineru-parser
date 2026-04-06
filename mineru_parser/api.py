"""MinerU API 模块：上传、轮询、下载。"""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING

import requests
from loguru import logger
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 默认 API 并发限制（信号量）
DEFAULT_API_RATE_LIMIT = 5

from mineru_parser.cache import get_cached_zip, save_to_cache
from mineru_parser.markdown import build_markdown_from_zip, merge_markdown_parts
from mineru_parser.pdf_splitter import (
    extract_pages_to_pdf,
    get_pdf_info,
    parse_pages_spec,
    split_pdf_by_limits,
)

if TYPE_CHECKING:
    from mineru_parser.config import Config

# Thread-local storage for sessions to ensure thread safety
_thread_local = threading.local()


def get_headers(token: str) -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }


def get_session(
    pool_connections: int = 10,
    pool_maxsize: int = 20,
    max_retries: int = 3,
) -> requests.Session:
    """
    获取带连接池的 requests.Session。

    使用线程本地存储确保线程安全。每个线程有自己的 session 实例。

    :param pool_connections: 保持的连接数（默认 10）
    :param pool_maxsize: 连接池最大大小（默认 20）
    :param max_retries: 重试次数（默认 3）
    :return: 配置好的 Session 实例
    """
    if not hasattr(_thread_local, "session"):
        session = requests.Session()

        # 配置重试策略
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )

        # 配置连接池
        adapter = HTTPAdapter(
            pool_connections=pool_connections,
            pool_maxsize=pool_maxsize,
            max_retries=retry_strategy,
        )

        session.mount("http://", adapter)
        session.mount("https://", adapter)

        _thread_local.session = session

    return _thread_local.session


def close_session() -> None:
    """关闭当前线程的 session。"""
    if hasattr(_thread_local, "session"):
        _thread_local.session.close()
        delattr(_thread_local, "session")


def apply_upload_urls(
    token: str,
    base_url: str,
    file_name: str,
    model_version: str,
    timeout: int,
    session: requests.Session | None = None,
) -> dict | None:
    """申请文件上传链接。返回 {"batch_id": "...", "file_urls": ["https://..."]} 或 None。"""
    url = f"{base_url}/file-urls/batch"
    data = {"files": [{"name": file_name}], "model_version": model_version}
    _session = session or get_session()
    try:
        resp = _session.post(url, headers=get_headers(token), json=data, timeout=timeout)
        if resp.status_code != 200:
            logger.error(f"申请上传链接失败: HTTP {resp.status_code}")
            return None
        body = resp.json()
        if body.get("code") != 0:
            logger.error(f"申请上传链接失败: code={body.get('code')}, msg={body.get('msg')}")
            return None
        data_obj = body.get("data", {})
        file_urls = data_obj.get("file_urls") or data_obj.get("files")
        batch_id = data_obj.get("batch_id")
        if not batch_id or not file_urls:
            logger.error(f"响应中缺少 batch_id 或 file_urls")
            return None
        return {"batch_id": batch_id, "file_urls": file_urls}
    except requests.RequestException as e:
        logger.error(f"申请上传链接异常: {e}")
        return None


def upload_file_to_url(
    pdf_path: Path,
    upload_url: str,
    timeout: int,
    session: requests.Session | None = None,
) -> bool:
    """将本地 PDF 用 PUT 上传到 upload_url。"""
    if not pdf_path.exists():
        logger.error(f"文件不存在: {pdf_path}")
        return False
    _session = session or get_session()
    try:
        with open(pdf_path, "rb") as f:
            resp = _session.put(upload_url, data=f, timeout=timeout)
        if resp.status_code != 200:
            logger.error(f"上传失败: HTTP {resp.status_code}")
            return False
        return True
    except requests.RequestException as e:
        logger.error(f"上传异常: {e}")
        return False


def poll_batch_result(
    token: str,
    base_url: str,
    batch_id: str,
    poll_interval: int,
    max_wait: int,
    timeout: int,
    session: requests.Session | None = None,
) -> dict | None:
    """轮询批量任务结果，直到 state=done 或失败或超时。"""
    url = f"{base_url}/extract-results/batch/{batch_id}"
    _session = session or get_session()
    start = time.time()
    while time.time() - start < max_wait:
        try:
            resp = _session.get(url, headers=get_headers(token), timeout=timeout)
            if resp.status_code != 200:
                time.sleep(poll_interval)
                continue
            body = resp.json()
            if body.get("code") != 0:
                time.sleep(poll_interval)
                continue
            results = body.get("data", {}).get("extract_result", [])
            if not results:
                time.sleep(poll_interval)
                continue
            first = results[0]
            state = first.get("state", "")
            if state == "done":
                zip_url = first.get("full_zip_url")
                if zip_url:
                    return first
                logger.error("state=done 但无 full_zip_url")
                return None
            if state == "failed":
                logger.error(f"解析失败: {first.get('err_msg', '未知原因')}")
                return None
            progress = first.get("extract_progress", {})
            if progress:
                logger.debug(
                    f"状态: {state}, "
                    f"{progress.get('extracted_pages', '?')}/{progress.get('total_pages', '?')}"
                )
            time.sleep(poll_interval)
        except requests.RequestException as e:
            logger.warning(f"轮询异常: {e}")
            time.sleep(poll_interval)
    logger.error("轮询超时")
    return None


def download_zip(
    zip_url: str,
    token: str,
    timeout: int,
    max_retries: int,
    retry_wait_cap: int,
    session: requests.Session | None = None,
) -> bytes | None:
    """下载 zip 内容，支持重试。"""
    import random
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    header_variants = [
        get_headers(token),
        {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
    ]
    last_error: Exception | None = None
    _session = session or get_session()

    for attempt in range(max_retries):
        if attempt > 0:
            # 指数退避 + 随机抖动，避免惊群效应
            wait = min(retry_wait_cap, 2**attempt) + random.uniform(0, 1)
            logger.info(f"下载重试 {attempt + 1}/{max_retries}，{wait:.1f}s 后重试...")
            time.sleep(wait)

        for verify_ssl in (True, False):
            for headers in header_variants:
                try:
                    resp = _session.get(
                        zip_url, headers=headers, timeout=timeout, verify=verify_ssl
                    )
                    if resp.status_code == 200:
                        if not verify_ssl:
                            logger.warning("已通过关闭 SSL 校验完成下载")
                        return resp.content
                except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as e:
                    last_error = e
    logger.error(f"下载 zip 失败（已重试 {max_retries} 次）: {last_error}")
    return None


def parse_pdf_via_api(
    pdf_path: Path,
    token: str,
    output_dir: Path,
    config: Config,
    base_url: str = "",
    model_version: str = "",
    poll_interval: int = 0,
    max_wait: int = 0,
    include_header: bool = False,
    include_footer: bool = False,
    include_page_number: bool = False,
    include_footnote: bool = True,
    merge_paragraphs: bool = True,
    inline_footnotes: bool = True,
    cache_enabled: bool = True,
    cache_dir: Path | None = None,
    use_cache: bool = True,
    save_zip_to_output: bool = False,
    output_md_name: str | None = None,
    session: requests.Session | None = None,
) -> str | None:
    """
    上传 PDF 到 MinerU API 解析，下载 zip，解压并生成 Markdown。
    支持缓存：相同 PDF 命中缓存时直接使用，避免重复调用 API。

    :param use_cache: 本次调用是否使用缓存（False 时强制重新解析）
    :param save_zip_to_output: 是否将 zip 保存到输出目录旁（默认否，仅缓存）
    :param output_md_name: 输出 md 文件名，默认 {pdf_stem}.md
    :param session: 可选的 requests Session，用于连接复用
    :return: markdown 字符串，失败返回 None
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
        return None

    # 尝试从缓存获取
    if cache_enabled and use_cache:
        zip_content = get_cached_zip(pdf_path, _cache_dir, config, model_version)
        if zip_content is not None:
            output_dir.mkdir(parents=True, exist_ok=True)
            if save_zip_to_output:
                zip_path = output_dir.parent / f"{pdf_path.stem}{zip_suffix}"
                zip_path.write_bytes(zip_content)
                logger.info(f"已保存 zip: {zip_path}")
            else:
                logger.debug("命中缓存，zip 已保存至缓存目录")
            markdown = build_markdown_from_zip(
                zip_content,
                output_dir,
                output_dir,
                include_header=include_header,
                include_footer=include_footer,
                include_page_number=include_page_number,
                include_footnote=include_footnote,
                merge_paragraphs=merge_paragraphs,
                inline_footnotes=inline_footnotes,
                output_md_name=md_name,
            )
            return markdown

    logger.info("正在申请上传链接...")
    apply_result = apply_upload_urls(
        token, base_url, pdf_path.name, model_version, config.request_timeout_apply, session=_session
    )
    if not apply_result:
        return None
    batch_id = apply_result["batch_id"]
    file_urls = apply_result["file_urls"]
    logger.info(f"batch_id: {batch_id}")

    logger.info("正在上传文件...")
    if not upload_file_to_url(pdf_path, file_urls[0], config.request_timeout_upload, session=_session):
        return None
    logger.info("上传成功，等待解析...")

    result = poll_batch_result(
        token,
        base_url,
        batch_id,
        poll_interval,
        max_wait,
        config.request_timeout_poll,
        session=_session,
    )
    if not result:
        return None
    zip_url = result.get("full_zip_url")
    if not zip_url:
        return None

    logger.info("正在下载解析结果...")
    zip_content = download_zip(
        zip_url,
        token,
        config.request_timeout_download,
        config.download_max_retries,
        config.download_retry_wait_cap,
        session=_session,
    )
    if not zip_content:
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    if save_zip_to_output:
        zip_path = output_dir.parent / f"{pdf_path.stem}{zip_suffix}"
        zip_path.write_bytes(zip_content)
        logger.info(f"已保存 zip: {zip_path}")

    # 写入缓存
    if cache_enabled and use_cache:
        save_to_cache(pdf_path, zip_content, _cache_dir, config, model_version)

    markdown = build_markdown_from_zip(
        zip_content,
        output_dir,
        output_dir,
        include_header=include_header,
        include_footer=include_footer,
        include_page_number=include_page_number,
        include_footnote=include_footnote,
        merge_paragraphs=merge_paragraphs,
        inline_footnotes=inline_footnotes,
        output_md_name=md_name,
    )
    return markdown


def parse_pdf_via_api_with_auto_split(
    pdf_path: Path,
    token: str,
    output_dir: Path,
    config: Config,
    file_size_limit_mb: float = 0,
    page_limit: int = 0,
    max_workers: int = 0,
    api_rate_limit: int = DEFAULT_API_RATE_LIMIT,
    base_url: str = "",
    model_version: str = "",
    poll_interval: int = 0,
    max_wait: int = 0,
    include_header: bool = False,
    include_footer: bool = False,
    include_page_number: bool = False,
    include_footnote: bool = True,
    merge_paragraphs: bool = True,
    inline_footnotes: bool = True,
    cache_enabled: bool = True,
    cache_dir: Path | None = None,
    use_cache: bool = True,
    pages_spec: str | None = None,
) -> str | None:
    """
    解析 PDF，若超出页数/大小限制则自动切分、并发处理、合并结果。

    :param file_size_limit_mb: 文件大小限制（MB），默认 200
    :param page_limit: 每片页数，默认 100
    :param max_workers: 最大并发线程数，默认 20
    :param api_rate_limit: API 并发限制（信号量），默认 5
    :param pages_spec: 可选，仅解析指定页，格式如 ``10-20,30-40``（1-based，与 CLI --pages 一致）
    :return: markdown 字符串，失败返回 None
    """
    file_size_limit_mb = file_size_limit_mb or config.file_size_limit_mb
    page_limit = page_limit or config.page_limit
    max_workers = max_workers or config.max_workers
    base_url = base_url or config.base_url
    model_version = model_version or config.model_version
    poll_interval = poll_interval or config.poll_interval
    max_wait = max_wait or config.max_wait

    if not pdf_path.exists():
        logger.error(f"文件不存在: {pdf_path}")
        return None

    working_pdf = pdf_path
    temp_extracted: Path | None = None
    md_stem = pdf_path.stem

    if pages_spec and pages_spec.strip():
        total_pages, _ = get_pdf_info(pdf_path)
        indices, _warns = parse_pages_spec(pages_spec, total_pages)
        if not indices:
            logger.error(
                "页码范围未选中任何有效页面（可能全部超出 PDF 页数），请检查 --pages"
            )
            return None
        try:
            tf = tempfile.NamedTemporaryFile(
                suffix=".pdf",
                delete=False,
                prefix=f"{pdf_path.stem}_pages_",
            )
            tf.close()
            temp_extracted = Path(tf.name)
            extract_pages_to_pdf(pdf_path, indices, temp_extracted)
        except Exception as e:
            logger.error(f"按页码提取 PDF 失败: {e}")
            if temp_extracted is not None:
                temp_extracted.unlink(missing_ok=True)
            return None
        working_pdf = temp_extracted
        logger.info(f"已按 --pages 提取 {len(indices)} 页用于解析")

    size_limit_bytes = int(file_size_limit_mb * 1024 * 1024)
    num_pages, size_bytes = get_pdf_info(working_pdf)

    md_name = f"{md_stem}.md"

    try:
        return _parse_pdf_via_api_with_auto_split_body(
            working_pdf=working_pdf,
            md_name=md_name,
            token=token,
            output_dir=output_dir,
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
            include_header=include_header,
            include_footer=include_footer,
            include_page_number=include_page_number,
            include_footnote=include_footnote,
            merge_paragraphs=merge_paragraphs,
            inline_footnotes=inline_footnotes,
            cache_enabled=cache_enabled,
            cache_dir=cache_dir,
            use_cache=use_cache,
            api_rate_limit=api_rate_limit,
        )
    finally:
        if temp_extracted is not None:
            temp_extracted.unlink(missing_ok=True)


def _parse_pdf_via_api_with_auto_split_body(
    working_pdf: Path,
    md_name: str,
    token: str,
    output_dir: Path,
    config: Config,
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
    api_rate_limit: int = DEFAULT_API_RATE_LIMIT,
) -> str | None:
    if num_pages <= page_limit and size_bytes <= size_limit_bytes:
        return parse_pdf_via_api(
            working_pdf,
            token,
            output_dir,
            config,
            base_url=base_url,
            model_version=model_version,
            poll_interval=poll_interval,
            max_wait=max_wait,
            include_header=include_header,
            include_footer=include_footer,
            include_page_number=include_page_number,
            include_footnote=include_footnote,
            merge_paragraphs=merge_paragraphs,
            inline_footnotes=inline_footnotes,
            cache_enabled=cache_enabled,
            cache_dir=cache_dir,
            use_cache=use_cache,
            save_zip_to_output=False,
            output_md_name=md_name,
        )

    # 需要切分：片段输出到临时目录，合并后仅保留 xx.md 和 images/
    with tempfile.TemporaryDirectory(prefix=config.temp_dir_prefix) as tmp:
        temp_dir = Path(tmp)
        split_paths = split_pdf_by_limits(
            working_pdf,
            page_limit=page_limit,
            size_limit_bytes=size_limit_bytes,
            temp_dir=temp_dir,
        )

        md_opts = dict(
            include_header=include_header,
            include_footer=include_footer,
            include_page_number=include_page_number,
            include_footnote=include_footnote,
            merge_paragraphs=merge_paragraphs,
            inline_footnotes=inline_footnotes,
        )
        api_opts = dict(
            config=config,
            token=token,
            base_url=base_url,
            model_version=model_version,
            poll_interval=poll_interval,
            max_wait=max_wait,
            cache_enabled=cache_enabled,
            cache_dir=cache_dir,
            use_cache=use_cache,
            save_zip_to_output=False,
        )

        part_results: dict[int, Path] = {}

        # 使用信号量限制并发 API 调用数
        api_semaphore = threading.Semaphore(api_rate_limit)

        def parse_one(idx: int, part_path: Path) -> tuple[int, Path | None]:
            with api_semaphore:
                part_out = temp_dir / f"_part{idx}"
                part_out.mkdir(parents=True, exist_ok=True)
                ok = parse_pdf_via_api(
                    part_path,
                    token,
                    part_out,
                    config,
                    output_md_name=config.part_md_name,
                    **{
                        k: v
                        for k, v in api_opts.items()
                        if k not in ("config", "token")
                    },
                    **md_opts,
                )
                return (idx, part_out if ok else None)

        failed = 0
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = [ex.submit(parse_one, i, p) for i, p in enumerate(split_paths)]
            for fut in as_completed(futures):
                idx, result = fut.result()
                if result:
                    part_results[idx] = result
                else:
                    failed += 1

        if failed > 0:
            logger.error(f"有 {failed}/{len(split_paths)} 个片段解析失败")
            return None

        part_output_dirs = [part_results[i] for i in range(len(split_paths))]

        output_dir.mkdir(parents=True, exist_ok=True)
        merged = merge_markdown_parts(
            part_output_dirs,
            output_dir,
            output_md_name=md_name,
            images_dir_name=config.output_images_dir,
            part_md_name=config.part_md_name,
        )

        # 清理结果目录中非 xx.md、images/ 的文件（如旧运行残留的 zip、_part* 等）
        _clean_output_dir(output_dir, md_name, config.output_images_dir)

        return merged


def _clean_output_dir(
    output_dir: Path, md_filename: str, images_dir_name: str = "images"
) -> None:
    """仅保留 xx.md 和 images/，移除其他文件与目录。"""
    keep = {md_filename, images_dir_name}
    for item in output_dir.iterdir():
        if item.name in keep:
            continue
        try:
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)
        except Exception:
            pass

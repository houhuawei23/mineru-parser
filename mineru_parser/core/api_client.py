"""MinerU API 传输层：申请上传链接、上传、轮询、下载。

这些函数仅负责与 MinerU HTTP 接口交互，不含分片/合并/缓存等编排逻辑。
所有 HTTP 调用复用线程本地的 ``requests.Session``（见 :mod:`mineru_parser.core.http`）。
"""

from __future__ import annotations

import random
import time
from pathlib import Path

import requests
from loguru import logger

from mineru_parser.core.http import get_session


def get_headers(token: str) -> dict[str, str]:
    """构造 MinerU API 请求头。"""
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }


def apply_upload_urls(
    token: str,
    base_url: str,
    file_name: str,
    model_version: str,
    timeout: int,
    session: requests.Session | None = None,
) -> dict | None:
    """申请文件上传链接。返回 ``{"batch_id": "...", "file_urls": [...]}`` 或 ``None``。"""
    url = f"{base_url}/file-urls/batch"
    data = {"files": [{"name": file_name}], "model_version": model_version}
    _session = session or get_session()
    try:
        resp = _session.post(
            url, headers=get_headers(token), json=data, timeout=timeout
        )
        if resp.status_code != 200:
            logger.error(f"申请上传链接失败: HTTP {resp.status_code}")
            return None
        body = resp.json()
        if body.get("code") != 0:
            logger.error(
                f"申请上传链接失败: code={body.get('code')}, msg={body.get('msg')}"
            )
            return None
        data_obj = body.get("data", {})
        file_urls = data_obj.get("file_urls") or data_obj.get("files")
        batch_id = data_obj.get("batch_id")
        if not batch_id or not file_urls:
            logger.error("响应中缺少 batch_id 或 file_urls")
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
    """将本地 PDF 用 PUT 上传到 ``upload_url``。"""
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
    progress_callback=None,
) -> dict | None:
    """轮询批量任务结果，直到 ``state=done``、失败或超时。"""
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
            poll_info: dict = {"state": state, "elapsed": time.time() - start}
            if progress:
                extracted = progress.get("extracted_pages")
                total = progress.get("total_pages")
                poll_info["extracted_pages"] = extracted
                poll_info["total_pages"] = total
                logger.debug(f"状态: {state}, {extracted or '?'}/{total or '?'}")
            if progress_callback is not None:
                progress_callback("poll", poll_info)
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
    allow_insecure_fallback: bool = False,
) -> bytes | None:
    """下载 zip 内容，支持重试。

    SSL 行为：默认仅使用 ``verify=True``。仅当 ``allow_insecure_fallback=True`` 时，
    才在 ``verify=True`` 的所有 header 变体失败后，降级尝试 ``verify=False``。
    不再全局关闭 urllib3 警告——降级时会显式 ``logger.warning``。
    """
    _session = session or get_session()
    header_variants = [
        get_headers(token),
        {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
    ]
    verify_options = [True, False] if allow_insecure_fallback else [True]
    last_error: Exception | None = None

    for attempt in range(max_retries):
        if attempt > 0:
            # 指数退避 + 随机抖动，避免惊群
            wait = min(retry_wait_cap, 2**attempt) + random.uniform(0, 1)
            logger.info(f"下载重试 {attempt + 1}/{max_retries}，{wait:.1f}s 后重试...")
            time.sleep(wait)

        for verify_ssl in verify_options:
            for headers in header_variants:
                try:
                    resp = _session.get(
                        zip_url, headers=headers, timeout=timeout, verify=verify_ssl
                    )
                    if resp.status_code == 200:
                        if not verify_ssl:
                            logger.warning("已通过关闭 SSL 校验完成下载")
                        return resp.content
                except (
                    requests.exceptions.SSLError,
                    requests.exceptions.ConnectionError,
                ) as e:
                    last_error = e
    logger.error(f"下载 zip 失败（已重试 {max_retries} 次）: {last_error}")
    return None

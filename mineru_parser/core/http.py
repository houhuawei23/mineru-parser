"""HTTP 连接池：线程本地的 ``requests.Session``，复用连接、内置重试退避。"""

from __future__ import annotations

import atexit
import threading

import requests
from loguru import logger
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 线程本地存储：每个线程一个 Session，保证线程安全
_thread_local = threading.local()


def get_session(
    pool_connections: int = 10,
    pool_maxsize: int = 20,
    max_retries: int = 3,
) -> requests.Session:
    """获取带连接池的 ``requests.Session``（线程本地、懒加载）。

    :param pool_connections: 保持的连接数
    :param pool_maxsize: 连接池最大大小
    :param max_retries: 重试次数（指数退避 + 抖动，针对 429/5xx）
    """
    if not hasattr(_thread_local, "session"):
        session = requests.Session()
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
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


# 主线程退出时回收其 session，避免连接泄漏告警
atexit.register(close_session)


def log_http_error(label: str, exc: Exception) -> None:
    """统一的 HTTP 异常日志辅助。"""
    logger.error(f"{label}: {exc}")

"""状态管理模块：用于批量处理的断点续传和任务追踪。

使用 SQLite 存储任务状态，支持：
- 任务状态追踪（pending/running/completed/failed）
- 断点续传（跳过已完成的任务）
- 失败重试计数
- 处理历史记录
"""

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional



class JobStatus(str, Enum):
    """任务状态枚举。"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class JobRecord:
    """任务记录数据类。"""
    file_path: str
    status: JobStatus
    retry_count: int
    created_at: str
    updated_at: str
    error_message: Optional[str] = None


class BatchStateManager:
    """批量处理状态管理器。

    使用线程本地存储确保线程安全。
    每个批次有一个独立的 state 文件。
    """

    def __init__(self, state_file: Path):
        """
        初始化状态管理器。

        :param state_file: SQLite 状态文件路径
        """
        self.state_file = state_file
        self._local = threading.local()
        self._transition_lock = threading.Lock()
        self._ensure_db()

    def _get_connection(self) -> sqlite3.Connection:
        """获取线程本地的数据库连接。"""
        if not hasattr(self._local, "connection"):
            self._local.connection = sqlite3.connect(str(self.state_file))
            self._local.connection.row_factory = sqlite3.Row
            # 启用 WAL 模式以提升并发写入性能
            self._local.connection.execute("PRAGMA journal_mode=WAL")
        return self._local.connection

    def _ensure_db(self) -> None:
        """确保数据库表结构存在。"""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS batch_jobs (
                    file_path TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    retry_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error_message TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_status ON batch_jobs(status)
            """)
            conn.commit()

    def get_job(self, file_path: str) -> Optional[JobRecord]:
        """
        获取任务记录。

        :param file_path: 文件路径
        :return: 任务记录或 None
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM batch_jobs WHERE file_path = ?",
                (file_path,)
            )
            row = cursor.fetchone()
            if row:
                return JobRecord(
                    file_path=row["file_path"],
                    status=JobStatus(row["status"]),
                    retry_count=row["retry_count"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    error_message=row["error_message"],
                )
            return None

    def create_job(self, file_path: str) -> None:
        """
        创建新任务记录。

        :param file_path: 文件路径
        """
        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO batch_jobs
                (file_path, status, retry_count, created_at, updated_at)
                VALUES (?, ?, 0, ?, ?)
                """,
                (file_path, JobStatus.PENDING.value, now, now),
            )
            conn.commit()

    def update_job(
        self,
        file_path: str,
        status: JobStatus,
        error_message: Optional[str] = None,
    ) -> None:
        """
        更新任务状态。

        :param file_path: 文件路径
        :param status: 新状态
        :param error_message: 错误信息（可选）
        """
        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            if status == JobStatus.FAILED:
                conn.execute(
                    """
                    UPDATE batch_jobs
                    SET status = ?, updated_at = ?, retry_count = retry_count + 1,
                        error_message = ?
                    WHERE file_path = ?
                    """,
                    (status.value, now, error_message, file_path),
                )
            else:
                conn.execute(
                    """
                    UPDATE batch_jobs
                    SET status = ?, updated_at = ?, error_message = ?
                    WHERE file_path = ?
                    """,
                    (status.value, now, error_message, file_path),
                )
            conn.commit()

    def should_process(self, file_path: str, resume: bool = True) -> bool:
        """
        判断文件是否应该被处理。

        :param file_path: 文件路径
        :param resume: 是否启用断点续传模式
        :return: 是否需要处理
        """
        if not resume:
            return True

        job = self.get_job(file_path)
        if job is None:
            return True

        # 已完成或正在运行的任务跳过
        if job.status in (JobStatus.COMPLETED, JobStatus.RUNNING):
            return False

        # 失败的任务最多重试 3 次
        if job.status == JobStatus.FAILED and job.retry_count >= 3:
            return False

        return True

    def try_start_job(self, file_path: str, resume: bool = True) -> bool:
        """
        原子化地检查任务是否应被处理并将其标记为 RUNNING。

        在并发批处理中防止两个线程同时看到 PENDING 并都尝试启动。
        使用 ``_transition_lock`` 保证检查与状态更新的原子性。

        :param file_path: 文件路径
        :param resume: 是否启用断点续传模式
        :return: 是否成功认领该任务
        """
        with self._transition_lock:
            job = self.get_job(file_path)
            if job is None:
                # 新任务：创建并认领
                self.create_job(file_path)
                self.update_job(file_path, JobStatus.RUNNING)
                return True

            if not resume:
                # 非续传模式：允许重新处理（但 RUNNING 的跳过）
                if job.status == JobStatus.RUNNING:
                    return False
                self.update_job(file_path, JobStatus.RUNNING)
                return True

            # 已完成或正在运行的任务跳过
            if job.status in (JobStatus.COMPLETED, JobStatus.RUNNING):
                return False

            # 失败的任务最多重试 3 次
            if job.status == JobStatus.FAILED and job.retry_count >= 3:
                return False

            # PENDING 或可重试的 FAILED：认领
            self.update_job(file_path, JobStatus.RUNNING)
            return True

    def get_pending_count(self) -> int:
        """获取待处理任务数量。"""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM batch_jobs WHERE status = ?",
                (JobStatus.PENDING.value,)
            )
            return cursor.fetchone()[0]

    def get_summary(self) -> dict:
        """
        获取批次摘要统计。

        :return: 状态统计字典
        """
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT status, COUNT(*) as count
                FROM batch_jobs
                GROUP BY status
            """)
            summary = {status.value: 0 for status in JobStatus}
            for row in cursor.fetchall():
                summary[row["status"]] = row["count"]
            return summary

    def reset_failed(self) -> int:
        """
        重置失败任务为待处理状态。

        :return: 重置的任务数量
        """
        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE batch_jobs
                SET status = ?, updated_at = ?, retry_count = 0, error_message = NULL
                WHERE status = ?
                """,
                (JobStatus.PENDING.value, now, JobStatus.FAILED.value),
            )
            conn.commit()
            return cursor.rowcount

    def close(self) -> None:
        """关闭数据库连接。"""
        if hasattr(self._local, "connection"):
            self._local.connection.close()
            delattr(self._local, "connection")

    def __enter__(self):
        """上下文管理器入口。"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口。"""
        self.close()
        return False


def get_state_file(input_dir: Path, output_dir: Path) -> Path:
    """
    获取状态文件路径。

    状态文件保存在输出目录，命名为 .mineru_batch_state.db

    :param input_dir: 输入目录
    :param output_dir: 输出目录
    :return: 状态文件路径
    """
    return output_dir / ".mineru_batch_state.db"

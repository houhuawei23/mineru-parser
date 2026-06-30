"""批量状态管理（断点续传）单元测试。"""

from __future__ import annotations

from pathlib import Path

from mineru_parser.engines.state import (
    BatchStateManager,
    JobStatus,
    get_state_file,
)


def test_state_file_path(tmp_path: Path) -> None:
    sf = get_state_file(tmp_path / "in", tmp_path / "out")
    assert sf.name == ".mineru_batch_state.db"
    assert sf.parent == tmp_path / "out"


def test_create_and_get_job(tmp_path: Path) -> None:
    with BatchStateManager(tmp_path / "state.db") as state:
        state.create_job("/x/a.pdf")
        job = state.get_job("/x/a.pdf")
        assert job is not None
        assert job.status is JobStatus.PENDING
        assert job.retry_count == 0


def test_update_job_status(tmp_path: Path) -> None:
    with BatchStateManager(tmp_path / "state.db") as state:
        state.create_job("/x/a.pdf")
        state.update_job("/x/a.pdf", JobStatus.COMPLETED)
        assert state.get_job("/x/a.pdf").status is JobStatus.COMPLETED

        state.create_job("/x/b.pdf")
        state.update_job("/x/b.pdf", JobStatus.RUNNING)
        state.update_job("/x/b.pdf", JobStatus.FAILED, "boom")
        job_b = state.get_job("/x/b.pdf")
        assert job_b.status is JobStatus.FAILED
        assert job_b.retry_count == 1
        assert job_b.error_message == "boom"


def test_should_process_resumes_completed(tmp_path: Path) -> None:
    with BatchStateManager(tmp_path / "state.db") as state:
        state.create_job("/x/a.pdf")
        state.update_job("/x/a.pdf", JobStatus.COMPLETED)
        # resume=True 时已完成的不应再处理
        assert state.should_process("/x/a.pdf", resume=True) is False
        # resume=False 时始终处理
        assert state.should_process("/x/a.pdf", resume=False) is True


def test_try_start_job_atomic_claim(tmp_path: Path) -> None:
    with BatchStateManager(tmp_path / "state.db") as state:
        state.create_job("/x/a.pdf")
        # 首次认领成功
        assert state.try_start_job("/x/a.pdf", resume=True) is True
        # 已 RUNNING，再次认领失败（避免重复处理）
        assert state.try_start_job("/x/a.pdf", resume=True) is False


def test_summary_and_reset_failed(tmp_path: Path) -> None:
    with BatchStateManager(tmp_path / "state.db") as state:
        for f in ("/x/a.pdf", "/x/b.pdf", "/x/c.pdf"):
            state.create_job(f)
        state.update_job("/x/a.pdf", JobStatus.COMPLETED)
        state.update_job("/x/b.pdf", JobStatus.FAILED, "err")
        summary = state.get_summary()
        assert summary[JobStatus.COMPLETED.value] == 1
        assert summary[JobStatus.FAILED.value] == 1
        assert summary[JobStatus.PENDING.value] == 1

        reset = state.reset_failed()
        assert reset == 1
        assert state.get_job("/x/b.pdf").status is JobStatus.PENDING

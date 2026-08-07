"""Long-running job model with real per-stage progress (改进方案1.md §5).

Progress is never a fake timer: every stage carries a fixed weight and the
stage itself reports its own completion ratio (e.g. "layout 18/29 pages").
"""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """Python 3.10 compatible StrEnum (3.11+ has it built in)."""

    def __str__(self) -> str:
        return str(self.value)
from typing import Any

from pydantic import BaseModel, Field


class JobType(StrEnum):
    PARSE = "PARSE"
    TRANSLATE = "TRANSLATE"
    INDEX = "INDEX"
    ASSET_EXTRACT = "ASSET_EXTRACT"
    CV_PROFILE = "CV_PROFILE"
    QUALITY = "QUALITY"
    REFERENCE_RESOLVE = "REFERENCE_RESOLVE"
    REFERENCE_IMPORT = "REFERENCE_IMPORT"


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# Fixed stage weights (改进方案1.md §5.1). Sum == 1.0.
JOB_STAGE_WEIGHTS: dict[str, float] = {
    "file_validation": 0.05,
    "metadata_and_pages": 0.10,
    "layout_and_text": 0.25,
    "sections": 0.12,
    "assets": 0.18,
    "references": 0.10,
    "index": 0.10,
    "initial_translation": 0.10,
}


class JobStage(BaseModel):
    key: str
    status: JobStatus = JobStatus.QUEUED
    ratio: float = 0.0  # 0..1 within this stage
    detail: str = ""  # "18 / 29 pages"
    # 耗时证据（日志系统 V3.6）：mark_stage 自动记录时间戳，前端进度条可
    # 展示每步耗时，快速定位慢在哪个阶段
    started_at: str = ""
    finished_at: str = ""

    @property
    def duration_seconds(self) -> float:
        """Wall time of a finished stage; 0.0 while running/queued."""
        try:
            from datetime import datetime

            start = datetime.fromisoformat(self.started_at)
            finish = datetime.fromisoformat(self.finished_at) if self.finished_at else None
        except ValueError:
            return 0.0
        return round((finish - start).total_seconds(), 2) if finish else 0.0


class Job(BaseModel):
    job_id: str
    job_type: JobType
    paper_id: str = ""
    paper_version_id: str = ""
    owner_id: str = ""
    status: JobStatus = JobStatus.QUEUED
    stages: dict[str, JobStage] = Field(default_factory=dict)
    error_code: str = ""
    error_message: str = ""
    result_uri: str = ""
    created_at: str = ""
    updated_at: str = ""

    def progress(self) -> float:
        """Σ(stage_weight × stage_completed_ratio); finished stages are ratio 1."""
        total = 0.0
        for key, weight in JOB_STAGE_WEIGHTS.items():
            stage = self.stages.get(key)
            ratio = 1.0 if stage is None and self.status == JobStatus.SUCCEEDED else (
                stage.ratio if stage else 0.0
            )
            if stage and stage.status == JobStatus.SUCCEEDED:
                ratio = 1.0
            total += weight * ratio
        return round(min(total, 1.0), 4)

    def mark_stage(self, key: str, *, status: JobStatus, ratio: float = 0.0, detail: str = "") -> None:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        existing = self.stages.get(key)
        if status == JobStatus.QUEUED:
            # 预注册（V3.10）不记时间戳：直接 SUCCEEDED 的阶段才不会
            # 把"预注册到完成"的全程误算成本阶段耗时（fix 2026-08-04）
            self.stages[key] = JobStage(
                key=key, status=status, ratio=ratio, detail=detail,
                started_at="", finished_at="",
            )
            return
        if existing and existing.status == JobStatus.RUNNING and status in (
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
        ):
            # finishing an in-flight stage: keep its start time
            self.stages[key] = JobStage(
                key=key, status=status, ratio=ratio, detail=detail,
                started_at=existing.started_at, finished_at=now,
            )
            return
        # re-marking a RUNNING stage (progress updates) must keep the first
        # start time, or the stage duration collapses to ~0s (fix 2026-08-04)
        if status == JobStatus.RUNNING and existing and existing.started_at:
            started = existing.started_at
        else:
            # QUEUED 预注册无 started_at：直接 SUCCEEDED 的阶段视为瞬时
            #（started=now → 0.0s），只有 RUNNING 才真正开启计时
            started = now if status == JobStatus.RUNNING else ""
        finished = now if status in (JobStatus.SUCCEEDED, JobStatus.FAILED) else ""
        self.stages[key] = JobStage(
            key=key, status=status, ratio=ratio, detail=detail,
            started_at=started, finished_at=finished,
        )


# Agent-facing structured events (SSE payloads; only validated claims reach the UI).
class JobEvent(BaseModel):
    event: str  # stage_started | stage_progress | job_succeeded | job_failed | claim_validated
    job_id: str = ""
    stage: str = ""
    progress: float = 0.0
    payload: dict[str, Any] = Field(default_factory=dict)

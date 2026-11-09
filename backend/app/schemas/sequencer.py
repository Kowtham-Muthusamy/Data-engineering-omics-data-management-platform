from typing import Any, Optional

from pydantic import BaseModel

from app.schemas.common import ORM, UtcDt


class ScanOut(ORM):
    id: int
    trigger: str
    started_at: UtcDt
    finished_at: Optional[UtcDt]
    discovered_folders: int
    new_runs: int
    new_samples: int
    changed_versions: int
    skipped_folders: int
    unchanged_samples: int
    failed_operations: int
    jobs_submitted: int
    details: list[Any]


class SequencerStatus(BaseModel):
    scanning: bool
    auto_scan_enabled: bool
    interval_seconds: int
    next_scan_at: Optional[UtcDt]
    last_scan: Optional[ScanOut]
    scans_total: int


class SettingsOut(BaseModel):
    scan_interval_seconds: int
    auto_scan_enabled: bool
    auto_process: bool
    s3_versioning_enabled: bool
    warning_policy: str


class SettingsUpdate(BaseModel):
    scan_interval_seconds: Optional[int] = None
    auto_scan_enabled: Optional[bool] = None
    auto_process: Optional[bool] = None
    s3_versioning_enabled: Optional[bool] = None
    warning_policy: Optional[str] = None

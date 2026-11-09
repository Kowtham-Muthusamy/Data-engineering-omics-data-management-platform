from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.common import ORM, UtcDt


class RunCreate(BaseModel):
    run_id: Optional[str] = Field(None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    sample_count: int = Field(1, ge=0, le=12)
    scenarios: Optional[list[str]] = None
    mark_complete: bool = True
    catalogue_version: str = Field("V1", pattern=r"^V\d+$")


class SampleAdd(BaseModel):
    sample_id: Optional[str] = Field(None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    scenario: str = "A_GOOD"
    catalogue_version: str = Field("V1", pattern=r"^V\d+$")


class SampleSummary(ORM):
    sample_id: str
    run_id: str
    catalogue_version: str
    processed_version: Optional[str]
    status: str
    quality_status: str
    last_processed_at: Optional[UtcDt]
    latest_attempt_id: Optional[int]
    s3_destination: str


class RunOut(BaseModel):
    run_id: str
    state: str                      # NOT_DISCOVERED | INCOMPLETE | DISCOVERED | PROCESSING | PASSED | FAILED | ...
    complete: bool
    discovered: bool
    discovered_at: Optional[UtcDt] = None
    sample_count: int
    status_counts: dict[str, int] = {}
    samples: list[SampleSummary] = []
    nfs_samples: list[str] = []

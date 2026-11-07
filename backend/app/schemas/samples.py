from typing import Any, Optional

from pydantic import BaseModel, Field

from app.schemas.common import ORM, UtcDt
from app.schemas.runs import SampleSummary


class CatalogueUpdate(BaseModel):
    version: str = Field(..., pattern=r"^V\d+$", examples=["V2"])
    notes: Optional[str] = None
    fields: dict[str, Any] = Field(default_factory=dict, description=(
        "extra catalogue fields to set. Simulation hooks: 'simulation_scenario' "
        "(A_GOOD | B_POOR_QUALITY | C_INSTRUMENT_WARNING) and 'fault' "
        "({step, kind: transient|permanent|crash, times})."))


class BaseRecallIn(BaseModel):
    note: Optional[str] = None


class CatalogueVersionOut(ORM):
    id: int
    version: str
    source: str
    content: dict[str, Any]
    created_at: UtcDt


class AttemptOut(ORM):
    id: int
    attempt_no: int
    kind: str
    catalogue_version: str
    status: str
    qc_status: Optional[str]
    accepted: bool
    triggered_by: str
    job_id: Optional[str]
    error: Optional[str]
    created_at: UtcDt
    started_at: Optional[UtcDt]
    ended_at: Optional[UtcDt]


class SampleDetail(SampleSummary):
    eligible_for_downstream: bool
    downstream_reason: str
    nfs_complete: bool
    metadata: dict[str, Any] = {}


class HistoryOut(BaseModel):
    sample_id: str
    run_id: str
    current_status: str
    catalogue_version: str
    processed_version: Optional[str]
    catalogue_versions: list[CatalogueVersionOut]
    attempts: list[AttemptOut]
    s3_objects: list[dict[str, Any]]
    events: list[dict[str, Any]]


class SearchHit(ORM):
    sample_id: str
    run_id: str
    catalogue_version: str
    processing_status: str
    quality_status: str
    created_at: UtcDt
    indexed_at: UtcDt
    document: dict[str, Any]


class SearchResult(BaseModel):
    total: int
    items: list[SearchHit]

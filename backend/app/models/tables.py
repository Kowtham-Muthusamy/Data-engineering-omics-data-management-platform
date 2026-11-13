"""All tables.

Two logical stores live in one SQLite file but are kept strictly separate:

* operational state tracking (the "DynamoDB" simulator): runs, samples,
  catalogue_versions, processing_attempts, workflow_jobs/steps, quality_results
* the metadata search index (the "OpenSearch" simulator): ``search_index``,
  which is derived from state and never read to make state decisions.
"""
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.utils.common import utcnow


class Base(DeclarativeBase):
    pass


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


# --------------------------------------------------------------------------
# DynamoDB simulator: operational state
# --------------------------------------------------------------------------
class Run(Base):
    __tablename__ = "runs"
    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    nfs_path: Mapped[str] = mapped_column(Text)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    s3_destination: Mapped[str] = mapped_column(Text, default="")
    samples: Mapped[list["Sample"]] = relationship(back_populates="run", order_by="Sample.sample_id")


class Sample(Base):
    __tablename__ = "samples"
    sample_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), index=True)
    # catalogue version currently on record vs. the version last *successfully* processed
    catalogue_version: Mapped[str] = mapped_column(String(16))
    processed_version: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    # DISCOVERED INGESTING INGESTED PROCESSING QC_PENDING PASSED FAILED RERUN_REQUIRED
    status: Mapped[str] = mapped_column(String(20), default="DISCOVERED", index=True)
    # NOT_RUN PENDING PASS FAIL STALE
    quality_status: Mapped[str] = mapped_column(String(16), default="NOT_RUN")
    last_processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    latest_attempt_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    s3_destination: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    run: Mapped[Run] = relationship(back_populates="samples")


class CatalogueVersion(Base):
    __tablename__ = "catalogue_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sample_id: Mapped[str] = mapped_column(ForeignKey("samples.sample_id"), index=True)
    version: Mapped[str] = mapped_column(String(16))
    content: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    fingerprint: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(32))  # nfs_scan | scientist_update
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ProcessingAttempt(Base):
    __tablename__ = "processing_attempts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sample_id: Mapped[str] = mapped_column(ForeignKey("samples.sample_id"), index=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    attempt_no: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))  # INITIAL | BASE_RECALL | RETRY
    catalogue_version: Mapped[str] = mapped_column(String(16))
    # QUEUED RUNNING PASSED FAILED SUPERSEDED INTERRUPTED
    status: Mapped[str] = mapped_column(String(16), default="QUEUED")
    qc_status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    triggered_by: Mapped[str] = mapped_column(String(32), default="sequencer")
    job_id: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class WorkflowJob(Base):
    __tablename__ = "workflow_jobs"
    job_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    sample_id: Mapped[str] = mapped_column(String(64), index=True)
    attempt_id: Mapped[int] = mapped_column(Integer, index=True)
    # QUEUED RUNNING SUCCEEDED FAILED INTERRUPTED
    status: Mapped[str] = mapped_column(String(16), default="QUEUED")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    steps: Mapped[list["WorkflowStep"]] = relationship(order_by="WorkflowStep.step_order", cascade="all, delete-orphan")


class WorkflowStep(Base):
    __tablename__ = "workflow_steps"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("workflow_jobs.job_id"), index=True)
    step_order: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(48))
    # PENDING RUNNING SUCCEEDED FAILED SKIPPED INTERRUPTED
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    retries: Mapped[int] = mapped_column(Integer, default=0)
    logs: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class QualityResult(Base):
    __tablename__ = "quality_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    attempt_id: Mapped[int] = mapped_column(Integer, unique=True)
    sample_id: Mapped[str] = mapped_column(String(64), index=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    catalogue_version: Mapped[str] = mapped_column(String(16))
    interop: Mapped[dict[str, Any]] = mapped_column(JSON)
    fastqc: Mapped[dict[str, Any]] = mapped_column(JSON)
    overall: Mapped[str] = mapped_column(String(8))  # PASS | FAIL
    reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# --------------------------------------------------------------------------
# S3 simulator bookkeeping
# --------------------------------------------------------------------------
class S3Object(Base):
    """Current object at a key. A rerun REPLACES the row/content for the same key."""

    __tablename__ = "s3_objects"
    key: Mapped[str] = mapped_column(String(500), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    sample_id: Mapped[str] = mapped_column(String(64), index=True)
    size: Mapped[int] = mapped_column(Integer)
    checksum: Mapped[str] = mapped_column(String(64))            # sha256 of the stored object
    nfs_checksum: Mapped[str] = mapped_column(String(64))        # sha256 of the NFS file at upload time
    attempt_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    catalogue_version: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    overwrite_count: Mapped[int] = mapped_column(Integer, default=0)
    first_uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class S3ObjectVersion(Base):
    """Native S3-style object versions. Only written when the (default OFF) versioning
    simulation is enabled. Unrelated to catalogue versions."""

    __tablename__ = "s3_object_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(500), index=True)
    version_id: Mapped[str] = mapped_column(String(32))
    size: Mapped[int] = mapped_column(Integer)
    checksum: Mapped[str] = mapped_column(String(64))
    is_latest: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# --------------------------------------------------------------------------
# OpenSearch simulator: derived metadata index (never used for state decisions)
# --------------------------------------------------------------------------
class SearchIndex(Base):
    __tablename__ = "search_index"
    sample_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    catalogue_version: Mapped[str] = mapped_column(String(16), index=True)
    processing_status: Mapped[str] = mapped_column(String(20), index=True)
    quality_status: Mapped[str] = mapped_column(String(16), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    indexed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    document: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    text: Mapped[str] = mapped_column(Text, default="")


# --------------------------------------------------------------------------
# Sequencer + audit
# --------------------------------------------------------------------------
class ScanRecord(Base):
    __tablename__ = "scan_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trigger: Mapped[str] = mapped_column(String(16))  # manual | auto
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    discovered_folders: Mapped[int] = mapped_column(Integer, default=0)
    new_runs: Mapped[int] = mapped_column(Integer, default=0)
    new_samples: Mapped[int] = mapped_column(Integer, default=0)
    changed_versions: Mapped[int] = mapped_column(Integer, default=0)
    skipped_folders: Mapped[int] = mapped_column(Integer, default=0)
    unchanged_samples: Mapped[int] = mapped_column(Integer, default=0)
    failed_operations: Mapped[int] = mapped_column(Integer, default=0)
    jobs_submitted: Mapped[int] = mapped_column(Integer, default=0)
    details: Mapped[list[Any]] = mapped_column(JSON, default=list)


class ActivityLog(Base):
    __tablename__ = "activity_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    level: Mapped[str] = mapped_column(String(8), default="INFO")
    source: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text)
    run_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    sample_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class AuditLog(Base):
    """Append-only record of API activity. Rows form a hash chain (``row_hash`` covers
    ``prev_hash``) so edits or deletions are detectable via /api/audit/verify."""
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    actor: Mapped[str] = mapped_column(String(64), default="anonymous")   # claimed via X-Actor; there is no auth
    client_ip: Mapped[str] = mapped_column(String(64))
    method: Mapped[str] = mapped_column(String(8))
    route: Mapped[str] = mapped_column(String(200))     # route template, e.g. /api/samples/{sample_id}/base-recall
    path: Mapped[str] = mapped_column(String(500))
    resource: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    status_code: Mapped[int] = mapped_column(Integer, index=True)
    outcome: Mapped[str] = mapped_column(String(16), index=True)        # SUCCESS|REJECTED|DENIED|RATE_LIMITED|ERROR
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    prev_hash: Mapped[str] = mapped_column(String(64), default="")
    row_hash: Mapped[str] = mapped_column(String(64), default="")


Index("ix_attempt_sample_no", ProcessingAttempt.sample_id, ProcessingAttempt.attempt_no, unique=True)

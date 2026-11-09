"""State tracking (the "DynamoDB" simulator): sample state machine + processing attempts.

All status changes go through ``transition``; attempts are claimed with a single atomic
conditional UPDATE so two scans/clicks can never start the same sample twice.
"""
import uuid
from typing import Optional

from sqlalchemy import func, update
from sqlalchemy.orm import Session

from app.models.tables import ProcessingAttempt, Sample, WorkflowJob, WorkflowStep
from app.services import search_index
from app.services.activity import log_event
from app.utils.common import utcnow

STATES = ["DISCOVERED", "INGESTING", "INGESTED", "PROCESSING", "QC_PENDING", "PASSED", "FAILED", "RERUN_REQUIRED"]

ALLOWED: dict[str, set[str]] = {
    "DISCOVERED": {"INGESTING"},
    "INGESTING": {"INGESTED", "FAILED"},
    "INGESTED": {"PROCESSING", "FAILED"},
    "PROCESSING": {"QC_PENDING", "FAILED"},
    "QC_PENDING": {"PASSED", "FAILED", "RERUN_REQUIRED"},
    "PASSED": {"RERUN_REQUIRED"},
    "FAILED": {"RERUN_REQUIRED", "INGESTING"},
    "RERUN_REQUIRED": {"INGESTING"},
}

# which sample states each attempt kind may start from
START_FROM = {"INITIAL": {"DISCOVERED"}, "BASE_RECALL": {"RERUN_REQUIRED"}, "RETRY": {"FAILED"}}

WORKFLOW_STEPS = ["validate_source", "sync_to_s3", "register_ingestion", "instrument_metrics", "interop",
                  "fastqc", "evaluate_quality", "update_final_status", "publish_downstream"]


class InvalidTransition(Exception):
    pass


class Conflict(Exception):
    """The requested operation is not valid for the sample's current state."""


def transition(session: Session, sample: Sample, new_status: str, note: str = "") -> None:
    if new_status == sample.status:
        return
    if new_status not in ALLOWED.get(sample.status, set()):
        raise InvalidTransition(f"{sample.sample_id}: {sample.status} -> {new_status} is not allowed")
    old = sample.status
    sample.status = new_status
    sample.updated_at = utcnow()
    log_event(session, "state", f"{sample.sample_id}: {old} -> {new_status}" + (f" ({note})" if note else ""),
              run_id=sample.run_id, sample_id=sample.sample_id)
    search_index.index_sample(session, sample)


def start_attempt(session: Session, sample_id: str, kind: str, triggered_by: str) -> tuple[ProcessingAttempt, WorkflowJob]:
    """Atomically claim a sample and create its attempt + job + pending steps (caller commits)."""
    started_from = START_FROM[kind]
    previous = session.query(Sample.status).filter_by(sample_id=sample_id).scalar()
    claimed = session.execute(
        update(Sample).where(Sample.sample_id == sample_id, Sample.status.in_(started_from))
        .values(status="INGESTING", quality_status="PENDING", updated_at=utcnow())
    )
    sample = session.get(Sample, sample_id)
    if claimed.rowcount != 1:
        current = sample.status if sample else "unknown sample"
        raise Conflict(f"cannot start {kind} for {sample_id}: sample is {current} "
                       f"(requires {' or '.join(sorted(started_from))})")
    session.refresh(sample)

    attempt_no = (session.query(func.max(ProcessingAttempt.attempt_no)).filter_by(sample_id=sample_id).scalar() or 0) + 1
    session.query(ProcessingAttempt).filter_by(sample_id=sample_id).update({"accepted": False})
    attempt = ProcessingAttempt(sample_id=sample_id, run_id=sample.run_id, attempt_no=attempt_no, kind=kind,
                                catalogue_version=sample.catalogue_version, status="QUEUED", triggered_by=triggered_by)
    session.add(attempt)
    session.flush()
    job = WorkflowJob(job_id=f"job-{uuid.uuid4().hex[:10]}", run_id=sample.run_id, sample_id=sample_id,
                      attempt_id=attempt.id, status="QUEUED")
    session.add(job)
    attempt.job_id = job.job_id
    session.flush()
    for i, name in enumerate(WORKFLOW_STEPS):
        session.add(WorkflowStep(job_id=job.job_id, step_order=i, name=name, status="PENDING"))
    sample.latest_attempt_id = attempt.id
    log_event(session, "state", f"{sample_id}: {previous} -> INGESTING (claimed for attempt #{attempt_no})",
              run_id=sample.run_id, sample_id=sample_id)
    log_event(session, "state", f"{sample_id}: attempt #{attempt_no} ({kind}) created for catalogue "
                                f"{sample.catalogue_version} -> {job.job_id}", run_id=sample.run_id, sample_id=sample_id)
    search_index.index_sample(session, sample)
    session.flush()
    return attempt, job


def latest_attempt(session: Session, sample: Sample) -> Optional[ProcessingAttempt]:
    return session.get(ProcessingAttempt, sample.latest_attempt_id) if sample.latest_attempt_id else None

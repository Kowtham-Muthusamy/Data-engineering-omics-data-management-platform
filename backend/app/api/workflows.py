from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.tables import ProcessingAttempt, QualityResult, Run, Sample, WorkflowJob
from app.schemas.common import ORM, UtcDt
from app.services import downstream, state
from app.services.activity import log_event
from app.workers import job_runner

router = APIRouter(prefix="/api", tags=["workflows (local simulation of AWS Batch + miniWDL)"])

SIMULATION_NOTICE = "Local simulation - this is not AWS Batch or miniWDL."


class StepOut(ORM):
    step_order: int
    name: str
    status: str
    retries: int
    logs: str
    error: Optional[str]
    started_at: Optional[UtcDt]
    ended_at: Optional[UtcDt]


class JobOut(ORM):
    job_id: str
    run_id: str
    sample_id: str
    attempt_id: int
    status: str
    error: Optional[str]
    created_at: UtcDt
    started_at: Optional[UtcDt]
    ended_at: Optional[UtcDt]
    simulated: bool = True


class JobDetail(JobOut):
    steps: list[StepOut]
    attempt_no: Optional[int] = None
    attempt_kind: Optional[str] = None
    catalogue_version: Optional[str] = None
    notice: str = SIMULATION_NOTICE


class ExecuteIn(BaseModel):
    sample_ids: Optional[list[str]] = None


@router.get("/workflows", response_model=list[JobOut])
def list_jobs(run_id: Optional[str] = None, sample_id: Optional[str] = None, status: Optional[str] = None,
              limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    q = db.query(WorkflowJob)
    if run_id:
        q = q.filter(WorkflowJob.run_id == run_id)
    if sample_id:
        q = q.filter(WorkflowJob.sample_id == sample_id)
    if status:
        q = q.filter(WorkflowJob.status == status.upper())
    return q.order_by(WorkflowJob.created_at.desc(), WorkflowJob.job_id).limit(limit).all()


@router.get("/workflows/{job_id}", response_model=JobDetail)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(WorkflowJob, job_id)
    if job is None:
        raise HTTPException(404, f"job {job_id} not found")
    attempt = db.get(ProcessingAttempt, job.attempt_id)
    detail = JobDetail.model_validate(job)
    if attempt:
        detail.attempt_no, detail.attempt_kind, detail.catalogue_version = (
            attempt.attempt_no, attempt.kind, attempt.catalogue_version)
    return detail


@router.post("/workflows/{run_id}/execute", status_code=202)
def execute_run(run_id: str, body: Optional[ExecuteIn] = None, db: Session = Depends(get_db)):
    """Submit the workflow for every sample in the run that is waiting (DISCOVERED) or can be
    retried (FAILED). Samples already processing, passed, or awaiting an explicit base recall are skipped."""
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(404, f"run {run_id} has not been discovered yet - run a sequencer scan first")
    wanted = set(body.sample_ids) if body and body.sample_ids else None
    submitted, skipped = [], []
    for sample in run.samples:
        if wanted is not None and sample.sample_id not in wanted:
            continue
        kind = "INITIAL" if sample.status == "DISCOVERED" else "RETRY" if sample.status == "FAILED" else None
        if kind is None:
            skipped.append({"sample_id": sample.sample_id, "status": sample.status})
            continue
        try:
            attempt, job = state.start_attempt(db, sample.sample_id, kind, "user")
        except state.Conflict as e:
            skipped.append({"sample_id": sample.sample_id, "status": sample.status, "reason": str(e)})
            continue
        submitted.append({"sample_id": sample.sample_id, "job_id": job.job_id, "attempt_no": attempt.attempt_no,
                          "kind": kind})
    if not submitted:
        raise HTTPException(409, {"message": "no samples in this run are eligible to start", "skipped": skipped})
    log_event(db, "workflow", f"manual execute for {run_id}: {len(submitted)} job(s)", run_id=run_id)
    db.commit()  # jobs must be durable before workers see them
    for item in submitted:
        job_runner.submit(item["job_id"])
    return {"run_id": run_id, "submitted": submitted, "skipped": skipped, "notice": SIMULATION_NOTICE}


@router.post("/system/recover", tags=["system"])
def recover_jobs():
    """Recover jobs left RUNNING by a dead worker (also runs automatically at startup)."""
    return {"resubmitted_jobs": job_runner.recover()}


# ----------------------------------------------------------------- QC
@router.get("/qc/results", tags=["quality control"])
def qc_results(sample_id: Optional[str] = None, run_id: Optional[str] = None, overall: Optional[str] = None,
               latest_only: bool = False, db: Session = Depends(get_db)):
    """Simulated InterOp + FastQC results for each processing attempt."""
    q = db.query(QualityResult)
    if sample_id:
        q = q.filter(QualityResult.sample_id == sample_id)
    if run_id:
        q = q.filter(QualityResult.run_id == run_id)
    if overall:
        q = q.filter(QualityResult.overall == overall.upper())
    rows = q.order_by(QualityResult.id.desc()).all()
    latest_ids = {s.latest_attempt_id for s in db.query(Sample).all()}
    out = []
    for r in rows:
        is_latest = r.attempt_id in latest_ids
        if latest_only and not is_latest:
            continue
        attempt = db.get(ProcessingAttempt, r.attempt_id)
        out.append({
            "id": r.id, "attempt_id": r.attempt_id, "attempt_no": attempt.attempt_no if attempt else None,
            "sample_id": r.sample_id, "run_id": r.run_id, "catalogue_version": r.catalogue_version,
            "overall": r.overall, "reasons": r.reasons, "interop": r.interop, "fastqc": r.fastqc,
            "is_latest_attempt": is_latest, "simulated": True, "created_at": r.created_at.isoformat() + "Z",
        })
    return out

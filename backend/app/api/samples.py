from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.tables import ActivityLog, CatalogueVersion, ProcessingAttempt, S3Object, Sample
from app.schemas.runs import SampleSummary
from app.schemas.samples import (AttemptOut, BaseRecallIn, CatalogueUpdate, CatalogueVersionOut, HistoryOut,
                                 SampleDetail, SearchResult)
from app.services import catalogue, downstream, nfs, search_index, state
from app.simulators.data_gen import SCENARIOS
from app.services.activity import log_event

router = APIRouter(prefix="/api", tags=["samples, reruns & metadata"])


def _get_sample(db: Session, sample_id: str) -> Sample:
    sample = db.get(Sample, sample_id)
    if sample is None:
        raise HTTPException(404, f"sample {sample_id} not found")
    return sample


@router.get("/samples", response_model=list[SampleSummary])
def list_samples(run_id: Optional[str] = None, status: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(Sample)
    if run_id:
        q = q.filter(Sample.run_id == run_id)
    if status:
        q = q.filter(Sample.status == status.upper())
    return q.order_by(Sample.sample_id).all()


@router.get("/samples/{sample_id}", response_model=SampleDetail)
def get_sample(sample_id: str, db: Session = Depends(get_db)):
    sample = _get_sample(db, sample_id)
    ok, reason = downstream.eligibility(db, sample)
    try:
        meta = nfs.read_metadata(sample.run_id, sample.sample_id)
    except Exception:
        meta = {}
    return SampleDetail(**SampleSummary.model_validate(sample).model_dump(), eligible_for_downstream=ok,
                        downstream_reason=reason, nfs_complete=nfs.is_complete(sample.run_id), metadata=meta)


@router.post("/samples/{sample_id}/catalogue/update", response_model=CatalogueVersionOut)
def update_catalogue(sample_id: str, body: CatalogueUpdate, db: Session = Depends(get_db)):
    """Scientist updates catalogue information (V1 -> V2 ...). A sample that was already
    processed with a different version becomes RERUN_REQUIRED."""
    sample = _get_sample(db, sample_id)
    scenario = body.fields.get("simulation_scenario")
    if scenario is not None and scenario not in SCENARIOS:
        raise HTTPException(422, f"simulation_scenario must be one of {list(SCENARIOS)}")
    try:
        row = catalogue.update_catalogue(db, sample, body.version, body.notes, body.fields)
        db.commit()
        return row
    except catalogue.CatalogueError as e:
        raise HTTPException(409 if "already at" in str(e) else 422, str(e))
    except (nfs.NfsError, OSError, ValueError) as e:
        raise HTTPException(422, f"cannot update source catalogue: {e}")


@router.post("/samples/{sample_id}/base-recall", status_code=202)
def base_recall(sample_id: str, body: Optional[BaseRecallIn] = None, db: Session = Depends(get_db)):
    """Re-run the workflow for the SAME sample with its current catalogue version.
    Files are re-synchronised to the same S3 keys (overwriting) and a new processing attempt is recorded."""
    from app.workers import job_runner
    _get_sample(db, sample_id)
    try:
        attempt, job = state.start_attempt(db, sample_id, "BASE_RECALL", "scientist")
    except state.Conflict as e:
        raise HTTPException(409, str(e))
    log_event(db, "rerun", f"base recall initiated for {sample_id} (attempt #{attempt.attempt_no}, catalogue "
                           f"{attempt.catalogue_version})" + (f": {body.note}" if body and body.note else ""),
              run_id=attempt.run_id, sample_id=sample_id)
    db.commit()  # the job must be durable before a worker picks it up
    job_runner.submit(job.job_id)
    db.refresh(attempt)
    return {"sample_id": sample_id, "attempt_id": attempt.id, "attempt_no": attempt.attempt_no,
            "catalogue_version": attempt.catalogue_version, "job_id": job.job_id}


@router.get("/samples/{sample_id}/history", response_model=HistoryOut)
def sample_history(sample_id: str, db: Session = Depends(get_db)):
    sample = _get_sample(db, sample_id)
    versions = db.query(CatalogueVersion).filter_by(sample_id=sample_id).order_by(CatalogueVersion.id).all()
    attempts = db.query(ProcessingAttempt).filter_by(sample_id=sample_id).order_by(ProcessingAttempt.attempt_no).all()
    objs = db.query(S3Object).filter_by(sample_id=sample_id).order_by(S3Object.key).all()
    events = (db.query(ActivityLog).filter_by(sample_id=sample_id).order_by(ActivityLog.id.desc()).limit(100).all())
    return HistoryOut(
        sample_id=sample_id, run_id=sample.run_id, current_status=sample.status,
        catalogue_version=sample.catalogue_version, processed_version=sample.processed_version,
        catalogue_versions=[CatalogueVersionOut.model_validate(v) for v in versions],
        attempts=[AttemptOut.model_validate(a) for a in attempts],
        s3_objects=[{"key": o.key, "checksum": o.checksum, "overwrite_count": o.overwrite_count,
                     "uploaded_at": o.uploaded_at.isoformat() + "Z", "attempt_id": o.attempt_id,
                     "catalogue_version": o.catalogue_version} for o in objs],
        events=[{"ts": e.ts.isoformat() + "Z", "level": e.level, "source": e.source, "message": e.message}
                for e in events],
    )


@router.get("/metadata/search", response_model=SearchResult, tags=["metadata search"])
def metadata_search(q: Optional[str] = Query(None, description="free text over all indexed fields"),
                    sample_id: Optional[str] = None, run_id: Optional[str] = None,
                    catalogue_version: Optional[str] = None, processing_status: Optional[str] = None,
                    quality_status: Optional[str] = None, created_from: Optional[str] = None,
                    created_to: Optional[str] = None, limit: int = Query(50, ge=1, le=500),
                    offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    """Search the metadata index (the OpenSearch simulator). This index is derived data;
    operational state lives in the tracking tables."""
    from datetime import datetime

    def _dt(v: Optional[str]):
        if not v:
            return None
        try:
            return datetime.fromisoformat(v.replace("Z", ""))
        except ValueError:
            raise HTTPException(422, f"invalid date: {v}")

    total, items = search_index.search(
        db, q=q, sample_id=sample_id, run_id=run_id, catalogue_version=catalogue_version,
        processing_status=processing_status.upper() if processing_status else None,
        quality_status=quality_status.upper() if quality_status else None,
        created_from=_dt(created_from), created_to=_dt(created_to), limit=limit, offset=offset)
    return SearchResult(total=total, items=items)

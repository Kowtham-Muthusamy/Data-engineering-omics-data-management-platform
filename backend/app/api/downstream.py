from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.tables import S3Object, Sample
from app.services import downstream, nfs, s3_sim
from app.services.activity import log_event

router = APIRouter(prefix="/api/downstream", tags=["downstream application"])


def _gate(db: Session, sample_id: str) -> Sample:
    """Backend-enforced quality gate shared by fetch and download."""
    try:
        return downstream.require_eligible(db, db.get(Sample, sample_id))
    except LookupError:
        raise HTTPException(404, f"sample {sample_id} not found")
    except downstream.GateBlocked as e:
        log_event(db, "downstream", f"access to {sample_id} BLOCKED: {e.reason}", level="WARN", sample_id=sample_id)
        db.commit()  # keep the audit entry even though we raise
        raise HTTPException(403, {"code": "QUALITY_GATE_BLOCKED", "sample_id": sample_id, "reason": e.reason})


@router.get("/available")
def available(include_blocked: bool = False, db: Session = Depends(get_db)):
    """Samples this consumer may fetch. ``include_blocked`` lists the rest with their block reason."""
    out = []
    for s in db.query(Sample).order_by(Sample.sample_id).all():
        ok, reason = downstream.eligibility(db, s)
        if ok or include_blocked:
            out.append({"sample_id": s.sample_id, "run_id": s.run_id, "catalogue_version": s.catalogue_version,
                        "quality_status": s.quality_status, "status": s.status, "eligible": ok, "reason": reason,
                        "last_processed_at": s.last_processed_at.isoformat() + "Z" if s.last_processed_at else None})
    return out


@router.get("/{sample_id}/fetch")
def fetch(sample_id: str, db: Session = Depends(get_db)):
    sample = _gate(db, sample_id)
    try:
        metadata = nfs.read_metadata(sample.run_id, sample.sample_id)
    except Exception:
        metadata = {}
    log_event(db, "downstream", f"{sample_id} fetched by downstream application", sample_id=sample_id,
              run_id=sample.run_id)
    db.commit()
    return {"sample_id": sample.sample_id, "run_id": sample.run_id, "catalogue_version": sample.catalogue_version,
            "processed_version": sample.processed_version, "quality_status": sample.quality_status,
            "s3_destination": sample.s3_destination, "metadata": metadata,
            "files": downstream.sample_files(db, sample)}


@router.get("/{sample_id}/download/{path:path}")
def download(sample_id: str, path: str, db: Session = Depends(get_db)):
    sample = _gate(db, sample_id)
    key = f"{sample.run_id}/{sample.sample_id}/{path}"
    if db.get(S3Object, key) is None:
        raise HTTPException(404, f"no such file for {sample_id}: {path}")
    return FileResponse(s3_sim.object_path(key), filename=path.rsplit("/", 1)[-1])

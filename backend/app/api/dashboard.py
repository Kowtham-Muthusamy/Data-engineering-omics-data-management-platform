from collections import Counter, defaultdict
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.tables import ActivityLog, ProcessingAttempt, QualityResult, Run, S3Object, Sample
from app.services import nfs, runs as run_service
from app.utils.common import sha256_file, utcnow

router = APIRouter(prefix="/api", tags=["dashboard, logs & integrity"])


@router.get("/dashboard/summary")
def summary(db: Session = Depends(get_db)):
    runs = db.query(Run).all()
    samples = db.query(Sample).all()
    states = {r.run_id: run_service.derive_run_state([s.status for s in r.samples]) for r in runs}
    status_counts = Counter(s.status for s in samples)
    done = {"INGESTED", "PROCESSING", "QC_PENDING", "PASSED", "FAILED", "RERUN_REQUIRED"}

    kpis = {
        "total_runs": len(runs),
        "newly_discovered_runs": sum(1 for st in states.values() if st == "DISCOVERED"),
        "ingested_runs": sum(1 for r in runs if r.samples and all(s.status in done for s in r.samples)),
        "currently_processing": sum(status_counts[k] for k in ("INGESTING", "INGESTED", "PROCESSING", "QC_PENDING")),
        "passed_qc": status_counts["PASSED"],
        "failed_qc": status_counts["FAILED"],
        "reruns_initiated": db.query(func.count(ProcessingAttempt.id)).filter_by(kind="BASE_RECALL").scalar() or 0,
        "rerun_required": status_counts["RERUN_REQUIRED"],
        "total_samples": len(samples),
    }

    since = utcnow() - timedelta(days=13)
    per_day: dict[str, int] = defaultdict(int)
    for (created,) in db.query(ProcessingAttempt.created_at).filter(ProcessingAttempt.created_at >= since):
        per_day[created.strftime("%Y-%m-%d")] += 1
    activity = [{"date": (since + timedelta(days=i)).strftime("%Y-%m-%d"),
                 "attempts": per_day.get((since + timedelta(days=i)).strftime("%Y-%m-%d"), 0)} for i in range(14)]

    pass_fail = Counter(s.quality_status for s in samples if s.quality_status in ("PASS", "FAIL"))
    versions = Counter(s.catalogue_version for s in samples)
    feed = db.query(ActivityLog).order_by(ActivityLog.id.desc()).limit(15).all()
    return {
        "kpis": kpis,
        "charts": {
            "ingestion_activity": activity,
            "pass_fail": [{"name": "PASS", "value": pass_fail.get("PASS", 0)}, {"name": "FAIL", "value": pass_fail.get("FAIL", 0)}],
            "processing_status": [{"name": k, "value": status_counts.get(k, 0)} for k in
                                  ("DISCOVERED", "INGESTING", "INGESTED", "PROCESSING", "QC_PENDING", "PASSED", "FAILED", "RERUN_REQUIRED")],
            "catalogue_versions": [{"name": k, "value": v} for k, v in sorted(versions.items())],
        },
        "recent_activity": [{"id": e.id, "ts": e.ts.isoformat() + "Z", "level": e.level, "source": e.source,
                             "message": e.message, "run_id": e.run_id, "sample_id": e.sample_id} for e in feed],
    }


@router.get("/logs")
def logs(level: Optional[str] = None, source: Optional[str] = None, sample_id: Optional[str] = None,
         run_id: Optional[str] = None, limit: int = Query(200, ge=1, le=1000), db: Session = Depends(get_db)):
    q = db.query(ActivityLog)
    if level:
        q = q.filter(ActivityLog.level == level.upper())
    if source:
        q = q.filter(ActivityLog.source == source)
    if sample_id:
        q = q.filter(ActivityLog.sample_id == sample_id)
    if run_id:
        q = q.filter(ActivityLog.run_id == run_id)
    return [{"id": e.id, "ts": e.ts.isoformat() + "Z", "level": e.level, "source": e.source, "message": e.message,
             "run_id": e.run_id, "sample_id": e.sample_id} for e in q.order_by(ActivityLog.id.desc()).limit(limit)]


@router.get("/nfs/integrity")
def nfs_integrity(sample_id: Optional[str] = None, db: Session = Depends(get_db)):
    """Compare current NFS files with the checksum recorded when they were last synced.
    Syncing never modifies the source, so only deliberate source edits (catalogue updates) show as MODIFIED."""
    q = db.query(S3Object)
    if sample_id:
        q = q.filter(S3Object.sample_id == sample_id)
    out = []
    for o in q.order_by(S3Object.key).all():
        _run, _sample, rel = o.key.split("/", 2)
        path = nfs.sample_dir(o.run_id, o.sample_id) / rel
        if not path.is_file():
            status, now_sum = "MISSING", None
        else:
            now_sum = sha256_file(path)
            status = "UNCHANGED" if now_sum == o.nfs_checksum else "MODIFIED"
        out.append({"key": o.key, "status": status, "recorded_nfs_sha256": o.nfs_checksum, "current_nfs_sha256": now_sum})
    return out

"""Run views: DB state merged with what is physically on the NFS share."""
from collections import Counter
from typing import Optional

from sqlalchemy.orm import Session

from app.models.tables import Run, Sample
from app.schemas.runs import RunOut, SampleSummary
from app.services import nfs

IN_FLIGHT = {"INGESTING", "INGESTED", "PROCESSING", "QC_PENDING"}


def derive_run_state(statuses: list[str]) -> str:
    if not statuses:
        return "DISCOVERED"
    s = set(statuses)
    if s & IN_FLIGHT:
        return "PROCESSING"
    if "RERUN_REQUIRED" in s:
        return "RERUN_REQUIRED"
    if "FAILED" in s:
        return "FAILED"
    if s == {"PASSED"}:
        return "PASSED"
    if s == {"DISCOVERED"}:
        return "DISCOVERED"
    return "INGESTED"


def build_run_out(run: Optional[Run], run_id: str, with_samples: bool = True) -> RunOut:
    on_nfs = nfs.run_dir(run_id).is_dir()
    complete = on_nfs and nfs.is_complete(run_id)
    if run is None:
        return RunOut(run_id=run_id, state="NOT_DISCOVERED" if complete else "INCOMPLETE", complete=complete,
                      discovered=False, sample_count=len(nfs.list_sample_ids(run_id)),
                      nfs_samples=nfs.list_sample_ids(run_id))
    counts = Counter(s.status for s in run.samples)
    return RunOut(
        run_id=run.run_id, state=derive_run_state([s.status for s in run.samples]), complete=complete, discovered=True,
        discovered_at=run.discovered_at, sample_count=len(run.samples), status_counts=dict(counts),
        samples=[SampleSummary.model_validate(s) for s in run.samples] if with_samples else [],
        nfs_samples=nfs.list_sample_ids(run_id) if on_nfs else [],
    )


def list_runs(session: Session) -> list[RunOut]:
    db_runs = {r.run_id: r for r in session.query(Run).all()}
    ids = sorted(set(db_runs) | set(nfs.list_run_ids()))
    return [build_run_out(db_runs.get(rid), rid, with_samples=False) for rid in ids]


def known_ids(session: Session) -> tuple[list[str], list[str]]:
    return ([r for (r,) in session.query(Run.run_id)], [s for (s,) in session.query(Sample.sample_id)])

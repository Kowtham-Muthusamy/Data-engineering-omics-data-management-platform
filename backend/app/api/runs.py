from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.tables import Run
from app.schemas.runs import RunCreate, RunOut, SampleAdd
from app.services import nfs, runs as run_service
from app.services.activity import log_event

router = APIRouter(prefix="/api", tags=["runs & NFS"])


def _nfs_error(e: nfs.NfsError) -> HTTPException:
    msg = str(e)
    code = 409 if ("exists" in msg or "immutable" in msg) else 404 if "not found" in msg else 422
    return HTTPException(code, msg)


@router.get("/runs", response_model=list[RunOut])
def list_runs(db: Session = Depends(get_db)):
    return run_service.list_runs(db)


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: str, db: Session = Depends(get_db)):
    try:
        on_nfs = nfs.run_dir(run_id).is_dir()
    except nfs.NfsError as e:
        raise HTTPException(422, str(e))
    run = db.get(Run, run_id)
    if run is None and not on_nfs:
        raise HTTPException(404, f"run {run_id} not found")
    return run_service.build_run_out(run, run_id)


@router.post("/runs", response_model=RunOut, status_code=201)
def create_run(body: RunCreate, db: Session = Depends(get_db)):
    """Create a run folder (with generated sample data) on the simulated NFS share.
    The sequencer discovers it on its next scan."""
    known_runs, known_samples = run_service.known_ids(db)
    try:
        result = nfs.create_run(body.run_id, body.sample_count, body.scenarios, body.mark_complete,
                                known_runs, known_samples, body.catalogue_version)
    except nfs.NfsError as e:
        raise _nfs_error(e)
    log_event(db, "nfs", f"run folder created: {result['run_id']} samples={result['samples']} "
                         f"complete={result['complete']}", run_id=result["run_id"])
    db.commit()
    return run_service.build_run_out(None, result["run_id"])


@router.post("/nfs/simulate-arrival", response_model=RunOut, status_code=201)
def simulate_arrival(incomplete: bool = Query(False, description="leave the run without its completion marker"),
                     db: Session = Depends(get_db)):
    """Simulate a new sequencing run arriving on the share (3 samples: good / poor / warning)."""
    known_runs, known_samples = run_service.known_ids(db)
    result = nfs.create_run(None, 3, None, not incomplete, known_runs, known_samples)
    log_event(db, "nfs", f"new sequencing run arrived: {result['run_id']} (complete={result['complete']})",
              run_id=result["run_id"])
    db.commit()
    return run_service.build_run_out(None, result["run_id"])


@router.post("/runs/{run_id}/samples", response_model=RunOut, status_code=201)
def add_sample(run_id: str, body: SampleAdd, db: Session = Depends(get_db)):
    _, known_samples = run_service.known_ids(db)
    try:
        sid = nfs.add_sample(run_id, body.sample_id, body.scenario, body.catalogue_version, known_samples=known_samples)
    except nfs.NfsError as e:
        raise _nfs_error(e)
    log_event(db, "nfs", f"sample folder created: {sid}", run_id=run_id, sample_id=sid)
    db.commit()
    return run_service.build_run_out(db.get(Run, run_id), run_id)


@router.post("/runs/{run_id}/files", status_code=201)
async def upload_file(run_id: str, sample_id: str = Query(...),
                      path: str = Query(..., description="path inside the sample folder"),
                      file: UploadFile = File(...), db: Session = Depends(get_db)):
    data = await file.read()
    try:
        nfs.upload_file(run_id, sample_id, path, data)
    except nfs.NfsError as e:
        raise _nfs_error(e)
    log_event(db, "nfs", f"file uploaded: {sample_id}/{path} ({len(data)} bytes)", run_id=run_id, sample_id=sample_id)
    db.commit()
    return {"run_id": run_id, "sample_id": sample_id, "path": path, "size": len(data)}


@router.post("/runs/{run_id}/complete", response_model=RunOut)
def mark_complete(run_id: str, db: Session = Depends(get_db)):
    try:
        nfs.mark_run_complete(run_id)
    except nfs.NfsError as e:
        raise _nfs_error(e)
    log_event(db, "nfs", f"run marked complete: {run_id}", run_id=run_id)
    db.commit()
    return run_service.build_run_out(db.get(Run, run_id), run_id)


@router.get("/nfs/tree")
def nfs_tree():
    return nfs.tree()

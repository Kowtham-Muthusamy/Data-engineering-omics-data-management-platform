from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.tables import S3ObjectVersion
from app.schemas.s3 import S3ObjectOut
from app.services import s3_sim

router = APIRouter(prefix="/api/s3", tags=["S3 simulator"])


@router.get("/objects", response_model=list[S3ObjectOut])
def list_objects(run_id: Optional[str] = None, sample_id: Optional[str] = None, prefix: Optional[str] = None,
                 db: Session = Depends(get_db)):
    return s3_sim.list_objects(db, run_id, sample_id, prefix)


@router.get("/versions")
def list_versions(key: str = Query(...), db: Session = Depends(get_db)):
    """Native S3-style versions (only populated while the versioning simulation is enabled)."""
    rows = db.query(S3ObjectVersion).filter_by(key=key).order_by(S3ObjectVersion.id).all()
    return [{"version_id": r.version_id, "size": r.size, "checksum": r.checksum, "is_latest": r.is_latest,
             "created_at": r.created_at.isoformat() + "Z"} for r in rows]

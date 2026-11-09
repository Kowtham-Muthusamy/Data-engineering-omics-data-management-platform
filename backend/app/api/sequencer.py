from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.tables import ScanRecord
from app.schemas.sequencer import ScanOut, SequencerStatus, SettingsOut, SettingsUpdate
from app.services import sequencer, settings_service
from app.workers.scan_loop import scan_loop

router = APIRouter(prefix="/api", tags=["sequencer & settings"])


@router.post("/sequencer/scan", response_model=ScanOut)
def run_scan():
    """Manually trigger a scan of the NFS source folder."""
    try:
        return sequencer.scan("manual")
    except sequencer.ScanBusy:
        raise HTTPException(409, "a scan is already running")


@router.get("/sequencer/status", response_model=SequencerStatus)
def sequencer_status(db: Session = Depends(get_db)):
    last = db.query(ScanRecord).filter(ScanRecord.finished_at.isnot(None)).order_by(ScanRecord.id.desc()).first()
    return SequencerStatus(
        scanning=sequencer.is_scanning(),
        auto_scan_enabled=settings_service.get_bool(db, "auto_scan_enabled"),
        interval_seconds=int(settings_service.get_setting(db, "scan_interval_seconds")),
        next_scan_at=scan_loop.next_scan_at,
        last_scan=ScanOut.model_validate(last) if last else None,
        scans_total=db.query(func.count(ScanRecord.id)).scalar() or 0,
    )


@router.get("/sequencer/history", response_model=list[ScanOut])
def scan_history(limit: int = 20, db: Session = Depends(get_db)):
    return db.query(ScanRecord).order_by(ScanRecord.id.desc()).limit(min(limit, 200)).all()


def _settings_out(db: Session) -> SettingsOut:
    v = settings_service.get_all(db)
    return SettingsOut(scan_interval_seconds=int(v["scan_interval_seconds"]),
                       auto_scan_enabled=v["auto_scan_enabled"] == "true", auto_process=v["auto_process"] == "true",
                       s3_versioning_enabled=v["s3_versioning_enabled"] == "true", warning_policy=v["warning_policy"])


@router.get("/settings", response_model=SettingsOut)
def get_settings(db: Session = Depends(get_db)):
    return _settings_out(db)


@router.put("/settings", response_model=SettingsOut)
def update_settings(body: SettingsUpdate, db: Session = Depends(get_db)):
    data = body.model_dump(exclude_none=True)
    if "scan_interval_seconds" in data and not 1 <= data["scan_interval_seconds"] <= 86400:
        raise HTTPException(422, "scan_interval_seconds must be between 1 and 86400")
    if "warning_policy" in data:
        data["warning_policy"] = data["warning_policy"].upper()
        if data["warning_policy"] not in ("PASS", "FAIL"):
            raise HTTPException(422, "warning_policy must be PASS or FAIL")
    for key, value in data.items():
        settings_service.set_setting(db, key, str(value).lower() if isinstance(value, bool) else str(value))
    db.commit()
    return _settings_out(db)

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.tables import AuditLog
from app.services import audit as audit_service

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
def list_audit(outcome: Optional[str] = None, method: Optional[str] = None, actor: Optional[str] = None,
               resource: Optional[str] = None, status_code: Optional[int] = None,
               limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    q = db.query(AuditLog)
    for col, val in ((AuditLog.outcome, outcome), (AuditLog.method, method), (AuditLog.actor, actor),
                     (AuditLog.resource, resource), (AuditLog.status_code, status_code)):
        if val is not None:
            q = q.filter(col == val)
    total = q.count()
    rows = q.order_by(AuditLog.id.desc()).offset(offset).limit(limit).all()
    return {"total": total, "items": [
        {"id": r.id, "ts": r.ts.isoformat() + "Z", "request_id": r.request_id, "actor": r.actor,
         "client_ip": r.client_ip, "method": r.method, "route": r.route, "path": r.path, "resource": r.resource,
         "status_code": r.status_code, "outcome": r.outcome, "duration_ms": r.duration_ms} for r in rows]}


@router.get("/verify")
def verify(db: Session = Depends(get_db)):
    """Re-computes the hash chain; `valid: false` means a row was edited, removed or inserted."""
    return audit_service.verify_chain(db)

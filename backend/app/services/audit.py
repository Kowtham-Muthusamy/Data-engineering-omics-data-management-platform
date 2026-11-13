"""Append-only, hash-chained audit trail of API activity.

Separate from ``activity_log`` (pipeline events for the UI feed): this answers
"who called what, when, and what happened". Bodies and query strings are never stored.
"""
import hashlib
import logging
import threading

from sqlalchemy.orm import Session

from app.database import session_scope
from app.models.tables import AuditLog
from app.utils.common import utcnow

_log = logging.getLogger("platform.audit")
_chain_lock = threading.Lock()


def outcome_for(status: int) -> str:
    if status == 429:
        return "RATE_LIMITED"
    if status in (401, 403):
        return "DENIED"
    if status >= 500:
        return "ERROR"
    return "REJECTED" if status >= 400 else "SUCCESS"


def should_audit(method: str, path: str, status: int) -> bool:
    """Every state change, every downstream fetch/download, and every denied/limited/failed call.
    Routine polling GETs are not audited (they would drown the trail)."""
    if not path.startswith("/api/") or path.startswith("/api/audit"):
        return False
    if method not in ("GET", "HEAD", "OPTIONS"):
        return True
    downstream_read = path.startswith("/api/downstream/") and not path.endswith("/available")
    return downstream_read or status in (401, 403, 429) or status >= 500


def _digest(prev: str, row: AuditLog) -> str:
    parts = [prev, row.ts.isoformat(), row.request_id, row.actor, row.client_ip, row.method, row.route,
             row.path, row.resource or "", str(row.status_code), row.outcome, str(row.duration_ms)]
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def record(**fields) -> None:
    """Never raises: a failing audit write is logged to the platform log, not turned into a 500."""
    try:
        with _chain_lock, session_scope() as s:
            last = s.query(AuditLog.row_hash).order_by(AuditLog.id.desc()).first()
            row = AuditLog(ts=utcnow(), prev_hash=last[0] if last else "", **fields)
            row.row_hash = _digest(row.prev_hash, row)
            s.add(row)
    except Exception:  # noqa: BLE001
        _log.exception("audit write failed for %s %s", fields.get("method"), fields.get("path"))


def verify_chain(db: Session) -> dict:
    prev, count = "", 0
    for row in db.query(AuditLog).order_by(AuditLog.id):
        if row.prev_hash != prev or row.row_hash != _digest(prev, row):
            return {"valid": False, "checked": count, "first_bad_id": row.id}
        prev, count = row.row_hash, count + 1
    return {"valid": True, "checked": count, "first_bad_id": None}

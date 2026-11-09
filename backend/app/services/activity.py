"""Audit/activity log: DB rows for the UI feed + a rotating-free plain log file."""
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.config import get_config
from app.database import session_scope
from app.models.tables import ActivityLog

_logger = logging.getLogger("platform")
_configured = False


def _configure() -> None:
    global _configured
    if _configured:
        return
    handler = logging.FileHandler(get_config().logs_dir / "platform.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    _logger.addHandler(handler)
    _logger.setLevel(logging.INFO)
    _configured = True


def log_event(session: Optional[Session], source: str, message: str, level: str = "INFO",
              run_id: Optional[str] = None, sample_id: Optional[str] = None) -> None:
    """Record an event. Pass ``session=None`` to write in its own transaction
    (used for failure logging so the entry survives a rolled-back caller)."""
    _configure()
    _logger.log(getattr(logging, level, logging.INFO), "[%s] %s run=%s sample=%s", source, message, run_id, sample_id)
    row = ActivityLog(source=source, message=message, level=level, run_id=run_id, sample_id=sample_id)
    if session is not None:
        session.add(row)
    else:
        with session_scope() as s:
            s.add(row)

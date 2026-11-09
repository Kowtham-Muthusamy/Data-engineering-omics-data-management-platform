from sqlalchemy.orm import Session

from app.models.tables import Setting

DEFAULTS: dict[str, str] = {
    "scan_interval_seconds": "30",
    "auto_scan_enabled": "true",
    "auto_process": "true",            # sequencer submits workflows for new samples
    "s3_versioning_enabled": "false",  # optional native-S3-versioning simulation
    "warning_policy": "PASS",          # how QC WARN results are treated by the gate: PASS | FAIL
}


def get_setting(session: Session, key: str) -> str:
    row = session.get(Setting, key)
    return row.value if row else DEFAULTS[key]


def get_bool(session: Session, key: str) -> bool:
    return get_setting(session, key).lower() == "true"


def get_all(session: Session) -> dict[str, str]:
    out = dict(DEFAULTS)
    for row in session.query(Setting).filter(Setting.key.in_(DEFAULTS)):
        out[row.key] = row.value
    return out


def set_setting(session: Session, key: str, value: str) -> None:
    if key not in DEFAULTS:
        raise KeyError(key)
    row = session.get(Setting, key)
    if row:
        row.value = value
    else:
        session.add(Setting(key=key, value=value))

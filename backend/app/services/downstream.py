"""Downstream quality gate. Enforced here (and called by the API), never in the UI.

A sample is consumable only when ALL of these hold:
* sample.status == PASSED
* its latest processing attempt PASSED QC and is the accepted one
* that attempt used the sample's *current* catalogue version (no stale results)
* the stored quality result for that attempt is PASS
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.models.tables import ProcessingAttempt, QualityResult, S3Object, Sample
from app.services import nfs, s3_sim, state


class GateBlocked(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def eligibility(session: Session, sample: Sample) -> tuple[bool, str]:
    if sample.status != "PASSED":
        return False, f"sample status is {sample.status}, not PASSED"
    attempt = state.latest_attempt(session, sample)
    if attempt is None or attempt.status != "PASSED" or not attempt.accepted:
        return False, "no accepted passing processing attempt"
    if attempt.catalogue_version != sample.catalogue_version or sample.processed_version != sample.catalogue_version:
        return False, (f"latest results are for catalogue {attempt.catalogue_version}, "
                       f"current catalogue is {sample.catalogue_version}")
    qr = session.query(QualityResult).filter_by(attempt_id=attempt.id).first()
    if qr is None or qr.overall != "PASS":
        return False, "quality gate result is not PASS"
    return True, "latest required processing attempt passed QC"


def require_eligible(session: Session, sample: Optional[Sample]) -> Sample:
    if sample is None:
        raise LookupError("sample not found")
    ok, reason = eligibility(session, sample)
    if not ok:
        raise GateBlocked(reason)
    return sample


def sample_files(session: Session, sample: Sample) -> list[dict]:
    rows = session.query(S3Object).filter_by(sample_id=sample.sample_id).order_by(S3Object.key).all()
    prefix = f"{sample.run_id}/{sample.sample_id}/"
    return [{"key": o.key, "path": o.key[len(prefix):], "s3_uri": s3_sim.s3_uri(o.key), "size": o.size,
             "checksum": o.checksum,
             "download_url": f"/api/downstream/{sample.sample_id}/download/{o.key[len(prefix):]}"} for o in rows]

"""Catalogue versioning (V1, V2, ...). Completely independent of S3 object versioning."""
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.tables import CatalogueVersion, Sample
from app.services import nfs, search_index, state
from app.services.activity import log_event
from app.utils.common import VERSION_RE, sha256_bytes


class CatalogueError(Exception):
    pass


def canonical_fingerprint(content: dict[str, Any]) -> str:
    import json
    return sha256_bytes(json.dumps(content, sort_keys=True).encode())


def record_version(session: Session, sample: Sample, content: dict[str, Any], source: str) -> CatalogueVersion:
    """Persist a catalogue version and make it the sample's current one.

    If the sample was already processed (PASSED/FAILED) with a different version, it is
    marked RERUN_REQUIRED so stale results can no longer be consumed downstream.
    """
    version = str(content.get("version", "")).strip()
    if not VERSION_RE.match(version):
        raise CatalogueError(f"catalogue version must look like V1, V2, ... (got {version!r})")
    row = CatalogueVersion(sample_id=sample.sample_id, version=version, content=content,
                           fingerprint=canonical_fingerprint(content), source=source)
    session.add(row)
    previous = sample.catalogue_version
    sample.catalogue_version = version
    log_event(session, "catalogue", f"{sample.sample_id}: catalogue {previous} -> {version} ({source})",
              run_id=sample.run_id, sample_id=sample.sample_id)

    attempt = state.latest_attempt(session, sample)
    used_version = attempt.catalogue_version if attempt else None
    if sample.status in ("PASSED", "FAILED") and version != used_version:
        state.transition(session, sample, "RERUN_REQUIRED",
                         f"catalogue {version} differs from processed {used_version}")
        sample.quality_status = "STALE"
    session.flush()
    search_index.index_sample(session, sample)
    return row


def update_catalogue(session: Session, sample: Sample, version: str, notes: Optional[str],
                     fields: dict[str, Any]) -> CatalogueVersion:
    """A scientist edits catalogue information. The change is written to the NFS source
    catalogue.json (the system of record) and registered here."""
    if not VERSION_RE.match(version):
        raise CatalogueError(f"catalogue version must look like V1, V2, ... (got {version!r})")
    if version == sample.catalogue_version:
        raise CatalogueError(f"sample is already at catalogue {version}; choose a new version")
    content = nfs.read_catalogue(sample.run_id, sample.sample_id)
    content.update(fields)
    content["version"] = version
    if notes is not None:
        content["notes"] = notes
    nfs.write_catalogue(sample.run_id, sample.sample_id, content)
    return record_version(session, sample, content, "scientist_update")

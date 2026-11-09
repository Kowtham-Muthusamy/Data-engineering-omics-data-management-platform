"""S3 simulator backed by ``local_data/s3_bucket``.

* put_file REPLACES whatever is stored at an existing key (the real project overwrites
  objects at configured keys on reruns) and counts the overwrite.
* Native S3 object versioning is a separate, optional simulation (setting
  ``s3_versioning_enabled``, default off). It is unrelated to catalogue versions.
* The NFS source is only ever read.
"""
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.config import get_config
from app.models.tables import S3Object, S3ObjectVersion
from app.services import settings_service
from app.utils.common import atomic_write_json, safe_join, sha256_file, utcnow

BUCKET = "local-sim-bucket"
SYSTEM_PREFIXES = ("_manifests", ".versions")


def s3_root() -> Path:
    return get_config().s3_dir


def object_path(key: str) -> Path:
    if key.startswith(SYSTEM_PREFIXES):
        raise ValueError("reserved key prefix")
    return safe_join(s3_root(), key)


def s3_uri(key: str) -> str:
    return f"s3://{BUCKET}/{key}"


def put_file(session: Session, key: str, src: Path, *, run_id: str, sample_id: str,
             attempt_id: Optional[int], catalogue_version: Optional[str]) -> S3Object:
    dest = object_path(key)
    nfs_checksum = sha256_file(src)
    dest.parent.mkdir(parents=True, exist_ok=True)

    # copy to a temp file next to the destination, verify, then atomically replace
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".tmp-")
    os.close(fd)
    try:
        shutil.copyfile(src, tmp)
        checksum = sha256_file(Path(tmp))
        if checksum != nfs_checksum:
            raise IOError(f"checksum mismatch while uploading {key}")
        os.replace(tmp, dest)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise

    size = dest.stat().st_size
    now = utcnow()
    obj = session.get(S3Object, key)
    if obj is None:
        obj = S3Object(key=key, run_id=run_id, sample_id=sample_id, size=size, checksum=checksum,
                       nfs_checksum=nfs_checksum, attempt_id=attempt_id, catalogue_version=catalogue_version,
                       overwrite_count=0, first_uploaded_at=now, uploaded_at=now)
        session.add(obj)
    else:  # overwrite at the same key
        obj.size, obj.checksum, obj.nfs_checksum = size, checksum, nfs_checksum
        obj.attempt_id, obj.catalogue_version = attempt_id, catalogue_version
        obj.overwrite_count += 1
        obj.uploaded_at = now

    if settings_service.get_bool(session, "s3_versioning_enabled"):
        version_id = uuid.uuid4().hex[:12]
        vpath = safe_join(s3_root() / ".versions", f"{key}/{version_id}")
        vpath.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(dest, vpath)
        session.execute(update(S3ObjectVersion).where(S3ObjectVersion.key == key).values(is_latest=False))
        session.add(S3ObjectVersion(key=key, version_id=version_id, size=size, checksum=checksum, is_latest=True))
    session.flush()
    return obj


def write_manifest(session: Session, run_id: str, sample_id: str) -> Path:
    rows = (session.query(S3Object).filter_by(run_id=run_id, sample_id=sample_id)
            .order_by(S3Object.key).all())
    manifest = {
        "bucket": BUCKET, "run_id": run_id, "sample_id": sample_id, "simulated": True,
        "generated_at": utcnow().isoformat() + "Z",
        "objects": [{"key": o.key, "size": o.size, "sha256": o.checksum,
                     "uploaded_at": o.uploaded_at.isoformat() + "Z", "overwrite_count": o.overwrite_count,
                     "attempt_id": o.attempt_id, "catalogue_version": o.catalogue_version} for o in rows],
    }
    path = s3_root() / "_manifests" / run_id / f"{sample_id}.json"
    atomic_write_json(path, manifest)
    return path


def list_objects(session: Session, run_id: Optional[str] = None, sample_id: Optional[str] = None,
                 prefix: Optional[str] = None) -> list[S3Object]:
    q = session.query(S3Object)
    if run_id:
        q = q.filter(S3Object.run_id == run_id)
    if sample_id:
        q = q.filter(S3Object.sample_id == sample_id)
    if prefix:
        q = q.filter(S3Object.key.like(prefix.replace("%", "") + "%"))
    return q.order_by(S3Object.key).all()

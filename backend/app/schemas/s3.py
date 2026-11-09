from typing import Optional

from app.schemas.common import ORM, UtcDt


class S3ObjectOut(ORM):
    key: str
    run_id: str
    sample_id: str
    size: int
    checksum: str
    nfs_checksum: str
    attempt_id: Optional[int]
    catalogue_version: Optional[str]
    overwrite_count: int
    first_uploaded_at: UtcDt
    uploaded_at: UtcDt

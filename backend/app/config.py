"""Application configuration.

Everything runs locally: the "NFS", "S3" and "DynamoDB/OpenSearch" are plain
folders and a SQLite file under ``local_data/`` (override with PLATFORM_DATA_DIR).
"""
import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class AppConfig(BaseModel):
    data_dir: Path
    autoscan: bool = True          # start the background folder sequencer
    step_delay: float = 0.6        # seconds each workflow step "takes" (visible in the UI timeline)
    inline_jobs: bool = False      # run workflow jobs synchronously (used by tests)
    max_workers: int = 2
    max_retries: int = 3           # retries for transient step errors
    retry_backoff: float = 0.3     # seconds, doubled on each retry

    @property
    def nfs_dir(self) -> Path:
        return self.data_dir / "nfs_source"

    @property
    def s3_dir(self) -> Path:
        return self.data_dir / "s3_bucket"

    @property
    def outputs_dir(self) -> Path:
        return self.data_dir / "workflow_outputs"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "platform.db"

    def ensure_dirs(self) -> None:
        for d in (self.nfs_dir, self.s3_dir, self.outputs_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_config() -> AppConfig:
    cfg = AppConfig(
        data_dir=Path(os.environ.get("PLATFORM_DATA_DIR", PROJECT_ROOT / "local_data")).resolve(),
        autoscan=_flag("PLATFORM_AUTOSCAN", True),
        step_delay=float(os.environ.get("PLATFORM_STEP_DELAY", "0.6")),
        inline_jobs=_flag("PLATFORM_INLINE_JOBS", False),
        retry_backoff=float(os.environ.get("PLATFORM_RETRY_BACKOFF", "0.3")),
    )
    cfg.ensure_dirs()
    return cfg

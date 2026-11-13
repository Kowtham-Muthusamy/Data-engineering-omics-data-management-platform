import os
import shutil
import tempfile
from pathlib import Path

# Isolate every test run from the real local_data/ BEFORE the app is imported.
_TMP = Path(tempfile.mkdtemp(prefix="sdp-tests-"))
os.environ["PLATFORM_DATA_DIR"] = str(_TMP)
os.environ["PLATFORM_AUTOSCAN"] = "0"
os.environ["PLATFORM_INLINE_JOBS"] = "1"
os.environ["PLATFORM_STEP_DELAY"] = "0"
os.environ["PLATFORM_RETRY_BACKOFF"] = "0"
# Generous limits so ordinary tests never trip; test_security.py lowers them explicitly.
os.environ["PLATFORM_RATE_LIMIT_READ"] = "100000"
os.environ["PLATFORM_RATE_LIMIT_WRITE"] = "100000"
os.environ["PLATFORM_RATE_LIMIT_DOWNLOAD"] = "100000"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_config  # noqa: E402
from app.database import reset_db  # noqa: E402


@pytest.fixture(autouse=True)
def clean_env():
    cfg = get_config()
    for d in (cfg.nfs_dir, cfg.s3_dir, cfg.outputs_dir):
        shutil.rmtree(d, ignore_errors=True)
    cfg.ensure_dirs()
    reset_db()
    from app.services.ratelimit import limiter
    limiter.reset()
    yield


@pytest.fixture()
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TMP, ignore_errors=True)

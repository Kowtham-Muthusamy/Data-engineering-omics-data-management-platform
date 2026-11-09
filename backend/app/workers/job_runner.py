"""Executes workflow jobs on a small thread pool (or inline, for tests)."""
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from app.config import get_config
from app.services import workflow
from app.services.activity import log_event

_pool: Optional[ThreadPoolExecutor] = None
_active: set[str] = set()
_lock = threading.Lock()


def active_job_ids() -> set[str]:
    with _lock:
        return set(_active)


def _run(job_id: str) -> None:
    with _lock:
        _active.add(job_id)
    try:
        workflow.run_job(job_id)
    except workflow.SimulatedCrash as e:
        # The "worker" died: leave DB state exactly as it was so recovery can find it.
        log_event(None, "workflow", f"{job_id} worker crashed: {e}", level="ERROR")
        if get_config().inline_jobs:
            raise
    except Exception as e:  # engine bug - make sure it is visible
        log_event(None, "workflow", f"{job_id} engine error: {type(e).__name__}: {e}", level="ERROR")
    finally:
        with _lock:
            _active.discard(job_id)


def submit(job_id: str) -> None:
    """Hand a COMMITTED job to a worker. Safe to call twice: run_job ignores non-QUEUED jobs."""
    global _pool
    cfg = get_config()
    if cfg.inline_jobs:
        _run(job_id)
        return
    with _lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=cfg.max_workers, thread_name_prefix="workflow")
        pool = _pool
    pool.submit(_run, job_id)


def recover() -> list[str]:
    """Recover jobs left behind by a previous process (called on startup)."""
    job_ids = workflow.recover_interrupted_jobs(exclude=active_job_ids())
    for jid in job_ids:
        submit(jid)
    return job_ids


def shutdown() -> None:
    global _pool
    if _pool is not None:
        _pool.shutdown(wait=False, cancel_futures=True)
        _pool = None

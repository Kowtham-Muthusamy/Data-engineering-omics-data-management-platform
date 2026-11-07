"""Scheduled folder sequencer: scans the NFS share, detects new runs / catalogue-version
changes, and safely submits workflow jobs.

Safety properties
* incomplete folders (no RUN_COMPLETE marker) are skipped, never ingested
* a process-wide lock prevents overlapping scans (manual click during an auto scan -> 409)
* each run is scanned in its own transaction, so one broken folder cannot poison the scan
* job submission is an atomic conditional UPDATE (state.start_attempt), so a sample can
  never have two active attempts -> duplicate processing is impossible
* unchanged samples are counted and left alone
"""
import threading
from typing import Any

from app.database import session_scope
from app.models.tables import CatalogueVersion, Run, ScanRecord, Sample
from app.services import catalogue, nfs, s3_sim, search_index, settings_service, state
from app.services.activity import log_event
from app.utils.common import VERSION_RE, utcnow

_scan_lock = threading.Lock()


class ScanBusy(Exception):
    pass


def _scan_run(run_id: str, auto_process: bool) -> dict[str, Any]:
    out: dict[str, Any] = dict(new_runs=0, new_samples=0, changed_versions=0, skipped=0, unchanged=0,
                               failed=0, job_ids=[], details=[])
    with session_scope() as s:
        if not nfs.is_complete(run_id):
            out["skipped"] = 1
            out["details"].append(f"{run_id}: skipped (no completion marker)")
            return out

        run = s.get(Run, run_id)
        if run is None:
            run = Run(run_id=run_id, nfs_path=str(nfs.run_dir(run_id)), s3_destination=s3_sim.s3_uri(f"{run_id}/"))
            s.add(run)
            s.flush()
            out["new_runs"] = 1
            log_event(s, "sequencer", f"new run discovered: {run_id}", run_id=run_id)

        for sid in nfs.list_sample_ids(run_id):
            sample = s.get(Sample, sid)
            if sample is not None and sample.run_id != run_id:
                out["failed"] += 1
                out["details"].append(f"{run_id}/{sid}: sample id already belongs to {sample.run_id}")
                log_event(s, "sequencer", f"duplicate sample id {sid} in {run_id} (owned by {sample.run_id})",
                          level="ERROR", run_id=run_id, sample_id=sid)
                continue
            try:
                cat = nfs.read_catalogue(run_id, sid)
                meta = nfs.read_metadata(run_id, sid)
            except (OSError, ValueError, nfs.NfsError) as e:
                out["failed"] += 1
                out["details"].append(f"{run_id}/{sid}: unreadable ({e})")
                log_event(s, "sequencer", f"cannot read {sid}: {e}", level="ERROR", run_id=run_id, sample_id=sid)
                continue

            version = str(cat.get("version", "")).strip()
            if sample is None:
                if not VERSION_RE.match(version):
                    out["failed"] += 1
                    out["details"].append(f"{run_id}/{sid}: invalid catalogue version {version!r}")
                    log_event(s, "sequencer", f"{sid}: invalid catalogue version {version!r}", level="ERROR",
                              run_id=run_id, sample_id=sid)
                    continue
                sample = Sample(sample_id=sid, run_id=run_id, catalogue_version=version, status="DISCOVERED",
                                quality_status="NOT_RUN", s3_destination=s3_sim.s3_uri(f"{run_id}/{sid}/"))
                s.add(sample)
                s.flush()
                catalogue.record_version(s, sample, cat, "nfs_scan")
                search_index.index_sample(s, sample, metadata=meta)
                out["new_samples"] += 1
                log_event(s, "sequencer", f"sample discovered: {sid} (catalogue {version})", run_id=run_id, sample_id=sid)
            elif version != sample.catalogue_version:
                try:
                    catalogue.record_version(s, sample, cat, "nfs_scan")
                except catalogue.CatalogueError as e:
                    out["failed"] += 1
                    out["details"].append(f"{run_id}/{sid}: {e}")
                    continue
                out["changed_versions"] += 1
                out["details"].append(f"{run_id}/{sid}: catalogue changed to {version}")
            else:
                latest = (s.query(CatalogueVersion).filter_by(sample_id=sid).order_by(CatalogueVersion.id.desc()).first())
                if latest and latest.fingerprint != catalogue.canonical_fingerprint(cat):
                    log_event(s, "sequencer", f"{sid}: catalogue content changed without a version bump; ignored",
                              level="WARN", run_id=run_id, sample_id=sid)
                out["unchanged"] += 1

            if auto_process and sample.status == "DISCOVERED":
                try:
                    _attempt, job = state.start_attempt(s, sid, "INITIAL", "sequencer")
                    out["job_ids"].append(job.job_id)
                except state.Conflict:
                    pass  # another worker already claimed it: exactly what we want
    return out


def scan(trigger: str = "manual") -> ScanRecord:
    if not _scan_lock.acquire(blocking=False):
        raise ScanBusy("a scan is already running")
    try:
        with session_scope() as s:
            rec = ScanRecord(trigger=trigger)
            s.add(rec)
            s.flush()
            rec_id = rec.id
            auto_process = settings_service.get_bool(s, "auto_process")

        totals: dict[str, Any] = dict(new_runs=0, new_samples=0, changed_versions=0, skipped=0, unchanged=0, failed=0)
        details: list[str] = []
        job_ids: list[str] = []
        folders = nfs.list_run_ids()
        for run_id in folders:
            try:
                r = _scan_run(run_id, auto_process)
            except Exception as e:  # the run's transaction was rolled back; keep scanning others
                totals["failed"] += 1
                details.append(f"{run_id}: scan failed ({type(e).__name__}: {e})")
                log_event(None, "sequencer", f"scan of {run_id} failed: {e}", level="ERROR", run_id=run_id)
                continue
            for k in totals:
                totals[k] += r[k]
            details += r["details"]
            job_ids += r["job_ids"]

        if job_ids:
            from app.workers import job_runner  # local import: avoids a cycle at module load
            for jid in job_ids:  # submit only after the claiming transactions committed
                job_runner.submit(jid)

        with session_scope() as s:
            rec = s.get(ScanRecord, rec_id)
            rec.finished_at = utcnow()
            rec.discovered_folders = len(folders)
            rec.new_runs, rec.new_samples = totals["new_runs"], totals["new_samples"]
            rec.changed_versions, rec.skipped_folders = totals["changed_versions"], totals["skipped"]
            rec.unchanged_samples, rec.failed_operations = totals["unchanged"], totals["failed"]
            rec.jobs_submitted, rec.details = len(job_ids), details
            log_event(s, "sequencer", f"{trigger} scan: {len(folders)} folders, {rec.new_runs} new runs, "
                                      f"{rec.changed_versions} version changes, {rec.skipped_folders} skipped, "
                                      f"{rec.failed_operations} failed, {rec.jobs_submitted} jobs")
            s.flush()
            s.expunge(rec)
        return rec
    finally:
        _scan_lock.release()


def is_scanning() -> bool:
    return _scan_lock.locked()

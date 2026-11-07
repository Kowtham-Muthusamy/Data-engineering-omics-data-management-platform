"""Local workflow engine - a SIMULATION of the roles AWS Batch + miniWDL play in the real
project. It does not run AWS Batch or miniWDL.

One job == one processing attempt of one sample. Steps run in order; each step is its own
transaction with start/end times, logs and errors. Transient errors are retried with backoff;
permanent errors fail the job. A sample is only ever marked PASSED by ``update_final_status``.
"""
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from app.config import get_config
from app.database import session_scope
from app.models.tables import (CatalogueVersion, ProcessingAttempt, QualityResult, S3Object, Sample, Setting,
                               WorkflowJob, WorkflowStep)
from app.services import downstream, nfs, s3_sim, search_index, settings_service, state
from app.services.activity import log_event
from app.simulators import interop as interop_sim, fastqc as fastqc_sim, quality
from app.utils.common import atomic_write_json, utcnow


class TransientError(Exception):
    """Retryable (e.g. a flaky filesystem call)."""


class PermanentError(Exception):
    """Not retryable - the job fails."""


class SimulatedCrash(BaseException):
    """Simulates the worker process dying mid-job. Deliberately NOT an Exception so no
    failure handling runs and the job is left RUNNING for recovery to find."""


@dataclass
class Ctx:
    job_id: str
    attempt_id: int
    attempt_no: int
    sample_id: str
    run_id: str
    version: str
    shared: dict[str, Any] = field(default_factory=dict)

    @property
    def prefix(self) -> str:
        return f"{self.run_id}/{self.sample_id}"

    @property
    def out_dir(self):
        return get_config().outputs_dir / self.run_id / self.sample_id / f"attempt_{self.attempt_no}"


class StepLog:
    """Buffers step log lines in memory; the engine persists them (``flush``) once the step's own
    transaction is closed. Writing straight to the DB from inside a step would open a second
    writer while the step still holds a write lock, and SQLite would deadlock on itself."""

    def __init__(self, job_id: str, step: str):
        self.job_id, self.step = job_id, step
        self._lines: list[str] = []

    def write(self, line: str) -> None:
        self._lines.append(f"[{utcnow().strftime('%H:%M:%S')}] {line}\n")

    def flush(self) -> None:
        if not self._lines:
            return
        text, self._lines = "".join(self._lines), []
        with session_scope() as s:
            row = s.query(WorkflowStep).filter_by(job_id=self.job_id, name=self.step).one()
            row.logs = (row.logs or "") + text


# ---------------------------------------------------------------- effective inputs
def _catalogue_content(s, ctx: Ctx) -> dict[str, Any]:
    row = (s.query(CatalogueVersion).filter_by(sample_id=ctx.sample_id, version=ctx.version)
           .order_by(CatalogueVersion.id.desc()).first())
    return row.content if row else {}


def effective_setting(ctx: Ctx, key: str, default: Any = None) -> Any:
    """catalogue content wins over sample_metadata.json (so a catalogue update can change the outcome)."""
    with session_scope() as s:
        content = _catalogue_content(s, ctx)
    if key in content:
        return content[key]
    try:
        meta = nfs.read_metadata(ctx.run_id, ctx.sample_id)
    except Exception:
        return default
    return meta.get("scenario" if key == "simulation_scenario" else key, default)


def _scenario(ctx: Ctx) -> str:
    sc = effective_setting(ctx, "simulation_scenario", "A_GOOD")
    if sc not in interop_sim.PROFILES:
        raise PermanentError(f"unknown simulation scenario {sc!r}")
    return sc


def _maybe_inject_fault(ctx: Ctx, step: str, log: StepLog) -> None:
    fault = effective_setting(ctx, "fault")
    if not fault or fault.get("step") != step:
        return
    kind = fault.get("kind", "permanent")
    times = fault.get("times", 2 if kind == "transient" else 1 if kind == "crash" else None)
    key = f"fault:{ctx.sample_id}:{step}"
    with session_scope() as s:
        row = s.get(Setting, key)
        used = int(row.value) if row else 0
        if times is not None and used >= times:
            return
        if row:
            row.value = str(used + 1)
        else:
            s.add(Setting(key=key, value="1"))
    log.write(f"[fault injection] firing {kind} fault #{used + 1}")
    if kind == "transient":
        raise TransientError("injected transient error")
    if kind == "crash":
        raise SimulatedCrash(f"injected worker crash in {step}")
    raise PermanentError("injected permanent error")


# ---------------------------------------------------------------- steps
def step_validate_source(ctx: Ctx, log: StepLog) -> None:
    problems = nfs.validate_sample_dir(ctx.run_id, ctx.sample_id)
    if problems:
        raise PermanentError("source folder not ready: " + "; ".join(problems))
    ctx.shared["nfs_before"] = nfs.fingerprint(nfs.sample_dir(ctx.run_id, ctx.sample_id))
    log.write(f"source folder ready: {len(ctx.shared['nfs_before'])} files, completion marker present")


def step_sync_to_s3(ctx: Ctx, log: StepLog) -> None:
    sd = nfs.sample_dir(ctx.run_id, ctx.sample_id)
    try:
        with session_scope() as s:
            for path in nfs.iter_files(sd):
                key = f"{ctx.prefix}/{path.relative_to(sd).as_posix()}"
                existed = s.get(S3Object, key) is not None
                obj = s3_sim.put_file(s, key, path, run_id=ctx.run_id, sample_id=ctx.sample_id,
                                      attempt_id=ctx.attempt_id, catalogue_version=ctx.version)
                log.write(f"{'OVERWRITE' if existed else 'PUT      '} {s3_sim.s3_uri(key)} "
                          f"({obj.size} bytes, sha256 {obj.checksum[:12]})")
            manifest = s3_sim.write_manifest(s, ctx.run_id, ctx.sample_id)
            log.write(f"upload manifest written: {manifest.name}")
    except OSError as e:
        raise TransientError(f"filesystem error during sync: {e}") from e
    after = nfs.fingerprint(sd)
    before = ctx.shared["nfs_before"]
    changed = sorted(k for k in before if after.get(k) != before[k])
    if [k for k in changed if k != "catalogue.json"]:
        raise PermanentError(f"NFS source changed while syncing: {changed}")
    if changed:
        log.write("note: catalogue.json was updated on the source during sync")
    log.write("NFS source verified unchanged by synchronization")


def step_register_ingestion(ctx: Ctx, log: StepLog) -> None:
    with session_scope() as s:
        sample = s.get(Sample, ctx.sample_id)
        state.transition(s, sample, "INGESTED", f"attempt #{ctx.attempt_no}")
    log.write("ingestion state registered (INGESTED)")


def step_instrument_metrics(ctx: Ctx, log: StepLog) -> None:
    with session_scope() as s:
        state.transition(s, s.get(Sample, ctx.sample_id), "PROCESSING")
    scenario = _scenario(ctx)
    metrics = interop_sim.generate_instrument_metrics(ctx.sample_id, scenario)
    ctx.shared["instrument_metrics"] = metrics
    atomic_write_json(ctx.out_dir / "instrument_metrics.json", metrics)
    log.write(f"generated simulated instrument metrics for {len(metrics['lanes'])} lanes (scenario {scenario})")


def step_interop(ctx: Ctx, log: StepLog) -> None:
    report = interop_sim.simulate_interop(ctx.sample_id, _scenario(ctx), ctx.shared["instrument_metrics"])
    ctx.shared["interop"] = report
    atomic_write_json(ctx.out_dir / "interop.json", report)
    m = report["metrics"]
    log.write(f"InterOp simulation: density={m['cluster_density_k_mm2']}K/mm2 PF={m['clusters_pf_pct']}% "
              f"Q30={m['q30_pct']}% -> {report['status']}")


def step_fastqc(ctx: Ctx, log: StepLog) -> None:
    fastq = s3_sim.object_path(f"{ctx.prefix}/reads.fastq")  # QC runs on the synced S3 copy
    report = fastqc_sim.simulate_fastqc(ctx.sample_id, _scenario(ctx), fastq)
    ctx.shared["fastqc"] = report
    atomic_write_json(ctx.out_dir / "fastqc.json", report)
    summary = ", ".join(k + "=" + v["status"] for k, v in report["modules"].items())
    log.write(f"FastQC simulation on {report['basic_statistics']['total_reads']} reads -> {report['status']} ({summary})")


def step_evaluate_quality(ctx: Ctx, log: StepLog) -> None:
    with session_scope() as s:
        state.transition(s, s.get(Sample, ctx.sample_id), "QC_PENDING")
        policy = settings_service.get_setting(s, "warning_policy")
        verdict = quality.evaluate(ctx.shared["interop"], ctx.shared["fastqc"], policy)
        s.query(QualityResult).filter_by(attempt_id=ctx.attempt_id).delete()  # idempotent on retry
        s.add(QualityResult(attempt_id=ctx.attempt_id, sample_id=ctx.sample_id, run_id=ctx.run_id,
                            catalogue_version=ctx.version, interop=ctx.shared["interop"], fastqc=ctx.shared["fastqc"],
                            overall=verdict["overall"], reasons=verdict["reasons"]))
    ctx.shared["verdict"] = verdict
    atomic_write_json(ctx.out_dir / "quality_verdict.json", verdict)
    log.write(f"quality gate: {verdict['overall']} - " + "; ".join(verdict["reasons"]))


def step_update_final_status(ctx: Ctx, log: StepLog) -> None:
    """The ONLY place a sample can become PASSED, and only if QC passed for the catalogue
    version that is still current."""
    verdict = ctx.shared["verdict"]
    now = utcnow()
    with session_scope() as s:
        sample = s.get(Sample, ctx.sample_id)
        attempt = s.get(ProcessingAttempt, ctx.attempt_id)
        attempt.qc_status, attempt.ended_at = verdict["overall"], now
        if sample.catalogue_version != attempt.catalogue_version:
            attempt.status, attempt.accepted = "SUPERSEDED", False
            attempt.error = f"catalogue changed to {sample.catalogue_version} during processing"
            state.transition(s, sample, "RERUN_REQUIRED", attempt.error)
            sample.quality_status = "STALE"
            log.write(attempt.error + " -> results discarded, rerun required")
        elif verdict["overall"] == "PASS":
            attempt.status, attempt.accepted = "PASSED", True
            state.transition(s, sample, "PASSED", f"attempt #{ctx.attempt_no}")
            sample.processed_version = attempt.catalogue_version
            sample.quality_status = "PASS"
            sample.last_processed_at = now
            log.write(f"sample PASSED; processed_version={sample.processed_version}")
        else:
            attempt.status, attempt.accepted = "FAILED", False
            attempt.error = "quality gate failed: " + "; ".join(verdict["reasons"])
            state.transition(s, sample, "FAILED", "quality gate failed")
            sample.quality_status = "FAIL"
            sample.last_processed_at = now
            log.write("sample FAILED QC; processed_version unchanged, downstream access blocked")
        search_index.index_sample(s, sample)


def step_publish_downstream(ctx: Ctx, log: StepLog) -> Optional[str]:
    with session_scope() as s:
        sample = s.get(Sample, ctx.sample_id)
        ok, reason = downstream.eligibility(s, sample)
        if not ok:
            log.write(f"not published - blocked by quality gate: {reason}")
            return "SKIPPED"
        sample.published_at = utcnow()
        log_event(s, "downstream", f"{ctx.sample_id} published to downstream application (simulated)",
                  run_id=ctx.run_id, sample_id=ctx.sample_id)
    log.write("published to downstream application (simulated)")
    return None


STEP_FUNCS: dict[str, Callable[[Ctx, StepLog], Optional[str]]] = {
    "validate_source": step_validate_source,
    "sync_to_s3": step_sync_to_s3,
    "register_ingestion": step_register_ingestion,
    "instrument_metrics": step_instrument_metrics,
    "interop": step_interop,
    "fastqc": step_fastqc,
    "evaluate_quality": step_evaluate_quality,
    "update_final_status": step_update_final_status,
    "publish_downstream": step_publish_downstream,
}
assert list(STEP_FUNCS) == state.WORKFLOW_STEPS


# ---------------------------------------------------------------- engine
def _set_step(ctx: Ctx, name: str, **values: Any) -> None:
    with session_scope() as s:
        row = s.query(WorkflowStep).filter_by(job_id=ctx.job_id, name=name).one()
        for k, v in values.items():
            setattr(row, k, v)


def _execute_step(ctx: Ctx, name: str) -> bool:
    cfg = get_config()
    log = StepLog(ctx.job_id, name)
    _set_step(ctx, name, status="RUNNING", started_at=utcnow())
    if cfg.step_delay:
        time.sleep(cfg.step_delay)
    retries = 0
    while True:
        try:
            _maybe_inject_fault(ctx, name, log)
            outcome = STEP_FUNCS[name](ctx, log)
            log.flush()
            _set_step(ctx, name, status=outcome or "SUCCEEDED", ended_at=utcnow(), retries=retries)
            return True
        except TransientError as e:
            retries += 1
            if retries > cfg.max_retries:
                log.write(f"transient error persisted after {cfg.max_retries} retries: {e}")
                log.flush()
                _set_step(ctx, name, status="FAILED", ended_at=utcnow(), retries=retries - 1, error=str(e))
                return False
            wait = cfg.retry_backoff * 2 ** (retries - 1)
            log.write(f"transient error: {e} - retry {retries}/{cfg.max_retries} in {wait:.2f}s")
            log.flush()
            _set_step(ctx, name, status="RUNNING", retries=retries)
            if wait:
                time.sleep(wait)
        except SimulatedCrash:
            log.flush()
            raise
        except Exception as e:
            log.write(f"ERROR {type(e).__name__}: {e}")
            log.write(traceback.format_exc(limit=3))
            log.flush()
            _set_step(ctx, name, status="FAILED", ended_at=utcnow(), retries=retries, error=f"{type(e).__name__}: {e}")
            return False


def _fail_job(ctx: Ctx, failed_step: str) -> None:
    now = utcnow()
    with session_scope() as s:
        job = s.get(WorkflowJob, ctx.job_id)
        failed = next(st for st in job.steps if st.name == failed_step)
        for st in job.steps:
            if st.status == "PENDING":
                st.status = "SKIPPED"
        job.status, job.ended_at, job.error = "FAILED", now, f"step '{failed_step}' failed: {failed.error}"
        attempt = s.get(ProcessingAttempt, ctx.attempt_id)
        attempt.status, attempt.ended_at, attempt.error = "FAILED", now, job.error
        attempt.accepted = False
        sample = s.get(Sample, ctx.sample_id)
        if "FAILED" in state.ALLOWED.get(sample.status, set()):
            state.transition(s, sample, "FAILED", job.error)
        sample.quality_status = "ERROR"   # workflow error: no valid QC result exists
        search_index.index_sample(s, sample)
        log_event(s, "workflow", f"{ctx.job_id} FAILED: {job.error}", level="ERROR",
                  run_id=ctx.run_id, sample_id=ctx.sample_id)


def run_job(job_id: str) -> None:
    with session_scope() as s:
        job = s.get(WorkflowJob, job_id)
        if job is None or job.status != "QUEUED":
            return   # already picked up / finished: submission is idempotent
        attempt = s.get(ProcessingAttempt, job.attempt_id)
        now = utcnow()
        job.status, job.started_at = "RUNNING", now
        attempt.status, attempt.started_at = "RUNNING", now
        ctx = Ctx(job_id=job_id, attempt_id=attempt.id, attempt_no=attempt.attempt_no, sample_id=job.sample_id,
                  run_id=job.run_id, version=attempt.catalogue_version)
        log_event(s, "workflow", f"{job_id} started (simulated workflow; attempt #{attempt.attempt_no}, "
                                 f"catalogue {attempt.catalogue_version})", run_id=job.run_id, sample_id=job.sample_id)
    for name in state.WORKFLOW_STEPS:
        if not _execute_step(ctx, name):
            _fail_job(ctx, name)
            return
    with session_scope() as s:
        job = s.get(WorkflowJob, job_id)
        job.status, job.ended_at = "SUCCEEDED", utcnow()
        log_event(s, "workflow", f"{job_id} finished", run_id=ctx.run_id, sample_id=ctx.sample_id)


# ---------------------------------------------------------------- recovery
def recover_interrupted_jobs(exclude: set[str] = frozenset()) -> list[str]:
    """Called at startup (or on demand): find jobs a dead worker left RUNNING.

    * attempt still in progress -> attempt/job INTERRUPTED, sample FAILED, a RETRY attempt is queued
    * attempt already final (crash in the last step) -> just close the job, state is already correct
    * QUEUED jobs that never started -> returned for resubmission as-is
    """
    to_submit: list[str] = []
    with session_scope() as s:
        jobs = s.query(WorkflowJob).filter(WorkflowJob.status.in_(("QUEUED", "RUNNING"))).all()
        for job in jobs:
            if job.job_id in exclude:
                continue
            if job.status == "QUEUED":
                to_submit.append(job.job_id)
                continue
            attempt = s.get(ProcessingAttempt, job.attempt_id)
            now = utcnow()
            for st in job.steps:
                if st.status == "RUNNING":
                    st.status, st.ended_at = "INTERRUPTED", now
                    st.logs = (st.logs or "") + f"[{now:%H:%M:%S}] worker died - step interrupted\n"
                elif st.status == "PENDING":
                    st.status = "SKIPPED"
            job.status, job.ended_at, job.error = "INTERRUPTED", now, "worker stopped before the job finished"
            if attempt.status in ("QUEUED", "RUNNING"):
                attempt.status, attempt.ended_at, attempt.error, attempt.accepted = "INTERRUPTED", now, job.error, False
                sample = s.get(Sample, job.sample_id)
                if "FAILED" in state.ALLOWED.get(sample.status, set()):
                    state.transition(s, sample, "FAILED", "job interrupted")
                sample.quality_status = "ERROR"
                log_event(s, "recovery", f"{job.job_id} was interrupted; queuing a retry attempt", level="WARN",
                          run_id=job.run_id, sample_id=job.sample_id)
                s.flush()
                try:
                    _a, new_job = state.start_attempt(s, job.sample_id, "RETRY", "recovery")
                    to_submit.append(new_job.job_id)
                except state.Conflict:
                    pass
            else:
                log_event(s, "recovery", f"{job.job_id} interrupted after the attempt had already finished; closed",
                          level="WARN", run_id=job.run_id, sample_id=job.sample_id)
    return to_submit

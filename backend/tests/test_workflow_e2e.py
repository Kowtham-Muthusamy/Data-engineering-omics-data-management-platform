"""End-to-end behaviour through the real API (workflow jobs run inline in tests)."""
import hashlib

import pytest


def scan(client):
    r = client.post("/api/sequencer/scan")
    assert r.status_code == 200, r.text
    return r.json()


def ingest_three(client):
    """RUN_001 with SAMPLE_001 (good), SAMPLE_002 (poor quality), SAMPLE_003 (instrument warning)."""
    client.post("/api/runs", json={"sample_count": 3})
    return scan(client)


def sample(client, sid):
    return client.get(f"/api/samples/{sid}").json()


def nfs_hashes():
    from app.services import nfs
    root = nfs.nfs_root()
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


# ---- 3. initial ingestion + 7/8 FastQC PASS/FAIL ----------------------------------------------
def test_initial_ingestion_end_to_end(client):
    scanned = ingest_three(client)
    assert scanned["jobs_submitted"] == 3

    good = sample(client, "SAMPLE_001")
    assert good["status"] == "PASSED" and good["quality_status"] == "PASS"
    assert good["processed_version"] == "V1" and good["eligible_for_downstream"] is True

    # S3 has the files under RUN/SAMPLE/..., with size + checksum + manifest
    objs = client.get("/api/s3/objects", params={"sample_id": "SAMPLE_001"}).json()
    keys = {o["key"] for o in objs}
    assert {"RUN_001/SAMPLE_001/reads.fastq", "RUN_001/SAMPLE_001/catalogue.json",
            "RUN_001/SAMPLE_001/instrument_data/run_parameters.json"} <= keys
    assert all(o["size"] > 0 and len(o["checksum"]) == 64 and o["overwrite_count"] == 0 for o in objs)
    from app.config import get_config
    assert (get_config().s3_dir / "_manifests" / "RUN_001" / "SAMPLE_001.json").is_file()

    # the 9 workflow steps ran with timings and logs
    jobs = client.get("/api/workflows", params={"sample_id": "SAMPLE_001"}).json()
    detail = client.get(f"/api/workflows/{jobs[0]['job_id']}").json()
    assert detail["status"] == "SUCCEEDED" and detail["notice"].startswith("Local simulation")
    assert [s["name"] for s in detail["steps"]] == [
        "validate_source", "sync_to_s3", "register_ingestion", "instrument_metrics", "interop", "fastqc",
        "evaluate_quality", "update_final_status", "publish_downstream"]
    assert all(s["status"] == "SUCCEEDED" and s["started_at"] and s["ended_at"] and s["logs"] for s in detail["steps"])

    # the state machine was walked in order
    import re
    msgs = [e["message"] for e in client.get("/api/logs", params={"sample_id": "SAMPLE_001", "source": "state"}).json()]
    walked = [m.group(1) for m in (re.match(r"SAMPLE_001: ([A-Z_]+ -> [A-Z_]+)", x) for x in reversed(msgs)) if m]
    assert walked == ["DISCOVERED -> INGESTING", "INGESTING -> INGESTED", "INGESTED -> PROCESSING",
                      "PROCESSING -> QC_PENDING", "QC_PENDING -> PASSED"]


def test_fastqc_pass_and_fail_are_deterministic(client):
    ingest_three(client)
    qc = {r["sample_id"]: r for r in client.get("/api/qc/results").json()}
    assert qc["SAMPLE_001"]["overall"] == "PASS" and qc["SAMPLE_001"]["fastqc"]["status"] == "PASS"
    assert qc["SAMPLE_002"]["overall"] == "FAIL" and qc["SAMPLE_002"]["fastqc"]["status"] == "FAIL"
    assert qc["SAMPLE_002"]["fastqc"]["modules"]["per_base_sequence_quality"]["status"] == "FAIL"
    assert qc["SAMPLE_002"]["fastqc"]["modules"]["adapter_content"]["status"] == "FAIL"
    assert all(r["simulated"] and "simulation" in r["fastqc"]["tool"] for r in qc.values())
    assert qc["SAMPLE_001"]["interop"]["metrics"]["q30_pct"] > 85

    bad = sample(client, "SAMPLE_002")
    assert bad["status"] == "FAILED" and bad["quality_status"] == "FAIL" and bad["processed_version"] is None
    assert bad["eligible_for_downstream"] is False


def test_scenario_c_warning_result_is_configurable(client):
    ingest_three(client)
    c = sample(client, "SAMPLE_003")
    assert c["status"] == "PASSED"                       # default warning_policy=PASS
    qc = client.get("/api/qc/results", params={"sample_id": "SAMPLE_003"}).json()[0]
    assert qc["interop"]["status"] == "WARN"

    client.put("/api/settings", json={"warning_policy": "FAIL"})
    client.post("/api/runs", json={"sample_count": 3})      # RUN_002 -> SAMPLE_004..006
    scan(client)
    assert sample(client, "SAMPLE_006")["status"] == "FAILED"   # same warning scenario, stricter policy


def test_rescan_does_not_reprocess_anything(client):
    ingest_three(client)
    again = scan(client)
    assert again["jobs_submitted"] == 0 and again["unchanged_samples"] == 3 and again["new_runs"] == 0
    assert len(client.get("/api/workflows").json()) == 3


# ---- 9. downstream access restriction (enforced by the backend) ---------------------------------
def test_downstream_blocks_failed_samples_server_side(client):
    ingest_three(client)
    available = {s["sample_id"] for s in client.get("/api/downstream/available").json()}
    assert available == {"SAMPLE_001", "SAMPLE_003"}

    ok = client.get("/api/downstream/SAMPLE_001/fetch")
    assert ok.status_code == 200 and ok.json()["files"] and ok.json()["metadata"]["sample_id"] == "SAMPLE_001"
    dl = client.get(ok.json()["files"][0]["download_url"])
    assert dl.status_code == 200 and len(dl.content) > 0

    blocked = client.get("/api/downstream/SAMPLE_002/fetch")
    assert blocked.status_code == 403 and blocked.json()["detail"]["code"] == "QUALITY_GATE_BLOCKED"
    # guessing the download URL of a blocked sample must not work either
    assert client.get("/api/downstream/SAMPLE_002/download/reads.fastq").status_code == 403
    assert client.get("/api/downstream/NOPE/fetch").status_code == 404
    assert client.get("/api/downstream/SAMPLE_001/download/not/a/file").status_code == 404
    blocked_list = client.get("/api/downstream/available", params={"include_blocked": True}).json()
    assert {s["sample_id"]: s["eligible"] for s in blocked_list}["SAMPLE_002"] is False


# ---- 4/5/6. catalogue update, base recall, S3 overwrite, NFS untouched, history -----------------
def test_catalogue_update_and_base_recall_reprocesses_same_sample(client):
    ingest_three(client)
    before_s3 = {o["key"]: o for o in client.get("/api/s3/objects", params={"sample_id": "SAMPLE_001"}).json()}
    nfs_before = nfs_hashes()

    # scientist updates V1 -> V2: stale result is immediately withdrawn from downstream
    up = client.post("/api/samples/SAMPLE_001/catalogue/update", json={"version": "V2", "notes": "new basecalling"})
    assert up.status_code == 200
    s = sample(client, "SAMPLE_001")
    assert (s["status"], s["catalogue_version"], s["processed_version"]) == ("RERUN_REQUIRED", "V2", "V1")
    assert client.get("/api/downstream/SAMPLE_001/fetch").status_code == 403

    # a scan must NOT auto-run the rerun (it needs an explicit base recall)
    assert scan(client)["jobs_submitted"] == 0
    assert sample(client, "SAMPLE_001")["status"] == "RERUN_REQUIRED"

    r = client.post("/api/samples/SAMPLE_001/base-recall")
    assert r.status_code == 202 and r.json()["attempt_no"] == 2 and r.json()["catalogue_version"] == "V2"
    assert client.post("/api/samples/SAMPLE_001/base-recall").status_code == 409   # not RERUN_REQUIRED anymore

    after = sample(client, "SAMPLE_001")
    assert after["status"] == "PASSED" and after["processed_version"] == "V2"
    assert after["eligible_for_downstream"] is True
    assert len(client.get("/api/samples").json()) == 3                      # same sample, no duplicate created

    # S3: same keys, overwritten (not new keys), catalogue.json content changed
    after_s3 = {o["key"]: o for o in client.get("/api/s3/objects", params={"sample_id": "SAMPLE_001"}).json()}
    assert set(after_s3) == set(before_s3)
    assert all(o["overwrite_count"] == 1 and o["catalogue_version"] == "V2" for o in after_s3.values())
    cat_key = "RUN_001/SAMPLE_001/catalogue.json"
    assert after_s3[cat_key]["checksum"] != before_s3[cat_key]["checksum"]
    assert after_s3["RUN_001/SAMPLE_001/reads.fastq"]["checksum"] == before_s3["RUN_001/SAMPLE_001/reads.fastq"]["checksum"]
    from app.services import s3_sim
    assert '"V2"' in s3_sim.object_path(cat_key).read_text()
    assert client.get("/api/s3/versions", params={"key": cat_key}).json() == []   # native versioning stays off

    # NFS: only the deliberately edited catalogue.json differs; everything else is byte-identical
    nfs_after = nfs_hashes()
    changed = {k for k in nfs_before if nfs_before[k] != nfs_after[k]}
    assert changed == {"RUN_001/SAMPLE_001/catalogue.json"} and set(nfs_before) == set(nfs_after)
    integrity = {i["key"]: i["status"] for i in client.get("/api/nfs/integrity", params={"sample_id": "SAMPLE_001"}).json()}
    assert set(integrity.values()) == {"UNCHANGED"}                             # re-synced, so the record matches again

    # full history
    h = client.get("/api/samples/SAMPLE_001/history").json()
    assert [(a["attempt_no"], a["kind"], a["catalogue_version"], a["status"]) for a in h["attempts"]] == [
        (1, "INITIAL", "V1", "PASSED"), (2, "BASE_RECALL", "V2", "PASSED")]
    assert [a["accepted"] for a in h["attempts"]] == [False, True]
    assert [v["version"] for v in h["catalogue_versions"]] == ["V1", "V2"]
    assert h["processed_version"] == "V2"


def test_failed_rerun_never_exposes_stale_results(client):
    ingest_three(client)
    assert client.get("/api/downstream/SAMPLE_001/fetch").status_code == 200

    # V2 switches the sample into the poor-quality scenario, so the rerun fails QC
    client.post("/api/samples/SAMPLE_001/catalogue/update",
                json={"version": "V2", "fields": {"simulation_scenario": "B_POOR_QUALITY"}})
    assert client.post("/api/samples/SAMPLE_001/base-recall").status_code == 202
    s = sample(client, "SAMPLE_001")
    assert s["status"] == "FAILED" and s["quality_status"] == "FAIL"
    assert s["processed_version"] == "V1"                       # last *successful* version is kept for audit...
    assert s["eligible_for_downstream"] is False                # ...but the stale V1 result is NOT consumable
    assert client.get("/api/downstream/SAMPLE_001/fetch").status_code == 403
    assert client.get("/api/downstream/SAMPLE_001/download/reads.fastq").status_code == 403
    assert "SAMPLE_001" not in {x["sample_id"] for x in client.get("/api/downstream/available").json()}

    # fix the catalogue again -> V3 passes and access returns
    client.post("/api/samples/SAMPLE_001/catalogue/update",
                json={"version": "V3", "fields": {"simulation_scenario": "A_GOOD"}})
    client.post("/api/samples/SAMPLE_001/base-recall")
    s = sample(client, "SAMPLE_001")
    assert s["status"] == "PASSED" and s["processed_version"] == "V3"
    h = client.get("/api/samples/SAMPLE_001/history").json()
    assert [a["status"] for a in h["attempts"]] == ["PASSED", "FAILED", "PASSED"]


def test_catalogue_changed_during_processing_discards_result(client):
    """A catalogue edit that lands mid-run must not let the (now stale) result be accepted."""
    from app.database import session_scope
    from app.models.tables import Sample
    from app.services import catalogue, state, workflow
    client.post("/api/runs", json={"sample_count": 1})
    client.put("/api/settings", json={"auto_process": False})
    scan(client)
    with session_scope() as s:
        _a, job = state.start_attempt(s, "SAMPLE_001", "INITIAL", "test")
        job_id = job.job_id

    orig = workflow.step_interop

    def interop_then_edit(ctx, log):
        orig(ctx, log)
        with session_scope() as s:
            catalogue.update_catalogue(s, s.get(Sample, "SAMPLE_001"), "V2", "edited mid-run", {})

    workflow.STEP_FUNCS["interop"] = interop_then_edit
    try:
        workflow.run_job(job_id)
    finally:
        workflow.STEP_FUNCS["interop"] = orig
    s = sample(client, "SAMPLE_001")
    assert s["status"] == "RERUN_REQUIRED" and s["processed_version"] is None and s["quality_status"] == "STALE"
    assert s["eligible_for_downstream"] is False


# ---- 10. failures, retries and recovery --------------------------------------------------------
def make_faulty_sample(client, fault):
    client.post("/api/runs", json={"run_id": "RUN_F", "sample_count": 1, "mark_complete": False})
    from app.services import nfs
    meta = nfs.read_metadata("RUN_F", "SAMPLE_001")
    meta["fault"] = fault
    from app.utils.common import atomic_write_json
    atomic_write_json(nfs.sample_dir("RUN_F", "SAMPLE_001") / "sample_metadata.json", meta)
    client.post("/api/runs/RUN_F/complete")


def test_transient_error_is_retried_and_succeeds(client):
    make_faulty_sample(client, {"step": "sync_to_s3", "kind": "transient", "times": 2})
    scan(client)
    s = sample(client, "SAMPLE_001")
    assert s["status"] == "PASSED"
    job = client.get("/api/workflows", params={"sample_id": "SAMPLE_001"}).json()[0]
    step = next(x for x in client.get(f"/api/workflows/{job['job_id']}").json()["steps"] if x["name"] == "sync_to_s3")
    assert step["retries"] == 2 and "retry 2/3" in step["logs"]


def test_permanent_error_fails_job_and_never_marks_processed(client):
    make_faulty_sample(client, {"step": "fastqc", "kind": "permanent"})
    scan(client)
    s = sample(client, "SAMPLE_001")
    assert s["status"] == "FAILED" and s["processed_version"] is None and s["eligible_for_downstream"] is False
    job = client.get("/api/workflows", params={"sample_id": "SAMPLE_001"}).json()[0]
    d = client.get(f"/api/workflows/{job['job_id']}").json()
    assert d["status"] == "FAILED" and "fastqc" in d["error"]
    statuses = {x["name"]: x["status"] for x in d["steps"]}
    assert statuses["fastqc"] == "FAILED" and statuses["evaluate_quality"] == "SKIPPED"
    assert statuses["sync_to_s3"] == "SUCCEEDED"
    # execute endpoint retries a FAILED sample as a new attempt of kind RETRY
    again = client.post("/api/workflows/RUN_F/execute")
    assert again.status_code == 202 and again.json()["submitted"][0]["kind"] == "RETRY"
    assert sample(client, "SAMPLE_001")["status"] == "FAILED"          # fault still active


def test_recovery_after_simulated_worker_crash(client):
    from app.services import workflow
    from app.workers import job_runner
    from app.services import sequencer
    make_faulty_sample(client, {"step": "fastqc", "kind": "crash", "times": 1})
    with pytest.raises(workflow.SimulatedCrash):
        sequencer.scan("manual")                        # worker "dies" inside the fastqc step

    # state is exactly what a dead process leaves behind
    s = sample(client, "SAMPLE_001")
    assert s["status"] == "PROCESSING" and s["processed_version"] is None
    job = client.get("/api/workflows", params={"sample_id": "SAMPLE_001"}).json()[0]
    assert job["status"] == "RUNNING"
    assert client.get("/api/downstream/SAMPLE_001/fetch").status_code == 403

    resubmitted = job_runner.recover()                  # what the app does on startup
    assert len(resubmitted) == 1

    s = sample(client, "SAMPLE_001")
    assert s["status"] == "PASSED" and s["processed_version"] == "V1"
    h = client.get("/api/samples/SAMPLE_001/history").json()
    assert [(a["attempt_no"], a["kind"], a["status"]) for a in h["attempts"]] == [
        (1, "INITIAL", "INTERRUPTED"), (2, "RETRY", "PASSED")]
    old = client.get(f"/api/workflows/{job['job_id']}").json()
    assert old["status"] == "INTERRUPTED"
    assert {x["name"]: x["status"] for x in old["steps"]}["fastqc"] == "INTERRUPTED"
    assert job_runner.recover() == []                   # nothing left to recover


def test_invalid_source_folder_fails_validation(client):
    client.post("/api/runs", json={"run_id": "RUN_V", "sample_count": 1})
    from app.services import nfs
    (nfs.sample_dir("RUN_V", "SAMPLE_001") / "reads.fastq").write_text("not a fastq\n")
    scan(client)
    s = sample(client, "SAMPLE_001")
    assert s["status"] == "FAILED"
    job = client.get("/api/workflows").json()[0]
    assert "not valid FASTQ" in client.get(f"/api/workflows/{job['job_id']}").json()["error"]
    assert client.get("/api/s3/objects").json() == []          # nothing was uploaded


def test_s3_versioning_simulation_is_optional_and_separate_from_catalogue_versions(client):
    client.put("/api/settings", json={"s3_versioning_enabled": True})
    ingest_three(client)
    client.post("/api/samples/SAMPLE_001/catalogue/update", json={"version": "V2"})
    client.post("/api/samples/SAMPLE_001/base-recall")
    versions = client.get("/api/s3/versions", params={"key": "RUN_001/SAMPLE_001/catalogue.json"}).json()
    assert len(versions) == 2 and [v["is_latest"] for v in versions] == [False, True]
    objs = client.get("/api/s3/objects", params={"sample_id": "SAMPLE_001"}).json()
    assert len(objs) == 5                                       # object versions did not create extra keys


def test_dashboard_and_logs(client):
    ingest_three(client)
    client.post("/api/samples/SAMPLE_001/catalogue/update", json={"version": "V2"})
    client.post("/api/samples/SAMPLE_001/base-recall")
    d = client.get("/api/dashboard/summary").json()
    k = d["kpis"]
    assert (k["total_runs"], k["total_samples"], k["passed_qc"], k["failed_qc"], k["reruns_initiated"]) == (1, 3, 2, 1, 1)
    assert {c["name"]: c["value"] for c in d["charts"]["catalogue_versions"]} == {"V1": 2, "V2": 1}
    assert {c["name"]: c["value"] for c in d["charts"]["pass_fail"]} == {"PASS": 2, "FAIL": 1}
    assert d["recent_activity"] and len(d["charts"]["ingestion_activity"]) == 14
    assert client.get("/api/logs", params={"level": "ERROR"}).status_code == 200


def test_openapi_documents_all_required_endpoints(client):
    paths = client.get("/openapi.json").json()["paths"]
    for p in ["/api/runs", "/api/runs/{run_id}", "/api/sequencer/scan", "/api/sequencer/status", "/api/s3/objects",
              "/api/metadata/search", "/api/workflows", "/api/workflows/{job_id}", "/api/workflows/{run_id}/execute",
              "/api/samples/{sample_id}/catalogue/update", "/api/samples/{sample_id}/base-recall",
              "/api/samples/{sample_id}/history", "/api/qc/results", "/api/downstream/available",
              "/api/downstream/{sample_id}/fetch"]:
        assert p in paths, p

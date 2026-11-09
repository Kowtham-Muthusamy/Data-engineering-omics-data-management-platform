"""Sequencer discovery, version detection, state tracking and metadata search."""
import pytest


@pytest.fixture()
def no_auto(client):
    """Discovery only: don't submit workflows (those are covered in the workflow tests)."""
    assert client.put("/api/settings", json={"auto_process": False}).status_code == 200


def scan(client):
    r = client.post("/api/sequencer/scan")
    assert r.status_code == 200, r.text
    return r.json()


def test_new_folder_discovery(client, no_auto):
    client.post("/api/runs", json={"sample_count": 2})
    s = scan(client)
    assert (s["discovered_folders"], s["new_runs"], s["new_samples"], s["skipped_folders"]) == (1, 1, 2, 0)
    run = client.get("/api/runs/RUN_001").json()
    assert run["discovered"] and run["state"] == "DISCOVERED" and run["sample_count"] == 2
    sample = client.get("/api/samples/SAMPLE_001").json()
    assert sample["status"] == "DISCOVERED" and sample["catalogue_version"] == "V1"
    assert sample["s3_destination"] == "s3://local-sim-bucket/RUN_001/SAMPLE_001/"


def test_duplicate_folder_detection_is_idempotent(client, no_auto):
    client.post("/api/runs", json={"sample_count": 2})
    scan(client)
    second = scan(client)
    assert second["new_runs"] == 0 and second["new_samples"] == 0 and second["unchanged_samples"] == 2
    assert len(client.get("/api/samples").json()) == 2


def test_incomplete_folder_is_skipped_until_marker_arrives(client, no_auto):
    client.post("/api/runs", json={"run_id": "RUN_X", "sample_count": 1, "mark_complete": False})
    first = scan(client)
    assert first["skipped_folders"] == 1 and first["new_runs"] == 0
    assert client.get("/api/samples").json() == []
    assert client.get("/api/runs/RUN_X").json()["state"] == "INCOMPLETE"
    client.post("/api/runs/RUN_X/complete")
    assert scan(client)["new_runs"] == 1


def test_catalogue_update_marks_processed_sample_rerun_required(client, no_auto):
    from app.database import session_scope
    from app.models.tables import Sample
    client.post("/api/runs", json={"sample_count": 1})
    scan(client)
    with session_scope() as s:  # pretend the sample was already processed successfully at V1
        smp = s.get(Sample, "SAMPLE_001")
        smp.status, smp.processed_version, smp.quality_status = "PASSED", "V1", "PASS"

    r = client.post("/api/samples/SAMPLE_001/catalogue/update", json={"version": "V2", "notes": "recalibrated"})
    assert r.status_code == 200 and r.json()["version"] == "V2"
    smp = client.get("/api/samples/SAMPLE_001").json()
    assert smp["status"] == "RERUN_REQUIRED" and smp["catalogue_version"] == "V2"
    assert smp["processed_version"] == "V1" and smp["quality_status"] == "STALE"
    assert smp["eligible_for_downstream"] is False


def test_catalogue_update_validation(client, no_auto):
    client.post("/api/runs", json={"sample_count": 1})
    scan(client)
    assert client.post("/api/samples/SAMPLE_001/catalogue/update", json={"version": "banana"}).status_code == 422
    assert client.post("/api/samples/SAMPLE_001/catalogue/update", json={"version": "V1"}).status_code == 409
    assert client.post("/api/samples/NOPE/catalogue/update", json={"version": "V2"}).status_code == 404


def test_scan_detects_version_change_made_directly_on_nfs(client, no_auto):
    from app.services import nfs
    client.post("/api/runs", json={"sample_count": 1})
    scan(client)
    cat = nfs.read_catalogue("RUN_001", "SAMPLE_001")
    cat["version"] = "V3"
    nfs.write_catalogue("RUN_001", "SAMPLE_001", cat)
    s = scan(client)
    assert s["changed_versions"] == 1 and s["unchanged_samples"] == 0
    assert client.get("/api/samples/SAMPLE_001").json()["catalogue_version"] == "V3"
    history = client.get("/api/samples/SAMPLE_001/history").json()
    assert [v["version"] for v in history["catalogue_versions"]] == ["V1", "V3"]


def test_metadata_search_filters(client, no_auto):
    client.post("/api/runs", json={"sample_count": 3})
    scan(client)
    assert client.get("/api/metadata/search").json()["total"] == 3
    assert client.get("/api/metadata/search", params={"sample_id": "SAMPLE_002"}).json()["total"] == 1
    assert client.get("/api/metadata/search", params={"run_id": "RUN_001", "catalogue_version": "V1"}).json()["total"] == 3
    assert client.get("/api/metadata/search", params={"processing_status": "PASSED"}).json()["total"] == 0
    assert client.get("/api/metadata/search", params={"quality_status": "NOT_RUN"}).json()["total"] == 3
    assert client.get("/api/metadata/search", params={"q": "homo sapiens"}).status_code == 200
    assert client.get("/api/metadata/search", params={"created_from": "2999-01-01"}).json()["total"] == 0
    assert client.get("/api/metadata/search", params={"created_from": "garbage"}).status_code == 422


def test_invalid_state_transition_rejected(client, no_auto):
    from app.database import session_scope
    from app.models.tables import Sample
    from app.services import state
    client.post("/api/runs", json={"sample_count": 1})
    scan(client)
    with session_scope() as s:
        with pytest.raises(state.InvalidTransition):
            state.transition(s, s.get(Sample, "SAMPLE_001"), "PASSED")  # DISCOVERED -> PASSED is not allowed


def test_concurrent_claim_cannot_double_start(client, no_auto):
    from app.database import session_scope
    from app.services import state
    client.post("/api/runs", json={"sample_count": 1})
    scan(client)
    with session_scope() as s:
        state.start_attempt(s, "SAMPLE_001", "INITIAL", "test")
    with session_scope() as s:
        with pytest.raises(state.Conflict):
            state.start_attempt(s, "SAMPLE_001", "INITIAL", "test")


def test_settings_validation(client):
    assert client.put("/api/settings", json={"scan_interval_seconds": 0}).status_code == 422
    assert client.put("/api/settings", json={"warning_policy": "maybe"}).status_code == 422
    assert client.put("/api/settings", json={"scan_interval_seconds": 5}).json()["scan_interval_seconds"] == 5
    st = client.get("/api/sequencer/status").json()
    assert st["interval_seconds"] == 5 and st["scanning"] is False

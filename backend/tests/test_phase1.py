def test_create_run_and_upload(client):
    r = client.post("/api/runs", json={"sample_count": 2})
    assert r.status_code == 201
    body = r.json()
    assert body["run_id"] == "RUN_001" and body["state"] == "NOT_DISCOVERED" and body["complete"]
    assert body["nfs_samples"] == ["SAMPLE_001", "SAMPLE_002"]

    tree = client.get("/api/nfs/tree").json()
    files = {f["path"] for f in tree[0]["samples"][0]["files"]}
    assert {"reads.fastq", "catalogue.json", "sample_metadata.json", "instrument_data/run_parameters.json"} <= files


def test_incomplete_run_accepts_uploads_complete_run_is_immutable(client):
    client.post("/api/runs", json={"run_id": "RUN_X", "sample_count": 0, "mark_complete": False})
    assert client.post("/api/runs/RUN_X/samples", json={"scenario": "A_GOOD"}).status_code == 201
    up = client.post("/api/runs/RUN_X/files", params={"sample_id": "SAMPLE_001", "path": "instrument_data/extra.txt"},
                     files={"file": ("extra.txt", b"hello")})
    assert up.status_code == 201
    assert client.post("/api/runs/RUN_X/complete").json()["complete"] is True
    again = client.post("/api/runs/RUN_X/files", params={"sample_id": "SAMPLE_001", "path": "x.txt"},
                        files={"file": ("x.txt", b"nope")})
    assert again.status_code == 409


def test_upload_path_traversal_rejected(client):
    client.post("/api/runs", json={"run_id": "RUN_X", "sample_count": 1, "mark_complete": False})
    r = client.post("/api/runs/RUN_X/files", params={"sample_id": "SAMPLE_001", "path": "../../evil.txt"},
                    files={"file": ("e.txt", b"x")})
    assert r.status_code == 422


def test_duplicate_run_conflict(client):
    assert client.post("/api/runs", json={"run_id": "RUN_A", "sample_count": 1}).status_code == 201
    assert client.post("/api/runs", json={"run_id": "RUN_A", "sample_count": 1}).status_code == 409


def test_s3_put_overwrites_same_key(client, tmp_path):
    from app.database import session_scope
    from app.services import s3_sim
    src = tmp_path / "f.txt"
    src.write_text("one")
    with session_scope() as s:
        a = s3_sim.put_file(s, "RUN_1/S_1/f.txt", src, run_id="RUN_1", sample_id="S_1", attempt_id=1,
                            catalogue_version="V1")
        assert a.overwrite_count == 0
        first_checksum = a.checksum
    src.write_text("two-changed")
    with session_scope() as s:
        b = s3_sim.put_file(s, "RUN_1/S_1/f.txt", src, run_id="RUN_1", sample_id="S_1", attempt_id=2,
                            catalogue_version="V2")
        assert b.overwrite_count == 1 and b.checksum != first_checksum
    assert s3_sim.object_path("RUN_1/S_1/f.txt").read_text() == "two-changed"
    assert len(client.get("/api/s3/objects").json()) == 1
    assert client.get("/api/s3/versions", params={"key": "RUN_1/S_1/f.txt"}).json() == []  # versioning off by default

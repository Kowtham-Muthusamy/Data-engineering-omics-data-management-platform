"""Rate limiting and audit logging."""
import pytest

from app.services.ratelimit import SlidingWindowLimiter


@pytest.fixture()
def limits():
    """Temporarily lower the limits; restored afterwards."""
    from app.config import get_config
    cfg = get_config()
    saved = (cfg.rate_limit_read, cfg.rate_limit_write, cfg.rate_limit_download)
    yield cfg
    cfg.rate_limit_read, cfg.rate_limit_write, cfg.rate_limit_download = saved


def audit_rows(client, **params):
    return client.get("/api/audit", params=params).json()["items"]


# ---- rate limiting ----------------------------------------------------------------------------
def test_limiter_sliding_window():
    lim = SlidingWindowLimiter()
    assert [lim.check(("a",), 2, 10, now=t)[0] for t in (0, 1, 2)] == [True, True, False]
    ok, _, retry = lim.check(("a",), 2, 10, now=3)
    assert not ok and 1 <= retry <= 8
    assert lim.check(("a",), 2, 10, now=10.5)[0]          # first hit slid out of the window
    assert lim.check(("b",), 2, 10, now=3)[0]             # other clients are independent


def test_write_limit_returns_429_with_headers(client, limits):
    limits.rate_limit_write = 3
    codes = [client.post("/api/sequencer/scan").status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    r = client.post("/api/sequencer/scan")
    assert r.json()["detail"]["code"] == "RATE_LIMITED"
    assert int(r.headers["Retry-After"]) >= 1 and r.headers["X-RateLimit-Remaining"] == "0"
    assert r.headers["X-Request-ID"]


def test_buckets_are_independent_and_health_is_exempt(client, limits):
    limits.rate_limit_write = 1
    assert client.post("/api/sequencer/scan").status_code == 200
    assert client.post("/api/sequencer/scan").status_code == 429
    assert client.get("/api/runs").status_code == 200        # reads have their own bucket
    for _ in range(5):
        assert client.get("/api/health").status_code == 200


def test_spoofed_forwarded_header_does_not_bypass_limit(client, limits):
    limits.rate_limit_write = 1
    client.post("/api/sequencer/scan")
    r = client.post("/api/sequencer/scan", headers={"X-Forwarded-For": "9.9.9.9"})
    assert r.status_code == 429


def test_download_bucket(client, limits):
    limits.rate_limit_download = 2
    codes = [client.get("/api/downstream/SAMPLE_001/fetch").status_code for _ in range(3)]
    assert codes[-1] == 429 and 429 not in codes[:2]


# ---- audit log --------------------------------------------------------------------------------
def test_writes_are_audited_and_reads_are_not(client):
    client.get("/api/runs")
    resp = client.post("/api/runs", json={"sample_count": 1}, headers={"X-Actor": "alice", "X-Request-ID": "req-123"})
    rows = audit_rows(client)
    assert len(rows) == 1
    row = rows[0]
    assert (row["method"], row["route"], row["actor"], row["outcome"]) == ("POST", "/api/runs", "alice", "SUCCESS")
    assert row["request_id"] == "req-123" and row["status_code"] == resp.status_code


def test_denied_downstream_fetch_is_audited_with_resource(client):
    from tests.test_workflow_e2e import ingest_three
    ingest_three(client)
    assert client.get("/api/downstream/SAMPLE_001/fetch").status_code == 200
    assert client.get("/api/downstream/SAMPLE_002/fetch").status_code == 403
    denied = audit_rows(client, outcome="DENIED")
    assert [(r["resource"], r["status_code"]) for r in denied] == [("SAMPLE_002", 403)]
    assert any(r["resource"] == "SAMPLE_001" and r["outcome"] == "SUCCESS" for r in audit_rows(client, method="GET"))


def test_rate_limited_requests_are_audited(client, limits):
    limits.rate_limit_write = 1
    client.post("/api/sequencer/scan")
    client.post("/api/sequencer/scan")
    assert [r["status_code"] for r in audit_rows(client, outcome="RATE_LIMITED")] == [429]


def test_request_id_is_sanitised_and_no_body_is_stored(client):
    client.post("/api/runs", json={"sample_count": 1}, headers={"X-Request-ID": "a b<script>"})
    row = audit_rows(client)[0]
    assert row["request_id"] == "abscript"
    assert set(row) == {"id", "ts", "request_id", "actor", "client_ip", "method", "route", "path", "resource",
                        "status_code", "outcome", "duration_ms"}


def test_hash_chain_detects_tampering(client):
    for _ in range(3):
        client.post("/api/sequencer/scan")
    assert client.get("/api/audit/verify").json() == {"valid": True, "checked": 3, "first_bad_id": None}

    from app.database import session_scope
    from app.models.tables import AuditLog
    with session_scope() as s:
        s.query(AuditLog).filter_by(id=2).one().status_code = 204      # rewrite history
    bad = client.get("/api/audit/verify").json()
    assert bad["valid"] is False and bad["first_bad_id"] == 2

    with session_scope() as s:
        s.query(AuditLog).filter_by(id=2).one().status_code = 200
        s.query(AuditLog).filter_by(id=1).delete()                     # delete a row
    assert client.get("/api/audit/verify").json()["valid"] is False

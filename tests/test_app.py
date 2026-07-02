from fastapi.testclient import TestClient

from ski_memory.app import create_app
from ski_memory.config import Config


def make_client(tmp_path):
    cfg = Config(home=tmp_path, host="127.0.0.1", port=0)
    return TestClient(create_app(cfg))


def test_health(tmp_path):
    c = make_client(tmp_path)
    r = c.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_status_reports_sovereign_and_verified(tmp_path):
    c = make_client(tmp_path)
    s = c.get("/api/status").json()
    assert s["sovereign"] is True
    assert s["outbound_connections"] == 0
    assert s["ledger"]["verified"] is True
    assert s["ledger"]["entries"] >= 1  # store.initialized entry
    assert len(s["identity"]["fingerprint"]) > 0


def test_index_served(tmp_path):
    c = make_client(tmp_path)
    r = c.get("/")
    assert r.status_code == 200
    assert "Continuum" in r.text

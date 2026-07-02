import time

from fastapi.testclient import TestClient

from ski_memory import llm, ollama
from ski_memory.app import create_app
from ski_memory.config import Config


def client(tmp_path):
    return TestClient(create_app(Config(home=tmp_path)))


def test_models_endpoint_shape(tmp_path):
    c = client(tmp_path)
    d = c.get("/api/models").json()
    assert "available" in d and "installed" in d
    assert isinstance(d["recommended"], list) and d["recommended"]
    assert all("name" in r and "note" in r for r in d["recommended"])


def test_pull_requires_ollama_when_absent(tmp_path, monkeypatch):
    # Force "no ollama" regardless of environment.
    monkeypatch.setattr(ollama, "detect", lambda timeout=0.4: {"available": False, "models": []})
    c = client(tmp_path)
    r = c.post("/api/models/pull", json={"name": "llama3.2"})
    assert r.status_code == 503


def test_pull_missing_name(tmp_path, monkeypatch):
    monkeypatch.setattr(ollama, "detect", lambda timeout=0.4: {"available": True, "models": []})
    c = client(tmp_path)
    r = c.post("/api/models/pull", json={"name": "  "})
    assert r.status_code == 400


def test_start_pull_records_error_without_ollama():
    # No Ollama running in CI/sandbox -> the background pull should fail cleanly.
    name = "no-such-model-xyz"
    llm.start_pull(name)
    for _ in range(50):
        st = llm.pull_status().get(name, {})
        if st.get("done"):
            break
        time.sleep(0.1)
    st = llm.pull_status().get(name, {})
    assert st.get("done") is True
    assert st.get("error")  # connection refused / failure captured, not crashed

from fastapi.testclient import TestClient

from ski_memory import sysinfo
from ski_memory.app import create_app
from ski_memory.config import Config


def test_detect_shape():
    info = sysinfo.detect()
    for k in ("os", "arch", "cpu_count", "ram_gb", "apple_silicon", "gpu"):
        assert k in info
    assert info["cpu_count"] >= 0


def test_recommend_low_memory_machine():
    info = {"ram_gb": 4.0, "gpu": None, "apple_silicon": False}
    r = sysinfo.recommend(info)
    tiers = {c["tier"]: c for c in r["cards"]}
    assert tiers["Fast"]["feasible"] is True
    # On a small machine, Max collapses onto Recommended.
    assert tiers["Max quality"]["name"] == tiers["Recommended"]["name"]
    assert r["accelerator"] == "CPU only"


def test_recommend_workstation():
    info = {"ram_gb": 64.0, "gpu": {"vendor": "NVIDIA", "vram_gb": 48.0, "unified": False},
            "apple_silicon": False}
    r = sysinfo.recommend(info)
    tiers = {c["tier"]: c for c in r["cards"]}
    assert tiers["Max quality"]["name"] == "llama3.3:70b"
    assert tiers["Max quality"]["feasible"] is True
    assert "NVIDIA" in r["accelerator"]


def test_recommend_mid_machine_16gb():
    info = {"ram_gb": 16.0, "gpu": None, "apple_silicon": False}
    r = sysinfo.recommend(info)
    tiers = {c["tier"]: c for c in r["cards"]}
    assert tiers["Recommended"]["name"] == "qwen2.5:7b"
    assert tiers["Max quality"]["name"] == "qwen2.5:14b"
    assert tiers["Recommended"]["feasible"] and tiers["Max quality"]["feasible"]


def test_recommend_apple_silicon():
    info = {"ram_gb": 24.0, "gpu": {"vendor": "Apple Silicon", "vram_gb": 16.8, "unified": True},
            "apple_silicon": True}
    r = sysinfo.recommend(info)
    assert "Apple" in r["accelerator"]


def test_system_endpoint(tmp_path):
    c = TestClient(create_app(Config(home=tmp_path)))
    d = c.get("/api/system").json()
    assert "system" in d and "recommendation" in d
    assert len(d["recommendation"]["cards"]) == 3
    assert all("installed" in card for card in d["recommendation"]["cards"])

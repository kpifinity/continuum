"""Update check: version comparison, toggle, and offline-safety."""
from ski_memory import updates


def test_version_comparison():
    assert updates._newer("0.2.0", "0.1.0")
    assert updates._newer("1.0.0", "0.9.9")
    assert updates._newer("0.1.10", "0.1.2")
    assert not updates._newer("0.1.0", "0.1.0")
    assert not updates._newer("0.1.0", "0.2.0")
    # lenient about suffixes
    assert updates._newer("0.2.0-beta", "0.1.0")


def test_settings_default_on_and_toggle(tmp_path):
    assert updates.settings(tmp_path) == {"check_enabled": True}
    assert updates.set_check_enabled(tmp_path, False) == {"check_enabled": False}
    assert updates.settings(tmp_path) == {"check_enabled": False}


def test_check_offline_is_safe(tmp_path, monkeypatch):
    # No network: manifest fetch fails -> falls back to a safe empty result.
    monkeypatch.setattr(updates, "_fetch_manifest", lambda: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(updates, "_ollama_version", lambda: None)
    r = updates.check(tmp_path, force=True)
    assert r["app_update_available"] is False
    assert r["current"] == updates.__version__
    assert r["check_enabled"] is True


def test_check_detects_update(tmp_path, monkeypatch):
    monkeypatch.setattr(updates, "_fetch_manifest", lambda: {
        "version": "999.0.0", "notes": "Big update", "url": "https://skiframework.org/continuum",
        "ollama_recommended": "0.0.0"})
    monkeypatch.setattr(updates, "_ollama_version", lambda: "0.1.0")
    r = updates.check(tmp_path, force=True)
    assert r["app_update_available"] is True
    assert r["latest"] == "999.0.0"
    assert r["notes"] == "Big update"
    # ollama recommended is older -> no ollama update
    assert r["ollama_update_available"] is False


def test_check_detects_ollama_update(tmp_path, monkeypatch):
    monkeypatch.setattr(updates, "_fetch_manifest", lambda: {
        "version": "0.0.0", "ollama_recommended": "0.5.0"})
    monkeypatch.setattr(updates, "_ollama_version", lambda: "0.1.0")
    r = updates.check(tmp_path, force=True)
    assert r["app_update_available"] is False
    assert r["ollama_update_available"] is True


def test_disabled_skips_network(tmp_path, monkeypatch):
    updates.set_check_enabled(tmp_path, False)
    called = {"n": 0}

    def boom():
        called["n"] += 1
        raise AssertionError("should not fetch when disabled")

    monkeypatch.setattr(updates, "_fetch_manifest", boom)
    r = updates.check(tmp_path)  # not forced, disabled
    assert called["n"] == 0
    assert r["check_enabled"] is False

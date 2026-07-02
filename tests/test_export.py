import copy
from pathlib import Path

from ski_memory import export, ingest, continuation, llm
from ski_memory.config import Config
from ski_memory.store import Store

EX = Path(__file__).parent.parent / "examples"


def seeded(tmp_path):
    s = Store(Config(home=tmp_path))
    ingest.import_into_store(s, (EX / "claude_export.json").read_text(), "claude")
    return s


def test_build_and_verify_roundtrip(tmp_path):
    s = seeded(tmp_path)
    bundle = export.build_export(s, "claude:c-001")
    ok, checks = export.verify_export(bundle)
    assert ok, checks
    assert all(c["ok"] for c in checks)
    assert bundle["manifest"]["message_count"] == 2


def test_export_includes_continuation_ledger_entry(tmp_path, monkeypatch):
    s = seeded(tmp_path)
    monkeypatch.setattr(llm, "chat", lambda msgs, model=None: ("reply", "llama3.2"))
    continuation.continue_conversation(s, "claude:c-001", "more?")
    bundle = export.build_export(s, "claude:c-001")
    kinds = [e["kind"] for e in bundle["manifest"]["ledger_entries"]]
    assert "continuation" in kinds
    ok, _ = export.verify_export(bundle)
    assert ok


def test_tampered_message_detected(tmp_path):
    s = seeded(tmp_path)
    bundle = export.build_export(s, "claude:c-001")
    bad = copy.deepcopy(bundle)
    bad["manifest"]["messages"][0]["content"] = "ALTERED"
    ok, checks = export.verify_export(bad)
    assert not ok
    assert any(c["name"].startswith("messages") and not c["ok"] for c in checks)


def test_tampered_signature_detected(tmp_path):
    s = seeded(tmp_path)
    bundle = export.build_export(s, "claude:c-001")
    bad = copy.deepcopy(bundle)
    bad["signature"] = "00" * 64
    ok, checks = export.verify_export(bad)
    assert not ok
    assert any(c["name"].startswith("export signature") and not c["ok"] for c in checks)


def test_malformed_bundle_is_safe(tmp_path):
    ok, checks = export.verify_export({"nope": 1})
    assert not ok

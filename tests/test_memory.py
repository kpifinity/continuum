from pathlib import Path

from ski_memory import memory, ask, ingest, llm
from ski_memory.config import Config
from ski_memory.store import Store

EX = Path(__file__).parent.parent / "examples"


def test_add_list_search_and_ledger(tmp_path):
    s = Store(Config(home=tmp_path))
    r = memory.add_entry(s, "Ledger choice", "We use Ed25519 to sign the hash-chained ledger.",
                         tags=["crypto"], provenance={"sources": ["Claude", "ChatGPT"]})
    assert r["id"].startswith("mem:")
    entries = memory.list_entries(s)
    assert len(entries) == 1 and entries[0]["title"] == "Ledger choice"
    hits = memory.search(s, "Ed25519")
    assert hits and "Ed25519" in hits[0]["snippet"]
    ok, err = s.ledger.verify()
    assert ok, err


def test_consolidate_uses_model(tmp_path, monkeypatch):
    s = Store(Config(home=tmp_path))
    seen = {}
    def fake(msgs, model=None):
        seen["msgs"] = msgs
        return ("Consensus: yes.\nConflicts: none.\nConsolidated: do it.", "llama3.2")
    monkeypatch.setattr(llm, "chat", fake)
    res = memory.consolidate(s, "Rent or sell?",
                             [{"model": "Claude", "text": "Rent it."},
                              {"model": "ChatGPT", "text": "Sell it."}])
    assert res["model"] == "llama3.2" and res["sources"] == ["Claude", "ChatGPT"]
    user_msg = [m for m in seen["msgs"] if m["role"] == "user"][0]["content"]
    assert "Claude answered" in user_msg and "ChatGPT answered" in user_msg
    ok, err = s.ledger.verify()
    assert ok, err


def test_ask_includes_saved_memory(tmp_path, monkeypatch):
    s = Store(Config(home=tmp_path))
    ingest.import_into_store(s, (EX / "claude_export.json").read_text(), "claude")
    memory.add_entry(s, "Signing decision",
                     "We decided to use Ed25519 signing for every ledger entry.",
                     provenance={"sources": ["consolidated"]})
    captured = {}
    def fake(msgs, model=None):
        captured["msgs"] = msgs
        return ("answer", "m")
    monkeypatch.setattr(llm, "chat", fake)
    res = ask.ask(s, "What did we decide about signing?")
    assert any(c.get("method") == "memory" for c in res["context"])
    assert any("saved Memory" in m["content"] for m in captured["msgs"])

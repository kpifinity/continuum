import pytest

from ski_memory import continuation, ingest, llm
from ski_memory.config import Config
from ski_memory.store import Store
from pathlib import Path

EX = Path(__file__).parent.parent / "examples"


def seeded_store(tmp_path):
    s = Store(Config(home=tmp_path))
    ingest.import_into_store(s, (EX / "claude_export.json").read_text(), "claude")
    return s


def test_continuation_appends_and_keeps_ledger_valid(tmp_path, monkeypatch):
    s = seeded_store(tmp_path)
    monkeypatch.setattr(llm, "chat", lambda msgs, model=None: ("Sure, here's more.", "llama3.2"))
    before = s.counts()["messages"]
    res = continuation.continue_conversation(s, "claude:c-001", "What about key management?")
    assert res["model"] == "llama3.2"
    assert len(res["messages"]) == 2
    assert s.counts()["messages"] == before + 2
    ok, err = s.ledger.verify()
    assert ok, err
    row = s.conn.execute(
        "SELECT meta FROM messages WHERE role='assistant' ORDER BY seq DESC LIMIT 1").fetchone()
    assert "local_continuation" in (row[0] or "")


def test_continuation_passes_history_to_model(tmp_path, monkeypatch):
    s = seeded_store(tmp_path)
    captured = {}
    def fake(msgs, model=None):
        captured["msgs"] = msgs
        return ("ok", "m")
    monkeypatch.setattr(llm, "chat", fake)
    continuation.continue_conversation(s, "claude:c-001", "Follow-up question")
    roles = [m["role"] for m in captured["msgs"]]
    assert roles[0] == "system" and roles[-1] == "user"
    assert any("Ed25519" in m["content"] for m in captured["msgs"])


def test_unknown_conversation_raises(tmp_path):
    s = seeded_store(tmp_path)
    with pytest.raises(continuation.ConversationNotFound):
        continuation.continue_conversation(s, "nope:123", "hi")


def test_llm_unavailable_propagates(tmp_path, monkeypatch):
    s = seeded_store(tmp_path)
    def boom(msgs, model=None):
        raise llm.LLMUnavailable("no ollama")
    monkeypatch.setattr(llm, "chat", boom)
    with pytest.raises(llm.LLMUnavailable):
        continuation.continue_conversation(s, "claude:c-001", "hi")


def test_artifact_marker_filtered(tmp_path):
    s = Store(Config(home=tmp_path))
    export = ('[{"uuid":"x","name":"T","chat_messages":['
              '{"sender":"assistant","content":[{"type":"text","text":"This block is not supported on your current device yet."}]},'
              '{"sender":"assistant","text":"Real content here."}]}]')
    ingest.import_into_store(s, export, "claude")
    contents = [r[0] for r in s.conn.execute("SELECT content FROM messages").fetchall()]
    assert "Real content here." in contents
    assert not any("not supported on your current device" in c for c in contents)

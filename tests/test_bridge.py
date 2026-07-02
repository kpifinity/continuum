from pathlib import Path

from ski_memory import bridge, ingest, llm
from ski_memory.config import Config
from ski_memory.store import Store

EX = Path(__file__).parent.parent / "examples"


def test_parse_pasted_with_role_markers():
    text = "You: How do I sign the ledger?\nClaude: Use Ed25519.\nYou: Thanks"
    fmt, convs = bridge.parse_pasted(text, "Signing")
    assert fmt == "paste"
    roles = [m["role"] for m in convs[0]["messages"]]
    assert roles == ["user", "assistant", "user"]
    assert convs[0]["title"] == "Signing"


def test_parse_pasted_plain_blob_single_block():
    fmt, convs = bridge.parse_pasted("just some notes with no speakers", None)
    msgs = convs[0]["messages"]
    assert len(msgs) == 1 and msgs[0]["role"] == "user"


def test_parse_pasted_json_export_routes_to_importer():
    fmt, convs = bridge.parse_pasted((EX / "claude_export.json").read_text())
    assert fmt == "claude" and convs[0]["source"] == "claude"


def test_ingest_pasted_creates_conversation(tmp_path):
    s = Store(Config(home=tmp_path))
    summary, ids = bridge.ingest_pasted(s, "You: hi\nClaude: hello there", "Greeting")
    assert summary["conversations_added"] == 1 and ids
    ok, err = s.ledger.verify()
    assert ok, err


def test_make_brief_fallback_without_model(tmp_path):
    s = Store(Config(home=tmp_path))
    _, ids = bridge.ingest_pasted(s,
        "You: Let's design the ledger.\nClaude: We'll hash-chain entries and sign them.", "Ledger")
    res = bridge.make_brief(s, ids[0])  # no Ollama -> deterministic fallback
    assert "Ledger" in res["brief"]
    assert "pick up" in res["brief"].lower()
    assert res["model"] is None
    ok, err = s.ledger.verify()
    assert ok, err


def test_make_brief_uses_model_when_available(tmp_path, monkeypatch):
    s = Store(Config(home=tmp_path))
    _, ids = bridge.ingest_pasted(s, "You: hi\nClaude: hello", "Chat")
    monkeypatch.setattr(llm, "chat", lambda msgs, model=None: ("GOAL: greet.\nNEXT: continue.", "llama3.2"))
    res = bridge.make_brief(s, ids[0])
    assert res["model"] == "llama3.2"
    assert "GOAL: greet" in res["brief"]

from pathlib import Path

from ski_memory import retrieval, ingest, continuation, llm, kg
from ski_memory.config import Config
from ski_memory.store import Store

EX = Path(__file__).parent.parent / "examples"


def store_with_two(tmp_path):
    s = Store(Config(home=tmp_path))
    # conv A: about Ed25519 / SKI (the claude sample)
    ingest.import_into_store(s, (EX / "claude_export.json").read_text(), "claude")
    # conv B: a separate conversation that also mentions Ed25519 signing
    other = ('{"title":"Crypto notes","messages":['
             '{"role":"user","content":"Remind me why we picked Ed25519 for signing the ledger?"},'
             '{"role":"assistant","content":"Ed25519 is fast, small keys, and great for a hash-chained ledger."}]}')
    ingest.import_into_store(s, other, "notes")
    return s


def test_retrieval_pulls_from_other_conversations(tmp_path):
    s = store_with_two(tmp_path)
    cites, text = retrieval.retrieve_context(s, "claude:c-001", "How does Ed25519 signing work for the ledger?")
    assert cites, "expected cross-conversation context"
    assert all(c["conversation_id"] != "claude:c-001" for c in cites)
    assert "Ed25519" in text


def test_retrieval_empty_query(tmp_path):
    s = store_with_two(tmp_path)
    cites, text = retrieval.retrieve_context(s, "claude:c-001", "the and of")
    assert cites == [] and text == ""


def test_continuation_uses_and_reports_context(tmp_path, monkeypatch):
    s = store_with_two(tmp_path)
    captured = {}
    def fake(msgs, model=None):
        captured["msgs"] = msgs
        return ("answer", "llama3.2")
    monkeypatch.setattr(llm, "chat", fake)
    res = continuation.continue_conversation(s, "claude:c-001", "Why Ed25519 for the ledger?")
    # context surfaced to caller
    assert res["context"], "continuation should return citations"
    # context injected as a system message
    sys_msgs = [m for m in captured["msgs"] if m["role"] == "system"]
    assert any("other saved conversations" in m["content"] for m in sys_msgs)
    ok, err = s.ledger.verify()
    assert ok, err


def test_entity_cleanup_drops_sentence_initial_noise(tmp_path):
    s = Store(Config(home=tmp_path))
    export = ('{"title":"Noise test","messages":['
              '{"role":"assistant","content":"See the plan. Here is the idea. Help yourself. '
              'We used Ed25519 and SpaceX. Ed25519 again."}]}')
    ingest.import_into_store(s, export, "n")
    kg.build_all(s)
    labels = {r[0] for r in s.conn.execute(
        "SELECT label FROM kg_nodes WHERE type='entity'").fetchall()}
    assert "Ed25519" in labels        # repeated / has digit -> kept
    assert "SpaceX" in labels         # internal caps -> kept
    assert "See" not in labels and "Here" not in labels and "Help" not in labels

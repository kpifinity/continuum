import json
from pathlib import Path

from ski_memory import ingest, kg
from ski_memory.config import Config
from ski_memory.store import Store

EX = Path(__file__).parent.parent / "examples"


def fresh_store(tmp_path):
    return Store(Config(home=tmp_path))


def test_import_all_three_formats(tmp_path):
    s = fresh_store(tmp_path)
    for f in ["claude_export.json", "chatgpt_export.json", "grok_export.json"]:
        summary = ingest.import_into_store(s, (EX / f).read_text(), f)
        assert summary["conversations_added"] == 1
        assert summary["messages_added"] >= 2
    c = s.counts()
    assert c["conversations"] == 3
    assert c["messages"] == 6
    ok, err = s.ledger.verify()
    assert ok, err


def test_format_detection(tmp_path):
    assert ingest.parse((EX / "claude_export.json").read_text())[0] == "claude"
    assert ingest.parse((EX / "chatgpt_export.json").read_text())[0] == "chatgpt"
    assert ingest.parse((EX / "grok_export.json").read_text())[0] == "generic"


def test_kg_and_search(tmp_path):
    s = fresh_store(tmp_path)
    ingest.import_into_store(s, (EX / "claude_export.json").read_text(), "claude")
    summary = kg.build_all(s)
    assert summary["nodes_added"] > 0
    # link + code block extracted
    types = {r[0] for r in s.conn.execute("SELECT type FROM kg_nodes").fetchall()}
    assert "conversation" in types and "link" in types and "code_block" in types
    # search finds content
    res = kg.search(s, "Ed25519")
    assert any("Ed25519" in r["snippet"] for r in res)
    # graph retrieval
    g = kg.graph_for_conversation(s, "claude:c-001")
    assert len(g["nodes"]) >= 2 and len(g["edges"]) >= 1
    ok, err = s.ledger.verify()
    assert ok, err


def test_reimport_is_idempotent(tmp_path):
    s = fresh_store(tmp_path)
    txt = (EX / "chatgpt_export.json").read_text()
    ingest.import_into_store(s, txt, "c")
    second = ingest.import_into_store(s, txt, "c")
    assert second["conversations_added"] == 0
    assert second["conversations_skipped"] == 1

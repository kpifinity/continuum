from fastapi.testclient import TestClient

from ski_memory import bridge, overlaps
from ski_memory.app import create_app
from ski_memory.config import Config
from ski_memory.store import Store


def test_finds_repeated_question_across_conversations(tmp_path):
    s = Store(Config(home=tmp_path))
    bridge.ingest_pasted(s, "You: Should I rent or sell my Calgary property?\nClaude: Rent it.", "A")
    bridge.ingest_pasted(s, "You: Should I rent or sell my Calgary property?\nChatGPT: Sell it.", "B")
    bridge.ingest_pasted(s, "You: What's the capital of France?\nGrok: Paris.", "C")
    ov = overlaps.find_overlaps(s)
    assert len(ov) == 1
    o = ov[0]
    assert len(o["members"]) == 2
    answers = {m["answer"] for m in o["members"]}
    assert "Rent it." in answers and "Sell it." in answers


def test_no_overlap_for_distinct_questions(tmp_path):
    s = Store(Config(home=tmp_path))
    bridge.ingest_pasted(s, "You: Tell me about black holes.\nClaude: ...", "A")
    bridge.ingest_pasted(s, "You: Best pasta recipe?\nChatGPT: ...", "B")
    assert overlaps.find_overlaps(s) == []


def test_overlaps_endpoint(tmp_path):
    c = TestClient(create_app(Config(home=tmp_path)))
    d = c.get("/api/overlaps").json()
    assert "overlaps" in d and isinstance(d["overlaps"], list)

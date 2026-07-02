import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ski_memory import ask, ingest, llm
from ski_memory.app import create_app
from ski_memory.config import Config
from ski_memory.store import Store

EX = Path(__file__).parent.parent / "examples"


def seeded(tmp_path):
    s = Store(Config(home=tmp_path))
    ingest.import_into_store(s, (EX / "claude_export.json").read_text(), "claude")
    ingest.import_into_store(s, (EX / "chatgpt_export.json").read_text(), "chatgpt")
    return s


def test_ask_answers_from_archive(tmp_path, monkeypatch):
    s = seeded(tmp_path)
    seen = {}
    def fake(msgs, model=None):
        seen["msgs"] = msgs
        return ("It uses Ed25519 signing.", "llama3.2")
    monkeypatch.setattr(llm, "chat", fake)
    res = ask.ask(s, "Tell me about Ed25519 signing and the ledger")
    assert res["answer"] and res["model"] == "llama3.2"
    assert res["context"], "should cite sources"
    # the model was handed retrieved context
    assert any("Context from your past conversations" in m["content"] for m in seen["msgs"])
    ok, err = s.ledger.verify()
    assert ok, err


def test_ask_no_match_does_not_call_model(tmp_path, monkeypatch):
    s = seeded(tmp_path)
    def boom(*a, **k):
        raise AssertionError("model should not be called when nothing is found")
    monkeypatch.setattr(llm, "chat", boom)
    res = ask.ask(s, "zzzqqq nonexistent topic wxyv")
    assert res["context"] == [] and "couldn't find" in res["answer"].lower()


def test_ask_endpoint_empty_question(tmp_path):
    c = TestClient(create_app(Config(home=tmp_path)))
    assert c.post("/api/ask", json={"question": "   "}).status_code == 400


def test_quit_endpoint_schedules_exit(tmp_path, monkeypatch):
    import time
    calls = []
    monkeypatch.setattr(os, "_exit", lambda code: calls.append(code))
    c = TestClient(create_app(Config(home=tmp_path)))
    r = c.post("/api/quit")
    assert r.status_code == 200 and r.json()["quitting"] is True
    time.sleep(0.5)
    assert calls == [0]

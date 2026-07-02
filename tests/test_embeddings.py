from pathlib import Path

from ski_memory import embeddings, retrieval, ingest
from ski_memory.config import Config
from ski_memory.store import Store

EX = Path(__file__).parent.parent / "examples"

# A deterministic fake embedding: vector of keyword counts (stands in for a real model).
KEYS = ["ledger", "vacation", "banff", "resume", "ed25519", "signing"]


def fake_embed(text, model="nomic-embed-text", timeout=60.0):
    t = text.lower()
    v = [float(t.count(k)) for k in KEYS]
    return v if any(v) else [0.0] * len(KEYS)


def store_multi(tmp_path):
    s = Store(Config(home=tmp_path))
    ingest.import_into_store(s, (EX / "claude_export.json").read_text(), "claude")  # ed25519/signing
    ingest.import_into_store(s, (EX / "chatgpt_export.json").read_text(), "chatgpt")  # banff/vacation
    ingest.import_into_store(s,
        '{"title":"Crypto","messages":[{"role":"assistant","content":"We sign the ledger with key material."}]}', "n")
    return s


def test_build_index_populates_vectors(tmp_path, monkeypatch):
    s = store_multi(tmp_path)
    monkeypatch.setattr(embeddings, "embed_text", fake_embed)
    assert not embeddings.has_index(s)
    embeddings._run_build(s, "nomic-embed-text")          # synchronous build
    indexed, total = embeddings.index_counts(s)
    assert indexed == total and indexed > 0
    assert embeddings.has_index(s)


def test_semantic_context_ranks_by_meaning(tmp_path, monkeypatch):
    s = store_multi(tmp_path)
    monkeypatch.setattr(embeddings, "embed_text", fake_embed)
    embeddings._run_build(s, "nomic-embed-text")
    # Query about the ledger from the ChatGPT (banff) conversation should surface
    # the crypto/ledger conversation, not the vacation one.
    cites, text = embeddings.semantic_context(s, "chatgpt:g-77", "how is the ledger signed?")
    assert cites
    assert "ledger" in text.lower()
    assert all(c["method"] == "semantic" for c in cites)


def test_retrieval_uses_semantic_when_available(tmp_path, monkeypatch):
    s = store_multi(tmp_path)
    monkeypatch.setattr(embeddings, "embed_text", fake_embed)
    monkeypatch.setattr(embeddings, "model_available", lambda model="nomic-embed-text": True)
    embeddings._run_build(s, "nomic-embed-text")
    cites, text = retrieval.retrieve_context(s, "chatgpt:g-77", "ledger signing")
    assert cites and any(c.get("method") == "semantic" for c in cites)


def test_retrieval_falls_back_to_lexical_without_index(tmp_path):
    s = store_multi(tmp_path)
    # No embeddings built -> lexical path; should still find Ed25519 cross-conversation.
    cites, text = retrieval.retrieve_context(s, "chatgpt:g-77", "Ed25519 signing ledger")
    assert cites  # lexical fallback worked
    assert all(c.get("method") != "semantic" for c in cites)

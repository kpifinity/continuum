"""Semantic retrieval via local embeddings (Ollama, localhost only).

Embeds each message with a local embedding model (default nomic-embed-text),
stores the vectors in SQLite, and ranks continuation context by cosine
similarity — so retrieval catches paraphrases, not just shared words. Fully
local; no internet. If no index exists or the embedding model isn't installed,
the caller falls back to lexical retrieval (see retrieval.py).
"""
from __future__ import annotations

import array
import json
import math
import threading
import urllib.error
import urllib.request

from . import retrieval
from .ollama import detect

EMBED_URL = "http://127.0.0.1:11434/api/embeddings"
DEFAULT_MODEL = "nomic-embed-text"


class EmbeddingsUnavailable(Exception):
    pass


_state = {"building": False, "error": None, "model": None, "done": 0, "todo": 0}
_lock = threading.Lock()


# --- model + embedding calls ---------------------------------------------
def model_available(model: str = DEFAULT_MODEL) -> bool:
    return model in (detect().get("models") or [])


def embed_text(text: str, model: str = DEFAULT_MODEL, timeout: float = 60.0) -> list[float]:
    payload = json.dumps({"model": model, "prompt": text}).encode()
    req = urllib.request.Request(
        EMBED_URL, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, TimeoutError, ValueError) as e:
        raise EmbeddingsUnavailable(str(e))
    vec = d.get("embedding")
    if not vec:
        raise EmbeddingsUnavailable("no embedding returned")
    return [float(x) for x in vec]


# --- vector (de)serialization --------------------------------------------
def _pack(vec) -> bytes:
    return array.array("f", vec).tobytes()


def _unpack(b: bytes):
    a = array.array("f")
    a.frombytes(b)
    return a


def _cosine(q, qnorm: float, vec) -> float:
    if len(vec) != len(q):
        return 0.0
    dot = 0.0
    vn = 0.0
    for i in range(len(vec)):
        dot += q[i] * vec[i]
        vn += vec[i] * vec[i]
    if vn == 0 or qnorm == 0:
        return 0.0
    return dot / (qnorm * math.sqrt(vn))


# --- index ----------------------------------------------------------------
def index_counts(store) -> tuple[int, int]:
    total = store.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    indexed = store.conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    return indexed, total


def has_index(store) -> bool:
    return store.conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0] > 0


def status(store, model: str = DEFAULT_MODEL) -> dict:
    indexed, total = index_counts(store)
    with _lock:
        st = dict(_state)
    return {"model": model, "model_available": model_available(model),
            "indexed": indexed, "total": total,
            "building": st["building"], "error": st["error"],
            "done": st["done"], "todo": st["todo"]}


def build_index(store, model: str = DEFAULT_MODEL) -> None:
    with _lock:
        if _state["building"]:
            return
        _state.update({"building": True, "error": None, "model": model})
    threading.Thread(target=_run_build, args=(store, model), daemon=True).start()


def _run_build(store, model: str = DEFAULT_MODEL) -> None:
    try:
        rows = store.conn.execute(
            "SELECT m.id, m.content FROM messages m "
            "LEFT JOIN embeddings e ON e.message_id = m.id "
            "WHERE e.message_id IS NULL").fetchall()
        with _lock:
            _state.update({"todo": len(rows), "done": 0})
        for mid, content in rows:
            vec = embed_text(content[:4000], model)
            store.conn.execute(
                "INSERT OR REPLACE INTO embeddings(message_id, model, dim, vec) "
                "VALUES(?,?,?,?)", (mid, model, len(vec), _pack(vec)))
            store.conn.commit()
            with _lock:
                _state["done"] += 1
        with _lock:
            _state["building"] = False
    except Exception as e:  # noqa: BLE001
        with _lock:
            _state.update({"building": False, "error": str(e)})


# --- semantic retrieval ---------------------------------------------------
def semantic_context(store, conversation_id: str, query: str, k: int = 5,
                     max_chars: int = 3500, per_conversation: int = 2,
                     model: str = DEFAULT_MODEL) -> tuple[list[dict], str]:
    q = embed_text(query, model)
    qnorm = math.sqrt(sum(x * x for x in q)) or 1.0
    rows = store.conn.execute(
        "SELECT e.vec, m.conversation_id, c.title, m.role, m.content "
        "FROM embeddings e JOIN messages m ON m.id = e.message_id "
        "JOIN conversations c ON c.id = m.conversation_id "
        "WHERE m.conversation_id != ?", (conversation_id,)).fetchall()

    scored = []
    for vecb, conv_id, title, role, content in rows:
        sim = _cosine(q, qnorm, _unpack(vecb))
        if sim > 0:
            scored.append((sim, conv_id, title, role, content))
    scored.sort(key=lambda r: r[0], reverse=True)

    qterms = retrieval.terms(query)
    citations: list[dict] = []
    per_conv: dict[str, int] = {}
    total = 0
    for sim, conv_id, title, role, content in scored:
        if per_conv.get(conv_id, 0) >= per_conversation:
            continue
        snip = retrieval._snippet(content, qterms)
        if total + len(snip) > max_chars:
            break
        per_conv[conv_id] = per_conv.get(conv_id, 0) + 1
        total += len(snip)
        citations.append({"conversation_id": conv_id, "title": title, "role": role,
                          "snippet": snip, "score": round(sim, 3), "method": "semantic"})
        if len(citations) >= k:
            break

    if not citations:
        return [], ""
    text = "\n".join(f"- ({c['title']}) {c['snippet']}" for c in citations)
    return citations, text

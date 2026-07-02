"""My Memory — a curated, user-owned knowledge base.

Distinct from raw imported chats: these are notes the user deliberately keeps
(often a consolidation of several models' answers). Each entry is Ed25519-signed
and recorded in the ledger, so the user's curated knowledge is verifiable. The
Ask flow weights Memory above raw conversations.

Also hosts `consolidate`: synthesize several models' answers to one question
into consensus / conflicts / a single best answer, using the local model.
"""
from __future__ import annotations

import hashlib
import json
import time

from . import llm, retrieval
from .ledger import canonical_bytes


def _entry_dict(title, body, tags, provenance, created_at):
    return {"title": title, "body": body, "tags": tags or [],
            "provenance": provenance or {}, "created_at": created_at}


def add_entry(store, title: str, body: str, tags=None, provenance=None) -> dict:
    now = time.time()
    eid = "mem:" + hashlib.sha256(
        canonical_bytes([title, body, now])).hexdigest()[:16]
    payload = {"id": eid, **_entry_dict(title, body, tags, provenance, now)}
    signature = store.identity.sign(canonical_bytes(payload)).hex()
    store.conn.execute(
        "INSERT INTO memory_entries(id, title, body, tags, provenance, signature, created_at)"
        " VALUES(?,?,?,?,?,?,?)",
        (eid, title, body, json.dumps(tags or []), json.dumps(provenance or {}),
         signature, now))
    store.conn.commit()
    store.ledger.append("memory.add", {
        "id": eid, "title": title, "chars": len(body),
        "sources": (provenance or {}).get("sources", []),
    })
    return {"id": eid, "title": title, "created_at": now}


def list_entries(store) -> list[dict]:
    rows = store.conn.execute(
        "SELECT id, title, body, tags, provenance, created_at "
        "FROM memory_entries ORDER BY created_at DESC").fetchall()
    return [{"id": r[0], "title": r[1], "body": r[2],
             "tags": json.loads(r[3] or "[]"), "provenance": json.loads(r[4] or "{}"),
             "created_at": r[5]} for r in rows]


def search(store, query: str, limit: int = 6) -> list[dict]:
    terms = sorted(retrieval.terms(query), key=len, reverse=True)[:8]
    if not terms:
        return []
    where = " OR ".join("(title LIKE ? OR body LIKE ?)" for _ in terms)
    params: list = []
    for t in terms:
        params += [f"%{t}%", f"%{t}%"]
    rows = store.conn.execute(
        f"SELECT id, title, body FROM memory_entries WHERE {where} "
        "ORDER BY created_at DESC LIMIT ?", (*params, limit)).fetchall()
    out = []
    for eid, title, body in rows:
        low = body.lower()
        idx = -1
        for t in terms:
            i = low.find(t)
            if i >= 0 and (idx < 0 or i < idx):
                idx = i
        start = max(0, idx - 50) if idx >= 0 else 0
        snippet = ("…" if start > 0 else "") + body[start:start + 200].replace("\n", " ") + "…"
        out.append({"id": eid, "title": title, "snippet": snippet})
    return out


CONSOLIDATE_SYSTEM = (
    "You are consolidating answers that several different AI assistants gave to "
    "the SAME question. Respond in three short sections:\n"
    "1. Consensus — what they agree on.\n"
    "2. Conflicts — where they differ, and how.\n"
    "3. Consolidated answer — the single best answer.\n"
    "Attribute specific claims to the assistant that made them (e.g. Claude, "
    "ChatGPT, Grok). Use only what's in the answers; do not invent anything."
)


def consolidate(store, question: str, answers: list[dict], model: str | None = None) -> dict:
    parts = [f"Question: {question}", ""]
    for a in answers:
        name = (a.get("model") or "Assistant").strip()
        parts.append(f"--- {name} answered ---\n{(a.get('text') or '').strip()}\n")
    reply, used_model = llm.chat(
        [{"role": "system", "content": CONSOLIDATE_SYSTEM},
         {"role": "user", "content": "\n".join(parts)}], model)  # may raise LLMUnavailable
    sources = [(a.get("model") or "Assistant") for a in answers]
    store.ledger.append("consolidate", {"models": sources, "reply_chars": len(reply)})
    return {"consolidation": reply, "model": used_model, "sources": sources,
            "question": question}

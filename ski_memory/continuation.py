"""Continue an imported conversation with a local model.

Assembles recent conversation history (a simple, bounded context for the POC;
GraphRAG-style KG retrieval comes later), calls the local model, then writes
both the user prompt and the model reply back into the store as new messages
with provenance, and records the event in the hash-chained ledger.
"""
from __future__ import annotations

import json
import time

from . import llm, retrieval

SYSTEM_PROMPT = (
    "You are continuing an existing conversation that the user previously had "
    "with another AI assistant. Use the prior messages as context and continue "
    "naturally and helpfully. Be concise unless asked otherwise."
)

VALID_ROLES = {"user", "assistant", "system"}


class ConversationNotFound(Exception):
    pass


def _build_messages(store, conversation_id, user_text, history_limit, char_budget):
    conn = store.conn
    conv = conn.execute(
        "SELECT id FROM conversations WHERE id=?", (conversation_id,)).fetchone()
    if not conv:
        raise ConversationNotFound(conversation_id)
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE conversation_id=? ORDER BY seq",
        (conversation_id,)).fetchall()
    history = [{"role": role if role in VALID_ROLES else "user", "content": content}
               for role, content in rows]
    history = history[-history_limit:]
    while history and sum(len(m["content"]) for m in history) > char_budget:
        history.pop(0)
    citations, context_text = retrieval.retrieve_context(store, conversation_id, user_text)
    system_msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    if context_text:
        system_msgs.append({"role": "system", "content":
            "Relevant context retrieved from the user's other saved conversations. "
            "Use it only if pertinent:\n" + context_text})
    chat_messages = system_msgs + history + [{"role": "user", "content": user_text}]
    return chat_messages, history, citations


def _persist_turn(store, conversation_id, user_text, reply, used_model, history, citations):
    conn = store.conn
    now = time.time()
    seq = _next_seq(conn, conversation_id)
    conn.execute(
        "INSERT INTO messages(id, conversation_id, seq, role, model, content, created_at, meta)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (f"{conversation_id}:{seq}", conversation_id, seq, "user", None, user_text, now,
         '{"origin":"local_continuation"}'))
    conn.execute(
        "INSERT INTO messages(id, conversation_id, seq, role, model, content, created_at, meta)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (f"{conversation_id}:{seq + 1}", conversation_id, seq + 1, "assistant", used_model,
         reply, now, '{"origin":"local_continuation"}'))
    conn.commit()
    store.ledger.append("continuation", {
        "conversation_id": conversation_id, "model": used_model,
        "prompt_chars": len(user_text), "reply_chars": len(reply),
        "history_messages": len(history),
        "context_sources": sorted({c["conversation_id"] for c in citations}),
        "context_count": len(citations),
    })
    return seq


def stream_continue(store, conversation_id: str, user_text: str, model: str | None = None,
                    history_limit: int = 16, char_budget: int = 12000):
    """Validate + resolve model eagerly (so errors surface before streaming),
    then return an NDJSON line generator: meta -> delta* -> done.
    Persists the turn + ledger entry once the stream completes."""
    chat_messages, history, citations = _build_messages(
        store, conversation_id, user_text, history_limit, char_budget)
    used_model = llm.resolve_model(model)

    def gen():
        yield json.dumps({"type": "meta", "model": used_model}) + "\n"
        parts = []
        try:
            for chunk in llm.chat_stream(chat_messages, used_model):
                parts.append(chunk)
                yield json.dumps({"type": "delta", "text": chunk}) + "\n"
        except llm.LLMUnavailable as e:
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"
            return
        reply = "".join(parts).strip()
        if not reply:
            yield json.dumps({"type": "error", "message": "The local model returned an empty reply."}) + "\n"
            return
        seq = _persist_turn(store, conversation_id, user_text, reply, used_model, history, citations)
        yield json.dumps({"type": "done", "model": used_model, "context": citations,
                          "seq_user": seq, "seq_asst": seq + 1}) + "\n"
    return gen()


def _next_seq(conn, conversation_id: str) -> int:
    row = conn.execute(
        "SELECT MAX(seq) FROM messages WHERE conversation_id=?",
        (conversation_id,)).fetchone()
    return (row[0] + 1) if row and row[0] is not None else 0


def continue_conversation(store, conversation_id: str, user_text: str,
                          model: str | None = None, history_limit: int = 16,
                          char_budget: int = 12000) -> dict:
    conn = store.conn
    conv = conn.execute(
        "SELECT id FROM conversations WHERE id=?", (conversation_id,)).fetchone()
    if not conv:
        raise ConversationNotFound(conversation_id)

    rows = conn.execute(
        "SELECT role, content FROM messages WHERE conversation_id=? ORDER BY seq",
        (conversation_id,)).fetchall()
    history = []
    for role, content in rows:
        history.append({"role": role if role in VALID_ROLES else "user",
                        "content": content})
    history = history[-history_limit:]

    # Trim oldest until under the char budget.
    while history and sum(len(m["content"]) for m in history) > char_budget:
        history.pop(0)

    citations, context_text = retrieval.retrieve_context(store, conversation_id, user_text)
    system_msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    if context_text:
        system_msgs.append({"role": "system", "content":
            "Relevant context retrieved from the user's other saved conversations. "
            "Use it only if pertinent:\n" + context_text})
    chat_messages = system_msgs + history + [{"role": "user", "content": user_text}]

    reply, used_model = llm.chat(chat_messages, model)  # may raise LLMUnavailable

    now = time.time()
    seq = _next_seq(conn, conversation_id)
    user_id = f"{conversation_id}:{seq}"
    asst_id = f"{conversation_id}:{seq + 1}"
    conn.execute(
        "INSERT INTO messages(id, conversation_id, seq, role, model, content, created_at, meta)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (user_id, conversation_id, seq, "user", None, user_text, now,
         '{"origin":"local_continuation"}'))
    conn.execute(
        "INSERT INTO messages(id, conversation_id, seq, role, model, content, created_at, meta)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (asst_id, conversation_id, seq + 1, "assistant", used_model, reply, now,
         '{"origin":"local_continuation"}'))
    conn.commit()

    store.ledger.append("continuation", {
        "conversation_id": conversation_id, "model": used_model,
        "prompt_chars": len(user_text), "reply_chars": len(reply),
        "history_messages": len(history),
        "context_sources": sorted({c["conversation_id"] for c in citations}),
        "context_count": len(citations),
    })

    return {
        "model": used_model,
        "context": citations,
        "messages": [
            {"seq": seq, "role": "user", "model": None, "content": user_text},
            {"seq": seq + 1, "role": "assistant", "model": used_model, "content": reply},
        ],
    }

"""Ask-your-memory: answer a question from across ALL saved conversations.

Retrieves the most relevant passages from the entire archive (semantic when an
embedding index exists, otherwise lexical — see retrieval.py), then asks the
local model to answer using only that context and cite the conversations it
drew from. Fully local; nothing leaves the machine.
"""
from __future__ import annotations

import json

from . import llm, memory as memory_mod, retrieval

SYSTEM_PROMPT = (
    "You are SKI Memory's assistant. Answer the user's question using ONLY the "
    "context below, which is drawn from their own past AI conversations. If the "
    "context does not contain the answer, say you couldn't find it in their saved "
    "conversations rather than guessing. Be concise, and mention which "
    "conversation titles you relied on."
)


def ask(store, question: str, model: str | None = None,
        k: int = 8, max_chars: int = 6000) -> dict:
    # conversation_id="" matches no real conversation, so retrieval spans the whole archive.
    citations, context = retrieval.retrieve_context(
        store, "", question, k=k, max_chars=max_chars, per_conversation=2)

    # Saved Memory is the user's verified knowledge — weight it above raw chats.
    mem_hits = memory_mod.search(store, question, limit=4)
    if mem_hits:
        mem_text = "\n".join(f"- (saved memory: {m['title']}) {m['snippet']}" for m in mem_hits)
        context = ("Your saved Memory (verified knowledge):\n" + mem_text
                   + ("\n\n" + context if context else ""))
        mem_cites = [{"conversation_id": "", "title": m["title"], "role": "memory",
                      "snippet": m["snippet"], "method": "memory"} for m in mem_hits]
        citations = mem_cites + citations

    if not citations:
        return {"answer": "I couldn't find anything about that in your saved conversations or memory.",
                "model": None, "context": []}

    prompt = (f"Context from your past conversations:\n{context}\n\n"
              f"Question: {question}")
    reply, used_model = llm.chat(
        [{"role": "system", "content": SYSTEM_PROMPT},
         {"role": "user", "content": prompt}], model)  # may raise LLMUnavailable

    store.ledger.append("ask", {
        "question_chars": len(question), "model": used_model,
        "sources": sorted({c["conversation_id"] for c in citations}),
        "context_count": len(citations),
    })
    return {"answer": reply, "model": used_model, "context": citations}


def stream_ask(store, question: str, model: str | None = None,
               k: int = 8, max_chars: int = 6000):
    """NDJSON line generator for Ask: meta -> delta* -> done (with citations)."""
    citations, context = retrieval.retrieve_context(
        store, "", question, k=k, max_chars=max_chars, per_conversation=2)
    mem_hits = memory_mod.search(store, question, limit=4)
    if mem_hits:
        mem_text = "\n".join(f"- (saved memory: {m['title']}) {m['snippet']}" for m in mem_hits)
        context = ("Your saved Memory (verified knowledge):\n" + mem_text
                   + ("\n\n" + context if context else ""))
        mem_cites = [{"conversation_id": "", "title": m["title"], "role": "memory",
                      "snippet": m["snippet"], "method": "memory"} for m in mem_hits]
        citations = mem_cites + citations

    if not citations:
        def empty():
            msg = "I couldn't find anything about that in your saved conversations or memory."
            yield json.dumps({"type": "meta", "model": None}) + "\n"
            yield json.dumps({"type": "delta", "text": msg}) + "\n"
            yield json.dumps({"type": "done", "model": None, "context": []}) + "\n"
        return empty()

    prompt = (f"Context from your past conversations:\n{context}\n\n"
              f"Question: {question}")
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt}]
    used_model = llm.resolve_model(model)

    def gen():
        yield json.dumps({"type": "meta", "model": used_model}) + "\n"
        parts = []
        try:
            for chunk in llm.chat_stream(messages, used_model):
                parts.append(chunk)
                yield json.dumps({"type": "delta", "text": chunk}) + "\n"
        except llm.LLMUnavailable as e:
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"
            return
        reply = "".join(parts).strip()
        store.ledger.append("ask", {
            "question_chars": len(question), "model": used_model,
            "sources": sorted({c["conversation_id"] for c in citations}),
            "context_count": len(citations),
        })
        yield json.dumps({"type": "done", "model": used_model, "context": citations}) + "\n"
    return gen()

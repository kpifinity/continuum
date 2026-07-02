"""GraphRAG-style context retrieval (lexical + KG, no embeddings).

When continuing a thread, this pulls the most relevant passages from across
ALL of the user's conversations — not just the current one — so the local
model answers with the user's broader memory in view. Retrieval is lexical
(term overlap) and KG-aware (the current thread's entity nodes broaden the
query). Fully local; no embedding model required.

A future upgrade is vector embeddings for semantic recall; the interface
(retrieve_context) would stay the same.
"""
from __future__ import annotations

import re
from collections import Counter

_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-]{2,}")

_STOP = {
    "the", "and", "for", "that", "this", "with", "you", "your", "are", "was",
    "but", "not", "have", "has", "had", "will", "would", "can", "could", "should",
    "what", "when", "where", "which", "who", "how", "why", "from", "into", "about",
    "they", "them", "then", "than", "there", "here", "more", "some", "any", "all",
    "out", "get", "got", "use", "using", "like", "just", "also", "been", "being",
    "over", "under", "each", "very", "much", "such", "only", "make", "made", "want",
    "one", "two", "now", "see", "help", "let", "yes", "able", "may", "might",
}


def terms(text: str) -> set[str]:
    return {w.lower() for w in _WORD_RE.findall(text or "")
            if w.lower() not in _STOP and len(w) >= 3}


def _entity_terms(store, conversation_id: str) -> set[str]:
    rows = store.conn.execute(
        "SELECT n.label FROM kg_edges e JOIN kg_nodes n ON n.id = e.dst "
        "WHERE e.src=? AND n.type='entity'", (conversation_id,)).fetchall()
    out: set[str] = set()
    for (label,) in rows:
        out |= terms(label)
    return out


def _snippet(content: str, qterms: set[str], width: int = 220) -> str:
    low = content.lower()
    pos = -1
    for t in qterms:
        i = low.find(t)
        if i >= 0 and (pos < 0 or i < pos):
            pos = i
    if pos < 0:
        pos = 0
    start = max(0, pos - 40)
    snip = content[start:start + width].replace("\n", " ").strip()
    return ("…" if start > 0 else "") + snip + ("…" if start + width < len(content) else "")


def retrieve_context(store, conversation_id: str, query: str,
                     k: int = 5, max_chars: int = 3500,
                     per_conversation: int = 2) -> tuple[list[dict], str]:
    """Return (citations, context_text) drawn from OTHER conversations.

    Uses semantic (embedding) retrieval when an index exists and the embedding
    model is available; otherwise falls back to lexical term overlap.
    """
    # Prefer semantic retrieval when available.
    try:
        from . import embeddings
        if embeddings.has_index(store) and embeddings.model_available():
            cites, text = embeddings.semantic_context(
                store, conversation_id, query, k, max_chars, per_conversation)
            if cites:
                return cites, text
    except Exception:
        pass  # fall back to lexical

    conn = store.conn
    qterms = terms(query) | _entity_terms(store, conversation_id)
    if not qterms:
        return [], ""

    # Prefilter candidates with a bounded LIKE-OR over the strongest terms.
    probe = sorted(qterms, key=len, reverse=True)[:8]
    where = " OR ".join("m.content LIKE ?" for _ in probe)
    params = [f"%{t}%" for t in probe]
    rows = conn.execute(
        "SELECT m.id, m.conversation_id, c.title, m.role, m.content "
        "FROM messages m JOIN conversations c ON c.id = m.conversation_id "
        f"WHERE m.conversation_id != ? AND ({where}) LIMIT 400",
        [conversation_id, *params]).fetchall()

    scored = []
    for mid, conv_id, title, role, content in rows:
        overlap = len(qterms & terms(content))
        if overlap:
            scored.append((overlap, conv_id, title, role, content))
    scored.sort(key=lambda r: r[0], reverse=True)

    citations: list[dict] = []
    per_conv: Counter = Counter()
    total = 0
    for overlap, conv_id, title, role, content in scored:
        if per_conv[conv_id] >= per_conversation:
            continue
        snip = _snippet(content, qterms)
        if total + len(snip) > max_chars:
            break
        per_conv[conv_id] += 1
        total += len(snip)
        citations.append({"conversation_id": conv_id, "title": title,
                          "role": role, "snippet": snip, "score": overlap})
        if len(citations) >= k:
            break

    if not citations:
        return [], ""

    lines = [f"- ({c['title']}) {c['snippet']}" for c in citations]
    context_text = "\n".join(lines)
    return citations, context_text

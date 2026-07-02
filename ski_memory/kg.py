"""Quick structural knowledge-graph builder (no LLM required).

Extracts a first-pass graph from imported messages: one node per conversation,
plus globally-deduplicated nodes for links, code blocks, and salient entities
(capitalized multi-word terms). Edges connect a conversation to what it
mentions. Every node/edge carries a provenance envelope. LLM-assisted semantic
extraction (decisions, facts, action items) is a later milestone.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter

URL_RE = re.compile(r"https?://[^\s<>()\"']+")
CODE_RE = re.compile(r"```(\w+)?\n?(.*?)```", re.DOTALL)
ENTITY_RE = re.compile(r"\b([A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+){0,3})\b")

STOPWORDS = {"The", "This", "That", "These", "Those", "I", "A", "An", "It",
             "We", "You", "He", "She", "They", "If", "But", "And", "Or",
             "So", "In", "On", "At", "To", "For", "Of", "As", "Is", "Are",
             "See", "Help", "Here", "Now", "Below", "Above", "Let", "Two",
             "One", "Three", "With", "Your", "Also", "Then", "When", "While",
             "Yes", "No", "Sure", "Okay", "Great", "Thanks", "Please", "Why",
             "What", "How", "Where", "Who", "Based", "Given", "Note", "First",
             "Next", "Finally", "Overall", "However", "Because", "Since"}


def _nid(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def _provenance(conversation_id: str, method: str = "structural") -> str:
    return json.dumps({
        "conversation_id": conversation_id, "model": None,
        "method": method, "confidence": 1.0, "ts": time.time(),
    })


def build_for_conversation(store, conversation_id: str) -> dict:
    conn = store.conn
    conv = conn.execute(
        "SELECT id, title FROM conversations WHERE id=?", (conversation_id,)).fetchone()
    if not conv:
        return {"nodes_added": 0, "edges_added": 0}
    msgs = conn.execute(
        "SELECT content FROM messages WHERE conversation_id=? ORDER BY seq",
        (conversation_id,)).fetchall()
    text = "\n\n".join(m[0] for m in msgs)
    now = time.time()

    nodes: dict[str, tuple] = {}   # id -> (type, label, body)
    edges: list[tuple] = []        # (type, dst_id)

    conv_node_id = conversation_id
    nodes[conv_node_id] = ("conversation", conv[1] or "Untitled", None)

    # Links
    for url in set(URL_RE.findall(text)):
        nid = "link:" + _nid(url)
        nodes[nid] = ("link", url, None)
        edges.append(("mentions", nid))

    # Code blocks
    for lang, code in CODE_RE.findall(text):
        snippet = code.strip()[:400]
        if snippet:
            nid = "code:" + _nid(snippet)
            nodes[nid] = ("code_block", (lang or "code") + " block", snippet)
            edges.append(("contains", nid))

    # Entities: keep proper-noun-like terms, drop sentence-initial noise.
    raw = [e for e in ENTITY_RE.findall(text)
           if e not in STOPWORDS and len(e) > 2]
    counts = Counter(raw)

    def _keep(label: str, count: int) -> bool:
        if " " in label:                       # multi-word proper noun
            return True
        if count >= 2:                          # repeated -> meaningful
            return True
        if any(ch.isdigit() for ch in label):   # e.g. Ed25519, GPT4
            return True
        if label[1:] != label[1:].lower():      # internal caps e.g. SpaceX, GraphRAG
            return True
        return False

    selected = [(l, c) for l, c in counts.most_common(40) if _keep(l, c)]
    for label, _count in selected[:15]:
        nid = "entity:" + _slug(label)
        nodes[nid] = ("entity", label, None)
        edges.append(("mentions", nid))

    # Upsert nodes
    nodes_added = 0
    for nid, (ntype, label, body) in nodes.items():
        exists = conn.execute("SELECT 1 FROM kg_nodes WHERE id=?", (nid,)).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO kg_nodes(id, type, label, body, provenance, created_at)"
                " VALUES(?,?,?,?,?,?)",
                (nid, ntype, label, body, _provenance(conversation_id), now))
            nodes_added += 1

    # Insert edges (deduped)
    edges_added = 0
    for etype, dst in edges:
        eid = _nid(conv_node_id, dst, etype)
        exists = conn.execute("SELECT 1 FROM kg_edges WHERE id=?", (eid,)).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO kg_edges(id, src, dst, type, provenance, created_at)"
                " VALUES(?,?,?,?,?,?)",
                (eid, conv_node_id, dst, etype, _provenance(conversation_id), now))
            edges_added += 1

    conn.commit()
    return {"nodes_added": nodes_added, "edges_added": edges_added}


def build_all(store) -> dict:
    conn = store.conn
    ids = [r[0] for r in conn.execute("SELECT id FROM conversations").fetchall()]
    total_n = total_e = 0
    for cid in ids:
        r = build_for_conversation(store, cid)
        total_n += r["nodes_added"]
        total_e += r["edges_added"]
    summary = {"conversations": len(ids), "nodes_added": total_n, "edges_added": total_e}
    store.ledger.append("kg.build", summary)
    return summary


def graph_for_conversation(store, conversation_id: str) -> dict:
    conn = store.conn
    edges = conn.execute(
        "SELECT src, dst, type FROM kg_edges WHERE src=?", (conversation_id,)).fetchall()
    node_ids = {conversation_id} | {e[1] for e in edges}
    nodes = []
    for nid in node_ids:
        row = conn.execute(
            "SELECT id, type, label FROM kg_nodes WHERE id=?", (nid,)).fetchone()
        if row:
            nodes.append({"id": row[0], "type": row[1], "label": row[2]})
    return {
        "nodes": nodes,
        "edges": [{"src": e[0], "dst": e[1], "type": e[2]} for e in edges],
    }


def search(store, query: str, limit: int = 30) -> list[dict]:
    """Simple LIKE search over messages with a snippet around the match."""
    if not query.strip():
        return []
    conn = store.conn
    like = f"%{query}%"
    rows = conn.execute(
        "SELECT m.conversation_id, c.title, c.source, m.role, m.content "
        "FROM messages m JOIN conversations c ON c.id=m.conversation_id "
        "WHERE m.content LIKE ? ORDER BY m.created_at DESC LIMIT ?",
        (like, limit)).fetchall()
    results = []
    q = query.lower()
    for conv_id, title, source, role, content in rows:
        idx = content.lower().find(q)
        start = max(0, idx - 60)
        snippet = ("…" if start > 0 else "") + content[start:idx + len(query) + 80] + "…"
        results.append({
            "conversation_id": conv_id, "title": title, "source": source,
            "role": role, "snippet": snippet.replace("\n", " "),
        })
    return results

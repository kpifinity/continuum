"""The Memory knowledge graph — one global, editable graph across all LLMs.

Built automatically from everything already extracted (entities + the
conversations that mention them, across providers), then overlaid with the
user's edits (rename / pin / hide / merge / add-fact). Every edit is
Ed25519-signed and written to the ledger, and overrides survive re-extraction.
This graph is the user's memory.
"""
from __future__ import annotations

import json
import time
from collections import Counter, defaultdict

from .ledger import canonical_bytes

VALID_OPS = {"rename", "pin", "hide", "merge", "fact"}


def _load_overrides(store):
    rows = store.conn.execute(
        "SELECT target, op, value FROM memory_overrides ORDER BY created_at").fetchall()
    renames, pins, hidden, merges = {}, set(), set(), {}
    facts = defaultdict(list)
    for target, op, raw in rows:
        v = json.loads(raw) if raw else None
        if op == "rename":
            renames[target] = v
        elif op == "pin":
            (pins.add if v else pins.discard)(target)
        elif op == "hide":
            (hidden.add if (v is None or v) else hidden.discard)(target)
        elif op == "merge" and v:
            merges[target] = v
        elif op == "fact" and v:
            facts[target].append(v)

    def canon(x):
        seen = set()
        while x in merges and x not in seen:
            seen.add(x)
            x = merges[x]
        return x

    return renames, pins, hidden, facts, canon


def build_global_graph(store, type_filter: str | None = None,
                       provider: str | None = None, limit: int = 60) -> dict:
    conn = store.conn
    renames, pins, hidden, facts, canon = _load_overrides(store)
    conv_src = {r[0]: r[1] for r in conn.execute("SELECT id, source FROM conversations").fetchall()}

    label, ntype = {}, {}
    for nid, lbl in conn.execute("SELECT id, label FROM kg_nodes WHERE type='entity'").fetchall():
        label[nid], ntype[nid] = lbl, "entity"

    prov = defaultdict(list)            # node -> [conversation ids]
    conv_entities = defaultdict(set)    # conversation -> {node ids}
    for src, dst in conn.execute("SELECT src, dst FROM kg_edges WHERE dst LIKE 'entity:%'").fetchall():
        c = canon(dst)
        if c in hidden:
            continue
        prov[c].append(src)
        conv_entities[src].add(c)

    importance = {e: len(set(v)) for e, v in prov.items()}

    # Memory notes (My Memory / consolidations) are first-class nodes too.
    for nid, title in conn.execute("SELECT id, title FROM memory_entries").fetchall():
        c = canon(nid)
        if c in hidden:
            continue
        label[c], ntype[c] = title, "note"
        importance[c] = importance.get(c, 0) + 3

    prov_providers = defaultdict(set)
    for e, cl in prov.items():
        for cid in cl:
            prov_providers[e].add(conv_src.get(cid, "?"))

    items = list(importance.keys())
    if type_filter:
        items = [i for i in items if ntype.get(i) == type_filter]
    if provider:
        items = [i for i in items
                 if provider in prov_providers.get(i, set()) or ntype.get(i) == "note"]
    items.sort(key=lambda i: (i in pins, importance.get(i, 0)), reverse=True)
    keep = items[:limit]
    keepset = set(keep)

    nodes = [{"id": i, "label": renames.get(i, label.get(i, i)),
              "type": ntype.get(i, "entity"), "importance": importance.get(i, 0),
              "pinned": i in pins, "providers": sorted(prov_providers.get(i, set()))}
             for i in keep]

    pair = Counter()
    for ents in conv_entities.values():
        es = sorted({canon(e) for e in ents if canon(e) in keepset})
        for a in range(len(es)):
            for b in range(a + 1, len(es)):
                pair[(es[a], es[b])] += 1
    edges = [{"src": a, "dst": b, "weight": w} for (a, b), w in pair.most_common(140)]

    return {"nodes": nodes, "edges": edges, "total": len(importance)}


def node_detail(store, node_id: str) -> dict:
    conn = store.conn
    renames, pins, hidden, facts, canon = _load_overrides(store)
    nid = canon(node_id)

    row = conn.execute("SELECT label, type FROM kg_nodes WHERE id=?", (nid,)).fetchone()
    body, ntype = None, "entity"
    if row:
        base_label, ntype = row[0], row[1]
    else:
        m = conn.execute("SELECT title, body FROM memory_entries WHERE id=?", (nid,)).fetchone()
        if m:
            base_label, body, ntype = m[0], m[1], "note"
        else:
            base_label = nid

    convs = []
    for (src,) in conn.execute("SELECT DISTINCT src FROM kg_edges WHERE dst=?", (nid,)).fetchall():
        c = conn.execute("SELECT title, source FROM conversations WHERE id=?", (src,)).fetchone()
        if c:
            convs.append({"id": src, "title": c[0], "source": c[1]})

    return {"id": nid, "label": renames.get(nid, base_label), "type": ntype,
            "body": body, "facts": facts.get(nid, []), "pinned": nid in pins,
            "conversations": convs}


def edit(store, target: str, op: str, value=None) -> dict:
    if op not in VALID_OPS:
        raise ValueError(f"unknown op: {op}")
    now = time.time()
    payload = {"target": target, "op": op, "value": value, "ts": now}
    signature = store.identity.sign(canonical_bytes(payload)).hex()
    store.conn.execute(
        "INSERT INTO memory_overrides(target, op, value, signature, created_at)"
        " VALUES(?,?,?,?,?)",
        (target, op, json.dumps(value), signature, now))
    store.conn.commit()
    store.ledger.append("memory.edit", {"target": target, "op": op})
    return {"ok": True, "target": target, "op": op}

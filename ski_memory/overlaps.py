"""Automatic Compare — find where you asked the same thing in more than one place.

Pairs each user question with the answer that followed it, then clusters
similar questions across conversations. Semantic clustering when a local
embedding index exists (reusing stored message vectors); lexical (term-overlap)
fallback otherwise. A cluster spanning 2+ conversations — ideally different
providers — is an "overlap" worth comparing. Fully local.
"""
from __future__ import annotations

import array
import math
from itertools import combinations

from . import embeddings, retrieval

MAX_UNITS = 300  # bound the O(n^2) clustering

# Generic asks that appear in many chats and aren't meaningful "same question" overlaps.
_GENERIC = {
    "summarize", "summarise", "summary", "summarize this", "summarize it",
    "continue", "go on", "keep going", "more", "tell me more", "explain",
    "explain this", "explain that", "the code", "full code", "complete code",
    "give me the code", "give me the complete code", "show me the code",
    "rewrite", "rewrite this", "fix", "fix it", "fix this", "again", "redo",
    "ok", "okay", "thanks", "thank you", "yes", "no", "help", "what next",
    "next", "and", "why", "how", "translate", "improve this", "make it better",
}
_CMD_PREFIX = ("summari", "give me", "show me", "write ", "rewrite", "fix",
               "continue", "explain", "generate", "create ", "make ", "list ",
               "translate", "improve", "code", "draft", "redo")


def _is_generic(q: str) -> bool:
    ql = q.strip().lower().rstrip("?.! ")
    if len(ql) < 18:
        return True
    if ql in _GENERIC:
        return True
    if len(ql) < 45 and ql.startswith(_CMD_PREFIX):
        return True
    if len(retrieval.terms(q)) < 3:
        return True
    return False


def _question_units(store) -> list[dict]:
    conn = store.conn
    units = []
    for cid, title, source in conn.execute(
            "SELECT id, title, source FROM conversations").fetchall():
        msgs = conn.execute(
            "SELECT id, role, content FROM messages WHERE conversation_id=? ORDER BY seq",
            (cid,)).fetchall()
        for i, (mid, role, content) in enumerate(msgs):
            if role != "user" or not content.strip():
                continue
            answer = ""
            for j in range(i + 1, len(msgs)):
                if msgs[j][1] == "assistant":
                    answer = msgs[j][2]
                    break
            q = content.strip()
            if _is_generic(q):
                continue
            units.append({"message_id": mid, "conversation_id": cid, "title": title,
                          "source": source, "question": q, "answer": answer})
    return units[:MAX_UNITS]


def _load_vecs(store, ids):
    out = {}
    if not ids:
        return out
    qs = ",".join("?" * len(ids))
    for mid, vec in store.conn.execute(
            f"SELECT message_id, vec FROM embeddings WHERE message_id IN ({qs})", ids).fetchall():
        a = array.array("f")
        a.frombytes(vec)
        out[mid] = a
    return out


def _cos(a, an, b, bn):
    if len(a) != len(b) or an == 0 or bn == 0:
        return 0.0
    return sum(a[i] * b[i] for i in range(len(a))) / (an * bn)


def find_overlaps(store, threshold: float = 0.78, min_convs: int = 2) -> list[dict]:
    units = _question_units(store)
    if len(units) < 2:
        return []

    use_sem = embeddings.has_index(store) and embeddings.model_available()
    clusters: list[list[int]] = []
    method = "semantic" if use_sem else "lexical"

    if use_sem:
        vecs = _load_vecs(store, [u["message_id"] for u in units])
        units = [u for u in units if u["message_id"] in vecs]
        norms = {u["message_id"]: math.sqrt(sum(x * x for x in vecs[u["message_id"]])) for u in units}
        assigned = [False] * len(units)
        for i in range(len(units)):
            if assigned[i]:
                continue
            cl = [i]
            assigned[i] = True
            vi, ni = vecs[units[i]["message_id"]], norms[units[i]["message_id"]]
            for j in range(i + 1, len(units)):
                if assigned[j]:
                    continue
                if _cos(vi, ni, vecs[units[j]["message_id"]], norms[units[j]["message_id"]]) >= threshold:
                    cl.append(j)
                    assigned[j] = True
            clusters.append(cl)
        sim = lambda a, b: _cos(vecs[units[a]["message_id"]], norms[units[a]["message_id"]],
                                vecs[units[b]["message_id"]], norms[units[b]["message_id"]])
    else:
        termsets = [retrieval.terms(u["question"]) for u in units]
        assigned = [False] * len(units)
        for i in range(len(units)):
            if assigned[i] or not termsets[i]:
                continue
            cl = [i]
            assigned[i] = True
            for j in range(i + 1, len(units)):
                if assigned[j] or not termsets[j]:
                    continue
                inter = len(termsets[i] & termsets[j])
                union = len(termsets[i] | termsets[j])
                if union and inter / union >= 0.5:
                    cl.append(j)
                    assigned[j] = True
            clusters.append(cl)
        def sim(a, b):
            inter = len(termsets[a] & termsets[b])
            union = len(termsets[a] | termsets[b])
            return inter / union if union else 0.0

    overlaps = []
    for cl in clusters:
        members = [units[k] for k in cl]
        if len({m["conversation_id"] for m in members}) < min_convs:
            continue
        pairs = list(combinations(cl, 2))
        score = sum(sim(a, b) for a, b in pairs) / len(pairs) if pairs else 1.0
        overlaps.append({
            "id": "ov:" + members[0]["message_id"][:16],
            "question": members[0]["question"][:200],
            "method": method,
            "score": round(score, 2),
            "providers": sorted({m["source"] for m in members}),
            "members": [{"conversation_id": m["conversation_id"], "title": m["title"],
                         "source": m["source"], "question": m["question"],
                         "answer": m["answer"]} for m in members],
        })
    overlaps.sort(key=lambda o: (len(set(o["providers"])), o["score"], len(o["members"])),
                  reverse=True)
    return overlaps

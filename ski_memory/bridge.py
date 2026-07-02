"""The bridge: hand off between cloud AI and local continuation.

Two directions:
  * IN  — paste a conversation (a copied transcript or an export JSON) and turn
          it into a local conversation you can continue while Claude is limited.
  * OUT — generate a concise "handoff brief" of what happened (including local
          continuation) to paste back into Claude so it picks up where you left
          off.

The brief generator uses the local model when available, but falls back to a
deterministic recap so the bridge works with no model installed.
"""
from __future__ import annotations

import re
import time

from . import ingest, llm

# Standalone marker lines like "You", "Claude:", "Assistant".
_MARKER_LINE = re.compile(r"^\s*(you|human|me|user|prompt)\s*:?\s*$", re.I)
_MARKER_ASST = re.compile(r"^\s*(claude|assistant|chatgpt|gpt|ai|bot|answer)\s*:?\s*$", re.I)
# Inline markers like "You: hello".
_INLINE = re.compile(r"^\s*(you|human|me|user|claude|assistant|chatgpt|gpt|ai)\s*:\s*(.+)$", re.I)
_USER_WORDS = {"you", "human", "me", "user", "prompt"}


def parse_pasted(text: str, title: str | None = None) -> tuple[str, list[dict]]:
    """Parse a pasted conversation. Returns (format, [conversation])."""
    text = text.strip()
    # If it looks like an export, reuse the JSON importers.
    if text[:1] in "[{":
        try:
            return ingest.parse(text)
        except Exception:
            pass

    msgs: list[tuple[str, str]] = []
    cur_role = "user"
    buf: list[str] = []
    found_markers = False

    def flush():
        if buf:
            content = "\n".join(buf).strip()
            if content:
                msgs.append((cur_role, content))

    for line in text.split("\n"):
        stripped = line.strip()
        inline = _INLINE.match(stripped)
        if _MARKER_LINE.match(stripped):
            flush(); buf.clear(); cur_role = "user"; found_markers = True
        elif _MARKER_ASST.match(stripped):
            flush(); buf.clear(); cur_role = "assistant"; found_markers = True
        elif inline:
            flush(); buf.clear()
            cur_role = "user" if inline.group(1).lower() in _USER_WORDS else "assistant"
            buf.append(inline.group(2)); found_markers = True
        else:
            buf.append(line)
    flush()

    if not msgs:
        # No structure detected — keep the whole paste as one context block.
        msgs = [("user", text)]

    title = (title or "").strip() or "Pasted conversation"
    cid = "paste:" + ingest._hash_id(title, text[:200], str(time.time()))
    conv = {
        "id": cid, "source": "paste", "title": title, "created_at": time.time(),
        "messages": [{"seq": i, "role": r, "model": None, "content": c,
                      "created_at": None} for i, (r, c) in enumerate(msgs)],
    }
    return "paste", [conv]


def ingest_pasted(store, text: str, title: str | None = None) -> tuple[dict, list[str]]:
    fmt, conversations = parse_pasted(text, title)
    return ingest.store_parsed(store, fmt, conversations, "pasted")


_BRIEF_SYSTEM = (
    "You write a concise handoff brief so another AI assistant can resume a "
    "conversation. Summarize the goal, the key decisions and facts established, "
    "any code or artifacts in progress, and the single most important next step. "
    "Use short sections. Do not invent anything not in the transcript."
)


def make_brief(store, conversation_id: str, model: str | None = None) -> dict:
    conn = store.conn
    row = conn.execute(
        "SELECT title FROM conversations WHERE id=?", (conversation_id,)).fetchone()
    if not row:
        raise ValueError("conversation not found")
    title = row[0] or "our conversation"
    msgs = conn.execute(
        "SELECT role, content FROM messages WHERE conversation_id=? ORDER BY seq",
        (conversation_id,)).fetchall()
    transcript = "\n\n".join(f"{r.upper()}: {c}" for r, c in msgs)

    summary = None
    used_model = None
    try:
        summary, used_model = llm.chat(
            [{"role": "system", "content": _BRIEF_SYSTEM},
             {"role": "user", "content": transcript[-9000:]}], model)
    except llm.LLMUnavailable:
        summary = None  # fall back to a deterministic recap below

    if not summary:
        first_user = next((c for r, c in msgs if r == "user"), "")
        last_asst = next((c for r, c in reversed(msgs) if r == "assistant"), "")
        parts = []
        if first_user:
            parts.append("What we set out to do:\n" + first_user.strip()[:600])
        if last_asst:
            parts.append("Where we left off:\n" + last_asst.strip()[:900])
        summary = "\n\n".join(parts) or "(no content captured)"

    brief = (
        f'I was working with you on "{title}" and continued locally while you '
        f"were rate-limited. Here's a recap so you can pick up exactly where we "
        f"left off:\n\n{summary}\n\nPlease continue from here."
    )
    store.ledger.append("handoff_brief", {
        "conversation_id": conversation_id, "model": used_model,
        "messages": len(msgs), "brief_chars": len(brief),
    })
    return {"brief": brief, "model": used_model, "messages": len(msgs)}

"""Chat importers.

Parses export files from Claude, ChatGPT, and a generic/Grok fallback into a
common normalized shape, then writes them into the store and records the
import in the hash-chained ledger.

Normalized conversation:
    {
      "id": "<source>:<native_id>",
      "source": "claude" | "chatgpt" | "generic",
      "title": str,
      "created_at": float | None,
      "messages": [
        {"seq": int, "role": "user|assistant|system",
         "model": str | None, "content": str, "created_at": float | None}
      ]
    }
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Optional


# --- helpers --------------------------------------------------------------
def _hash_id(*parts: str) -> str:
    h = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return h[:16]


def _coerce_ts(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        # ISO-8601 like "2024-01-02T03:04:05Z"
        try:
            from datetime import datetime
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


# Placeholder strings some exports embed for content the device can't render.
_ARTIFACT_MARKERS = (
    "This block is not supported on your current device",
)


def _clean(text: str) -> str:
    if not text:
        return ""
    for marker in _ARTIFACT_MARKERS:
        if marker in text:
            return ""
    return text


def _claude_message_text(msg: dict) -> str:
    if isinstance(msg.get("text"), str) and msg["text"].strip():
        return _clean(msg["text"])
    parts = []
    for block in msg.get("content", []) or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(_clean(block.get("text", "")))
        elif isinstance(block, str):
            parts.append(_clean(block))
    return "\n".join(p for p in parts if p)


# --- format detection -----------------------------------------------------
def detect_format(data: Any) -> str:
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            if "chat_messages" in first:
                return "claude"
            if "mapping" in first:
                return "chatgpt"
            if "role" in first and "content" in first:
                return "generic_messages"
    if isinstance(data, dict):
        if "mapping" in data:
            return "chatgpt"
        if "messages" in data:
            return "generic"
        if "chat_messages" in data:
            return "claude"
    return "unknown"


# --- per-format parsers ---------------------------------------------------
def parse_claude(data: list) -> list[dict]:
    out = []
    for conv in data:
        cid = str(conv.get("uuid") or conv.get("id") or _hash_id(json.dumps(conv)[:200]))
        messages = []
        for i, m in enumerate(conv.get("chat_messages", []) or []):
            sender = (m.get("sender") or m.get("role") or "").lower()
            role = "user" if sender in ("human", "user") else (
                "assistant" if sender in ("assistant", "ai") else (sender or "user"))
            text = _claude_message_text(m)
            if not text.strip():
                continue
            messages.append({
                "seq": i, "role": role, "model": None,
                "content": text, "created_at": _coerce_ts(m.get("created_at")),
            })
        out.append({
            "id": f"claude:{cid}", "source": "claude",
            "title": conv.get("name") or "Untitled",
            "created_at": _coerce_ts(conv.get("created_at")),
            "messages": messages,
        })
    return out


def parse_chatgpt(data: Any) -> list[dict]:
    conversations = data if isinstance(data, list) else [data]
    out = []
    for conv in conversations:
        mapping = conv.get("mapping", {}) or {}
        rows = []
        for node in mapping.values():
            msg = (node or {}).get("message")
            if not msg:
                continue
            role = ((msg.get("author") or {}).get("role")) or "user"
            content = msg.get("content") or {}
            parts = content.get("parts") if isinstance(content, dict) else None
            text = ""
            if isinstance(parts, list):
                text = "\n".join(p for p in parts if isinstance(p, str))
            text = _clean(text)
            if not text.strip():
                continue
            rows.append((msg.get("create_time") or 0, role, text,
                         (msg.get("metadata") or {}).get("model_slug")))
        rows.sort(key=lambda r: r[0])
        messages = [{
            "seq": i, "role": r[1], "model": r[3],
            "content": r[2], "created_at": _coerce_ts(r[0]) if r[0] else None,
        } for i, r in enumerate(rows)]
        cid = str(conv.get("conversation_id") or conv.get("id")
                  or _hash_id(conv.get("title", ""), str(conv.get("create_time", ""))))
        out.append({
            "id": f"chatgpt:{cid}", "source": "chatgpt",
            "title": conv.get("title") or "Untitled",
            "created_at": _coerce_ts(conv.get("create_time")),
            "messages": messages,
        })
    return out


def parse_generic(data: Any) -> list[dict]:
    """Grok / generic: {messages:[...]} or a bare [{role,content}] list."""
    if isinstance(data, dict):
        msgs = data.get("messages", [])
        title = data.get("title") or "Imported conversation"
        created = _coerce_ts(data.get("created_at"))
    else:
        msgs = data
        title = "Imported conversation"
        created = None
    messages = []
    for i, m in enumerate(msgs or []):
        content = m.get("content") or m.get("text") or ""
        if isinstance(content, list):
            content = "\n".join(str(x) for x in content)
        content = _clean(str(content))
        if not content.strip():
            continue
        messages.append({
            "seq": i, "role": (m.get("role") or "user").lower(),
            "model": m.get("model"), "content": content,
            "created_at": _coerce_ts(m.get("created_at")),
        })
    first = messages[0]["content"] if messages else ""
    cid = _hash_id(title, first[:200])
    return [{
        "id": f"generic:{cid}", "source": "generic",
        "title": title, "created_at": created, "messages": messages,
    }]


def parse(content: str) -> tuple[str, list[dict]]:
    """Parse raw export text. Returns (detected_format, conversations)."""
    data = json.loads(content)
    fmt = detect_format(data)
    if fmt == "claude":
        return fmt, parse_claude(data if isinstance(data, list) else [data])
    if fmt == "chatgpt":
        return fmt, parse_chatgpt(data)
    if fmt in ("generic", "generic_messages"):
        return fmt, parse_generic(data)
    raise ValueError("Unrecognized export format")


# --- store integration ----------------------------------------------------
def store_parsed(store, fmt: str, conversations: list[dict], filename: str = "") -> tuple[dict, list[str]]:
    """Insert/merge already-parsed conversations; return (summary, added_conversation_ids).

    Re-importing a conversation that already exists (e.g. you continued it in
    Claude and re-exported) merges in only the genuinely new messages — matched
    by (role, content) so identical messages aren't duplicated — rather than
    creating a second conversation or skipping the new turns.
    """
    conn = store.conn
    new_conv = updated_conv = new_msg = skipped = 0
    added_ids: list[str] = []
    now = time.time()
    for conv in conversations:
        exists = conn.execute(
            "SELECT 1 FROM conversations WHERE id=?", (conv["id"],)).fetchone()

        if not exists:
            conn.execute(
                "INSERT INTO conversations(id, source, title, created_at, imported_at, meta)"
                " VALUES(?,?,?,?,?,?)",
                (conv["id"], conv["source"], conv["title"], conv["created_at"], now,
                 json.dumps({"filename": filename})))
            new_conv += 1
            added_ids.append(conv["id"])
            for m in conv["messages"]:
                conn.execute(
                    "INSERT OR IGNORE INTO messages"
                    "(id, conversation_id, seq, role, model, content, created_at, meta)"
                    " VALUES(?,?,?,?,?,?,?,?)",
                    (f"{conv['id']}:{m['seq']}", conv["id"], m["seq"], m["role"],
                     m.get("model"), m["content"], m.get("created_at"), None))
                new_msg += 1
            continue

        # Existing conversation: merge new messages only.
        existing = {(r[0], r[1]) for r in conn.execute(
            "SELECT role, content FROM messages WHERE conversation_id=?", (conv["id"],)).fetchall()}
        max_seq = conn.execute(
            "SELECT COALESCE(MAX(seq), -1) FROM messages WHERE conversation_id=?",
            (conv["id"],)).fetchone()[0]
        added_here = 0
        for m in conv["messages"]:
            key = (m["role"], m["content"])
            if key in existing:
                continue
            max_seq += 1
            mid = f"{conv['id']}:{max_seq}"
            while conn.execute("SELECT 1 FROM messages WHERE id=?", (mid,)).fetchone():
                max_seq += 1
                mid = f"{conv['id']}:{max_seq}"
            conn.execute(
                "INSERT INTO messages"
                "(id, conversation_id, seq, role, model, content, created_at, meta)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (mid, conv["id"], max_seq, m["role"], m.get("model"),
                 m["content"], m.get("created_at"), '{"origin":"reimport"}'))
            existing.add(key)
            added_here += 1
            new_msg += 1
        if added_here:
            updated_conv += 1
            conn.execute("UPDATE conversations SET title=?, imported_at=? WHERE id=?",
                         (conv["title"], now, conv["id"]))
        else:
            skipped += 1

    conn.commit()
    summary = {
        "format": fmt, "filename": filename,
        "conversations_added": new_conv, "conversations_updated": updated_conv,
        "messages_added": new_msg, "conversations_skipped": skipped,
    }
    store.ledger.append("import", summary)
    return summary, added_ids


def import_into_store(store, content: str, filename: str = "") -> dict:
    fmt, conversations = parse(content)
    summary, _ = store_parsed(store, fmt, conversations, filename)
    return summary

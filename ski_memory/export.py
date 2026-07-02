"""Verifiable thread export.

Produces a signed, self-contained bundle for a single conversation that a
third party can verify offline — proving the messages are intact and were
exported by the holder of a specific Ed25519 identity, and that the bundled
ledger entries are authentic. Verification needs only the bundle itself (the
public key is embedded) and the `cryptography` library.

This is the SKI Framework's "provenance, not trust" idea applied to a personal
conversation: any auditor can replay the checks.
"""
from __future__ import annotations

import hashlib
import time

from . import __version__, kg
from .crypto import verify as verify_sig
from .ledger import canonical_bytes

EXPORT_VERSION = "ski-memory-export/v1"


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _entry_hash(e: dict) -> str:
    return _sha256_hex(canonical_bytes({
        "seq": e["seq"], "ts": e["ts"], "kind": e["kind"],
        "payload": e["payload"], "prev_hash": e["prev_hash"],
    }))


def build_export(store, conversation_id: str) -> dict:
    conn = store.conn
    c = conn.execute(
        "SELECT id, title, source, created_at FROM conversations WHERE id=?",
        (conversation_id,)).fetchone()
    if not c:
        raise ValueError("conversation not found")

    rows = conn.execute(
        "SELECT seq, role, model, content, created_at, meta FROM messages "
        "WHERE conversation_id=? ORDER BY seq", (conversation_id,)).fetchall()
    messages = [{
        "seq": r[0], "role": r[1], "model": r[2], "content": r[3],
        "created_at": r[4],
        "local": (r[5] or "").find("local_continuation") >= 0,
    } for r in rows]

    # Ledger entries that explicitly reference this conversation (e.g. continuations).
    related = [e.to_public_dict() for e in store.ledger.entries()
               if isinstance(e.payload, dict)
               and e.payload.get("conversation_id") == conversation_id]
    head = store.ledger.head()

    manifest = {
        "export_version": EXPORT_VERSION,
        "app_version": __version__,
        "exported_at": time.time(),
        "identity": {
            "public_key": store.identity.public_key_hex,
            "fingerprint": store.identity.fingerprint,
        },
        "conversation": {
            "id": c[0], "title": c[1], "source": c[2], "created_at": c[3],
        },
        "messages": messages,
        "message_count": len(messages),
        "graph": kg.graph_for_conversation(store, conversation_id),
        "ledger_entries": related,
        "ledger_head_hash": head.entry_hash if head else None,
        "messages_hash": _sha256_hex(canonical_bytes(messages)),
    }
    signature = store.identity.sign(canonical_bytes(manifest)).hex()
    return {"manifest": manifest, "signature": signature}


def verify_export(bundle: dict) -> tuple[bool, list[dict]]:
    """Pure, offline verification. Returns (ok, [{name, ok, detail}])."""
    checks: list[dict] = []

    def add(name, ok, detail=""):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    if not isinstance(bundle, dict) or "manifest" not in bundle or "signature" not in bundle:
        add("bundle structure", False, "missing manifest or signature")
        return False, checks

    manifest = bundle["manifest"]
    try:
        pub = bytes.fromhex(manifest["identity"]["public_key"])
        signature = bytes.fromhex(bundle["signature"])
    except (KeyError, ValueError, TypeError) as e:
        add("bundle structure", False, str(e))
        return False, checks

    # 1. Messages integrity.
    recomputed = _sha256_hex(canonical_bytes(manifest.get("messages", [])))
    add("messages integrity (hash)", recomputed == manifest.get("messages_hash"),
        f"{manifest.get('message_count', '?')} messages")

    # 2. Export signature over the whole manifest.
    add("export signature (Ed25519)",
        verify_sig(pub, signature, canonical_bytes(manifest)),
        manifest["identity"]["fingerprint"])

    # 3. Each bundled ledger entry: recompute hash + verify signature under the same key.
    le_ok = True
    detail = ""
    for e in manifest.get("ledger_entries", []):
        try:
            if _entry_hash(e) != e["entry_hash"]:
                le_ok = False
                detail = f"hash mismatch at seq {e.get('seq')}"
                break
            if not verify_sig(pub, bytes.fromhex(e["signature"]),
                              bytes.fromhex(e["entry_hash"])):
                le_ok = False
                detail = f"bad signature at seq {e.get('seq')}"
                break
        except (KeyError, ValueError, TypeError) as ex:
            le_ok = False
            detail = str(ex)
            break
    add("ledger entries authenticity", le_ok,
        detail or f"{len(manifest.get('ledger_entries', []))} entries")

    ok = all(c["ok"] for c in checks)
    return ok, checks

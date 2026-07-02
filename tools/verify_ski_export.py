#!/usr/bin/env python3
"""Standalone verifier for a SKI Memory export bundle (*.skimem.json).

Usage:  python verify_ski_export.py path/to/thread.skimem.json

Self-contained: needs only the Python standard library and `cryptography`
(`pip install cryptography`). It does NOT require SKI Memory to be installed.
Verifies, fully offline:
  1. the exported messages are intact (content hash),
  2. the bundle was signed by the embedded Ed25519 identity,
  3. every bundled ledger entry is authentic under that same identity.
"""
import hashlib
import json
import sys


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def verify_sig(pub: bytes, sig: bytes, data: bytes) -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes(pub).verify(sig, data)
        return True
    except Exception:
        return False


def entry_hash(e: dict) -> str:
    return hashlib.sha256(canonical({
        "seq": e["seq"], "ts": e["ts"], "kind": e["kind"],
        "payload": e["payload"], "prev_hash": e["prev_hash"],
    })).hexdigest()


def main(path: str) -> int:
    with open(path, encoding="utf-8") as f:
        bundle = json.load(f)
    m = bundle["manifest"]
    pub = bytes.fromhex(m["identity"]["public_key"])
    sig = bytes.fromhex(bundle["signature"])

    results = []
    results.append(("Messages intact (SHA-256)",
                    hashlib.sha256(canonical(m["messages"])).hexdigest() == m["messages_hash"]))
    results.append(("Export signed by identity (Ed25519)",
                    verify_sig(pub, sig, canonical(m))))
    le_ok = True
    for e in m.get("ledger_entries", []):
        if entry_hash(e) != e["entry_hash"] or not verify_sig(
                pub, bytes.fromhex(e["signature"]), bytes.fromhex(e["entry_hash"])):
            le_ok = False
            break
    results.append(("Ledger entries authentic", le_ok))

    print(f"\nSKI Memory export — {m['conversation']['title']}")
    print(f"  source: {m['conversation']['source']}  ·  messages: {m['message_count']}")
    print(f"  identity fingerprint: {m['identity']['fingerprint']}\n")
    for name, ok in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    overall = all(ok for _, ok in results)
    print(f"\n  => {'VERIFIED — authentic and intact' if overall else 'VERIFICATION FAILED'}\n")
    return 0 if overall else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python verify_ski_export.py <bundle.skimem.json>")
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))

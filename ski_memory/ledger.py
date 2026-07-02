"""Hash-chained, append-only audit ledger.

Every meaningful event in SKI Memory — an import, a knowledge-graph build, a
locally generated continuation — is recorded as a ledger entry. Each entry is
chained to the previous one by hash and signed by the local identity, so any
later alteration to any past entry breaks the chain and fails verification.

This mirrors the SKI Framework's append-only audit ledger and its canonical
serialization approach.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Optional

from .crypto import Identity, verify as verify_sig

GENESIS_PREV = "0" * 64


def canonical_bytes(obj: Any) -> bytes:
    """Deterministic JSON serialization used for hashing."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _entry_hash(seq: int, ts: float, kind: str, payload: dict, prev_hash: str) -> str:
    material = canonical_bytes(
        {
            "seq": seq,
            "ts": ts,
            "kind": kind,
            "payload": payload,
            "prev_hash": prev_hash,
        }
    )
    return hashlib.sha256(material).hexdigest()


@dataclass
class LedgerEntry:
    seq: int
    ts: float
    kind: str
    payload: dict
    prev_hash: str
    entry_hash: str
    signature: str  # hex-encoded Ed25519 signature over entry_hash bytes

    def to_public_dict(self) -> dict:
        return {
            "seq": self.seq,
            "ts": self.ts,
            "kind": self.kind,
            "payload": self.payload,
            "prev_hash": self.prev_hash,
            "entry_hash": self.entry_hash,
            "signature": self.signature,
        }


class Ledger:
    """Append-only hash-chained ledger backed by a SQLite table."""

    def __init__(self, conn: sqlite3.Connection, identity: Identity):
        self._conn = conn
        self._identity = identity
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ledger (
                seq        INTEGER PRIMARY KEY,
                ts         REAL    NOT NULL,
                kind       TEXT    NOT NULL,
                payload    TEXT    NOT NULL,
                prev_hash  TEXT    NOT NULL,
                entry_hash TEXT    NOT NULL,
                signature  TEXT    NOT NULL
            )
            """
        )
        self._conn.commit()

    # --- writing --------------------------------------------------------
    def append(self, kind: str, payload: Optional[dict] = None) -> LedgerEntry:
        payload = payload or {}
        row = self._conn.execute(
            "SELECT seq, entry_hash FROM ledger ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        if row is None:
            seq, prev_hash = 0, GENESIS_PREV
        else:
            seq, prev_hash = row[0] + 1, row[1]

        ts = time.time()
        entry_hash = _entry_hash(seq, ts, kind, payload, prev_hash)
        signature = self._identity.sign(bytes.fromhex(entry_hash)).hex()

        self._conn.execute(
            "INSERT INTO ledger (seq, ts, kind, payload, prev_hash, entry_hash, signature)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (seq, ts, kind, json.dumps(payload), prev_hash, entry_hash, signature),
        )
        self._conn.commit()
        return LedgerEntry(seq, ts, kind, payload, prev_hash, entry_hash, signature)

    # --- reading --------------------------------------------------------
    def __len__(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM ledger").fetchone()[0]

    def entries(self) -> list[LedgerEntry]:
        rows = self._conn.execute(
            "SELECT seq, ts, kind, payload, prev_hash, entry_hash, signature"
            " FROM ledger ORDER BY seq ASC"
        ).fetchall()
        return [
            LedgerEntry(r[0], r[1], r[2], json.loads(r[3]), r[4], r[5], r[6])
            for r in rows
        ]

    def head(self) -> Optional[LedgerEntry]:
        entries = self.entries()
        return entries[-1] if entries else None

    # --- integrity ------------------------------------------------------
    def verify(self) -> tuple[bool, Optional[str]]:
        """Recompute the chain and check every signature.

        Returns ``(ok, error)``. ``error`` describes the first problem found.
        """
        pub = self._identity.public_bytes_raw()
        prev_hash = GENESIS_PREV
        expected_seq = 0
        for e in self.entries():
            if e.seq != expected_seq:
                return False, f"sequence gap at seq={e.seq} (expected {expected_seq})"
            if e.prev_hash != prev_hash:
                return False, f"broken chain at seq={e.seq}: prev_hash mismatch"
            recomputed = _entry_hash(e.seq, e.ts, e.kind, e.payload, e.prev_hash)
            if recomputed != e.entry_hash:
                return False, f"tampered entry at seq={e.seq}: entry_hash mismatch"
            if not verify_sig(pub, bytes.fromhex(e.signature), bytes.fromhex(e.entry_hash)):
                return False, f"invalid signature at seq={e.seq}"
            prev_hash = e.entry_hash
            expected_seq += 1
        return True, None

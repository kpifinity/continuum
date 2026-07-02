"""Local app-data store.

A single SQLite database in the user's SKI Memory folder holds everything:
conversations, messages, the knowledge graph (nodes + edges), and the
hash-chained ledger. The schema skeleton for conversations/messages/KG is
created now; importers and the KG builder populate it in later milestones.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from .config import Config
from .crypto import Identity
from .ledger import Ledger

SCHEMA = """
-- Imported conversations and their messages -------------------------------
CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT PRIMARY KEY,        -- stable id (source + native id)
    source      TEXT NOT NULL,           -- 'claude' | 'chatgpt' | 'grok'
    title       TEXT,
    created_at  REAL,
    imported_at REAL NOT NULL,
    meta        TEXT                      -- JSON: arbitrary source metadata
);

CREATE TABLE IF NOT EXISTS messages (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    seq             INTEGER NOT NULL,     -- order within conversation
    role            TEXT NOT NULL,        -- 'user' | 'assistant' | 'system'
    model           TEXT,                 -- generating model, when known
    content         TEXT NOT NULL,
    created_at      REAL,
    meta            TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, seq);

-- Knowledge graph ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS kg_nodes (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL,            -- entity | decision | fact | action_item | ...
    label       TEXT NOT NULL,
    body        TEXT,
    provenance  TEXT NOT NULL,            -- JSON envelope: source, model, ts, method, confidence
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS kg_edges (
    id          TEXT PRIMARY KEY,
    src         TEXT NOT NULL REFERENCES kg_nodes(id),
    dst         TEXT NOT NULL REFERENCES kg_nodes(id),
    type        TEXT NOT NULL,
    provenance  TEXT NOT NULL,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_edges_src ON kg_edges(src);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON kg_edges(dst);

-- Message embeddings (semantic search) ------------------------------------
CREATE TABLE IF NOT EXISTS embeddings (
    message_id TEXT PRIMARY KEY REFERENCES messages(id),
    model      TEXT NOT NULL,
    dim        INTEGER NOT NULL,
    vec        BLOB NOT NULL
);

-- My Memory: curated, user-owned knowledge (signed) ---------------------
CREATE TABLE IF NOT EXISTS memory_entries (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    body       TEXT NOT NULL,
    tags       TEXT,
    provenance TEXT,
    signature  TEXT,
    created_at REAL NOT NULL
);

-- User edits to the Memory graph (rename/pin/hide/merge/fact), signed --------
CREATE TABLE IF NOT EXISTS memory_overrides (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    target     TEXT NOT NULL,
    op         TEXT NOT NULL,
    value      TEXT,
    signature  TEXT,
    created_at REAL NOT NULL
);

-- Key/value metadata ------------------------------------------------------
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


class Store:
    """Owns the SQLite connection, the identity, and the ledger."""

    def __init__(self, config: Config):
        self.config = config
        # check_same_thread=False: the FastAPI server dispatches sync endpoints
        # on a worker thread pool. Access is effectively single-user and low
        # concurrency, so sharing one connection across threads is safe here.
        self.conn = sqlite3.connect(str(config.db_path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

        self.identity = Identity.load_or_create(
            config.identity_key_path, config.identity_pub_path
        )
        self.ledger = Ledger(self.conn, self.identity)
        self._record_first_run()

    def _record_first_run(self) -> None:
        if len(self.ledger) == 0:
            self.ledger.append(
                "store.initialized",
                {"identity": self.identity.public_key_hex, "schema": "v0.1"},
            )

    # --- convenience ----------------------------------------------------
    def get_meta(self, key: str) -> Optional[str]:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.conn.commit()

    def counts(self) -> dict:
        c = self.conn
        return {
            "conversations": c.execute("SELECT COUNT(*) FROM conversations").fetchone()[0],
            "messages": c.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
            "kg_nodes": c.execute("SELECT COUNT(*) FROM kg_nodes").fetchone()[0],
            "kg_edges": c.execute("SELECT COUNT(*) FROM kg_edges").fetchone()[0],
            "ledger_entries": len(self.ledger),
        }

    def close(self) -> None:
        self.conn.close()


def open_store(config: Optional[Config] = None) -> Store:
    from .config import load_config

    return Store(config or load_config())

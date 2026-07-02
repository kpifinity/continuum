"""Local cryptographic identity (Ed25519).

On first run SKI Memory generates an Ed25519 keypair stored locally. This
identity signs ledger entries and (later) the knowledge graph, giving every
record verifiable provenance — the same signing primitive the SKI Framework
uses for its sovereign knowledge graph and audit ledger.
"""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


class Identity:
    """An Ed25519 signing identity backed by local key files."""

    def __init__(self, private_key: Ed25519PrivateKey):
        self._sk = private_key
        self._pk = private_key.public_key()

    # --- construction ---------------------------------------------------
    @classmethod
    def load_or_create(cls, key_path: Path, pub_path: Path) -> "Identity":
        if key_path.exists():
            data = key_path.read_bytes()
            sk = serialization.load_pem_private_key(data, password=None)
            if not isinstance(sk, Ed25519PrivateKey):
                raise ValueError("identity.key is not an Ed25519 private key")
            ident = cls(sk)
        else:
            ident = cls(Ed25519PrivateKey.generate())
            ident._write_private(key_path)
        # Always (re)write the public key so it stays in sync.
        ident._write_public(pub_path)
        return ident

    # --- persistence ----------------------------------------------------
    def _write_private(self, path: Path) -> None:
        pem = self._sk.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        path.write_bytes(pem)
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
        except (OSError, NotImplementedError):
            pass  # best-effort on platforms without POSIX perms

    def _write_public(self, path: Path) -> None:
        path.write_bytes(self.public_bytes_raw())

    # --- operations -----------------------------------------------------
    def sign(self, data: bytes) -> bytes:
        return self._sk.sign(data)

    def verify(self, signature: bytes, data: bytes) -> bool:
        return verify(self.public_bytes_raw(), signature, data)

    def public_bytes_raw(self) -> bytes:
        return self._pk.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    @property
    def public_key_hex(self) -> str:
        return self.public_bytes_raw().hex()

    @property
    def fingerprint(self) -> str:
        """Short, human-readable fingerprint of the public key."""
        digest = hashlib.sha256(self.public_bytes_raw()).hexdigest()
        return ":".join(digest[i : i + 4] for i in range(0, 16, 4))


def verify(public_key_raw: bytes, signature: bytes, data: bytes) -> bool:
    """Verify a signature against a raw Ed25519 public key. Never raises."""
    try:
        pk = Ed25519PublicKey.from_public_bytes(public_key_raw)
        pk.verify(signature, data)
        return True
    except Exception:
        return False

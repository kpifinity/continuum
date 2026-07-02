import sqlite3

from ski_memory.crypto import Identity
from ski_memory.ledger import Ledger


def make_ledger(tmp_path):
    conn = sqlite3.connect(":memory:")
    ident = Identity.load_or_create(tmp_path / "k", tmp_path / "p")
    return Ledger(conn, ident), conn, ident


def test_append_and_verify(tmp_path):
    ledger, _, _ = make_ledger(tmp_path)
    ledger.append("import", {"source": "claude", "n": 3})
    ledger.append("kg.build", {"nodes": 12})
    assert len(ledger) == 2
    ok, err = ledger.verify()
    assert ok and err is None


def test_chain_links_are_sequential(tmp_path):
    ledger, _, _ = make_ledger(tmp_path)
    e0 = ledger.append("a")
    e1 = ledger.append("b")
    assert e0.seq == 0 and e1.seq == 1
    assert e1.prev_hash == e0.entry_hash


def test_tampering_with_payload_is_detected(tmp_path):
    ledger, conn, _ = make_ledger(tmp_path)
    ledger.append("import", {"source": "claude"})
    ledger.append("import", {"source": "chatgpt"})

    # Mutate a stored payload directly — simulating tampering.
    conn.execute("UPDATE ledger SET payload=? WHERE seq=0", ('{"source": "evil"}',))
    conn.commit()

    ok, err = ledger.verify()
    assert not ok
    assert "tampered" in err or "mismatch" in err


def test_tampering_with_signature_is_detected(tmp_path):
    ledger, conn, _ = make_ledger(tmp_path)
    ledger.append("import", {"source": "grok"})
    bad = "00" * 64
    conn.execute("UPDATE ledger SET signature=? WHERE seq=0", (bad,))
    conn.commit()
    ok, err = ledger.verify()
    assert not ok
    assert "signature" in err

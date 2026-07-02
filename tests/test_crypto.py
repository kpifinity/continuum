from ski_memory.crypto import Identity, verify


def test_keypair_persisted_and_loaded(tmp_path):
    key = tmp_path / "identity.key"
    pub = tmp_path / "identity.pub"

    a = Identity.load_or_create(key, pub)
    assert key.exists() and pub.exists()
    fp1 = a.fingerprint

    # Reloading yields the same identity.
    b = Identity.load_or_create(key, pub)
    assert b.fingerprint == fp1
    assert b.public_key_hex == a.public_key_hex


def test_sign_and_verify_roundtrip(tmp_path):
    ident = Identity.load_or_create(tmp_path / "k", tmp_path / "p")
    msg = b"sovereign memory"
    sig = ident.sign(msg)
    assert ident.verify(sig, msg)
    assert verify(ident.public_bytes_raw(), sig, msg)


def test_verify_rejects_tampered_message(tmp_path):
    ident = Identity.load_or_create(tmp_path / "k", tmp_path / "p")
    sig = ident.sign(b"original")
    assert not ident.verify(sig, b"tampered")


def test_verify_never_raises_on_garbage():
    assert verify(b"not-a-key", b"not-a-sig", b"data") is False

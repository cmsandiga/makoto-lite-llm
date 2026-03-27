from app.auth.crypto import decrypt, encrypt


def test_encrypt_decrypt_roundtrip():
    plaintext = "my-super-secret-client-secret"
    encrypted = encrypt(plaintext)
    assert encrypted != plaintext
    assert decrypt(encrypted) == plaintext


def test_different_ciphertexts_for_same_plaintext():
    e1 = encrypt("same")
    e2 = encrypt("same")
    assert e1 != e2  # different IV each time

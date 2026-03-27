from app.auth.api_key_auth import generate_api_key, get_key_prefix, hash_api_key


def test_generate_api_key_format():
    key = generate_api_key()
    assert key.startswith("sk-")
    assert len(key) == 43  # "sk-" + 8 prefix + 32 random


def test_generate_api_key_uniqueness():
    k1 = generate_api_key()
    k2 = generate_api_key()
    assert k1 != k2


def test_hash_api_key():
    key = generate_api_key()
    hashed = hash_api_key(key)
    assert len(hashed) == 64  # SHA-256 hex
    assert hash_api_key(key) == hashed  # deterministic


def test_get_key_prefix():
    key = generate_api_key()
    prefix = get_key_prefix(key)
    assert prefix.startswith("sk-")
    assert len(prefix) == 11  # "sk-" + 8 chars

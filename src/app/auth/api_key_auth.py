import hashlib
import secrets


def generate_api_key() -> str:
    prefix = secrets.token_hex(4)  # 8 hex chars
    random_part = secrets.token_hex(16)  # 32 hex chars
    return f"sk-{prefix}{random_part}"


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def get_key_prefix(key: str) -> str:
    return key[:11]  # "sk-" + 8 chars

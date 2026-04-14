from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/makoto_lite_llm"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # JWT
    jwt_secret_key: str = "changeme-in-production-use-long-random-string"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # Encryption
    encryption_key: str = "changeme-32-bytes-key-in-prod!!!"  # Must be 32 bytes for AES-256

    # Auth
    max_login_attempts: int = 5
    lockout_duration_minutes: int = 15
    api_key_cache_ttl_seconds: int = 5

    # App
    app_name: str = "Makoto LiteLLM"
    debug: bool = False
    cors_origins: list[str] = ["http://localhost:3000"]
    base_url: str = "http://localhost:8000"


settings = Settings()

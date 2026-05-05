"""Side-effect import: registers each provider into PROVIDER_REGISTRY."""

from app.sdk.providers import (
    anthropic,  # noqa: F401  registers "anthropic"
    openai,  # noqa: F401  registers "openai"
)

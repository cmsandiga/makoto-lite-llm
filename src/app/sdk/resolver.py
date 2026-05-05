from app.sdk.exceptions import UnknownProviderError
from app.sdk.providers.base import PROVIDER_REGISTRY, BaseProvider


def resolve_provider(model: str) -> tuple[str, str, BaseProvider]:
    """Parse 'provider/model' and return (provider_name, bare_model, provider_instance).

    Strict: model MUST contain '/'. Bare names raise UnknownProviderError.
    """
    if "/" not in model:
        raise UnknownProviderError(
            400,
            f"Model string must be 'provider/model', got '{model}'. "
            f"Known providers: {sorted(PROVIDER_REGISTRY)}",
        )
    provider_name, _, bare_model = model.partition("/")
    cls = PROVIDER_REGISTRY.get(provider_name)
    if cls is None:
        raise UnknownProviderError(
            400,
            f"Unknown provider '{provider_name}'. Known: {sorted(PROVIDER_REGISTRY)}",
        )
    return provider_name, bare_model, cls()

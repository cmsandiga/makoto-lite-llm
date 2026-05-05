import pytest

from app.sdk.exceptions import UnknownProviderError
from app.sdk.providers.base import BaseProvider, register_provider
from app.sdk.resolver import resolve_provider


class _StubProvider(BaseProvider):
    name = "stub"

    def get_api_base(self, model, api_base): return "https://stub"
    def get_headers(self, api_key, extra_headers): return {}
    def transform_request(self, model, messages, params): return {}
    def transform_response(self, raw, model): raise NotImplementedError
    def transform_stream_chunk(self, chunk, model): return None
    def get_error_class(self, status_code, body): return RuntimeError()


def test_resolve_strict_prefix_returns_provider():
    register_provider("stub", _StubProvider)
    name, model, inst = resolve_provider("stub/super-model-v1")
    assert name == "stub"
    assert model == "super-model-v1"
    assert isinstance(inst, _StubProvider)


def test_resolve_bare_name_raises():
    with pytest.raises(UnknownProviderError, match="Model string must be"):
        resolve_provider("gpt-4o")


def test_resolve_unknown_provider_raises():
    with pytest.raises(UnknownProviderError, match="Unknown provider 'nope'"):
        resolve_provider("nope/some-model")


def test_resolve_preserves_slashes_in_model_name():
    """Provider is split on the FIRST slash only."""
    register_provider("stub", _StubProvider)
    name, model, _ = resolve_provider("stub/org/some-model:v2")
    assert name == "stub"
    assert model == "org/some-model:v2"

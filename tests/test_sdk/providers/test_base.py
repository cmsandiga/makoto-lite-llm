from app.sdk.providers.base import (
    PROVIDER_REGISTRY,
    BaseProvider,
    register_provider,
)


class _DummyProvider(BaseProvider):
    name = "dummy"

    def get_api_base(self, model, api_base):
        return api_base or "https://dummy.example.com"

    def get_headers(self, api_key, extra_headers):
        return {"Authorization": f"Bearer {api_key}"}

    def transform_request(self, model, messages, params):
        return {"model": model, "messages": messages}

    def transform_response(self, raw, model):
        raise NotImplementedError

    def transform_stream_chunk(self, chunk, model):
        return None

    def get_error_class(self, status_code, body):
        return RuntimeError(f"{status_code}: {body}")


def test_register_and_lookup():
    register_provider("dummy", _DummyProvider)
    assert PROVIDER_REGISTRY["dummy"] is _DummyProvider
    # Can construct an instance
    inst = _DummyProvider()
    assert inst.name == "dummy"
    assert inst.get_api_base("foo", None) == "https://dummy.example.com"


def test_baseprovider_is_abstract():
    """Cannot instantiate BaseProvider directly — abstract methods unimplemented."""
    import pytest

    with pytest.raises(TypeError):
        BaseProvider()

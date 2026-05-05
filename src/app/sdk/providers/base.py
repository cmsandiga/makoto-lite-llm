from abc import ABC, abstractmethod

from app.sdk.types import ModelResponse, ModelResponseStream


class BaseProvider(ABC):
    """All providers implement this interface.

    Stateless. Receives bare model names ('gpt-4o'), not 'openai/gpt-4o'.
    """

    name: str

    @abstractmethod
    def get_api_base(self, model: str, api_base: str | None) -> str: ...

    @abstractmethod
    def get_headers(self, api_key: str, extra_headers: dict | None) -> dict: ...

    @abstractmethod
    def transform_request(
        self, model: str, messages: list[dict], params: dict
    ) -> dict: ...

    @abstractmethod
    def transform_response(self, raw: dict, model: str) -> ModelResponse: ...

    @abstractmethod
    def transform_stream_chunk(
        self, chunk: dict, model: str
    ) -> ModelResponseStream | None: ...

    @abstractmethod
    def get_error_class(self, status_code: int, body: dict) -> Exception: ...


PROVIDER_REGISTRY: dict[str, type[BaseProvider]] = {}


def register_provider(name: str, provider_class: type[BaseProvider]) -> None:
    PROVIDER_REGISTRY[name] = provider_class

import pytest

from app.sdk.exceptions import (
    AuthenticationError,
    BadRequestError,
    ContentPolicyViolationError,
    ContextWindowExceededError,
    InternalServerError,
    LiteLLMError,
    NotFoundError,
    RateLimitError,
    ServiceUnavailableError,
    TimeoutError,
    UnknownProviderError,
)


def test_litellm_error_str_format():
    err = LiteLLMError(401, "bad key")
    assert str(err) == "[401] bad key"
    assert err.status_code == 401
    assert err.message == "bad key"


@pytest.mark.parametrize(
    "cls",
    [
        AuthenticationError,
        RateLimitError,
        BadRequestError,
        NotFoundError,
        ContentPolicyViolationError,
        ContextWindowExceededError,
        InternalServerError,
        TimeoutError,
        ServiceUnavailableError,
        UnknownProviderError,
    ],
)
def test_subclasses_inherit_from_litellm_error(cls):
    err = cls(400, "x")
    assert isinstance(err, LiteLLMError)
    assert err.status_code == 400
    assert err.message == "x"

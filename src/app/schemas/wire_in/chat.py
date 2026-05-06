from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    """One message in the conversation.

    Permissive on extras so tool-result and multimodal shapes pass through;
    the SDK's per-provider transform_request handles the actual wire format.
    """

    model_config = ConfigDict(extra="allow")

    role: str
    content: str | list[dict] | None = None


class ChatCompletionRequest(BaseModel):
    """OpenAI-shape /v1/chat/completions request body.

    Permissive on top-level extras — OpenAI ships new fields constantly,
    and we don't want to fail requests at the proxy boundary. The SDK's
    per-provider _FORWARDED_PARAMS allowlist controls what's actually sent
    upstream.
    """

    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[ChatMessage] = Field(min_length=1)

    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stream: bool = False
    stop: str | list[str] | None = None
    user: str | None = None

    tools: list[dict] | None = None
    tool_choice: str | dict | None = None

    response_format: dict | None = None
    seed: int | None = None
    n: int | None = None

    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    logit_bias: dict | None = None
    logprobs: bool | None = None
    top_logprobs: int | None = None
    stream_options: dict | None = None

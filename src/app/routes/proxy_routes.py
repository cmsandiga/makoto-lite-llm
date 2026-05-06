import json
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_extensions import uuid7

from app.auth.dependencies import get_current_api_key, get_current_user
from app.config import settings
from app.database import get_db
from app.models.api_key import ApiKey
from app.models.organization import Organization
from app.models.team import Team
from app.models.user import User
from app.schemas.wire_in.chat import ChatCompletionRequest
from app.sdk import LiteLLMError, ModelResponse, StreamWrapper, acompletion
from app.sdk.cost import calculate_cost
from app.services.proxy_guard import (
    check_budget,
    check_rate_limit,
    enforce_model_access,
    estimate_input_tokens,
    map_sdk_error,
    resolve_provider_api_key,
)
from app.services.spend_service import log_spend

router = APIRouter(prefix="/v1", tags=["proxy"])


@router.post("/chat/completions", response_model=None)
async def chat_completions(
    body: ChatCompletionRequest,
    response: Response,
    user: User = Depends(get_current_user),
    api_key: ApiKey | None = Depends(get_current_api_key),
    db: AsyncSession = Depends(get_db),
) -> ModelResponse | StreamingResponse:
    """OpenAI-compatible chat completion endpoint.

    Pipeline (per CLAUDE.md):
        authenticate -> rate limit -> budget -> model access -> dispatch -> spend log
    """
    request_id = f"req-{uuid7().hex}"
    response.headers["X-Request-Id"] = request_id
    started_at = time.time()

    # Resolve team/org for the model-access check
    team: Team | None = None
    org: Organization | None = None
    if api_key:
        if api_key.team_id:
            team = await db.get(Team, api_key.team_id)
        if api_key.org_id:
            org = await db.get(Organization, api_key.org_id)

    # Guard chain (only enforced for sk- API key auth; JWT users bypass key-level checks).
    # proxy_admin users bypass model-access/rate-limit/budget even when using an sk- key.
    if api_key and user.role != "proxy_admin":
        enforce_model_access(body.model, api_key, team, org)
        estimated = estimate_input_tokens(body.messages)
        await check_rate_limit(api_key, estimated)
        await check_budget(db, api_key)

    # Resolve upstream provider key + model parts (used by both streaming + non-streaming)
    provider_name = body.model.split("/", 1)[0] if "/" in body.model else ""
    bare_model = body.model.split("/", 1)[1] if "/" in body.model else body.model
    upstream_key = resolve_provider_api_key(provider_name, settings)

    # Forwarded params (used by both branches)
    forwarded = body.model_dump(
        exclude={"model", "messages", "stream"},
        exclude_none=True,
    )

    if body.stream:
        try:
            wrapper = await acompletion(
                model=body.model,
                messages=[m.model_dump() for m in body.messages],
                api_key=upstream_key,
                stream=True,
                **forwarded,
            )
        except LiteLLMError as exc:
            status, error_body = map_sdk_error(exc)
            raise HTTPException(status_code=status, detail=error_body) from exc

        assert isinstance(wrapper, StreamWrapper)

        async def _sse_generator() -> AsyncIterator[str]:
            last_usage = None
            finish_reason: str | None = None
            try:
                async for chunk in wrapper:
                    if chunk.usage:
                        last_usage = chunk.usage
                    if chunk.choices and chunk.choices[0].finish_reason:
                        finish_reason = chunk.choices[0].finish_reason
                    yield (
                        f"data: {chunk.model_dump_json(exclude_none=True)}\n\n"
                    )
                yield "data: [DONE]\n\n"
            except LiteLLMError as exc:
                _, error_body = map_sdk_error(exc)
                yield f"data: {json.dumps(error_body)}\n\n"
                yield "data: [DONE]\n\n"
            finally:
                elapsed_ms = int((time.time() - started_at) * 1000)
                cost = (
                    calculate_cost(body.model, last_usage)
                    if last_usage
                    else None
                )
                await log_spend(
                    db,
                    request_id=request_id,
                    api_key_hash=api_key.api_key_hash if api_key else "",
                    model=bare_model,
                    provider=provider_name,
                    input_tokens=last_usage.prompt_tokens if last_usage else 0,
                    output_tokens=last_usage.completion_tokens
                    if last_usage
                    else 0,
                    spend=cost or 0.0,
                    status="completed" if finish_reason else "partial",
                    response_time_ms=elapsed_ms,
                    user_id=user.id if user else None,
                    team_id=api_key.team_id if api_key else None,
                    org_id=api_key.org_id if api_key else None,
                )

        return StreamingResponse(
            _sse_generator(),
            media_type="text/event-stream",
            headers={"X-Request-Id": request_id},
        )

    # Non-streaming dispatch
    try:
        sdk_response = await acompletion(
            model=body.model,
            messages=[m.model_dump() for m in body.messages],
            api_key=upstream_key,
            **forwarded,
        )
    except LiteLLMError as exc:
        status, error_body = map_sdk_error(exc)
        raise HTTPException(status_code=status, detail=error_body) from exc

    # Type narrowing: non-streaming returns ModelResponse, not StreamWrapper
    assert isinstance(sdk_response, ModelResponse)

    # Spend log
    elapsed_ms = int((time.time() - started_at) * 1000)
    usage = sdk_response.usage
    cost = usage.cost if usage else None
    await log_spend(
        db,
        request_id=request_id,
        api_key_hash=api_key.api_key_hash if api_key else "",
        model=bare_model,
        provider=provider_name,
        input_tokens=usage.prompt_tokens if usage else 0,
        output_tokens=usage.completion_tokens if usage else 0,
        spend=cost or 0.0,
        status="completed",
        response_time_ms=elapsed_ms,
        user_id=user.id if user else None,
        team_id=api_key.team_id if api_key else None,
        org_id=api_key.org_id if api_key else None,
    )

    return sdk_response

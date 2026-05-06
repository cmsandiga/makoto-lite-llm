from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import fastapi.exception_handlers
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.routes.auth_routes import router as auth_router
from app.routes.budget_routes import router as budget_router
from app.routes.key_routes import router as key_router
from app.routes.org_routes import router as org_router
from app.routes.proxy_routes import router as proxy_router
from app.routes.sso_routes import router as sso_router
from app.routes.team_routes import router as team_router
from app.routes.user_routes import router as user_router
from app.schemas.wire_out.common import HealthResponse


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    yield
    # Shutdown: close pooled HTTP clients used by the SDK
    from app.sdk.http_client import get_http_client

    await get_http_client().aclose_all()


app = FastAPI(
    title=settings.app_name,
    description="Unified LLM proxy gateway",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(HTTPException)
async def openai_shape_error_handler(request: Request, exc: HTTPException):
    """OpenAI-shape error envelope for /v1/* routes; default for the rest.

    The proxy_guard helpers raise HTTPException with detail set to either
    a string (which we wrap as `{message, type, code: None}`) or a dict
    that already contains the OpenAI-shape error body (from map_sdk_error).
    """
    if not request.url.path.startswith("/v1/"):
        return await fastapi.exception_handlers.http_exception_handler(request, exc)

    if isinstance(exc.detail, dict) and "error" in exc.detail:
        # map_sdk_error produced {"error": {...}}; pass through
        body = exc.detail
    elif isinstance(exc.detail, dict):
        body = {"error": exc.detail}
    else:
        body = {
            "error": {
                "message": str(exc.detail),
                "type": "api_error",
                "code": None,
            }
        }
    return JSONResponse(
        status_code=exc.status_code,
        content=body,
        headers=exc.headers or {},
    )


app.include_router(auth_router)
app.include_router(user_router)
app.include_router(org_router)
app.include_router(team_router)
app.include_router(key_router)
app.include_router(budget_router)
app.include_router(sso_router)
app.include_router(proxy_router)


@app.get("/health")
async def health() -> HealthResponse:
    return HealthResponse()

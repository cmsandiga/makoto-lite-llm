from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.routes.auth_routes import router as auth_router
from app.routes.user_routes import router as user_router
from app.schemas.wire_out.common import HealthResponse


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup: DB y Redis connections se inicializarán aquí en olas futuras
    yield
    # Shutdown: cierre de conexiones aquí en olas futuras


app = FastAPI(
    title=settings.app_name,
    description="Unified LLM proxy gateway",
    version="0.1.0",
    lifespan=lifespan,
)


app.include_router(auth_router)
app.include_router(user_router)


@app.get("/health")
async def health() -> HealthResponse:
    return HealthResponse()

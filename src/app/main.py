from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.routes.auth_routes import router as auth_router
from app.routes.budget_routes import router as budget_router
from app.routes.key_routes import router as key_router
from app.routes.org_routes import router as org_router
from app.routes.sso_routes import router as sso_router
from app.routes.team_routes import router as team_router
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
app.include_router(org_router)
app.include_router(team_router)
app.include_router(key_router)
app.include_router(budget_router)
app.include_router(sso_router)


@app.get("/health")
async def health() -> HealthResponse:
    return HealthResponse()

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings


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


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

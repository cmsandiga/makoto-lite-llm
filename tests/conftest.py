import asyncio
import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

from app.database import get_db
from app.main import app
from app.models import Base

# Required for testcontainers with Colima (macOS only)
import sys

if sys.platform == "darwin":
    os.environ.setdefault(
        "DOCKER_HOST", "unix:///Users/makoto.sandiga/.colima/default/docker.sock"
    )
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")


@pytest.fixture(scope="session")
def postgres_container():
    with PostgresContainer("postgres:15-alpine") as container:
        yield container


@pytest.fixture(scope="session")
def redis_container():
    with RedisContainer("redis:7-alpine") as container:
        yield container


@pytest.fixture(scope="session")
def db_engine(postgres_container) -> AsyncEngine:
    url = postgres_container.get_connection_url().replace("psycopg2", "asyncpg")
    engine = create_async_engine(url, poolclass=NullPool)

    async def create_tables() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(create_tables())
    yield engine

    async def drop_tables() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()

    asyncio.run(drop_tables())


@pytest.fixture
async def db_session(db_engine: AsyncEngine):
    # Open a real connection and start a transaction we will ALWAYS roll back.
    # Inside the test, session.commit() hits a SAVEPOINT (nested transaction),
    # so the data is visible within the test but never persists to the DB.
    async with db_engine.connect() as conn:
        txn = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)

        # Make session.commit() create/release SAVEPOINTs instead of real commits
        @event.listens_for(session.sync_session, "after_transaction_end")
        def restart_savepoint(session_sync, transaction):
            if transaction.nested and not transaction._parent.nested:
                session_sync.begin_nested()

        await session.begin_nested()  # first SAVEPOINT
        yield session
        await session.close()
        await txn.rollback()


@pytest.fixture
async def client(db_session: AsyncSession):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()

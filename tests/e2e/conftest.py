"""E2E fixtures — Keycloak, uvicorn app server, real DB session, realm import.

Activated only via `pytest -m e2e` per the addopts in pyproject.toml.
"""

import asyncio
import os
import socket
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
import uvicorn
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from testcontainers.keycloak import KeycloakContainer

# Same Colima override pattern as the top-level conftest.
if sys.platform == "darwin":
    os.environ.setdefault(
        "DOCKER_HOST", "unix:///Users/makoto.sandiga/.colima/default/docker.sock"
    )
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

REALM_FIXTURE = (
    Path(__file__).parent / "fixtures" / "litellm-realm.json"
).resolve()


@pytest.fixture(scope="session")
def keycloak_container():
    """Boot Keycloak 24 with the litellm realm pre-imported.

    Mounts the realm JSON via testcontainers' built-in helper; the
    container's start command auto-appends --import-realm because
    `has_realm_imports` is set. Requires Colima to share the path
    (see ~/.colima/default/colima.yaml `mounts:`).
    """
    container = KeycloakContainer(
        "quay.io/keycloak/keycloak:24.0"
    ).with_realm_import_file(str(REALM_FIXTURE))
    with container as started:
        yield started


@pytest.fixture(scope="session")
def keycloak_issuer_url(keycloak_container) -> str:
    """URL of the imported litellm realm."""
    base = keycloak_container.get_url().rstrip("/")
    return f"{base}/realms/litellm"


def _reserve_free_port() -> int:
    """Bind to 127.0.0.1:0, read the assigned port, release the socket."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="session")
def app_server(postgres_container):
    """Start uvicorn in a background thread; yield the base URL.

    Depends on postgres_container so the app's engine has a reachable DB.
    Patches `app.database.engine` + `AsyncSessionLocal` to point at the
    testcontainer; restores them on teardown.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app import database
    from app.config import settings
    from app.main import app
    from app.models import Base

    pg_url = postgres_container.get_connection_url().replace("psycopg2", "asyncpg")
    new_engine = create_async_engine(pg_url, echo=False, poolclass=NullPool)
    new_sessionmaker = async_sessionmaker(new_engine, expire_on_commit=False)
    old_engine = database.engine
    old_sessionmaker = database.AsyncSessionLocal
    database.engine = new_engine
    database.AsyncSessionLocal = new_sessionmaker

    async def _create() -> None:
        async with new_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create())

    port = _reserve_free_port()
    base_url = f"http://127.0.0.1:{port}"
    old_base_url = settings.base_url
    settings.base_url = base_url
    # Point the post-SSO dashboard redirect at our own /health so the
    # browser navigation succeeds (default is localhost:3000 which is
    # not running in tests). The query string carries the JWTs we
    # assert on.
    old_dashboard_url = settings.sso_dashboard_redirect_url
    settings.sso_dashboard_redirect_url = f"{base_url}/health"

    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"{base_url}/health", timeout=1)
            if r.status_code == 200:
                break
        except httpx.RequestError:
            pass
        time.sleep(0.1)
    else:
        server.should_exit = True
        raise RuntimeError("uvicorn app_server did not become ready within 10s")

    yield base_url

    server.should_exit = True
    thread.join(timeout=5)
    settings.base_url = old_base_url
    settings.sso_dashboard_redirect_url = old_dashboard_url
    database.engine = old_engine
    database.AsyncSessionLocal = old_sessionmaker

    async def _dispose() -> None:
        await new_engine.dispose()

    asyncio.run(_dispose())


@pytest.fixture
async def e2e_db_session(app_server) -> AsyncSession:
    """A real session on the app's (now-overridden) engine.

    No savepoint wrapper — commits are real. Relies on _e2e_db_cleanup
    (autouse) to TRUNCATE after each test.
    """
    from app import database

    async with database.AsyncSessionLocal() as session:
        yield session


_TABLES_TO_TRUNCATE = [
    "audit_log",
    "refresh_tokens",
    "team_memberships",
    "org_memberships",
    "sso_configs",
    "api_keys",
    "users",
    "teams",
    "organizations",
    "budgets",
]


@pytest.fixture(autouse=True)
async def _e2e_db_cleanup(app_server):
    """After each test, TRUNCATE all tables the flow touches.

    CASCADE handles FK dependencies; the order in _TABLES_TO_TRUNCATE
    is informational.
    """
    yield
    from app import database

    async with database.engine.begin() as conn:
        tables = ", ".join(_TABLES_TO_TRUNCATE)
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@dataclass
class E2ESSOOrg:
    id: uuid.UUID
    slug: str


@pytest.fixture
async def sso_org(e2e_db_session, keycloak_issuer_url) -> E2ESSOOrg:
    """Create Organization + Budget + SSOConfig pointing at the Keycloak realm.

    Returns a small value object so tests can reference the org's id/slug
    without holding onto an ORM instance (which would detach after
    session scope ends).
    """
    from app.models.budget import Budget
    from app.models.organization import Organization
    from app.services.sso_service import create_sso_config

    budget = Budget(name="sso-test-budget", max_budget=1000)
    e2e_db_session.add(budget)
    await e2e_db_session.flush()

    slug = f"sso-test-{uuid.uuid4().hex[:8]}"
    org = Organization(name="SSO Test Org", slug=slug, budget_id=budget.id)
    e2e_db_session.add(org)
    await e2e_db_session.commit()
    await e2e_db_session.refresh(org)

    await create_sso_config(
        e2e_db_session,
        org_id=org.id,
        provider="keycloak",
        client_id="app",
        client_secret="secret",
        issuer_url=keycloak_issuer_url,
        allowed_domains=["example.com"],
        group_to_team_mapping=None,
        auto_create_user=True,
        default_role="member",
    )

    return E2ESSOOrg(id=org.id, slug=slug)

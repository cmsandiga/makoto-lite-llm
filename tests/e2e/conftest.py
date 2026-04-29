"""E2E fixtures — Keycloak, uvicorn app server, real DB session, realm import.

Activated only via `pytest -m e2e` per the addopts in pyproject.toml.
"""

import os
import sys
from pathlib import Path

import pytest
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

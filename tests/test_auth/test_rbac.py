from fastapi import Depends

from app.auth.api_key_auth import generate_api_key, get_key_prefix, hash_api_key
from app.auth.dependencies import require_model_access
from app.auth.jwt_handler import create_access_token
from app.auth.password import hash_password
from app.main import app
from app.models.api_key import ApiKey
from app.models.team import Team
from app.models.user import User

# ---------- Test-only route ----------
@app.get("/test-model-access/{model_name}")
async def _test_model_access_route(
    model_name: str,
    user: User = Depends(require_model_access("model_name")),
):
    return {"model": model_name, "user_email": user.email}


# ---------- Tests ----------

async def test_api_key_model_access_allowed(client, db_session):
    """API key with allowed_models=['gpt-4','claude-*'] can access gpt-4."""
    user = User(email="model-ok@test.com", role="member")
    db_session.add(user)
    await db_session.flush()

    raw_key = generate_api_key()
    api_key = ApiKey(
        api_key_hash=hash_api_key(raw_key),
        key_prefix=get_key_prefix(raw_key),
        user_id=user.id,
        allowed_models=["gpt-4", "claude-*"],
    )
    db_session.add(api_key)
    await db_session.commit()

    response = await client.get(
        "/test-model-access/gpt-4",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 200


async def test_api_key_model_access_denied(client, db_session):
    """API key with allowed_models=['gpt-4'] cannot access llama-70b."""
    user = User(email="model-deny@test.com", role="member")
    db_session.add(user)
    await db_session.flush()

    raw_key = generate_api_key()
    api_key = ApiKey(
        api_key_hash=hash_api_key(raw_key),
        key_prefix=get_key_prefix(raw_key),
        user_id=user.id,
        allowed_models=["gpt-4"],
    )
    db_session.add(api_key)
    await db_session.commit()

    response = await client.get(
        "/test-model-access/llama-70b",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 403


async def test_jwt_proxy_admin_bypasses_model_check(client, db_session):
    """JWT-authenticated proxy_admin has no model restrictions."""
    admin = User(email="admin-model@test.com", password_hash=hash_password("pass"), role="proxy_admin")
    db_session.add(admin)
    await db_session.commit()

    token = create_access_token(user_id=admin.id, role="proxy_admin")
    response = await client.get(
        "/test-model-access/any-model",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200


async def test_api_key_inherits_team_models(client, db_session):
    """API key with no allowed_models inherits from team."""
    team = Team(name="TeamModels", allowed_models=["gpt-4"])
    db_session.add(team)
    await db_session.flush()

    user = User(email="team-inherit@test.com", role="member")
    db_session.add(user)
    await db_session.flush()

    raw_key = generate_api_key()
    api_key = ApiKey(
        api_key_hash=hash_api_key(raw_key),
        key_prefix=get_key_prefix(raw_key),
        user_id=user.id,
        team_id=team.id,
        allowed_models=None,  # inherit from team
    )
    db_session.add(api_key)
    await db_session.commit()

    # gpt-4 allowed via team
    response = await client.get(
        "/test-model-access/gpt-4",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 200

    # llama denied via team
    response = await client.get(
        "/test-model-access/llama-70b",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert response.status_code == 403

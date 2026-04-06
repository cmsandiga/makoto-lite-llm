from app.auth.jwt_handler import create_access_token
from app.auth.password import hash_password
from app.models.user import User


def _admin_headers(user_id):
    token = create_access_token(user_id=user_id, role="proxy_admin")
    return {"Authorization": f"Bearer {token}"}


async def _create_admin(db_session):
    admin = User(email="admin@test.com", password_hash=hash_password("pass"), role="proxy_admin")
    db_session.add(admin)
    await db_session.commit()
    return admin


# ========== POST /budgets — create ==========


async def test_create_budget(client, db_session):
    admin = await _create_admin(db_session)
    response = await client.post(
        "/budgets",
        json={
            "name": "Standard",
            "max_budget": 100.0,
            "soft_budget": 80.0,
            "tpm_limit": 10000,
            "rpm_limit": 100,
            "budget_reset_period": "monthly",
        },
        headers=_admin_headers(admin.id),
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Standard"
    assert data["max_budget"] == 100.0
    assert data["soft_budget"] == 80.0
    assert data["tpm_limit"] == 10000
    assert data["budget_reset_period"] == "monthly"


# ========== GET /budgets — list ==========


async def test_list_budgets(client, db_session):
    admin = await _create_admin(db_session)
    headers = _admin_headers(admin.id)
    await client.post("/budgets", json={"name": "B1"}, headers=headers)
    await client.post("/budgets", json={"name": "B2"}, headers=headers)

    response = await client.get("/budgets", headers=headers)
    assert response.status_code == 200
    assert len(response.json()) >= 2


# ========== PATCH /budgets/{budget_id} — update ==========


async def test_update_budget(client, db_session):
    admin = await _create_admin(db_session)
    headers = _admin_headers(admin.id)
    create_resp = await client.post(
        "/budgets", json={"name": "Old", "max_budget": 50.0}, headers=headers
    )
    budget_id = create_resp.json()["id"]

    response = await client.patch(
        f"/budgets/{budget_id}",
        json={"name": "New", "max_budget": 200.0},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["name"] == "New"
    assert response.json()["max_budget"] == 200.0


# ========== DELETE /budgets/{budget_id} ==========


async def test_delete_budget(client, db_session):
    admin = await _create_admin(db_session)
    headers = _admin_headers(admin.id)
    create_resp = await client.post("/budgets", json={"name": "Del"}, headers=headers)
    budget_id = create_resp.json()["id"]

    response = await client.delete(f"/budgets/{budget_id}", headers=headers)
    assert response.status_code == 204


async def test_delete_budget_not_found(client, db_session):
    admin = await _create_admin(db_session)
    response = await client.delete(
        "/budgets/00000000-0000-0000-0000-000000000000",
        headers=_admin_headers(admin.id),
    )
    assert response.status_code == 404


# ========== Auth — non-admin cannot access ==========


async def test_non_admin_cannot_create_budget(client, db_session):
    user = User(email="normie@test.com", password_hash=hash_password("pass"), role="member")
    db_session.add(user)
    await db_session.commit()

    token = create_access_token(user_id=user.id, role="member")
    response = await client.post(
        "/budgets",
        json={"name": "Nope"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403

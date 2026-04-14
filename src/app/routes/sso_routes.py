import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.crypto import decrypt
from app.auth.dependencies import require_role
from app.config import settings
from app.database import get_db
from app.exceptions import DuplicateError
from app.models.user import User
from app.schemas.wire_in.sso import SSOConfigCreate
from app.schemas.wire_out.sso import SSOConfigResponse
from app.services.auth_service import create_tokens
from app.services.oidc_client import OIDCClient
from app.services.sso_service import (
    build_authorize_url,
    create_sso_config,
    delete_sso_config,
    get_sso_config,
    map_groups_to_teams,
    provision_sso_user,
    validate_and_consume_state,
)

router = APIRouter(prefix="/sso", tags=["sso"])


def _to_response(config) -> SSOConfigResponse:
    """Convert ORM model to response. Masking handled by model_validator."""
    return SSOConfigResponse.model_validate(config)


# ========== POST /sso/config — create ==========


@router.post("/config", status_code=201)
async def create(
    body: SSOConfigCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin")),
) -> SSOConfigResponse:
    try:
        config = await create_sso_config(
            db,
            org_id=body.org_id,
            provider=body.provider,
            client_id=body.client_id,
            client_secret=body.client_secret,
            issuer_url=body.issuer_url,
            allowed_domains=body.allowed_domains,
            group_to_team_mapping=body.group_to_team_mapping,
            auto_create_user=body.auto_create_user,
            default_role=body.default_role,
        )
    except DuplicateError as e:
        raise HTTPException(status_code=409, detail=e.detail) from None
    return _to_response(config)


# ========== GET /sso/config/{org_id} — read ==========


@router.get("/config/{org_id}")
async def get_one(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin")),
) -> SSOConfigResponse:
    config = await get_sso_config(db, org_id)
    if config is None:
        raise HTTPException(status_code=404, detail="SSO config not found")
    return _to_response(config)


# ========== DELETE /sso/config/{org_id} — delete ==========


@router.delete("/config/{org_id}", status_code=204)
async def delete_config(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role("proxy_admin")),
) -> None:
    deleted = await delete_sso_config(db, org_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="SSO config not found")


# ========== GET /sso/authorize — start OAuth2 flow ==========


@router.get("/authorize")
async def authorize(
    org_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    callback_url = f"{settings.base_url}/sso/callback"
    result = await build_authorize_url(
        db, org_id=org_id, callback_url=callback_url
    )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="SSO config not found for this organization",
        )
    url, _state = result
    return RedirectResponse(url=url, status_code=307)


# ========== GET /sso/callback — OIDC token exchange ==========


@router.get("/callback")
async def callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    # 1. Validate and consume state, get PKCE verifier + org_id
    state_data = validate_and_consume_state(state)
    if state_data is None:
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired state parameter",
        )

    org_id = state_data.get("org_id")
    verifier = state_data.get("verifier")

    if org_id is None:
        raise HTTPException(
            status_code=400, detail="Invalid state — missing org context"
        )

    # 2. Look up SSO config
    config = await get_sso_config(db, org_id)
    if config is None:
        raise HTTPException(status_code=404, detail="SSO config not found")

    # 3. Exchange code for tokens
    client_secret = decrypt(config.client_secret_encrypted)
    oidc = OIDCClient(issuer_url=config.issuer_url)
    callback_url = f"{settings.base_url}/sso/callback"

    tokens = await oidc.exchange_code(
        code=code,
        redirect_uri=callback_url,
        client_id=config.client_id,
        client_secret=client_secret,
        code_verifier=verifier,
    )

    # 4. Fetch user claims
    claims = await oidc.fetch_userinfo(
        access_token=tokens["access_token"]
    )

    email = claims.get("email")
    if not email:
        raise HTTPException(
            status_code=400,
            detail="IdP did not return email claim",
        )

    # 5. Validate email domain
    if config.allowed_domains:
        email_domain = email.split("@", 1)[1] if "@" in email else ""
        if email_domain not in config.allowed_domains:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Email domain '{email_domain}' "
                    f"is not in allowed domains"
                ),
            )

    # 6. Provision user
    user = await provision_sso_user(
        db,
        email=email,
        name=claims.get("name"),
        sso_provider=config.provider,
        sso_subject=claims.get("sub", ""),
        org_id=config.org_id,
        default_role=config.default_role,
    )

    # 7. Map groups to teams
    idp_groups = claims.get("groups")
    if idp_groups and config.group_to_team_mapping:
        await map_groups_to_teams(
            db, user.id, idp_groups, config.group_to_team_mapping
        )

    # 8. Issue our own JWT pair
    jwt_tokens = await create_tokens(db, user)

    # 9. Redirect to dashboard with tokens
    redirect_url = (
        f"{settings.sso_dashboard_redirect_url}"
        f"?access_token={jwt_tokens['access_token']}"
        f"&refresh_token={jwt_tokens['refresh_token']}"
    )
    return RedirectResponse(url=redirect_url, status_code=307)

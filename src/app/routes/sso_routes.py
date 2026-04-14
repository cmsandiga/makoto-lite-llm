import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.config import settings
from app.database import get_db
from app.exceptions import DuplicateError
from app.models.user import User
from app.schemas.wire_in.sso import SSOConfigCreate
from app.schemas.wire_out.sso import SSOConfigResponse
from app.services.sso_service import (
    build_authorize_url,
    create_sso_config,
    delete_sso_config,
    get_sso_config,
    validate_state,
)

router = APIRouter(prefix="/sso", tags=["sso"])


def _mask_response(config) -> SSOConfigResponse:
    """Convert ORM model to response with client_secret masked."""
    resp = SSOConfigResponse.model_validate(config)
    resp.client_secret = "***"
    return resp


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
        raise HTTPException(status_code=409, detail=e.detail)
    return _mask_response(config)


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
    return _mask_response(config)


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
    result = await build_authorize_url(db, org_id=org_id, callback_url=callback_url)
    if result is None:
        raise HTTPException(status_code=404, detail="SSO config not found for this organization")
    url, _state = result
    return RedirectResponse(url=url, status_code=307)


# ========== GET /sso/callback — stub ==========


@router.get("/callback")
async def callback(
    code: str = Query(...),
    state: str = Query(...),
) -> None:
    if not validate_state(state):
        raise HTTPException(status_code=400, detail="Invalid or expired state parameter")
    raise HTTPException(status_code=501, detail="OIDC token exchange not yet implemented")

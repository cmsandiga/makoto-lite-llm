from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.wire_in.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    RefreshRequest,
    ResetPasswordRequest,
)
from app.schemas.wire_out.auth import TokenResponse
from app.schemas.wire_out.common import (
    LogoutAllResponse,
    StatusMessageResponse,
    StatusResponse,
)
from app.services.auth_service import (
    authenticate_user,
    create_password_reset_token,
    create_tokens,
    refresh_tokens,
    revoke_all_user_tokens,
    revoke_refresh_token,
    reset_password_with_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


# ========== Login ==========


@router.post("/login")
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    user = await authenticate_user(db, body.email, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if user.is_blocked:
        raise HTTPException(status_code=403, detail="User is blocked")
    tokens = await create_tokens(db, user)
    return TokenResponse(**tokens)


# ========== Refresh ==========


@router.post("/refresh")
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    tokens = await refresh_tokens(db, body.refresh_token)
    if tokens is None:
        raise HTTPException(
            status_code=401, detail="Invalid or expired refresh token"
        )
    return TokenResponse(**tokens)


# ========== Logout ==========


@router.post("/logout")
async def logout(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> StatusResponse:
    await revoke_refresh_token(db, body.refresh_token)
    return StatusResponse()


@router.post("/logout-all")
async def logout_all(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> LogoutAllResponse:
    count = await revoke_all_user_tokens(db, user.id)
    return LogoutAllResponse(revoked_count=count)


# ========== Password Reset ==========


@router.post("/forgot-password")
async def forgot_password(
    body: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)
) -> StatusMessageResponse:
    await create_password_reset_token(db, body.email)
    return StatusMessageResponse(
        message="If the email exists, a reset link has been sent"
    )


@router.post("/reset-password")
async def reset_password(
    body: ResetPasswordRequest, db: AsyncSession = Depends(get_db)
) -> StatusResponse:
    success = await reset_password_with_token(db, body.token, body.new_password)
    if not success:
        raise HTTPException(
            status_code=400, detail="Invalid or expired reset token"
        )
    return StatusResponse()

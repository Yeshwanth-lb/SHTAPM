"""``/api/auth`` — login/refresh/logout (P4-M2 · Doc05 §05.7).

Login failures are uniformly a generic 401 regardless of cause (unknown
email, wrong password, inactive user) — Doc06 P2-AUTH-S1: no user
enumeration.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.deps import get_auth_settings, get_current_user
from app.core.config import AuthSettings
from app.core.db import get_db
from app.models import User
from app.services.auth_service import (
    IssuedTokens,
    RefreshTokenInvalid,
    authenticate_user,
    issue_tokens,
    record_login,
    revoke_refresh_token,
    rotate_refresh_token,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginRequest(_Body):
    email: str
    password: str


class RefreshRequest(_Body):
    refresh_token: str


class LogoutRequest(_Body):
    refresh_token: str


class TokenResponse(_Body):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


def _to_response(tokens: IssuedTokens) -> TokenResponse:
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_type=tokens.token_type,
    )


@router.post("/login", response_model=TokenResponse)
def login(
    body: LoginRequest,
    db: Session = Depends(get_db),
    settings: AuthSettings = Depends(get_auth_settings),
) -> TokenResponse:
    user = authenticate_user(db, body.email, body.password, settings)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid email or password")
    record_login(db, user)
    return _to_response(issue_tokens(db, user, settings))


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    body: RefreshRequest,
    db: Session = Depends(get_db),
    settings: AuthSettings = Depends(get_auth_settings),
) -> TokenResponse:
    try:
        tokens = rotate_refresh_token(db, body.refresh_token, settings)
    except RefreshTokenInvalid as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid refresh token") from exc
    return _to_response(tokens)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def logout(
    body: LogoutRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    revoke_refresh_token(db, body.refresh_token, current_user.id)

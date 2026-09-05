"""``/api/users`` — admin user management (P4-M4 · Doc05 §05.7/§05.2).

PATCH exposes only what Doc05's ``users`` table describes as admin-editable
(``full_name``, ``role``, ``is_active``). Doc05 has no password-reset
endpoint anywhere — this module does not invent one.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_auth_settings, require_role
from app.core.config import AuthSettings
from app.core.db import get_db
from app.core.security import hash_password
from app.models import User
from app.models.enums import UserRole

router = APIRouter(prefix="/api/users", tags=["users"])


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserOut(_Body):
    id: str
    email: str
    full_name: str | None
    role: UserRole
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


class UserCreate(_Body):
    email: EmailStr
    password: str
    full_name: str | None = None
    role: UserRole


class UserUpdate(_Body):
    full_name: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None


def _to_user_out(user: User) -> UserOut:
    return UserOut(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


@router.get("", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    _admin: object = Depends(require_role(UserRole.admin)),
) -> list[UserOut]:
    return [_to_user_out(u) for u in db.query(User).all()]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreate,
    db: Session = Depends(get_db),
    _admin: object = Depends(require_role(UserRole.admin)),
    settings: AuthSettings = Depends(get_auth_settings),
) -> UserOut:
    user = User(
        email=body.email,
        password_hash=hash_password(body.password, settings),
        full_name=body.full_name,
        role=body.role,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "email already registered") from exc
    db.refresh(user)
    return _to_user_out(user)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: str,
    body: UserUpdate,
    db: Session = Depends(get_db),
    _admin: object = Depends(require_role(UserRole.admin)),
) -> UserOut:
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found") from exc
    user = db.query(User).filter(User.id == user_uuid).one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return _to_user_out(user)

"""Auth/RBAC FastAPI dependencies (P4-M2 · Doc05 §05.6).

Authorization always re-checks the DB ``User.role``/``is_active``, never
trusts the JWT's own ``role`` claim alone — the claim is carried for
client/frontend convenience only.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import AuthSettings
from app.core.db import get_db
from app.core.security import TokenError, decode_access_token
from app.models import Device, User
from app.models.enums import UserRole
from app.services.audit import record as record_audit

_bearer = HTTPBearer(auto_error=False)


def get_auth_settings(request: Request) -> AuthSettings:
    return request.app.state.auth_settings


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
    settings: AuthSettings = Depends(get_auth_settings),
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    try:
        claims = decode_access_token(credentials.credentials, settings)
    except TokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token") from exc
    try:
        user_id = uuid.UUID(claims.sub)
    except ValueError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "malformed token subject") from exc
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user no longer active")
    return user


def require_role(*allowed: UserRole) -> Callable[..., User]:
    """RBAC dependency factory. A denial is audited (PRD requirement) before
    the 403 is raised — see Doc06 P4-AUTH-S2."""

    def _checker(
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if user.role not in allowed:
            record_audit(
                db,
                user_id=user.id,
                action="rbac_denied",
                detail={
                    "required_roles": [r.value for r in allowed],
                    "actual_role": user.role.value,
                },
            )
            raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient role")
        return user

    return _checker


def require_device_access(db: Session, current_user: User, device_id: str) -> Device:
    """Fetch a device by its wire ``device_id`` (not the internal UUID PK —
    every other part of the system, MQTT topics and WS ``?device_id=``
    filtering included, keys off this string) and app-level-scope it
    (Doc05 §05.6): admins see every device; anyone else only their own.

    A device that exists but isn't owned by the caller is reported
    identically to one that doesn't exist at all (404, never 403) — this is
    the RLS "empty, not error" behavior (Doc06 P2 test), done at the app
    layer since DB-level RLS is a deferred follow-up (see P4 plan).
    """
    device = db.query(Device).filter(Device.device_id == device_id).one_or_none()
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "device not found")
    if current_user.role != UserRole.admin and device.owner_user_id != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "device not found")
    return device


def scope_devices_query(query, current_user: User):
    """Apply the same ownership scoping as ``require_device_access`` to a
    list query (``GET /api/devices``, ``GET /api/alerts``)."""
    if current_user.role == UserRole.admin:
        return query
    return query.filter(Device.owner_user_id == current_user.id)

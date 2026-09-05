"""Dev admin-user seed (P4-M2).

Idempotent (re-running with the same email is a no-op). Password is read
from ``SEED_ADMIN_PASSWORD`` — never hardcoded, never logged. Intended for
local/offline demo bring-up, not production provisioning.

    PYTHONPATH=backend python -m app.core.seed
"""

from __future__ import annotations

import os

from sqlalchemy.orm import Session

from app.core.config import AuthSettings, DatabaseSettings
from app.core.db import make_engine, make_session_factory
from app.core.security import hash_password
from app.models import User
from app.models.enums import UserRole


def seed_admin(db: Session, settings: AuthSettings) -> User:
    email = os.environ.get("SEED_ADMIN_EMAIL", "admin@shtapm.local")
    existing = db.query(User).filter(User.email == email).one_or_none()
    if existing is not None:
        return existing

    password = os.environ.get("SEED_ADMIN_PASSWORD")
    if not password:
        raise RuntimeError("SEED_ADMIN_PASSWORD is required to seed the admin user")

    admin = User(
        email=email,
        password_hash=hash_password(password, settings),
        full_name="Admin",
        role=UserRole.admin,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


def main() -> None:
    db_settings = DatabaseSettings.from_env()
    auth_settings = AuthSettings.from_env()
    engine = make_engine(db_settings.url)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        admin = seed_admin(db, auth_settings)
        print(f"admin user ready: {admin.email}")


if __name__ == "__main__":
    main()

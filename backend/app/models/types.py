"""Shared portable column-type aliases (P4).

``Uuid`` renders as native ``UUID`` on Postgres and a portable fallback
(``CHAR(32)``) elsewhere, so the same models create real tables on both
Postgres (prod, Alembic) and SQLite (hardware/DB-free unit tests) — the
testing strategy agreed for P4 (no Docker/Postgres available in this
sandbox; see ``db_integration`` marker in ``pyproject.toml``).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from sqlalchemy import Uuid
from sqlalchemy.orm import mapped_column

UUIDPk = Annotated[uuid.UUID, mapped_column(Uuid, primary_key=True, default=uuid.uuid4)]

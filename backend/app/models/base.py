"""Declarative base for all SHTAPM ORM models (P4).

One shared ``Base`` so ``Base.metadata`` sees every table for Alembic
autogenerate and for ``create_all()`` in tests.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass

"""DatabaseSettings — URL resolution.

The bug this pins: .env.example carried the database password TWICE — once as
POSTGRES_PASSWORD (which initialises the container) and once inside a literal
DATABASE_URL (which the backend authenticates with) — kept in step only by a
comment. Setting one and not the other produced

    psycopg.OperationalError: FATAL: password authentication failed for user "shtapm"

which reads as a database fault rather than a config typo. Composing the URL
from the same variables Compose uses makes the two incapable of disagreeing.
"""

from __future__ import annotations

import pytest
from app.core.config import DatabaseSettings

BASE = {
    "POSTGRES_USER": "shtapm",
    "POSTGRES_PASSWORD": "s3cret",
    "POSTGRES_HOST": "localhost",
    "POSTGRES_PORT": "5432",
    "POSTGRES_DB": "shtapm",
}


# ---------------------------------------------------------------------------
# Explicit DATABASE_URL still wins (backwards compatibility)
# ---------------------------------------------------------------------------


def test_explicit_database_url_is_used_verbatim():
    settings = DatabaseSettings.from_env(env={"DATABASE_URL": "postgresql+psycopg://a:b@h:1/d"})
    assert settings.url == "postgresql+psycopg://a:b@h:1/d"


def test_sqlite_urls_still_work_for_tests():
    assert DatabaseSettings.from_env(env={"DATABASE_URL": "sqlite://"}).url == "sqlite://"


def test_explicit_url_wins_over_the_postgres_parts():
    settings = DatabaseSettings.from_env(env={**BASE, "DATABASE_URL": "sqlite://"})
    assert settings.url == "sqlite://"


# ---------------------------------------------------------------------------
# Composition from the POSTGRES_* parts
# ---------------------------------------------------------------------------


def test_composes_the_url_when_database_url_is_absent():
    assert (
        DatabaseSettings.from_env(env=BASE).url
        == "postgresql+psycopg://shtapm:s3cret@localhost:5432/shtapm"
    )


def test_composed_url_uses_the_same_password_as_the_container():
    """The whole point: one variable feeds both, so they cannot drift."""
    env = {**BASE, "POSTGRES_PASSWORD": "matching-password"}
    assert "matching-password" in DatabaseSettings.from_env(env=env).url


def test_host_defaults_to_localhost_not_the_compose_service_name():
    env = {k: v for k, v in BASE.items() if k != "POSTGRES_HOST"}
    assert "@localhost:" in DatabaseSettings.from_env(env=env).url


def test_special_characters_in_the_password_are_percent_encoded():
    """An unescaped @ or / silently redirects the URL to a different host or
    database instead of failing — the worst kind of config bug."""
    env = {**BASE, "POSTGRES_PASSWORD": "p@ss/w:rd#1"}
    url = DatabaseSettings.from_env(env=env).url
    assert "p%40ss%2Fw%3Ard%231" in url
    assert url.endswith("@localhost:5432/shtapm")  # host/db not corrupted


# ---------------------------------------------------------------------------
# The placeholder must fail loudly, not as a database error
# ---------------------------------------------------------------------------


def test_placeholder_inside_database_url_is_rejected_with_a_clear_message():
    with pytest.raises(RuntimeError, match="CHANGE_ME"):
        DatabaseSettings.from_env(
            env={"DATABASE_URL": "postgresql+psycopg://shtapm:CHANGE_ME@db:5432/shtapm"}
        )


def test_placeholder_in_postgres_password_is_rejected():
    with pytest.raises(RuntimeError, match="CHANGE_ME"):
        DatabaseSettings.from_env(env={**BASE, "POSTGRES_PASSWORD": "CHANGE_ME"})


def test_missing_password_names_both_ways_to_fix_it():
    with pytest.raises(RuntimeError) as exc:
        DatabaseSettings.from_env(env={"POSTGRES_USER": "shtapm"})
    message = str(exc.value)
    assert "DATABASE_URL" in message
    assert "POSTGRES_PASSWORD" in message


def test_errors_never_echo_the_password():
    """Config errors are logged and shown; they must not carry the secret."""
    with pytest.raises(RuntimeError) as exc:
        DatabaseSettings.from_env(env={**BASE, "POSTGRES_PASSWORD": "CHANGE_ME"})
    assert "s3cret" not in str(exc.value)

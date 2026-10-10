"""Shared fixtures.

Database tests need a disposable PostgreSQL 13+ server.  Set
``INFLECTION_TEST_DSN`` (for example ``postgresql://postgres@localhost:5432/postgres``);
each test gets a fresh database with the migrations applied.  Without the
variable those tests are skipped, never faked.
"""

import os
import uuid
from pathlib import Path

import pytest

MIGRATIONS = sorted((Path(__file__).parent.parent / "db" / "migrations").glob("*.sql"))


@pytest.fixture
def db():
    dsn = os.environ.get("INFLECTION_TEST_DSN")
    if not dsn:
        pytest.skip("INFLECTION_TEST_DSN not set")
    import psycopg
    name = f"inflection_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    test_dsn = psycopg.conninfo.make_conninfo(dsn, dbname=name)
    try:
        with psycopg.connect(test_dsn, autocommit=True) as conn:
            for m in MIGRATIONS:
                conn.execute(m.read_text())
            yield conn
    finally:
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')

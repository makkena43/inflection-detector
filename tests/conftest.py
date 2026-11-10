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
            # 0043 indexes two tables of the MakroGraph reference schema, which lives outside these migrations:
            # stand-ins for the migrations, dropped afterwards (tests that need the schema create it themselves)
            conn.execute("CREATE SCHEMA makrograph_ref")
            for t in ("mg_company_capabilities", "mg_company_product_roles"):
                conn.execute(f"CREATE TABLE makrograph_ref.{t} (ticker text, as_of_date date)")
            for m in MIGRATIONS:
                conn.execute(m.read_text())
            conn.execute("DROP SCHEMA makrograph_ref CASCADE")
            yield conn
    finally:
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')

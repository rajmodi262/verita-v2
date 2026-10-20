"""The least-privilege PostgreSQL role the API and the worker connect as (M6.02, M9.13).

Migrations run as the database owner. The application connects as a separate login role that
may read and write ordinary tables but can only SELECT and INSERT the evidentiary ones, and owns
nothing — so it can neither UPDATE/DELETE the ledger nor drop or disable the append-only trigger.
That is defence in depth behind the trigger itself: a compromised API process cannot rewrite
history even with arbitrary SQL.
"""

from __future__ import annotations

import re

from sqlalchemy import Connection, Engine, text

# Written once, never changed: the case ledger, the audit trail and the MLRO signatures.
APPEND_ONLY_TABLES = ("case_events", "audit_log", "signatures")

_ROLE_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _quoted(conn: Connection, template: str, *args: str) -> str:
    """Build a DDL statement with Postgres doing the quoting (%I identifiers, %L literals)."""
    params = {f"a{i}": a for i, a in enumerate(args)}
    placeholders = ", ".join(f"CAST(:a{i} AS text)" for i in range(len(args)))
    return str(conn.execute(text(f"SELECT format('{template}', {placeholders})"), params).scalar())


def grant_app_role(engine: Engine, role: str, password: str) -> None:
    """Create or update ROLE with LOGIN and the application's privileges. Idempotent."""
    if engine.dialect.name != "postgresql":
        raise ValueError("an application role only applies to PostgreSQL")
    if not _ROLE_NAME.fullmatch(role):
        raise ValueError(f"invalid role name: {role!r}")
    if len(password) < 16:  # noqa: PLR2004 - documented minimum
        raise ValueError("the application role password must be at least 16 characters")
    with engine.begin() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}
        ).scalar()
        verb = "ALTER" if exists else "CREATE"
        conn.execute(text(_quoted(conn, f"{verb} ROLE %I WITH LOGIN PASSWORD %L", role, password)))
        database = str(conn.execute(text("SELECT current_database()")).scalar())
        for template, args in (
            ("GRANT CONNECT ON DATABASE %I TO %I", (database, role)),
            ("GRANT USAGE ON SCHEMA public TO %I", (role,)),
            (
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO %I",
                (role,),
            ),
            ("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO %I", (role,)),
        ):
            conn.execute(text(_quoted(conn, template, *args)))
        for table in APPEND_ONLY_TABLES:
            conn.execute(
                text(_quoted(conn, "REVOKE UPDATE, DELETE, TRUNCATE ON %I FROM %I", table, role))
            )

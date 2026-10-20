"""Engine and session factory."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import ConnectionPoolEntry, StaticPool


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        in_memory = ":memory:" in url or url.endswith("://")
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool if in_memory else None,
        )

        @event.listens_for(engine, "connect")
        def _enable_fk(dbapi_conn: DBAPIConnection, _record: ConnectionPoolEntry) -> None:
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine
    # The API serves sync routes from a 40-thread pool; 5 + 10 connections made requests queue
    # for a connection under load.
    return create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=20, pool_timeout=10)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Yield a session; commit on success, roll back on error."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def transaction(factory: sessionmaker[Session]) -> Iterator[Session]:
    """``with transaction(factory) as db:`` — commits even when the block returns early.

    Scripts must use this rather than iterating :func:`session_scope`: a ``return`` inside
    ``for db in session_scope(...)`` closes the generator at its ``yield`` and the commit after
    it never runs (that silently discarded every CLI write until it was caught).
    """
    yield from session_scope(factory)

"""transaction(): commit on early return, roll back on error (regression for the CLI bug)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from verita.db.base import Base
from verita.db.models import Role, User
from verita.db.session import make_engine, make_session_factory, session_scope, transaction


@pytest.fixture
def factory():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)


def _user(name: str) -> User:
    return User(username=name, password_hash="x", role=Role.ANALYST)


def _names(factory) -> list[str]:
    with factory() as db:
        return list(db.scalars(select(User.username)))


def test_transaction_commits_when_the_block_returns_early(factory):
    def write() -> str:
        with transaction(factory) as db:
            db.add(_user("early"))
            return "done"

    assert write() == "done"
    assert _names(factory) == ["early"]


def test_transaction_rolls_back_on_error(factory):
    with pytest.raises(RuntimeError), transaction(factory) as db:
        db.add(_user("doomed"))
        db.flush()
        raise RuntimeError
    assert _names(factory) == []


def test_returning_inside_a_session_scope_loop_loses_the_write(factory):
    """Documents why scripts must not iterate session_scope (the generator never resumes)."""

    def write() -> str:
        for db in session_scope(factory):
            db.add(_user("lost"))
            return "done"
        return "unreachable"

    assert write() == "done"
    assert _names(factory) == []

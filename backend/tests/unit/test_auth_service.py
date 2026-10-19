from datetime import timedelta

import pytest

from tests.conftest import PASSWORD
from verita.core.errors import AppError
from verita.db.base import utcnow
from verita.db.models import AuditLog, Role
from verita.repositories.identity import AuditRepository
from verita.services.auth import AuthService


@pytest.fixture
def svc(db, settings):
    return AuthService(db, settings)


def test_login_success_issues_session(svc, make_user):
    make_user()
    result = svc.login("priya", PASSWORD, ip="1.2.3.4")
    assert result.user.username == "priya"
    assert result.session_token != result.csrf_token
    info = svc.resolve(result.session_token)
    assert info is not None and info.user.username == "priya"


def test_username_is_trimmed(svc, make_user):
    make_user()
    assert svc.login("  priya ", PASSWORD, ip=None).user.username == "priya"


@pytest.mark.parametrize(
    ("username", "password"), [("priya", "wrong-password-x"), ("ghost", PASSWORD)]
)
def test_failures_share_one_error(svc, make_user, username, password):
    make_user()
    with pytest.raises(AppError) as err:
        svc.login(username, password, ip=None)
    assert err.value.status == 401 and err.value.slug == "invalid-credentials"


def test_lockout_after_max_failures_even_with_right_password(svc, make_user, db, settings):
    user = make_user()
    for _ in range(settings.login_max_failures):
        with pytest.raises(AppError):
            svc.login("priya", "wrong-password-x", ip=None)
    db.refresh(user)
    assert user.locked_until is not None
    with pytest.raises(AppError):
        svc.login("priya", PASSWORD, ip=None)
    actions = [a.action for a in AuditRepository(db).recent()]
    assert "auth.locked" in actions and "auth.login_locked" in actions


def test_lockout_expires(svc, make_user, settings):
    make_user()
    for _ in range(settings.login_max_failures):
        with pytest.raises(AppError):
            svc.login("priya", "wrong-password-x", ip=None)
    later = utcnow() + timedelta(minutes=settings.login_lockout_minutes + 1)
    assert svc.login("priya", PASSWORD, ip=None, now=later).user.failed_logins == 0


def test_failure_count_resets_on_success(svc, make_user, db):
    user = make_user()
    with pytest.raises(AppError):
        svc.login("priya", "wrong-password-x", ip=None)
    db.refresh(user)
    assert user.failed_logins == 1
    svc.login("priya", PASSWORD, ip=None)
    assert user.failed_logins == 0


def test_resolve_rejects_unknown_empty_and_expired(svc, make_user, settings):
    make_user()
    assert svc.resolve(None) is None
    assert svc.resolve("not-a-session") is None
    result = svc.login("priya", PASSWORD, ip=None)
    expired = utcnow() + timedelta(minutes=settings.session_ttl_minutes + 1)
    assert svc.resolve(result.session_token, now=expired) is None
    assert svc.resolve(result.session_token) is None  # the expired session was deleted


def test_logout_invalidates_session(svc, make_user):
    make_user()
    result = svc.login("priya", PASSWORD, ip=None)
    info = svc.resolve(result.session_token)
    assert info is not None
    svc.logout(info, ip=None)
    assert svc.resolve(result.session_token) is None


def test_create_user_validation(svc, make_user):
    make_user()
    with pytest.raises(AppError) as dup:
        svc.create_user("priya", PASSWORD, Role.MLRO)
    assert dup.value.status == 409
    with pytest.raises(AppError) as blank:
        svc.create_user("   ", PASSWORD, Role.MLRO)
    assert blank.value.status == 422
    with pytest.raises(ValueError, match="at least"):
        svc.create_user("marcus", "short", Role.MLRO)


def test_every_outcome_is_audited(svc, make_user, db):
    make_user()
    svc.login("priya", PASSWORD, ip="9.9.9.9")
    with pytest.raises(AppError):
        svc.login("priya", "wrong-password-x", ip="9.9.9.9")
    rows = db.query(AuditLog).all()
    assert {r.action for r in rows} >= {"user.created", "auth.login", "auth.login_failed"}
    assert all(r.ip == "9.9.9.9" for r in rows if r.action.startswith("auth."))

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from verita.core.security import (
    MIN_PASSWORD_LENGTH,
    hash_password,
    new_token,
    token_digest,
    tokens_match,
    verify_password,
)


def test_hash_and_verify_roundtrip():
    h = hash_password("a-long-enough-password")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "a-long-enough-password")
    assert not verify_password(h, "a-long-enough-passwore")


def test_short_password_rejected():
    with pytest.raises(ValueError, match=str(MIN_PASSWORD_LENGTH)):
        hash_password("short")


def test_missing_hash_never_verifies():
    assert not verify_password(None, "anything-at-all")


def test_garbage_hash_never_verifies():
    assert not verify_password("not-a-hash", "anything-at-all")


def test_tokens_are_unique_and_long():
    tokens = {new_token() for _ in range(100)}
    assert len(tokens) == 100
    assert all(len(t) >= 40 for t in tokens)


@settings(max_examples=50)
@given(st.text(min_size=1))
def test_tokens_match_only_their_digest(token):
    digest = token_digest(token)
    assert tokens_match(token, digest)
    assert not tokens_match(token + "x", digest)


def test_tokens_match_rejects_empty():
    assert not tokens_match(None, token_digest("x"))
    assert not tokens_match("", token_digest(""))

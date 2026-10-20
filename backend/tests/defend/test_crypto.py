"""RFC 8785 canonical JSON, RFC 6962 Merkle tree, Ed25519 signatures."""

from __future__ import annotations

import json
import math
import struct

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from verita.defend.canonical import CanonicalizationError, canonicalize
from verita.defend.merkle import EMPTY_ROOT, MerkleTree, changed_leaves, verify_proof
from verita.defend.signing import Signer, load_public_pem, verify_signature

# ── RFC 8785 ─────────────────────────────────────────────────────────────────


def test_rfc8785_section_3_2_2_example():
    raw = (
        '{"numbers":[333333333.33333329,1E30,4.50,2e-3,0.000000000000000000000000001],'
        '"string":"\\u20ac$\\u000F\\u000aA\'\\u0042\\u0022\\u005c\\\\\\"\\/",'
        '"literals":[null,true,false]}'
    )
    expected = (
        '{"literals":[null,true,false],"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27],'
        '"string":"€$\\u000f\\nA\'B\\"\\\\\\\\\\"/"}'
    )
    assert canonicalize(json.loads(raw)).decode("utf-8") == expected


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (0.0, "0"),
        (-0.0, "0"),
        (1e21, "1e+21"),
        (1e20, "100000000000000000000"),
        (0.000001, "0.000001"),
        (1e-7, "1e-7"),
        (0.1, "0.1"),
        (5e-324, "5e-324"),
        (1.7976931348623157e308, "1.7976931348623157e+308"),
        (-1.5, "-1.5"),
    ],
)
def test_numbers_follow_ecmascript(value, text):
    assert canonicalize(value) == text.encode()


def test_keys_sort_by_utf16_code_units():
    # U+1F600 is a surrogate pair (D83D …) and sorts before U+FB33 in UTF-16, after it by code point
    out = canonicalize({"דּ": 1, "\U0001f600": 2, "a": 0}).decode("utf-8")
    assert out == '{"a":0,"\U0001f600":2,"דּ":1}'


@pytest.mark.parametrize(
    "bad", [math.nan, math.inf, {1: "x"}, {"s": {1, 2}}, 2**53 + 1, 10**400, b"bytes"]
)
def test_non_json_values_are_rejected(bad):
    with pytest.raises(CanonicalizationError):
        canonicalize(bad)


def test_large_exact_integers_match_their_double():
    assert canonicalize(2**53) == b"9007199254740992"
    assert canonicalize(10**21) == canonicalize(1e21) == b"1e+21"


@given(st.floats(allow_nan=False, allow_infinity=False))
def test_numbers_round_trip(value):
    assert float(canonicalize(value)) == value or value == 0


@given(st.integers(0, 2**64 - 1))
def test_every_double_bit_pattern_round_trips(bits):
    value = struct.unpack(">d", bits.to_bytes(8, "big"))[0]
    if math.isfinite(value):
        assert float(canonicalize(value)) == value


json_values = st.recursive(
    st.none()
    | st.booleans()
    | st.integers(-(2**53) + 1, 2**53 - 1)
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(),
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(st.text(), inner, max_size=4),
    max_leaves=20,
)


@given(json_values)
def test_canonical_form_is_valid_json_and_idempotent(value):
    out = canonicalize(value)
    assert canonicalize(json.loads(out)) == out


# ── Merkle ───────────────────────────────────────────────────────────────────


def test_empty_and_single_trees():
    assert MerkleTree.build({}).root == EMPTY_ROOT
    one = MerkleTree.build({"a": 1})
    assert one.root == one.leaf_hex()["a"]
    assert one.proof("a") == []


def test_root_ignores_insertion_order_and_sees_every_change():
    a = MerkleTree.build({"x": 1, "y": [1, 2], "z": {"k": "v"}})
    b = MerkleTree.build({"z": {"k": "v"}, "y": [1, 2], "x": 1})
    assert a.root == b.root
    assert MerkleTree.build({"x": 1, "y": [1, 3], "z": {"k": "v"}}).root != a.root
    assert MerkleTree.build({"x": 1.0, "y": [1, 2], "z": {"k": "v"}}).root == a.root  # 1.0 ≡ 1


def test_leaf_and_node_hashes_are_domain_separated():
    # a two-leaf tree's root must not equal any single leaf built from the same bytes
    tree = MerkleTree.build({"a": 1, "b": 2})
    assert tree.root not in tree.leaf_hex().values()


@settings(max_examples=60)
@given(
    st.dictionaries(
        st.text(min_size=1, max_size=6), st.integers(-(2**52), 2**52), min_size=1, max_size=40
    )
)
def test_every_audit_path_verifies(items):
    tree = MerkleTree.build(items)
    for name in items:
        assert verify_proof(name, items[name], tree.proof(name), tree.root)
        assert not verify_proof(name, (items[name] or 0) + 1, tree.proof(name), tree.root)


def test_changed_leaves_names_the_tampered_items():
    items = {"EV-TXN-1": {"amount": 100}, "EV-TXN-2": {"amount": 200}, "narrative": "text"}
    expected = MerkleTree.build(items).leaf_hex()
    tampered = {**items, "EV-TXN-2": {"amount": 201}, "extra": 1}
    del tampered["narrative"]
    assert changed_leaves(expected, tampered) == ["EV-TXN-2", "extra", "narrative"]
    assert changed_leaves(expected, items) == []


# ── Ed25519 ──────────────────────────────────────────────────────────────────


def test_sign_verify_and_reject_tampering(tmp_path):
    signer = Signer.load_or_create(tmp_path / "k.pem", tmp_path / "pub.pem")
    root = MerkleTree.build({"a": 1}).root
    sig = signer.sign(7, root)
    public = load_public_pem((tmp_path / "pub.pem").read_text())
    assert verify_signature(public, 7, root, sig)
    assert not verify_signature(public, 8, root, sig)  # bound to the case
    assert not verify_signature(public, 7, "00" * 32, sig)  # bound to the root
    assert not verify_signature(public, 7, root, "not base64!")
    other = Signer.load_or_create(tmp_path / "other.pem")
    assert not verify_signature(other.public, 7, root, sig)


def test_key_persists_and_id_is_stable(tmp_path):
    first = Signer.load_or_create(tmp_path / "k.pem")
    again = Signer.load_or_create(tmp_path / "k.pem")
    assert first.key_id == again.key_id and len(first.key_id) == 16
    info = again.describe()
    assert info["algorithm"] == "Ed25519" and "BEGIN PUBLIC KEY" in info["public_key_pem"]


def test_wrong_key_type_is_rejected(tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    ec_key = ec.generate_private_key(ec.SECP256R1())
    pem = ec_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    (tmp_path / "ec.pem").write_bytes(pem)
    with pytest.raises(ValueError, match="Ed25519"):
        Signer.load_or_create(tmp_path / "ec.pem")
    with pytest.raises(ValueError, match="Ed25519"):
        load_public_pem(
            ec_key.public_key().public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
        )

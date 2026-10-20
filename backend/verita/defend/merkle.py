"""Merkle tree over a case file's items (RFC 6962 hashing, PIVOT §8.5).

Every item of a case file — each evidence item, the narrative, the verification report, the
approval — is a *leaf* ``(name, value)``. Leaves are ordered by name, so the tree is a function
of the content alone. Domain separation follows RFC 6962 §2.1: a leaf hash is
``SHA-256(0x00 ‖ canonical({"name", "value"}))`` and an interior node is
``SHA-256(0x01 ‖ left ‖ right)``; the split point is the largest power of two below n.
Changing any byte of any item changes its leaf and therefore the root, and an audit path
proves one leaf's membership without revealing the others.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from verita.defend.canonical import canonicalize

LEAF_PREFIX = b"\x00"
NODE_PREFIX = b"\x01"
EMPTY_ROOT = hashlib.sha256(b"").hexdigest()


def leaf_hash(name: str, value: Any) -> bytes:
    return hashlib.sha256(LEAF_PREFIX + canonicalize({"name": name, "value": value})).digest()


def _node(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(NODE_PREFIX + left + right).digest()


def _split(n: int) -> int:
    """Largest power of two strictly less than n (n ≥ 2)."""
    k = 1
    while k * 2 < n:
        k *= 2
    return k


def _root(hashes: Sequence[bytes]) -> bytes:
    if len(hashes) == 1:
        return hashes[0]
    k = _split(len(hashes))
    return _node(_root(hashes[:k]), _root(hashes[k:]))


def _path(hashes: Sequence[bytes], index: int) -> list[tuple[str, bytes]]:
    """Sibling hashes from the leaf up, each tagged with the side it sits on."""
    if len(hashes) == 1:
        return []
    k = _split(len(hashes))
    if index < k:
        return [*_path(hashes[:k], index), ("right", _root(hashes[k:]))]
    return [*_path(hashes[k:], index - k), ("left", _root(hashes[:k]))]


@dataclass(frozen=True)
class MerkleTree:
    names: tuple[str, ...]
    leaves: tuple[bytes, ...]

    @classmethod
    def build(cls, items: Mapping[str, Any]) -> MerkleTree:
        names = tuple(sorted(items))
        return cls(names, tuple(leaf_hash(n, items[n]) for n in names))

    @property
    def root(self) -> str:
        return _root(self.leaves).hex() if self.leaves else EMPTY_ROOT

    def leaf_hex(self) -> dict[str, str]:
        return {n: h.hex() for n, h in zip(self.names, self.leaves, strict=True)}

    def proof(self, name: str) -> list[dict[str, str]]:
        index = self.names.index(name)
        return [{"side": side, "hash": h.hex()} for side, h in _path(self.leaves, index)]


def verify_proof(name: str, value: Any, proof: Sequence[Mapping[str, str]], root: str) -> bool:
    """Recompute the root from one item and its audit path."""
    current = leaf_hash(name, value)
    for step in proof:
        sibling = bytes.fromhex(step["hash"])
        current = _node(sibling, current) if step["side"] == "left" else _node(current, sibling)
    return current.hex() == root


def changed_leaves(expected: Mapping[str, str], items: Mapping[str, Any]) -> list[str]:
    """Names whose recomputed leaf differs from ``expected`` (added and removed included)."""
    actual = MerkleTree.build(items).leaf_hex()
    return sorted(n for n in set(expected) | set(actual) if expected.get(n) != actual.get(n))

"""Ed25519 signing of Merkle roots (PIVOT §8.5).

The private key lives in a PEM file outside the repository (``VERITA_SIGNING_KEY_PATH``; in dev
it is created on first use under ``keys/``, which git ignores except for the public key). The
key ID is the first 16 hex characters of SHA-256 over the raw 32-byte public key, so anyone
holding the public key can recompute it.

What is signed is the UTF-8 message ``verita-case-v1:<case id>:<merkle root hex>`` — binding the
root to the case and to the format version, so a signature cannot be replayed onto another
case or reinterpreted under a future format.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

FORMAT = "verita-case-v1"


def message(case_id: int, root: str) -> bytes:
    return f"{FORMAT}:{case_id}:{root}".encode()


def key_id(public: Ed25519PublicKey) -> str:
    raw = public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()[:16]


def public_pem(public: Ed25519PublicKey) -> str:
    return public.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()


def load_public_pem(pem: str | bytes) -> Ed25519PublicKey:
    key = serialization.load_pem_public_key(pem.encode() if isinstance(pem, str) else pem)
    if not isinstance(key, Ed25519PublicKey):
        msg = "not an Ed25519 public key"
        raise ValueError(msg)
    return key


@dataclass(frozen=True)
class Signer:
    private: Ed25519PrivateKey
    created_at: str

    @property
    def public(self) -> Ed25519PublicKey:
        return self.private.public_key()

    @property
    def key_id(self) -> str:
        return key_id(self.public)

    def sign(self, case_id: int, root: str) -> str:
        return base64.b64encode(self.private.sign(message(case_id, root))).decode()

    def describe(self) -> dict[str, str]:
        return {
            "key_id": self.key_id,
            "algorithm": "Ed25519",
            "public_key_pem": public_pem(self.public),
            "created_at": self.created_at,
            "message_format": f"{FORMAT}:<case_id>:<merkle_root_hex>",
        }

    @classmethod
    def load_or_create(cls, path: Path, public_out: Path | None = None) -> Signer:
        """Load the PEM key at ``path``; create it (mode 0600 where supported) if missing."""
        if path.exists():
            private = serialization.load_pem_private_key(path.read_bytes(), password=None)
            if not isinstance(private, Ed25519PrivateKey):
                msg = f"{path} is not an Ed25519 private key"
                raise ValueError(msg)
            created = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        else:
            private = Ed25519PrivateKey.generate()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(
                private.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            )
            path.chmod(0o600)
            created = datetime.now(UTC)
        signer = cls(private, created.replace(microsecond=0).isoformat())
        if public_out is not None:
            public_out.parent.mkdir(parents=True, exist_ok=True)
            public_out.write_text(public_pem(signer.public), encoding="utf-8")
        return signer


def verify_signature(public: Ed25519PublicKey, case_id: int, root: str, signature: str) -> bool:
    try:
        public.verify(base64.b64decode(signature, validate=True), message(case_id, root))
    except (InvalidSignature, ValueError):
        return False
    return True

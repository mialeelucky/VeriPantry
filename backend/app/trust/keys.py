"""Ed25519 keys, JWKs, thumbprints and JWS signing (trust-protocol §4, §6.1, §10)."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from app.core.jcs import to_jsonable


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64url_decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def generate_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def load_or_create_key(path: Path) -> Ed25519PrivateKey:
    if path.exists():
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        assert isinstance(key, Ed25519PrivateKey)
        return key
    key = generate_key()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    return key


def public_jwk(key: Ed25519PrivateKey | Ed25519PublicKey, kid: str | None = None) -> dict[str, str]:
    pub = key.public_key() if isinstance(key, Ed25519PrivateKey) else key
    raw = pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    jwk = {"kty": "OKP", "crv": "Ed25519", "x": b64url(raw)}
    if kid:
        jwk.update({"kid": kid, "use": "sig", "alg": "EdDSA"})
    return jwk


def public_key_from_jwk(jwk: dict[str, Any]) -> Ed25519PublicKey:
    if jwk.get("kty") != "OKP" or jwk.get("crv") != "Ed25519":
        raise ValueError("only Ed25519 OKP keys are supported")
    return Ed25519PublicKey.from_public_bytes(b64url_decode(jwk["x"]))


def jwk_thumbprint(jwk: dict[str, Any]) -> str:
    """RFC 7638 thumbprint of an OKP key."""
    members = {"crv": jwk["crv"], "kty": jwk["kty"], "x": jwk["x"]}
    return b64url(hashlib.sha256(json.dumps(members, separators=(",", ":"), sort_keys=True).encode()).digest())


@dataclass
class Signer:
    kid: str
    key: Ed25519PrivateKey

    def sign(self, payload: dict[str, Any], typ: str | None = None) -> str:
        headers = {"kid": self.kid}
        if typ:
            headers["typ"] = typ
        return jwt.encode(to_jsonable(payload), self.key, algorithm="EdDSA", headers=headers)

    @property
    def jwk(self) -> dict[str, str]:
        return public_jwk(self.key, self.kid)


def verify_jws(token: str, jwks: list[dict[str, Any]], **options: Any) -> dict[str, Any]:
    """Verify a compact JWS against a key set, selecting the key by ``kid``."""
    kid = jwt.get_unverified_header(token).get("kid")
    jwk = next((k for k in jwks if k.get("kid") == kid), None)
    if jwk is None:
        raise jwt.InvalidTokenError(f"unknown key id {kid!r}")
    return jwt.decode(token, public_key_from_jwk(jwk), algorithms=["EdDSA"], **options)


@dataclass
class GatewayKeys:
    """The gateway's own signing keys: one for offers and tokens, one for audit checkpoints."""

    gateway: Signer
    audit: Signer

    @property
    def jwks(self) -> list[dict[str, str]]:
        return [self.gateway.jwk, self.audit.jwk]

    @classmethod
    def load(cls, keys_dir: Path) -> "GatewayKeys":
        return cls(
            gateway=Signer("gw-2026-11", load_or_create_key(keys_dir / "gateway-ed25519.pem")),
            audit=Signer("audit-2026-11", load_or_create_key(keys_dir / "audit-ed25519.pem")),
        )

    @classmethod
    def ephemeral(cls) -> "GatewayKeys":
        return cls(gateway=Signer("gw-test", generate_key()), audit=Signer("audit-test", generate_key()))

"""Hash-chain arithmetic (audit-log §4.1).

entry_n = envelope_n without "payload" and "hash"
hash_n  = SHA-256( prevHash_n || JCS(entry_n) )
"""

from __future__ import annotations

from typing import Any

from app.core.jcs import canonical, digest, sha256_hex

GENESIS_HASH = "sha256:" + "0" * 64


def payload_digest(payload: dict[str, Any]) -> str:
    return digest(payload)


def entry_hash(prev_hash: str, entry: dict[str, Any]) -> str:
    return sha256_hex(prev_hash.encode("utf-8") + canonical(entry))

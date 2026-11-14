"""Canonical JSON (RFC 8785) and SHA-256 digests.

All hashing in the audit chain and in decision digests goes through here, so a
value always hashes the same way no matter how it was produced.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

import rfc8785
from pydantic import BaseModel


def to_jsonable(value: Any) -> Any:
    """Convert models and rich types into plain JSON values.

    Money (Decimal) becomes a string, so canonicalisation never sees binary
    floats (audit-log §11).
    """
    if isinstance(value, BaseModel):
        return to_jsonable(value.model_dump(mode="python", by_alias=True, exclude_none=False))
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [to_jsonable(v) for v in value]
        return sorted(items, key=repr) if isinstance(value, (set, frozenset)) else items
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, float):
        # Scores only. RFC 8785 serialises numbers deterministically; rounding
        # to 6 places keeps them readable and stable across platforms.
        return round(value, 6)
    return value


def canonical(value: Any) -> bytes:
    return rfc8785.dumps(to_jsonable(value))


def sha256_hex(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def digest(value: Any) -> str:
    return sha256_hex(canonical(value))

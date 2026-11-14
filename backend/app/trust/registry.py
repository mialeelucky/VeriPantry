"""Who the gateway knows: customers' registered keys, approvers and Valio staff.

Onboarding happens out of band (trust-protocol §4.1); in the demo the registry
is a JSON file in ``var/`` created by ``scripts/dev_setup.py``. Human tokens are
stored only as SHA-256 hashes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from app.core.contracts import Model


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class CustomerEntry(Model):
    id: str
    name: str
    org_jwks: list[dict[str, Any]]  # buyer organisation's mandate-signing keys


class HumanEntry(Model):
    id: str
    display_name: str
    kind: Literal["approver", "staff"]
    role: Literal["approver", "admin"] | None = None
    customer: str | None = None
    token_sha256: str


class Registry(Model):
    customers: list[CustomerEntry] = Field(default_factory=list)
    humans: list[HumanEntry] = Field(default_factory=list)
    revoked_mandates: list[str] = Field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "Registry":
        if not path.exists():
            return cls()
        return cls.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(by_alias=True, indent=2), encoding="utf-8")

    def customer(self, customer_id: str) -> CustomerEntry | None:
        return next((c for c in self.customers if c.id == customer_id), None)

    def human_by_token(self, token: str) -> HumanEntry | None:
        h = token_hash(token)
        return next((u for u in self.humans if u.token_sha256 == h), None)

    def is_revoked(self, mandate_id: str) -> bool:
        return mandate_id in self.revoked_mandates

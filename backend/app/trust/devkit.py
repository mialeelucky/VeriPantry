"""Helpers to create demo identities: buyer organisation keys, agent keys,
mandates, client assertions and human tokens. Used by tests and
``scripts/dev_setup.py``; a real buyer agent does the same with its own keys.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.trust.keys import Signer, generate_key, jwk_thumbprint, public_jwk
from app.trust.mandates import AUTHZ_TYPE
from app.trust.registry import CustomerEntry, HumanEntry, token_hash

DEFAULT_ACTIONS = ["catalog.search", "offer.request", "order.place"]
DEFAULT_LIMITS = {"maxOrderValueEUR": 2000, "maxQtyPerLine": 1500, "deliverWithinDays": 14}


def make_customer(customer_id: str, name: str) -> tuple[CustomerEntry, Signer]:
    signer = Signer(f"{customer_id.split(':')[-1].lower()}-org-1", generate_key())
    return CustomerEntry(id=customer_id, name=name, org_jwks=[signer.jwk]), signer


def make_mandate(
    org: Signer,
    customer: str,
    agent: str,
    agent_key: Ed25519PrivateKey,
    audience: str,
    now: datetime,
    days: int = 7,
    actions: list[str] | None = None,
    limits: dict[str, Any] | None = None,
) -> str:
    claims = {
        "iss": customer,
        "sub": agent,
        "aud": audience,
        "jti": f"mdt_{uuid.uuid4().hex[:8]}",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=days)).timestamp()),
        "cnf": {"jkt": jwk_thumbprint(public_jwk(agent_key))},
        "authorization_details": [
            {"type": AUTHZ_TYPE, "actions": actions or DEFAULT_ACTIONS, "limits": limits if limits is not None else DEFAULT_LIMITS}
        ],
    }
    return org.sign(claims, typ="mandate+jwt")


def make_client_assertion(agent_key: Ed25519PrivateKey, agent: str, audience: str, now: datetime) -> str:
    claims = {"iss": agent, "sub": agent, "aud": audience, "iat": int(now.timestamp()), "jti": uuid.uuid4().hex}
    return jwt.encode(claims, agent_key, algorithm="EdDSA", headers={"jwk": public_jwk(agent_key)})


def make_human(id: str, display_name: str, kind: str, role: str | None, customer: str | None) -> tuple[HumanEntry, str]:
    token = secrets.token_urlsafe(32)
    entry = HumanEntry(id=id, display_name=display_name, kind=kind, role=role, customer=customer, token_sha256=token_hash(token))
    return entry, token

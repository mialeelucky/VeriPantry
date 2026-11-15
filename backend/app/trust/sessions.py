"""Short-lived sessions for people, issued in demo mode (frontend.md §4.3).

A session is a gateway-signed JWT naming a registered person. It replaces
handing out the static demo tokens: the browser gets a token that expires,
and the token never appears in a URL or a notification.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

import jwt

from app.trust.keys import Signer, verify_jws
from app.trust.mandates import NO_LIBRARY_TIME_CHECKS
from app.trust.registry import HumanEntry, Registry

SESSION_TYP = "human-session+jwt"


def issue_session(signer: Signer, person: HumanEntry, audience: str, now: datetime, ttl_seconds: int) -> tuple[str, datetime]:
    exp = now + timedelta(seconds=ttl_seconds)
    claims = {
        "iss": audience,
        "aud": audience,
        "sub": person.id,
        "jti": f"hs_{uuid.uuid4().hex[:16]}",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return signer.sign(claims, typ=SESSION_TYP), exp


def verify_session(token: str, jwks: list[dict[str, Any]], audience: str, registry: Registry, now: datetime) -> HumanEntry | None:
    """Return the person for a valid session token, or None if it is not one."""
    try:
        if jwt.get_unverified_header(token).get("typ") != SESSION_TYP:
            return None
        claims = verify_jws(token, jwks, audience=audience, options=NO_LIBRARY_TIME_CHECKS)
    except jwt.InvalidTokenError:
        return None
    if claims.get("exp", 0) <= now.timestamp():
        return None
    return registry.human(claims["sub"])

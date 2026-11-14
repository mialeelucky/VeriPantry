"""Mandates, agent proof of key possession, and access tokens (trust-protocol §4).

Flow (§4.3): the agent posts its mandate (signed by the buyer organisation)
plus a client assertion (signed by the agent's own key, public key in the
``jwk`` header). The gateway checks both, checks that the agent's key matches
the mandate's ``cnf.jkt``, and issues a short-lived access token bound to that
key thumbprint.

Demo simplification (trust-protocol §12): the DPoP proof per request is not
enforced; the token's ``cnf.jkt`` binding is recorded for it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from app.core.contracts import Model
from app.guardrails.models import MandateInfo
from app.trust.keys import Signer, jwk_thumbprint, public_key_from_jwk, verify_jws
from app.trust.registry import Registry

JWT_BEARER = "urn:ietf:params:oauth:grant-type:jwt-bearer"
AUTHZ_TYPE = "veripantry_procurement"
# Time claims are checked against the injected clock, never the host clock (guardrails G5).
NO_LIBRARY_TIME_CHECKS = {"verify_exp": False, "verify_iat": False, "verify_nbf": False}


class TrustError(Exception):
    def __init__(self, code: str, detail: str, status: int = 401):
        super().__init__(detail)
        self.code, self.detail, self.status = code, detail, status


class AgentPrincipal(Model):
    agent: str
    customer: str
    mandate: MandateInfo
    jkt: str
    token_id: str


def verify_mandate(token: str, registry: Registry, audience: str, now: datetime) -> tuple[MandateInfo, str]:
    try:
        unverified = jwt.decode(token, options={"verify_signature": False})
    except jwt.InvalidTokenError as exc:
        raise TrustError("mandate_invalid", f"mandate is not a valid JWT: {exc}")
    customer = registry.customer(unverified.get("iss", ""))
    if customer is None:
        raise TrustError("mandate_invalid", "mandate issuer is not a registered customer")
    try:
        claims = verify_jws(token, customer.org_jwks, audience=audience, options=NO_LIBRARY_TIME_CHECKS)
    except jwt.InvalidTokenError as exc:
        raise TrustError("mandate_invalid", f"mandate signature or audience invalid: {exc}")
    expires = datetime.fromtimestamp(claims["exp"], tz=timezone.utc)
    if expires <= now:
        raise TrustError("mandate_invalid", "mandate has expired")
    if registry.is_revoked(claims["jti"]):
        raise TrustError("mandate_invalid", "mandate has been revoked")
    details = next((d for d in claims.get("authorization_details", []) if d.get("type") == AUTHZ_TYPE), None)
    if details is None:
        raise TrustError("mandate_invalid", f"mandate carries no {AUTHZ_TYPE} authorization_details")
    jkt = (claims.get("cnf") or {}).get("jkt")
    if not jkt:
        raise TrustError("mandate_invalid", "mandate is not bound to an agent key (cnf.jkt)")
    info = MandateInfo(
        id=claims["jti"],
        customer=claims["iss"],
        agent=claims["sub"],
        expires_at=expires,
        actions=list(details.get("actions", [])),
        limits=dict(details.get("limits", {})),
    )
    return info, jkt


def verify_client_assertion(assertion: str, jkt: str, audience: str, now: datetime) -> None:
    try:
        header = jwt.get_unverified_header(assertion)
        jwk = header.get("jwk")
        if not jwk:
            raise TrustError("agent_key_invalid", "client assertion must carry the agent's public key in its jwk header")
        claims = jwt.decode(assertion, public_key_from_jwk(jwk), algorithms=["EdDSA"], audience=audience, options=NO_LIBRARY_TIME_CHECKS)
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise TrustError("agent_key_invalid", f"client assertion invalid: {exc}")
    if jwk_thumbprint(jwk) != jkt:
        raise TrustError("agent_key_invalid", "agent key does not match the mandate's cnf.jkt")
    iat = claims.get("iat")
    if iat is None or abs(now.timestamp() - iat) > 300:
        raise TrustError("agent_key_invalid", "client assertion is stale (iat must be within 5 minutes)")


def issue_access_token(signer: Signer, mandate: MandateInfo, jkt: str, audience: str, now: datetime, ttl_seconds: int) -> tuple[str, datetime]:
    exp = now + timedelta(seconds=ttl_seconds)
    claims: dict[str, Any] = {
        "iss": audience,
        "aud": audience,
        "sub": mandate.agent,
        "customer": mandate.customer,
        "mandate": mandate.model_dump(mode="json", by_alias=True),
        "cnf": {"jkt": jkt},
        "jti": f"at_{uuid.uuid4().hex[:16]}",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return signer.sign(claims, typ="at+jwt"), exp


def verify_access_token(token: str, jwks: list[dict[str, Any]], audience: str, registry: Registry, now: datetime) -> AgentPrincipal:
    try:
        claims = verify_jws(token, jwks, audience=audience, options=NO_LIBRARY_TIME_CHECKS)
    except jwt.InvalidTokenError as exc:
        raise TrustError("token_invalid", f"access token invalid: {exc}")
    if claims.get("exp", 0) <= now.timestamp():
        raise TrustError("token_invalid", "access token has expired")
    mandate = MandateInfo.model_validate(claims["mandate"])
    if registry.is_revoked(mandate.id):
        raise TrustError("mandate_invalid", "mandate has been revoked")
    return AgentPrincipal(agent=claims["sub"], customer=claims["customer"], mandate=mandate, jkt=claims["cnf"]["jkt"], token_id=claims["jti"])

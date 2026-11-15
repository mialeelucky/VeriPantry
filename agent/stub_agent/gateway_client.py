"""Talks to the VeriPantry gateway as any third-party agent would (trust-protocol §4).

Holds the agent's private key and its mandate (signed by the buyer
organisation). Gets a short-lived access token with the mandate plus a
client assertion proving possession of the key, and refreshes it on expiry.
"""

from __future__ import annotations

import base64
import threading
import time
import uuid
from datetime import datetime
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

JWT_BEARER = "urn:ietf:params:oauth:grant-type:jwt-bearer"


class GatewayError(Exception):
    def __init__(self, status: int, problem: dict):
        super().__init__(problem.get("title", "gateway error"))
        self.status, self.problem = status, problem


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class GatewayClient:
    def __init__(self, base_url: str, audience: str, key: Ed25519PrivateKey, mandate: str, http: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.audience = audience
        self._key = key
        self.mandate = mandate
        claims = jwt.decode(mandate, options={"verify_signature": False})
        self.agent_id: str = claims["sub"]
        self.customer: str = claims["iss"]
        # IPv4 only: avoids a long IPv6 connect timeout on some networks.
        self._http = http or httpx.Client(timeout=60, transport=httpx.HTTPTransport(local_address="0.0.0.0"))
        self._token: str | None = None
        self._expires = 0.0
        self._offset: float | None = None
        self._lock = threading.Lock()

    def _public_jwk(self) -> dict[str, str]:
        raw = self._key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        return {"kty": "OKP", "crv": "Ed25519", "x": _b64url(raw)}

    def _gateway_now(self) -> float:
        """The gateway's clock, which may run on recorded time (fixture mode)."""
        if self._offset is None:
            r = self._http.get(f"{self.base_url}/health")
            gateway_now = datetime.fromisoformat(r.json()["now"]).timestamp()
            self._offset = gateway_now - time.time()
        return time.time() + self._offset

    def _assertion(self) -> str:
        now = int(self._gateway_now())
        claims = {"iss": self.agent_id, "sub": self.agent_id, "aud": self.audience, "iat": now, "jti": uuid.uuid4().hex}
        return jwt.encode(claims, self._key, algorithm="EdDSA", headers={"jwk": self._public_jwk()})

    def token(self, force: bool = False) -> str:
        with self._lock:
            if force or not self._token or time.time() > self._expires - 60:
                # Re-read the gateway's clock for every new token: a gateway on recorded
                # time restarts at the recording moment, so an old offset goes stale.
                self._offset = None
                r = self._http.post(f"{self.base_url}/oauth/token", data={
                    "grant_type": JWT_BEARER, "assertion": self.mandate, "client_assertion": self._assertion(),
                })
                if r.status_code != 200:
                    raise GatewayError(r.status_code, self._problem(r))
                body = r.json()
                self._token, self._expires = body["access_token"], time.time() + body["expires_in"]
            return self._token

    @staticmethod
    def _problem(r: httpx.Response) -> dict:
        try:
            return r.json()
        except ValueError:
            return {"title": f"Gateway returned HTTP {r.status_code}", "status": r.status_code}

    def call(self, method: str, path: str, **kwargs: Any) -> Any:
        for attempt in (0, 1):
            headers = {"Authorization": f"Bearer {self.token(force=attempt == 1)}"}
            r = self._http.request(method, f"{self.base_url}{path}", headers=headers, **kwargs)
            if r.status_code == 401 and attempt == 0:
                continue  # token expired or gateway restarted: get a new one once
            if r.status_code >= 400:
                raise GatewayError(r.status_code, self._problem(r))
            return r.json()


def load_key(path) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    assert isinstance(key, Ed25519PrivateKey)
    return key

"""Live smoke test against a running gateway (not a buyer agent: fixed requests only).

    python -m scripts.smoke http://127.0.0.1:8000

Gets a token with the demo mandate, submits the two worked-example requests
for the next delivery day and prints the outcome and the buyer report of each.
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta

import httpx

from app.config import settings
from app.core.clock import SystemClock
from app.trust.devkit import make_client_assertion, make_mandate
from app.trust.keys import Signer, load_or_create_key


def main(base: str) -> None:
    dev = settings.var_dir / "dev"
    creds = json.loads((dev / "credentials.json").read_text(encoding="utf-8"))
    now = SystemClock().now()
    org = Signer("hotel-123-org-1", load_or_create_key(dev / "org-ed25519.pem"))
    agent_key = load_or_create_key(dev / "agent-ed25519.pem")
    mandate = make_mandate(org, creds["customer"], creds["agent"], agent_key, settings.public_base_url, now)
    with httpx.Client(base_url=base, timeout=120) as http:
        tok = http.post("/oauth/token", data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": mandate,
            "client_assertion": make_client_assertion(agent_key, creds["agent"], settings.public_base_url, now),
        })
        tok.raise_for_status()
        headers = {"Authorization": f"Bearer {tok.json()['access_token']}"}
        deliver = (date.today() + timedelta(days=1 if date.today().weekday() < 4 else 7 - date.today().weekday())).isoformat()
        stamp = now.strftime("%H%M%S")
        requests = [
            ("spec", {"lineId": "L1", "spec": {"query": "semi skimmed milk", "category": "10400", "requiredAttributes": ["FREE_FROM_LACTOSE"]},
                      "quantity": {"value": 1000, "unit": "L"}}),
            ("arla", {"lineId": "L1", "productId": "469363", "spec": {"requiredAttributes": ["FREE_FROM_LACTOSE"],
                      "preferredAttributes": ["brand:Arla", "fat:1.5"]}, "quantity": {"value": 1000, "unit": "L"}}),
        ]
        for name, line in requests:
            rid = f"smoke-{name}-{stamp}"
            r = http.post("/v1/purchase-requests", headers=headers, json={
                "request": {"requestId": rid, "customer": creds["customer"], "deliverBy": deliver, "lines": [line]},
                "purpose": "quote_for_order", "originalText": f"Smoke test: {name}"})
            body = r.json()
            print(f"\n=== {rid}: HTTP {r.status_code}, status {body.get('status')}, order {body.get('order', {}).get('total')}")
            rep = http.get(f"/v1/audit/transactions/{rid}/report", headers={"Authorization": f"Bearer {creds['approverToken']}"})
            print(rep.text)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000")

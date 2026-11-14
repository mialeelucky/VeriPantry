"""Create a local demo environment in backend/var/ (git-ignored).

    python -m scripts.dev_setup

* registry.json: demo customer HOTEL-123 with its organisation key, two
  approvers (roles approver/admin) and one Valio auditor
* dev/org-ed25519.pem, dev/agent-ed25519.pem: buyer organisation and agent keys
* dev/credentials.json: human bearer tokens for local testing only
* policies/customer_HOTEL-123.json: the default guardrail policy

Tokens are written to the local file, never printed.
"""

from __future__ import annotations

import json

from app.config import settings
from app.guardrails.models import Policy
from app.trust.devkit import make_human
from app.trust.keys import Signer, load_or_create_key
from app.trust.registry import CustomerEntry, Registry

CUSTOMER = "customer:HOTEL-123"
AGENT = "agent:hotel-123-procurement-01"


def main() -> None:
    dev = settings.var_dir / "dev"
    org = Signer("hotel-123-org-1", load_or_create_key(dev / "org-ed25519.pem"))
    load_or_create_key(dev / "agent-ed25519.pem")
    approver, approver_token = make_human("u_chef", "Head Chef", "approver", "approver", CUSTOMER)
    admin, admin_token = make_human("u_fin", "Finance Lead", "approver", "admin", CUSTOMER)
    staff, staff_token = make_human("u_valio", "Valio Auditor", "staff", None, None)
    registry = Registry(customers=[CustomerEntry(id=CUSTOMER, name="Hotel 123 (demo)", org_jwks=[org.jwk])], humans=[approver, admin, staff])
    registry.save(settings.registry_path)
    (dev / "credentials.json").write_text(
        json.dumps({"customer": CUSTOMER, "agent": AGENT, "approverToken": approver_token, "adminToken": admin_token,
                    "staffToken": staff_token}, indent=2),
        encoding="utf-8",
    )
    settings.policies_dir.mkdir(parents=True, exist_ok=True)
    (settings.policies_dir / "customer_HOTEL-123.json").write_text(Policy(policy_id="pol_hotel123_v1").model_dump_json(by_alias=True, indent=2), encoding="utf-8")
    print(f"Demo environment written to {settings.var_dir} (registry, keys, policy, local credentials).")


if __name__ == "__main__":
    main()

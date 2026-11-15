"""Create a local demo environment in backend/var/ (git-ignored).

    python -m scripts.dev_setup              # identities, keys, policy, mandate
    python -m scripts.dev_setup --reset-demo # only clear transactions and the audit log

* registry.json: demo customer HOTEL-123 with its organisation key, two
  approvers (roles approver/admin) and one Valio auditor
* dev/org-ed25519.pem: the buyer organisation's key (signs the mandate)
* dev/agent-ed25519.pem + dev/mandate.jwt: what the buyer agent service holds.
  The agent gets the signed mandate, never the organisation's key.
* dev/credentials.json: human bearer tokens for local scripts only
* policies/customer_HOTEL-123.json: the default guardrail policy

Tokens are written to local files, never printed.
"""

from __future__ import annotations

import argparse
import json

from app.config import settings
from app.core.clock import SystemClock
from app.guardrails.models import Policy
from app.trust.devkit import make_human, make_mandate
from app.trust.keys import Signer, load_or_create_key
from app.trust.registry import CustomerEntry, Registry

CUSTOMER = "customer:HOTEL-123"
AGENT = "agent:hotel-123-procurement-01"
MANDATE_DAYS = 30


def reset_demo() -> None:
    """Delete transactions, approvals, orders and the audit log; keep keys and people."""
    removed = 0
    for suffix in ("", "-wal", "-shm"):
        path = settings.db_path.with_name(settings.db_path.name + suffix)
        if path.exists():
            path.unlink()
            removed += 1
    print(f"Demo data cleared ({removed} database file(s) removed). Restart the gateway.")


def main() -> None:
    dev = settings.var_dir / "dev"
    org = Signer("hotel-123-org-1", load_or_create_key(dev / "org-ed25519.pem"))
    agent_key = load_or_create_key(dev / "agent-ed25519.pem")
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
    mandate = make_mandate(org, CUSTOMER, AGENT, agent_key, settings.public_base_url, SystemClock().now(), days=MANDATE_DAYS)
    (dev / "mandate.jwt").write_text(mandate, encoding="utf-8")
    settings.policies_dir.mkdir(parents=True, exist_ok=True)
    (settings.policies_dir / "customer_HOTEL-123.json").write_text(Policy(policy_id="pol_hotel123_v1").model_dump_json(by_alias=True, indent=2), encoding="utf-8")
    print(f"Demo environment written to {settings.var_dir} (registry, keys, policy, mandate, local credentials).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset-demo", action="store_true", help="clear transactions and the audit log only")
    args = parser.parse_args()
    reset_demo() if args.reset_demo else main()

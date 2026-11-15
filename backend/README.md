# VeriPantry backend

The agent gateway: one FastAPI service with independent modules that exchange
the data contracts defined in `../docs/`.

| Module | Implements |
|---|---|
| `app/core/` | Shared contracts (purchase request, plan), clock, canonical JSON (RFC 8785) |
| `app/catalog/` | Static data loading, unit conversion, four-state allergens, bounded search |
| `app/upstream/` | Valio Aimo price/availability client: batching, 5-minute cache, IPv4 |
| `app/fulfilment/` | Optimal plan and Best / Second / Third substitution ([fulfilment-and-substitution.md](../docs/fulfilment-and-substitution.md)) |
| `app/guardrails/` | 26 rules, plan selection, approval re-evaluation ([guardrails.md](../docs/guardrails.md)) |
| `app/trust/` | Keys, mandates, tokens, data tiers, signed offers ([trust-protocol.md](../docs/trust-protocol.md)) |
| `app/audit/` | Hash-chained log, checkpoints, verification, reports ([audit-log.md](../docs/audit-log.md)) |
| `app/gateway/` | The transaction: request → plans → offers → guardrails → order or approval → close |
| `app/api/` | HTTP endpoints (thin layer over `GatewayService`) |

Python 3.13.

## Setup (PowerShell)

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env          # fill in VALIO_API_BASE_URL and VALIO_API_KEY
python -m scripts.dev_setup     # demo customer, keys, approvers, policy in var/ (git-ignored)
```

## Run

```powershell
uvicorn app.main:app --port 8000   # live supplier API
uvicorn app.demo:app --port 8000   # demo: recorded data, demo sign-in (/dev/*), tamper preview
python -m scripts.dev_setup --reset-demo   # clear transactions + audit log between takes
```

The full demo (gateway + stub agent + frontend) is described in `../frontend/README.md`.

Interactive API docs: http://127.0.0.1:8000/docs ·
discovery: http://127.0.0.1:8000/.well-known/agent-interface.json

Live smoke test (two fixed requests, prints the audit reports):

```powershell
python -m scripts.smoke http://127.0.0.1:8000
```

## Tests

```powershell
python -m pytest tests -q
```

Tests run offline on recorded API responses (`tests/fixtures/`, re-record with
`python -m scripts.record_fixtures 2026-11-16`) with a fixed clock. They cover
the guardrail acceptance cases T01–T36, the audit cases AT01–AT16 and the
worked examples of the fulfilment document.

## Main endpoints

| Method and path | Who | Purpose |
|---|---|---|
| `POST /oauth/token` | agent | Mandate + agent key proof → short-lived access token |
| `POST /v1/catalog/search` | agent | Bounded catalog search (T0 data) |
| `POST /v1/availability-check` | agent | "Can you deliver X by D?" for searched products |
| `POST /v1/purchase-requests` | agent | Full transaction: plans, signed offers, guardrails, order or approval |
| `GET /v1/purchase-requests/{id}` | agent / approver | Status, plans, offers, audit receipt |
| `GET /v1/approvals`, `POST /v1/approvals/{id}/decision` | approver | Approve, reject or modify |
| `GET /v1/audit/transactions/{id}/report?view=buyer\|valio&format=md\|html\|pdf` | buyer / Valio staff | Human-readable audit report; `format=pdf` downloads an A4 PDF |
| `GET /v1/audit/verify?fromSeq&toSeq` | any | Chain verification |

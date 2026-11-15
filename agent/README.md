# Stub buyer agent

A stand-in for the LLM buyer agent (`docs/frontend.md` §4.1). It provides the
four endpoints the frontend uses and talks to the gateway **only over HTTP**,
exactly as a third-party agent would: its own Ed25519 key, a mandate signed by
the buyer organisation, a short-lived access token.

It understands sentences without an LLM: an exact demo-scenario text returns a
prepared draft, anything else goes through a small rule-based parser that
reports what it had to assume.

| Endpoint | Purpose |
|---|---|
| `GET /agent/scenarios` | The five demo scenarios |
| `POST /agent/understand` `{ text }` | Draft request + ambiguities |
| `POST /agent/submit` `{ request, originalText }` | Submit to the gateway; returns the transaction view |
| `GET /agent/transactions/{id}` · `/verify` | Current state · audit verification |

## Run

The gateway's `scripts/dev_setup.py` writes the agent key and mandate to
`backend/var/dev/`. Then, from this folder:

```powershell
..\backend\.venv\Scripts\python.exe -m uvicorn stub_agent.app:app --port 8100
```

Settings use the `AGENT_` prefix (e.g. `AGENT_GATEWAY_URL`, `AGENT_TODAY` for
relative dates when the gateway runs on recorded data).

## Tests

```powershell
..\backend\.venv\Scripts\python.exe -m pytest tests -q
```

The integration tests start an in-process gateway on recorded data; the agent
code itself imports nothing from the backend.

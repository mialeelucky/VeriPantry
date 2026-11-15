# VeriPantry frontend

React 18 + TypeScript + Vite + Tailwind. Built to [`docs/frontend.md`](../docs/frontend.md).

| Route | Screen |
|---|---|
| `/buy`, `/buy/:id` | Buyer flow: Ask · Confirm · Working · Choose · Done (talks to the buyer agent only) |
| `/approvals`, `/approvals/:id` | Phone-first approvals: Inbox · Review · Decide · Result |
| `/settings/notifications` | Turn on web push for this device |
| `/audit`, `/audit/:id` | Audit overview; Story · Timeline · Integrity; PDF export; tamper demo (Valio staff) |
| `/stage` | Recording layout: buyer flow, the Head Chef's phone, live status |
| `/sign-in` | Demo persona picker |

## Run (three processes)

The simplest way is `py run_demo.py` from the repo root (see `JUDGES.md`). By hand:

```powershell
# 1. gateway in demo mode on recorded supplier data (from the repo root)
backend\.venv\Scripts\python.exe -m uvicorn app.demo:app --app-dir backend --port 8000
# 2. stub buyer agent
backend\.venv\Scripts\python.exe -m uvicorn stub_agent.app:app --app-dir agent --port 8100
# 3. frontend
cd frontend; npm install; npm run dev
```

Open http://localhost:5173. Before a new recording take:
`backend\.venv\Scripts\python.exe -m scripts.dev_setup --reset-demo` (from `backend/`), then restart the gateway.

Endpoints are set in `.env` (`VITE_GATEWAY_URL`, `VITE_AGENT_URL`).

## Notifications on a real phone

Web push needs a secure origin. `localhost` counts as secure on the computer
itself; a phone must open the app over **https** (e.g. a deployed preview or an
https tunnel), add it to the home screen (iOS 16.4+), sign in and turn
notifications on. The gateway then pushes every approval request to the
people whose role allows them to decide it.

## Checks

```powershell
npm run typecheck
npm test
npm run build
npm run e2e   # five demo scenarios + audit, in the installed Edge; starts the servers if needed
```

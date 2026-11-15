# Frontend Design

> Three screens that make the agent's work visible: a buyer asks, a manager approves, an auditor verifies.

This document is the **implementation baseline** for `frontend/`. It follows the approved mockups (buyer flow in five steps, phone approval in four, audit dashboard in four tabs). The data comes from the gateway described in [`trust-protocol.md`](trust-protocol.md), [`fulfilment-and-substitution.md`](fulfilment-and-substitution.md), [`guardrails.md`](guardrails.md) and [`audit-log.md`](audit-log.md).

The key words **MUST**, **MUST NOT**, **SHOULD** and **MAY** are used as defined in RFC 2119.

---

## 1. Goals and principles

| # | Principle | In practice |
|---|---|---|
| F1 | **One idea per screen** | Each step answers one question ("What do you need?", "Is this right?", "Which plan?"). Detail is one tap away, never on the first view. |
| F2 | **Colour means status, nothing else** | Neutral black, white and grey everywhere. Green = within the agent's authority / done. Amber = needs a person. Red = not allowed / must have. No other colours. |
| F3 | **One primary action per screen** | Exactly one filled button per view. Everything else is secondary or a text link. |
| F4 | **Show, don't claim** | Trust is shown with real artefacts: signed offers, guardrail rules with their numbers, a verifiable chain. Never a decorative "secure" badge without data behind it. |
| F5 | **The UI never decides** | All decisions (plans, guardrails, approvals) come from the gateway. The frontend renders them and sends human choices back. It holds no business rules. |
| F6 | **Agent ≠ browser** | The browser never holds the agent's private key or mandate. Purchasing goes through the buyer agent service (§4.1). |
| F7 | **Demo-proof** | Every scenario can be run with one tap, with no typing and no dependence on an LLM, and every screen has a defined state for errors and empty data. |

---

## 2. Platform and stack

**A responsive web app, installable on phones (PWA).** No native app: one codebase serves the desktop layouts and the phone approval screen. Installed on an approver's phone, the PWA receives push notifications, so an approval request reaches the right person without them having to open anything first (§5.2, §8).

| Concern | Choice | Why |
|---|---|---|
| Framework | React 18 + TypeScript + Vite | Fast to build, typed against the API |
| Styling | Tailwind CSS with design tokens as CSS variables (§6) | One source for light and dark mode |
| Components | shadcn/ui (Radix primitives), copied into the repo | Accessible primitives, fully restylable |
| Icons | lucide-react | Outline icons, consistent stroke |
| Data | TanStack Query | Caching, polling, retries, loading and error states |
| Routing | React Router | Plain URLs per screen (§3) |
| Motion | CSS transitions and one keyframe, no animation library | Step transitions and the progress replay only |
| PWA | vite-plugin-pwa | Installable approval screen; no offline ordering |
| Tests | Vitest + Testing Library; Playwright for demo scenarios | §11 |

The default theme is **light**: it projects best and keeps the three status colours most distinct. Dark mode follows the operating system and is fully supported through the tokens.

The UI language is **English**. In this version the strings live in the screen components; shared wording (status labels, problem messages, rationale texts) comes from `src/lib/` or from the gateway. Moving all strings into one module is the first step before adding Finnish and Swedish.

---

## 3. Information architecture

| Route | Screen | Primary user | Layout |
|---|---|---|---|
| `/buy` | Buyer flow (§5.1) | Chef / buyer | Desktop and tablet, centred column |
| `/buy/:transactionId` | Buyer flow resumed at its current step | Chef / buyer | Same |
| `/approvals` | Approval inbox (§5.2) | Kitchen manager, finance lead | Phone first |
| `/approvals/:approvalId` | Review → Decide → Result | Same | Phone first |
| `/audit` | Audit overview (§5.3) | Buyer admin, Valio auditor | Desktop |
| `/audit/:transactionId` | Story · Timeline · Integrity tabs | Same | Desktop |
| `/stage` | Recording layout (§9) | Demo recording | Buyer flow and the approver's phone side by side |
| `/settings/notifications` | Turn notifications on for this device; choose channels | Approvers | Phone first |
| `/sign-in` | Demo persona picker (§4.3) | Everyone in the demo | Phone and desktop |

A shared top bar shows the VeriPantry mark, the current persona and its role, and links to the three areas the persona may use. Personas only see the areas their role allows: a chef never sees `/audit` in Valio view, and a Valio auditor never sees `/buy`.

---

## 4. Architecture and data flow

```
                ┌──────────── Browser (this frontend) ────────────┐
                │  /buy            /approvals          /audit       │
                └──────┬────────────────┬───────────────────┬──────┘
   chef's sentence,    │                │ human token       │ human token
   confirmed request   ▼                ▼                   ▼
        ┌──────────────────────┐   ┌───────────────────────────────┐
        │ Buyer agent service   │──▶│ VeriPantry gateway (backend/) │
        │ holds agent key +     │   │ approvals, audit, reports      │
        │ mandate; NL → request │   └───────────────────────────────┘
        └──────────────────────┘
```

### 4.1 Buyer agent service (dependency)

The buyer flow talks to the **buyer agent**, not to the gateway's agent endpoints. The agent holds the agent key and mandate and calls the gateway exactly as any third-party agent would (trust protocol, §3). This keeps principle F6 and the openness claim intact.

The frontend needs these four agent endpoints. The agent service itself is specified separately; until it exists, a **stub agent** with the same endpoints (scenario presets and a rule-based parser, no LLM) unblocks frontend work.

| Method and path | Purpose | Returns |
|---|---|---|
| `POST /agent/understand` `{ text }` | Turn the chef's sentence into a draft request | `{ draft: PurchaseRequest, ambiguities: string[] }` |
| `POST /agent/submit` `{ request, originalText }` | Send the confirmed request to the gateway | The gateway's transaction view (§4.5) |
| `GET /agent/transactions/:id` | Current state of a transaction | Transaction view |
| `GET /agent/scenarios` | One-tap demo scenarios (§9) | `[{ id, title, text, draft }]` |
| `GET /agent/transactions/:id/verify` | Audit verification of the buyer's own transaction (step 5) | `VerifyResponse` |

The agent aligns its signature timestamps with the gateway's clock (`GET /health` returns `now`), so it also works when the gateway runs on recorded time. Relative dates such as "by Monday" use the same clock.

### 4.2 Gateway endpoints used directly

| Endpoint | Used by |
|---|---|
| `GET /v1/approvals?state=PENDING` | Approval inbox (polled, §8) |
| `GET /v1/approvals/:id` | Review screen |
| `POST /v1/approvals/:id/decision` | Approve / reject / modify |
| `GET /v1/purchase-requests/:id` | Review screen (plan details) and audit story |
| `GET /v1/audit/transactions` | Audit overview |
| `GET /v1/audit/transactions/:id` | Timeline (events in the caller's view) |
| `GET /v1/audit/transactions/:id/report?format=pdf&view=…` | "Export PDF" |
| `GET /v1/audit/verify?fromSeq&toSeq` | Integrity tab |
| `GET /.well-known/jwks.json` | Offer signature check in the browser (§5.1, step 5) |
| `GET /v1/audit/transactions/:id/verify` | Integrity tab: this transaction's part of the chain, in the caller's view |
| `GET /health` | The gateway's clock (`now`): countdowns use it, because the gateway decides expiry |

### 4.3 Authentication in the demo

Humans authenticate to the gateway with bearer tokens (registry, `scripts/dev_setup.py`). The demo needs a way to put a device into a persona **without putting a token in a URL or a notification**:

- `/sign-in` lists the demo personas (Head Chef, Finance Lead, Valio Auditor).
- Choosing one calls a **demo-only gateway endpoint**, `POST /dev/session { persona }`. It exists only when the gateway runs with `DEMO_MODE=true`, and returns that persona's token.
- The token is kept in memory, mirrored to `sessionStorage` (and, on an installed PWA, to the app's own storage so notifications can open the app signed in), and sent as `Authorization: Bearer …`. It is never written to a URL, into a notification or to logs.
- A person signs in on their phone **once**, when they turn notifications on (§4.4). After that, approval requests come to them; they never need to look for them.

### 4.4 Notifications: the request finds the approver

An approval request is useless if nobody sees it in time: the deadline is tied to the supplier's order cut-off. So the gateway **pushes** each request to the people allowed to decide it, instead of waiting for them to open the inbox.

**Who is notified.** When `approval.requested` is logged, the gateway selects every person registered for that customer whose role is at least the request's `requiredRole` (guardrails §2.2). A request needing `admin` therefore goes only to finance leads, never to the kitchen manager.

**Channels.** Each person may use one or more:

| Channel | How | Typical use |
|---|---|---|
| **Web Push** to the installed PWA | Standard Web Push (VAPID). The device registers its push subscription after sign-in (`POST /v1/me/push-subscriptions`). | The kitchen manager's phone |
| **Webhook** to a team tool | One HTTPS webhook URL per customer, configured by the buyer organisation (e.g. a Slack or Microsoft Teams incoming webhook) | A procurement channel or an existing approval system |

Web Push needs no app store and works on Android and on iOS 16.4 or later once the PWA is added to the home screen. The webhook lets an organisation route requests into a system it already uses; the approval itself still happens in VeriPantry, where identity and role are checked.

**What a notification contains.** Only what is needed to decide whether to open it, and nothing secret:

> **Approval needed · €3,030.00**
> 3,000 L lactose-free milk for Mon 16 Nov · above your agent's €2,000 limit · expires 16:30

Tapping it opens `/approvals/:approvalId`. Notifications MUST NOT contain tokens, prices of plans other than the recommended one, supplier stock, or any tier-T2 data (trust protocol §5.1). The webhook payload carries the same fields as JSON plus the link.

**When.** Three moments:

| Moment | Sent to |
|---|---|
| The request is created | Everyone with a sufficient role |
| 1 hour before the deadline, if still pending | The same people, as a reminder |
| The request is decided or expires | The other notified people ("Decided by Head Chef", so nobody acts twice) and the buyer who asked |

**Audit.** Every notification sent, and every delivery failure, is logged as a `notification.sent` event (audit log §3.2). The report can then show *who was told, when and how*, which answers the auditor's question "did the right person actually get the chance to approve?".

**Fallbacks.** The inbox still polls (§8), so nothing depends on push delivery alone. If no person with a sufficient role has any channel registered, the gateway logs `notification.sent` with outcome `no_recipient`, and the buyer flow shows "No {role} can be reached; the request will expire at {time}" instead of pretending someone was told.

### 4.5 Data contracts

The frontend uses the gateway's JSON as it is (camelCase). The types live in `src/api/types.ts` and mirror:

| Type | Source |
|---|---|
| `PurchaseRequest`, `RequestLine`, `Spec`, `Quantity` | `backend/app/core/contracts.py` |
| `TransactionView` (`status`, `lines[].plans[]`, `selectedRank`, `recommendedRank`, `approval`, `order`, `offers`, `auditRef`) | `GatewayService.transaction_view` |
| `PlanView` (`label`, `strategy`, `items[]`, `total`, `scores`, `deviations`, `flags`, `rationale`, `guardrail`) | `trust/tiers.plan_view` + guardrail summary |
| `Approval` (`approvalId`, `requiredRole`, `deadline`, `lines[].plans[]`, `orderReasons`, `state`) | `GatewayService._request_approval` |
| `AuditEvent`, `OpaqueLink`, `VerifyResult` | `backend/app/audit/` |
| `Problem` (RFC 9457) | `gateway/errors.py` |

The frontend MUST NOT recompute scores, rankings, guardrail outcomes or rationale. It displays what the gateway returns.

### 4.6 Backend additions this design needs

Small, isolated changes to `backend/`, all covered by tests before frontend work depends on them:

| # | Change | Why |
|---|---|---|
| B1 | CORS for the frontend origin (configurable list) | Browser calls from `localhost:5173` and the demo host |
| B2 | `POST /dev/session` (only with `DEMO_MODE=true`) | Persona sign-in without tokens in URLs (§4.3) |
| B3 | `rationaleText` on every plan and `selectionText` on every line, rendered with the audit templates | One wording in UI and reports, no logic duplicated in TypeScript |
| B4 | Richer `GET /v1/audit/transactions`: `title` (e.g. "1,000 L lactose-free milk"), `total`, `outcome`, `reasonCode`, `decidedBy` (`agent` or approver name), `closedAt` | Audit overview rows and the weekly tiles (§5.3) |
| B5 | `POST /v1/audit/tamper-preview { transactionId, seq }` (Valio staff and demo mode only) | The tamper demo. It verifies an **in-memory copy** of the range with one byte changed and returns the failing `VerifyResult`. It never writes to the database. |
| B6 | `UPSTREAM=fixture` option, and `scripts/dev_setup.py --reset-demo` (clears transactions and the audit database; keeps keys and personas) | Deterministic end-to-end tests; a fallback when the live API is unavailable; identical recording takes |
| B7 | Notifications (§4.4): push subscriptions per person (`POST`/`DELETE /v1/me/push-subscriptions`), a per-customer webhook URL, a dispatcher triggered by `approval.requested`, a reminder before the deadline and a decided/expired notice; `notification.sent` audit events; a public VAPID key at `GET /.well-known/push-key` | The approval request reaches the right person; the audit shows that it did |

---

## 5. Screens

### 5.1 Buyer flow (`/buy`), five steps

A step indicator at the top (`1 Ask · 2 Confirm · 3 Working · 4 Choose · 5 Done`) and one primary button at the bottom right. Back is always available, except during step 3.

| Step | Question it answers | Content | Primary action |
|---|---|---|---|
| **1 Ask** | What does your kitchen need? | One large text field; scenario chips below it (§9). | `Next` → `POST /agent/understand` |
| **2 Confirm** | Is this right? | Quantity and date as large tiles. **Must have** (red pills with a lock: `requiredAttributes`, `excludedAllergens`). **Nice to have** (outlined pills: `preferredAttributes`). Any `ambiguities` from the agent shown as amber questions. Every value is editable in place. | `Start` → `POST /agent/submit` |
| **3 Working** | What is the agent doing? | Five rows that tick in order: understood · searched N products · asked the supplier · received N signed offers · checked guardrails. If the line needed substitution, an amber note explains why (`reason.code`, `availableOnTime`). | none: advances automatically |
| **4 Choose** | Which way do you want it? | One card per presented plan, stacked: label and product, one-line `rationaleText`, total, status badge from `guardrail.outcome` (green "Within your agent's authority", amber "Needs approval", red "Not allowed"). The plan the agent selected is pre-selected. Tapping a card opens its **detail sheet**: items, deviations, score bars (fit, cost, reliability, sustainability), triggered rules, and the plans not presented. | Depends on the state (below) |
| **5 Done** | What happened? | Large status mark; outcome sentence; three tiles: decided by · offer signed · audit trail verified. A link to this transaction's audit page. | `New request` |

**What step 4 shows depends on the transaction's state:**

| Gateway state | Step 4 behaviour |
|---|---|
| `ORDERED` (agent decided, selection step 2 or 3) | The selected plan is marked "Ordered by your agent". The primary button reads `See confirmation`. The other plans stay visible for transparency. |
| `PENDING_APPROVAL` | The recommended plan is marked "Waiting for {role}". The subtitle says the approver has been notified (the gateway does this itself, §4.4), the primary button reads `See status`, and step 5 shows "Sent for approval" with the deadline. The screen polls (§8) and moves to "Ordered" when the approval lands. |
| `DENIED` / `UNFULFILLABLE` | No plan cards. A red or neutral explanation from the closing reason, and `Change request` back to step 2. |

**Why step 3 is a replay.** The gateway answers in well under a second, so step 3 replays the real stages afterwards (about 600 ms per row). Every number comes from the response or the transaction's audit events (`candidateCounts`, offers issued), never from a script. The replay MUST be skippable and MUST NOT be longer than 4 s in total.

**Offer check.** On step 5, "Offer signed" is a real check: the browser verifies the order's offer JWS against `/.well-known/jwks.json` (Web Crypto, Ed25519) and only then shows the tick. A failed check shows a red "Signature could not be verified" instead.

### 5.2 Approvals (`/approvals`), phone first, four steps

The usual way in is a **notification** (§4.4): tapping it opens step 2 of that request directly. The inbox is for people who open the app themselves, and for catching up.

| Step | Content | Primary action |
|---|---|---|
| **1 Inbox** | Pending approvals for the persona's customer, newest deadline first. Each row: title, total, one reason pill, time left. Rows needing a higher role are shown greyed with "Needs {role}" and cannot be opened. A short "Handled today" list underneath. | Tap a row |
| **2 Review** | Top: **Why you're asked**: the triggered rule messages of the recommended plan in plain words, in amber. Middle: **You asked → Proposed**, side by side for each deviation (brand, fat, quantity, date). Below: **Unchanged** chips: every required and preferred attribute the plan still satisfies, so the approver sees what did not change. Price per unit compared with the reference price. A link to the other presented plans. | `Make a decision` |
| **3 Decide** | `Approve` (the only filled button, green). `Reject` reveals a reason field, required and validated inline. `Change quantity` reveals a quantity field and sends `modify`. Footer: "Expires {time} · never auto-approved". | The chosen action → `POST /v1/approvals/:id/decision` |
| **4 Result** | Approved: "Approved and ordered", recorded as {name} · {role}, audit trail sealed. Rejected: the reason as it was sent. Modified: "Continued as {new id}" with its new state. | `Back to inbox` |

Error handling for decisions (from the gateway's problem types):

| Problem | Shown as |
|---|---|
| `insufficient-role` | "This needs {role}. Ask {role} to approve." The decision buttons are replaced with that message. |
| `approval-not-pending` | "This request was already decided or has expired." with a link to the transaction. The inbox refreshes. |
| `reason-required` | Inline under the reason field: "Enter a reason first" |

The deadline countdown updates every second on the client. When it reaches zero the screen shows "Expired. Nothing was ordered." and refetches; the gateway is the authority on expiry.

### 5.3 Audit (`/audit`), four tabs

| Tab | Content | Data |
|---|---|---|
| **Overview** | Three tiles: orders this week · decided by the agent (x of y) · blocked by a rule. Below, one row per transaction: title, id, outcome pill (green "Ordered by agent" / green "Approved by {name}" / amber "Waiting for {role}" / red "Blocked by rule" / grey "Expired" or "Failed"). | B4 list |
| **Story** | Four numbered sentences: asked for → found → guardrail → decided. The guardrail step is amber when it escalated, red when it denied, green when everything passed. | Transaction view + audit events |
| **Timeline** | A vertical timeline of every event in this transaction. A **Buyer / Valio** switch: in buyer view, Valio-only events appear as locked "Internal step · visible to Valio only" rows. The Valio view is available only to Valio staff; for others the switch is hidden. | `GET /v1/audit/transactions/:id` |
| **Integrity** | The chain of this transaction's steps as linked tiles, all green when verified. A verdict box ("All N steps verified" / "Verification failed at step N" with the reason). Footer: checkpoint seq and key id. `Tamper with step 4` (demo mode, Valio staff) calls B5 and shows the failing result in red; `Restore` returns to the real result. | `GET /v1/audit/verify`, B5 |

`Export PDF` appears on every transaction tab and downloads the report in the viewer's view. The frontend never renders the server's HTML report inside the page; it renders events itself, and the PDF is a download.

---

## 6. Visual design

### 6.1 Tokens

All colours, radii and spacing are CSS variables, so every component works in light and dark mode without per-component overrides.

| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg` | `#F7F7F5` | `#111111` | Page |
| `--surface` | `#FFFFFF` | `#1B1B1B` | Cards, sheets |
| `--surface-muted` | `#F1F1EE` | `#242424` | Tiles, inputs, inactive pills |
| `--border` | `rgba(0,0,0,0.08)` | `rgba(255,255,255,0.10)` | Hairlines (0.5 px on high-density screens, 1 px otherwise) |
| `--text` | `#1A1A1A` | `#F2F2F2` | Primary text |
| `--text-secondary` | `#5F5F5A` | `#B4B4AE` | Supporting text |
| `--text-muted` | `#8A8A84` | `#7E7E78` | Captions, metadata |
| `--ok-bg` / `--ok-fg` | `#EAF3DE` / `#3B6D11` | `#1E2D10` / `#A7D46E` | Within authority, done, verified |
| `--attn-bg` / `--attn-fg` | `#FAEEDA` / `#854F0B` | `#3A2A0E` / `#F2B866` | Needs a person, waiting |
| `--stop-bg` / `--stop-fg` | `#FCEBEB` / `#A32D2D` | `#3A1616` / `#F09595` | Not allowed, must have, failed |
| `--primary` / `--on-primary` | `#1A1A1A` / `#FFFFFF` | `#F2F2F2` / `#111111` | The one primary button |
| `--radius-sm` / `--radius` / `--radius-lg` | 8 / 14 / 20 px | same | Pills and inputs / cards / sheets and the phone frame |

Status colours are never used for decoration, and never as the only signal: every status also has an icon and words (accessibility, §10).

### 6.2 Typography

Inter (variable, self-hosted) with system fallbacks. Two weights only: 400 and 500.

| Role | Size / line height |
|---|---|
| Step title | 22 / 28 px, 500 |
| Card title | 15 / 22 px, 500 |
| Body | 14 / 21 px, 400 |
| Caption, step label | 12 / 16 px, 400, `--text-muted` |
| Figures (totals, quantities) | Tabular numerals, 18–22 px, 500 |
| IDs, hashes, times | Monospace, 11–12 px |

Sentence case everywhere. Buttons start with a verb ("Approve", "Export PDF"). No exclamation marks, no "please", no "successfully".

### 6.3 Layout and spacing

- 4-px grid; component padding 16–24 px; 12 px between cards.
- Buyer flow: a centred column of max. 720 px on desktop, so a sentence never spans the projector.
- Approvals: designed at 375 px; at desktop widths shown inside a phone frame on `/stage`, and as a centred 420-px column elsewhere.
- Audit: max. 1080 px; the overview table becomes stacked rows under 640 px.
- Breakpoints: 640 px (phone → tablet), 1024 px (tablet → desktop).

### 6.4 Motion

Only where it explains something: step transitions (150 ms fade and 8 px slide), the step 3 ticks, the chain tiles turning red. `prefers-reduced-motion` turns all of it off and shows final states directly.

---

## 7. Components

Built once in `src/components/`, used by all screens:

| Component | Purpose |
|---|---|
| `StepIndicator` | Numbered steps; current, done and upcoming states |
| `StepScreen` | Title, subtitle, body, one primary and one secondary action slot |
| `StatusBadge` | `ok` / `attention` / `stop` / `neutral`, always icon + words |
| `Pill` | Must-have (lock, red), nice-to-have (outlined), unchanged (tick), deviation (amber) |
| `PlanCard` | Label, product line, rationale text, total, `StatusBadge`; selectable |
| `PlanDetailSheet` | Items, deviations, `ScoreBars`, triggered rules, plans not presented |
| `ScoreBars` | Four labelled bars (fit, cost, reliability, sustainability); value shown as text too |
| `ProgressList` | The step 3 replay; skippable |
| `CompareRow` | "You asked → Proposed" for one attribute |
| `Countdown` | Time left to a deadline; switches to "Expired" |
| `MetricTile` | Label above, figure below |
| `Timeline` / `TimelineItem` | Events, locked rows for redacted and opaque entries |
| `ChainStrip` | Linked tiles with verified or broken state |
| `ProblemMessage` | Maps an RFC 9457 problem to a sentence and an action (§5.2) |
| `PhoneFrame` | Recording layout only |
| `NotificationSetup` | Asks for notification permission once, registers the push subscription, shows which channels reach this person |

---

## 8. State and freshness

| Data | Strategy |
|---|---|
| Transaction during the buyer flow | Fetched once after submit; polled every 2 s while `PENDING_APPROVAL`; polling stops on any terminal state |
| Approval inbox | Push notification (§4.4) refreshes it immediately; polled every 3 s while the page is visible as a fallback |
| Approval being reviewed | Refetched on focus and before every decision |
| Audit lists and events | Fetched on open; manual refresh |
| Verification result | Fetched on opening the Integrity tab; never cached across transactions |

Push brings a new request to the approver within seconds. Polling keeps every screen correct when push is unavailable (no permission, unsupported browser). A server-sent event stream MAY replace polling later without changing the screens.

---

## 9. Demo support

The demo is a **recording**. Judges watch it; they do not operate the system. Everything in it must therefore be real and visible on screen, and repeatable take after take.

**Scenarios.** `GET /agent/scenarios` provides one-tap presets. Each fills step 1 with a sentence and skips the LLM, so a take never fails on language parsing:

| Scenario | What the recording shows |
|---|---|
| Lactose-free milk for Monday | Fulfilled exactly, ordered by the agent |
| Arla, but stock is short | Substitution; Best ordered by the agent; Arla kept in Third |
| Arla, 3,000 litres for an event | Substitution, and €3,030 is above the agent's €2,000 limit: goes to the Head Chef's phone |
| 6,000 litres | Over the approver limit; needs the finance lead |
| Milk for a guest with a milk allergy | No milk is ever offered; only milk-free drinks, which need approval |

Policies are per customer, not per request (guardrails §4). A scenario that needs a different policy, such as "brand must not change", therefore needs a second demo customer with its own policy and personas. That is not part of this version.

**Recording layout (`/stage`).** One 16:9 frame, made for screen capture:

- **Left (about 60 %):** the buyer flow, as the chef sees it.
- **Right (about 40 %):** the Head Chef's phone. This is a real phone with the installed PWA, mirrored into the recording, or the same app in a phone-sized browser window when no phone is available. The frame's caption says which, so the recording does not imply more than it shows.
- **Bottom strip:** the live status of the current transaction ("Waiting for Head Chef · expires 16:30", then "Approved by Head Chef · ordered") and its latest audit receipt.

The approval moment then plays out in one shot: the chef submits the 3,000 L request → the phone shows the push notification → the manager taps it, sees *why* they are asked, and approves → within seconds the left side moves to "Ordered", and the audit receipt updates. Nobody touches the phone before the notification arrives, which is the point: the request found the person.

**Suggested recording order** (about 3 minutes): (1) lactose-free milk, ordered by the agent; (2) Arla short, substituted by the agent, with the Third plan keeping Arla; (3) 3,000 L, pushed to the Head Chef and approved on the phone; (4) milk allergy, where no milk is ever offered; (5) the audit tab of transaction 3: story, timeline, buyer/Valio switch, integrity and the tamper demo, then `Export PDF`.

**Reset between takes.** `scripts/dev_setup.py --reset-demo` (B6) clears transactions and the audit database, so every take starts from the same state and the same IDs order.

---

## 10. Accessibility and quality

- WCAG 2.2 AA contrast for all text and status colours, in both themes.
- Every interactive element reachable by keyboard; visible focus ring; sheets and dialogs trap focus and close with Esc.
- Status is never colour only: icon plus words.
- Touch targets at least 44 × 44 px on phone layouts.
- Live regions announce step changes, the step 3 progress and approval results.
- Numbers formatted with `Intl.NumberFormat` (`fi-FI` grouping when the UI language is Finnish); money always with currency and "VAT excluded".

---

## 11. Testing

| Level | What |
|---|---|
| Unit | Problem mapping, status mapping (`guardrail.outcome` → badge), countdown, number formatting |
| Component | `PlanCard` for each guardrail outcome; Confirm screen editing; Decide screen validation (reject without a reason) |
| End-to-end (Playwright) | Each scenario of §9 against the gateway with `UPSTREAM=fixture` (B6): asserts the final status, the badges shown, and that the audit Integrity tab says "verified". One test runs the approval on a second browser context (the "phone"). The tests drive the installed Microsoft Edge. Push delivery itself is not exercised in the browser (a test browser has no push service); recipients, payloads, reminders and the decided notice are covered by backend tests with a recording push sender. |
| Backend | Notification dispatch: the right recipients for each `requiredRole`, nothing secret in the payload, reminder and decided notices, `no_recipient` when nobody can be reached |

---

## 12. Project structure

```
frontend/
  src/
    api/          client.ts (fetch + problem handling), types.ts, agent.ts, gateway.ts
    auth/         persona session (memory + sessionStorage)
    components/   §7
    screens/      buy/, approvals/, audit/, stage/, sign-in/
    i18n/         en.ts (all strings)
    styles/       tokens.css (§6.1), tailwind.css
    lib/          format.ts, jws.ts (offer signature check), status.ts, problems.ts, push.ts, clock.ts
    sw.ts         service worker: app shell and push notifications
  e2e/            Playwright scenarios (§11)
  index.html, vite.config.ts, playwright.config.ts
```

---

## 13. Out of scope for this version

- Ordering without the buyer agent (the browser never acts as the agent).
- Editing guardrail policies in the UI. Policies are configuration files; a policy screen MAY come later.
- Weekly or multi-transaction report exports.
- Offline use beyond loading the installed app shell.

## 14. Build order

1. Backend additions B1–B6, with tests.
2. Stub agent service (§4.1) with the five scenarios.
3. Design tokens, `StepScreen`, `StatusBadge`, `Pill`, `PlanCard`.
4. Buyer flow end to end against the stub agent.
5. Sign-in, notifications (B7) and the approval flow on a phone.
6. Audit overview, story, timeline and integrity, plus PDF export.
7. Recording layout and demo reset, then Playwright scenarios.
8. Replace the stub parser with the LLM buyer agent.

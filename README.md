# VeriPantry

**The rules of the road for AI purchasing agents in food wholesale.**
VeriPantry is the gateway a wholesaler (Valio Aimo) puts in front of its systems so that
any buyer's AI agent can search, get a price, order and, when needed, ask a person, while
the wholesaler keeps its data safe and every decision can be audited afterwards.

Built for the Junction 2026 Valio Aimo challenge.

| | |
|---|---|
| ▶️ **Try it** | `py run_demo.py` (Windows) or `python3 run_demo.py` (macOS/Linux), then follow **[JUDGES.md](JUDGES.md)** |
| 🎬 **Video** | 1:42 walkthrough (link in our submission) |
| 📐 **Key design documents** | **[Trust protocol](docs/trust-protocol.md)** · **[Guardrails](docs/guardrails.md)** · **[Fulfilment & substitution](docs/fulfilment-and-substitution.md)** · [Audit log](docs/audit-log.md) |

---

## The problem

When an agent, not a person, orders from a wholesaler, both sides must answer questions a
human buyer answers by habit:

| Who asks | Question | VeriPantry's answer |
|---|---|---|
| Valio Aimo | *Who are you, who do you act for, what may you do?* | Signed **mandates** from the buyer organisation |
| Valio Aimo | *What may this agent see?* | **Data tiers** and question-shaped disclosure |
| The agent | *Can I rely on this price and stock without a human checking?* | **Signed offers** anyone can verify |
| The buyer | *What may the agent decide alone, and what needs a person?* | **Guardrails** and approval routing |
| Everyone | *What happened, and can anyone rewrite it later?* | A **hash-chained, signed audit log** |

A plain API key answers none of these: it identifies a caller, carries no limits, proves
nothing about the responses, and lets any holder pull as much data as rate limits allow.

## How it works

One purchase goes through three design modules, and every step is written to the audit log.

```
 "We need 1,000 L of Arla lactose-free milk by Monday"      (chef, natural language)
        │
        ▼
 Buyer's agent  ── turns words into a structured request ── holds its own key + mandate
        │  structured, key-bound requests over HTTPS
        ▼
┌──────────────────────────── VeriPantry Gateway (Valio Aimo side) ───────────────────────────┐
│                                                                                              │
│  ① TRUST PROTOCOL           ② FULFILMENT & SUBSTITUTION        ③ GUARDRAILS & APPROVAL       │
│  who are you? what may      can we deliver? if not, what       may the agent order this       │
│  you see? signed offers     are the Best / Second / Third       alone? if not, who decides?   │
│                             alternatives, and why?                                            │
│        └────────────────────────────┴──────────────────────────────────┘                     │
│                    ④ AUDIT LOG: every step hash-chained and signed                            │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
        │                                         │
        ▼                                         ▼
 Order placed (within authority)          Push notification to the person with the right role
                                          → approve / reject → order placed or closed
```

The gateway is **deterministic code with no LLM in the decision path**. Natural language is
handled on the buyer's side; the wholesaler never executes free text.

---

## ① Trust protocol: how both sides can trust each other

📄 **[docs/trust-protocol.md](docs/trust-protocol.md)**

**Identity and delegated authority.** The buyer organisation signs a **mandate** (a JWT
using OAuth Rich Authorization Requests) that says *"this agent may act for us, and only
like this"*: allowed actions, max order value, max quantity per line, categories, delivery
horizon. The mandate is bound to the agent's own key (`cnf.jkt`), so a stolen mandate is
useless. The agent exchanges it for a short-lived access token; every call is checked against
the mandate, and a refusal says exactly which limit was hit (RFC 9457 Problem Details).

**Data minimisation.** Valio Aimo's data is split into three tiers:

| Tier | Who sees it | Examples |
|---|---|---|
| **T0 Catalog** | any registered agent | names, allergens, nutrition, origin, carbon footprint |
| **T1 Customer** | agents with a valid mandate | price, fulfilment status, cut-off, reliability *band* |
| **T2 Internal** | **never** exposed | vendor names, producer IDs, exact stock, raw reliability scores |

Tiers alone are not enough, so **disclosure rules** close the gaps: availability is
answered *for a quantity and a date* (`full / partial / none / unconfirmed`, never the
warehouse count), searches are bounded, prices can be requested only for products found in
the same session, and query budgets are published.

**Verifiable claims.** Every price and availability answer the agent may act on is a
**signed offer** (JWS, Ed25519) that anyone can verify with Valio Aimo's published key. The
signed offer *is* the price commitment. Allergens have four states
(`contains / may_contain / free_from / not_declared`), and *unknown* is never turned into
"safe" or "in stock".

## ② Fulfilment & substitution: finding the best plan, and honest alternatives

📄 **[docs/fulfilment-and-substitution.md](docs/fulfilment-and-substitution.md)**

A deterministic 8-stage pipeline: **normalise → retrieve → hard-filter → shortlist + live
lookup → feasibility → optimal plan → substitution → ranking**. Only the shortlist (≤ 30
products) touches the live price and availability APIs.

- **Hard filters never bend.** Required claims must be present; an excluded allergen passes
  only with an explicit `FREE_FROM` declaration. Must-haves are locked; preferences can bend.
- **If the request can be met**, the cheapest valid plan wins (a small split penalty prefers
  one product over two).
- **If not, substitutes are found in tiers:** S0 Valio's official substitutes, S1 same
  category, S2 same family; cross-family is never automatic. Each candidate gets a
  **similarity score** (category 0.30, attributes 0.25, nutrition 0.15, pack format 0.10,
  name 0.10, brand 0.10).
- **Whole plans are ranked, not single products:** full substitute, split, multi-substitute,
  later delivery or partial. Score = fit 0.45 + cost 0.30 + reliability 0.15 +
  sustainability 0.10, minus 0.03 per extra product. Ranking is lexicographic, so a partial
  plan never outranks a complete one.
- **Best / Second / Third are genuinely different:** product and strategy diversity rules,
  and fewer than three are returned rather than padding with poor options. Every plan says,
  in plain words, how it differs from what was asked.

**Worked example on real data** (recorded 15 Nov 2026): 1,000 L of Arla lactose-free
semi-skimmed milk, but only 384 L are available by Monday.

| Rank | Plan | Cost | Score |
|---|---|---|---|
| **Best** | 1,000 L Valio Arki Eila semi-skimmed (only the brand differs) | €1,010.00 | 0.92 |
| **Second** | 1,000 L Valio Arki Eila **skimmed** (brand and fat differ) | €1,100.00 | 0.82 |
| **Third** | 384 L Arla as requested + 616 L Valio (the only plan that keeps the brand) | €1,574.48 | 0.80 |

## ③ Guardrails & human approval: what the agent may decide alone

📄 **[docs/guardrails.md](docs/guardrails.md)**

Every plan is checked against **26 rules** in 8 groups (authority, safety, validity, money,
quantity, delivery, substitution, data quality). Each rule returns one of three outcomes:

| Outcome | Meaning | Example |
|---|---|---|
| `ALLOW` | within the agent's authority, so it orders by itself | €1,010 substitute that only changes the brand |
| `ESCALATE(role)` | acceptable, but a person must decide | €3,030 is over the agent's €2,000 limit → Head Chef; over €5,000 → Finance Lead |
| `DENY` | not acceptable whoever approves | allergen-unsafe product, expired offer |

`DENY` is not a stronger `ESCALATE`: no approver can make an allergen-unsafe plan safe.
Principles: **fail closed**, deny dominates, every rule is evaluated so the explanation lists
*all* reasons, and **silence is not consent** (unanswered requests expire, never auto-approve).
If the top plan needs approval but a nearly-as-good plan is within authority, the agent may
take that one instead.

The approval request is **pushed to the person whose role can decide**. It shows which rule
was triggered and what did *not* change. The person can approve, reject or modify it.
Approval re-checks the plan, so an offer that expired while waiting still blocks the order
and the agent re-quotes. Orders are recorded by the gateway with references to the signed
offers, because the challenge environment has no ordering API.

## ④ Audit log: every step provable afterwards

📄 **[docs/audit-log.md](docs/audit-log.md)**

Every event (request, offers, guardrail evaluations, human decisions, order) is appended to
a **hash chain** and sealed with **signed checkpoints**, so any later change is detectable,
and verification shows exactly which step was altered. The same chain has **two views**:
the buyer's (Valio's internal data redacted) and Valio Aimo's (full). Each transaction gets
a readable report, *how this order was decided, in four sentences*, exportable to **PDF**
with one click.

---

## What is built

| Part | Folder | What | Tests |
|---|---|---|---|
| Gateway | [`backend/`](backend) | FastAPI: trust protocol, fulfilment, guardrails, approvals, web push, audit log, PDF reports | 101 |
| Buyer agent (stub) | [`agent/`](agent) | Talks to the gateway exactly as any third-party agent would. Rule-based understanding; an LLM would replace only this step | 7 |
| Web app | [`frontend/`](frontend) | Buyer flow (Ask · Confirm · Working · Choose · Done), approvals on a phone, audit with Story · Timeline · Integrity, tamper demo | 5 unit + 6 end-to-end |
| Design docs | [`docs/`](docs) | The four specifications above, plus [frontend](docs/frontend.md) and the [OpenAPI](docs/openapi.json) description | |
| Data | [`data/`](data) | The challenge's product, delivery-reliability and carbon data sets (17,546 products) | |

The demo runs on **recorded** Valio Aimo price and availability responses, so every run is
reproducible and needs no API key. The gateway also runs against the live API.

## Limits and next steps

- The buyer agent is a **rule-based stand-in**; it understands the demo scenarios and simple
  milk and cream requests. An LLM agent would plug into the same public interface.
- Human approvals currently route to the **buyer's** roles. A **seller-side review queue**
  for Valio Aimo (credit limits, unusual orders, new agents) is the natural next step.
- Demo sign-in has no passwords, and push notifications on a real phone need HTTPS hosting.

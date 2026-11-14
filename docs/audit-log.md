# Audit Log and Transaction Reports

> Every purchase transaction, successful or not, leaves a tamper-evident trail of events and ends with a report that a person can read and audit directly.

This document is the **implementation baseline** for the audit layer. It refines the audit trail outlined in [`trust-protocol.md`](trust-protocol.md) (§7) and defines the events that the other layers emit:

- the gateway ([`trust-protocol.md`](trust-protocol.md)),
- fulfilment ([`fulfilment-and-substitution.md`](fulfilment-and-substitution.md)),
- guardrails and approval ([`guardrails.md`](guardrails.md), §10).

The key words **MUST**, **MUST NOT**, **SHOULD** and **MAY** are used as defined in RFC 2119.

---

## 1. Principles

| # | Principle | Consequence |
|---|---|---|
| L1 | **Write as it happens** | Each step appends its event when it occurs, not at the end. A crash mid-transaction still leaves a complete trail up to that point. |
| L2 | **Append-only** | Events are never updated or deleted. A correction is a new event. |
| L3 | **Tamper-evident** | Events form a hash chain (§4). Changing, removing or reordering any event is detectable. |
| L4 | **One source of truth** | Human-readable reports are **rendered from the events**. A report never contains anything that is not in the log. |
| L5 | **Deterministic rendering** | The same events always produce the same report, byte for byte. Reports are built from templates, **not written by an LLM**. |
| L6 | **Failures are first-class** | Denied, rejected, expired, unfulfillable and failed transactions get a full report, just like successful ones. |
| L7 | **Two audiences, one chain** | The buyer and Valio Aimo see different levels of detail. Both can verify the same chain (§5). |
| L8 | **No secrets** | API keys, tokens, private keys and full JWS signatures are never logged. Digests are logged instead. |

---

## 2. Concepts

| Term | Definition |
|---|---|
| **Transaction** | The full lifecycle of one purchase request, from `request.received` to `transaction.closed`. `transactionId` = `requestId`. |
| **Event** | One immutable record of one step (§3). |
| **Chain** | The single, global, ordered sequence of all events, linked by hashes (§4) |
| **Receipt** | `auditRef = { seq, hash }`, returned in every gateway response (trust protocol, §7) |
| **Checkpoint** | A signed statement of the chain head at a point in time (§4.3) |
| **Report** | The human-readable rendering of one transaction's events, in a buyer view or a Valio view (§7) |

---

## 3. Events

### 3.1 Event envelope

```json
{
  "seq": 1042,
  "eventId": "evt_01JD2X…",
  "time": "2026-11-14T21:10:03.412+02:00",
  "type": "guardrail.evaluated",
  "transactionId": "req_001",
  "customer": "customer:HOTEL-123",
  "actor": { "kind": "system", "id": "guardrail-engine", "role": null },
  "mandate": "mdt_7f3c9a",
  "visibility": "both",
  "payload": { "...": "type-specific, see §3.3" },
  "payloadDigest": "sha256:9f2c…",
  "prevHash": "sha256:b6e1…",
  "hash": "sha256:4a07…"
}
```

| Field | Rule |
|---|---|
| `seq` | Strictly increasing by 1 across the whole chain, starting at 1 |
| `time` | Server time, timezone-aware, millisecond precision, taken from an injectable clock |
| `actor.kind` | `agent` (buyer agent), `human` (approver), `gateway`, or `system` (fulfilment, guardrail engine, watchdog) |
| `actor.role` | For humans: `approver` or `admin`. Otherwise `null`. |
| `visibility` | `both`: buyer and Valio Aimo. `valio`: Valio Aimo only. |
| `payloadDigest` | `SHA-256(JCS(payload))`. JCS is RFC 8785 canonical JSON. |
| `prevHash` | The `hash` of event `seq − 1`. For `seq = 1`, 64 zeros. |
| `hash` | See §4.1 |

### 3.2 Event catalogue

Event types are stable identifiers. The names used in the guardrails specification (§10 there) are kept unchanged.

| Phase | Type | Emitted by | Visibility | Emitted when |
|---|---|---|---|---|
| Access | `auth.token_issued` | gateway | both | A mandate was accepted and a session token issued |
| Access | `auth.denied` | gateway | both | A mandate or token was refused (`reason`) |
| Request | `request.received` | gateway | both | A purchase request arrived. **Opens the transaction.** |
| Lookup | `catalog.searched` | gateway | both | A catalog search ran |
| Lookup | `upstream.queried` | gateway | valio | The price or availability API was called |
| Lookup | `data.disclosed` | gateway | valio | Data was returned to the agent: which tier, which fields |
| Lookup | `offer.issued` | gateway | both | A signed offer was issued |
| Plan | `fulfilment.completed` | system | both | Plans were produced for the request |
| Decide | `guardrail.evaluated` | system | both | A plan was evaluated |
| Decide | `plan.selected` | system | both | A plan was selected (selection step 2 or 3) |
| Approve | `approval.requested` | system | both | An approval request was created |
| Approve | `approval.decided` | human | both | An approver approved or rejected |
| Approve | `approval.expired` | system | both | The approval deadline passed |
| Approve | `approval.superseded` | human | both | The request was modified and replaced |
| Retry | `requote.started` | system | both | An expired offer triggered a re-quote |
| Order | `order.submitted` | gateway | both | The order was recorded |
| Order | `order.failed` | gateway | both | Recording the order failed |
| Close | `transaction.closed` | system | both | The transaction reached a terminal outcome (§6). **Triggers the report.** |
| Integrity | `chain.checkpoint` | system | both | A checkpoint was signed (§4.3) |

### 3.3 Payloads

Payloads reuse the objects already defined in the other specifications wherever possible, instead of inventing new ones.

| Type | Payload |
|---|---|
| `auth.token_issued` | `{ agent, mandate, actions, limits, tokenExpiresAt }` |
| `auth.denied` | `{ agent, reason, problemType }`, using the RFC 9457 problem type |
| `request.received` | `{ purpose, request, originalText? }`. `request` is the standard purchase request. `originalText` is present only if the buyer agent supplied it. |
| `catalog.searched` | `{ searchId, query, filters, resultCount, productIds }` |
| `upstream.queried` | `{ endpoint, requestedDate, productCount, httpStatus, latencyMs, fromCache }` |
| `data.disclosed` | `{ productIds, tiers, fields }` |
| `offer.issued` | `{ offerId, productId, quantity, unitPrice, validUntil, jwsDigest }` |
| `fulfilment.completed` | `{ lines: [{ lineId, status, reason, candidateCounts, plans, notPresented }] }`. `plans` are the full plan objects, each with a `rationale` (§7.4). `notPresented` lists plans that were evaluated but not shown, each with its score and the reason, such as the strategy-diversity rule. `candidateCounts` = `{ retrieved, afterHardFilter, shortlisted, feasible, substitutePool }`. |
| `guardrail.evaluated` | The full Decision object (guardrails, §9) |
| `plan.selected` | `{ lineId, rank, selectionStep, reason, rationale }`. `rationale` explains the choice (§7.4). |
| `approval.requested` | The approval request (guardrails, §8.2) |
| `approval.decided` | `{ approvalId, action, planRank?, reason?, approver: { id, displayName, role } }` |
| `approval.expired` | `{ approvalId, deadline }` |
| `approval.superseded` | `{ approvalId, newRequestId, changes }` |
| `requote.started` | `{ attempt, maxAttempts, expiredOfferIds }` |
| `order.submitted` | `{ orderId, lines: [{ productId, salesUnits, unitPrice, lineTotal, offerId }], total, approvalId \| "auto" }` |
| `order.failed` | `{ reason }` |
| `transaction.closed` | `{ outcome, reasonCode, summary, durationMs, total? }` |
| `chain.checkpoint` | `{ headSeq, headHash, jws }` |

**Not logged.** API keys, access tokens, DPoP proofs, private keys, and full JWS strings (only `jwsDigest`). Mandates are referenced by ID, not copied. Upstream exact stock amounts appear only in `valio` events.

---

## 4. Integrity

### 4.1 Hash chain

```
entry_n = envelope_n without the fields "payload" and "hash"
hash_n  = SHA-256( prevHash_n || JCS(entry_n) )
```

The hash covers `payloadDigest`, not the payload itself. This is the trust protocol's formula (§7 there), with the payload represented by its digest. Hashing the digest gives two properties at once:

- the payload is still protected, because changing it changes `payloadDigest`, which changes `hash`;
- an event can be **redacted** (payload removed) without breaking verification (§5).

### 4.2 Receipts

Every gateway response carries the `auditRef` of the last event it caused. The buyer agent stores these. A receipt that does not match the chain proves tampering.

### 4.3 Checkpoints

The gateway signs the chain head with its Ed25519 key, published in the same JWKS as offer keys, under its own `kid`. It does so:

- every 100 events,
- every 10 minutes when events have occurred, and
- at every `transaction.closed`.

A checkpoint is itself an event (`chain.checkpoint`), so checkpoints are chained too.

### 4.4 Storage

| Aspect | Rule |
|---|---|
| Store | SQLite table `audit_events`, one row per event |
| Append-only | Database triggers reject `UPDATE` and `DELETE` on the table |
| Ordering | A single writer assigns `seq` inside a transaction, so concurrent requests cannot create gaps or duplicates |
| Columns | Every envelope field. `payload` is stored as canonical JSON text, and the hash fields have indexes on `transactionId` and `type`. |

---

## 5. Two views of one chain

| View | Who | Contents |
|---|---|---|
| **Buyer view** | The buyer organisation (its approvers and admins) | Their own transactions. Events with `visibility = both` are shown in full. Events with `visibility = valio` appear as **redacted stubs**. |
| **Valio view** | Valio Aimo staff | All events in full |

A redacted stub keeps `seq`, `time`, `type`, `transactionId`, `payloadDigest`, `prevHash` and `hash`, and drops `payload`. A buyer can therefore verify the **entire** chain of their transaction without seeing Valio Aimo's internal data, such as upstream stock levels or which fields were withheld. This is the data-minimisation principle of the trust protocol (§5), applied to the audit trail.

The chain is global, so other customers' events are interleaved with the buyer's own. In the buyer view they appear as **opaque links**: only `seq`, `prevHash` and `hash`, with no type, time, customer or transaction. The buyer can check that the links are continuous and that every one of their own events hashes correctly, up to the signed checkpoint, without learning anything about other customers.

---

## 6. Transaction lifecycle

### 6.1 Terminal outcomes

Every transaction MUST end with exactly one `transaction.closed` event. The outcomes summarise the approval states of the guardrails specification (§8.1 there): `ORDER_SUBMITTED` closes as `ORDERED`, and the remaining terminal states keep their names.

| Outcome | Reached when | `reasonCode` examples |
|---|---|---|
| `ORDERED` | `order.submitted` | `auto_approved`, `human_approved` |
| `DENIED` | Every plan was `DENY` (guardrails, §7 step 5) | `allergen_violation`, `item_not_orderable` |
| `REJECTED` | An approver rejected the request | `approver_rejected` |
| `EXPIRED` | The approval deadline passed and the re-quote attempts are used up | `approval_expired` |
| `UNFULFILLABLE` | Fulfilment found no acceptable plan | `no_candidates`, `hard_constraints_unmet` |
| `SUPERSEDED` | The buyer modified the request; a new transaction continues | `modified_by_approver` |
| `FAILED` | A system error, or the watchdog closed an abandoned transaction | `upstream_unavailable`, `abandoned` |

### 6.2 Guarantees

- **Always closed.** Request handling wraps every transaction in try/finally, and an unhandled error writes `transaction.closed` with `FAILED`.
- **Watchdog.** A transaction open for more than 24 hours with no pending approval is closed as `FAILED` / `abandoned`.
- **Report on close.** `transaction.closed` triggers report generation (§7). If generation fails, the error is logged as an event, and the report can be regenerated at any time from the events (L4).

---

## 7. Transaction report

### 7.1 Format and sections

Each report is rendered as **Markdown**, from which **HTML** is produced, with identical content. Sections always appear in this order. A section with nothing to say states that explicitly ("No approval was required"), instead of being omitted. In the rendered report the Summary is the header table, and the remaining sections are numbered from 1.

| # | Section | Content | View |
|---|---|---|---|
| 1 | **Summary** | Outcome, transaction ID, customer, agent, mandate, start and close times, duration, order total | both |
| 2 | **What was asked** | Original text (if supplied); the structured request lines | both |
| 3 | **What was checked** | Searches; candidate counts per stage; number of offers issued | both |
| 4 | **Options considered** | Why substitution was needed. Every presented plan with rank, strategy, total, score, deviations and flags, plus **why it holds that rank** (its rationale). Plans evaluated but not presented, with the reason. | both |
| 5 | **Decision** | **Why the selected plan was chosen** (its selection rationale); guardrail outcome per plan; every triggered rule with observed value and limit; selection step | both |
| 6 | **Human approval** | Who, which role, when, which action, which plan; or "Not required: within the agent's autonomous authority" | both |
| 7 | **Result** | Ordered lines with offer IDs; or the failure reason and what the buyer can do next | both |
| 8 | **Timeline** | Every event in order: time, actor, type, one-line description. Redacted stubs are shown as "internal step". | both |
| 9 | **Data disclosure** | Per product: tiers and fields disclosed; upstream calls made | valio |
| 10 | **Integrity** | First and last `seq` and `hash`, covering checkpoint, verification status | both |

### 7.2 Example: buyer view, abridged

The example below was rendered by the implementation from a live run against the Valio Aimo mock API (scenario 2 of the guardrails specification: 1,000 L of Arla 469363 by Monday). Long product names are shortened, and the timeline and the list of plans not presented are abridged; everything else is unchanged.

```markdown
# Transaction report: smoke-arla-004726

| Outcome | **ORDERED** (auto_approved) |
|---|---|
| Customer | customer:HOTEL-123 · Agent: agent:hotel-123-procurement-01 · Mandate: mdt_dab829d1 |
| Started / closed | 2026-11-15 00:47:27 → 2026-11-15 00:47:27 (0.2 s) |
| Order total | €1,010.00 (VAT excluded) |
| Summary | Ordered autonomously within the agent's authority. |

## 1. What was asked
Deliver by **2026-11-16** · purpose: quote_for_order

| Line | Product / specification | Quantity | Constraints |
|---|---|---|---|
| L1 | product 469363 | 1000 L | required: FREE_FROM_LACTOSE; preferred: brand:Arla, fat:1.5 |

## 2. What was checked
- **L1:** The requested product can deliver only 384 of 1000 L on time, so substitution was required.
  Candidates: 1 retrieved → 1 after hard filters → 1 shortlisted; 30 substitutes considered; 14 feasible on time.
- Signed offers issued: 4.

## 3. Options considered
Plans are ranked by fit to the request, cost, delivery reliability and sustainability
(weights 0.45 / 0.3 / 0.15 / 0.1); a complete, on-time plan always ranks above an incomplete one.

| Rank | Plan | Total | Score | Deviations | Flags |
|---|---|---|---|---|---|
| Best | 1000 L of 464306 Valio Arki Eila semi skimmed … | €1,010.00 | 0.92 | brand: Arla → Valio | substitution |
| Second | 1000 L of 464401 Valio Arki Eila skimmed … | €1,100.00 | 0.82 | brand: Arla → Valio; fat: 1.5 → 0.0 | substitution |
| Third | 384 L of 469363 Arla … + 616 L of 464306 Valio … | €1,574.48 | 0.80 | brand: Arla → Valio (61 %) | reliability_no_data, split, substitution |

Why each plan holds its rank:
- **Best:** cheapest complete plan (€90.00 below the next); from one product; only the brand differs.
- **Second:** €90.00 more expensive than Best; from one product; only the brand, fat differ.
- **Third:** €564.48 more expensive than Best; keeps the requested product for 384 L (38 %);
  shown as a different kind of option; split into 2 products.

Also evaluated, not presented:
- full_substitute of 464201 (€1,560.00, score 0.82): not shown because two plans of the same
  strategy are already listed (strategy-diversity rule)
- full_substitute of 464398 (€1,650.00, score 0.81): ranked below third
- …

## 4. Decision
**Line L1: Selected: Best plan. Why: the highest-ranked plan, and every guardrail rule passed.**

- Best plan: **ALLOW**. No guardrail rule was triggered.
- Second plan: **ESCALATE** (requires approver).
  - GR-X3 low_similarity: 464401 has similarity 0.66, below the minimum 0.80.
  - GR-X4 inflexible_deviation: fat changes from 1.5 to 0.0; fat is not a flexible attribute in your policy.
- Third plan: **ALLOW**. No guardrail rule was triggered.
- Order-level rules (mandate, spend, velocity): **ALLOW**. No guardrail rule was triggered.

## 5. Human approval
Not required: within the agent's autonomous authority.

## 6. Result
| Product | Quantity | Unit price | Line total | Offer |
|---|---|---|---|---|
| 464306 | 1000 ST | €1.01 | €1,010.00 | off_8e59f41f5a8a |

Order ord_3e9afa158017 · total €1,010.00 (VAT excluded) · approval: auto

## 7. Timeline
| Time | Actor | Event |
|---|---|---|
| 00:47:27.413 | agent | Request received (purpose: quote_for_order) |
| 00:47:27.414 | gateway | Internal step |
| 00:47:27.564 | gateway | Signed offer off_8e59f41f5a8a for 464306, valid until 2026-11-15T17:00:00+02:00 |
| 00:47:27.572 | system | Plans produced: L1 substitution_proposed (3 plans) |
| 00:47:27.580 | system | Guardrails on line L1 plan 1: ALLOW |
| 00:47:27.581 | system | Guardrails on line L1 plan 2: ESCALATE (2 rules) |
| 00:47:27.584 | system | Guardrails on order-level rules: ALLOW |
| 00:47:27.586 | system | Plan 1 selected for line L1 (top_plan_allowed) |
| 00:47:27.588 | gateway | Order ord_3e9afa158017 submitted, total €1,010.00 |
| 00:47:27.589 | system | Transaction closed: ORDERED (auto_approved) |

## 8. Integrity
Events seq 78–95 verified (18 links). Chain head sealed by checkpoint seq 96 (key kid `audit-2026-11`).
```

"Internal step" lines are the Valio-only events (upstream calls, data disclosure), shown as redacted stubs (§5). The report gives the guardrail outcome of **every** presented plan, not only the selected one: if the buyer later asks why the agent did not pick the cheaper skimmed milk, the answer is already in the record.

A failed transaction uses the same structure. Its Result section states that no order was placed and what the buyer can do next, for example *"No approval arrived before the deadline. Submit the request again to receive fresh offers."* for an expired one.

### 7.3 Rendering rules

- Templates are versioned (`reportTemplateVersion`), and every report records the version used.
- Money is shown with two decimals, the currency, and "VAT excluded" where applicable. Quantities carry their unit.
- Every rule is shown with its ID, its reason code and its message, filled in with the observed value and the limit (guardrails, §9).
- The report language is English. The templates allow fi and sv translations later.

### 7.4 Rationale: why a plan ranks where it does, and why it was chosen

The ranking and selection rules themselves are defined in the fulfilment document (§9) and the guardrails document (§7). The report does not restate them. It records **how they applied to this transaction**.

To keep reports deterministic (L5), a rationale is not free text. It is a list of **rationale codes with parameters**, computed by the fulfilment and selection steps from the scores and plan data, stored in the event, and rendered by templates:

```json
"rationale": [
  { "code": "cheapest_complete", "params": { "marginEUR": "90.00" } },
  { "code": "single_product" },
  { "code": "only_deviation", "params": { "attributes": ["brand"] } }
]
```

**Plan rationale codes** (on each plan in `fulfilment.completed`), listed in **priority order**: the codes that best distinguish a plan from the others come first.

| Code | Set when | Rendered as |
|---|---|---|
| `cheapest_complete` / `cost_above_best` | Lowest total among complete, on-time plans / any other plan costing more than Best | "cheapest complete plan (€{margin} below the next)" / "€{delta} more expensive than Best" |
| `keeps_requested_product` | Contains the requested product | "keeps the requested product for {qty} ({share})" |
| `diversity_rule_applied` | The plan was promoted into the top three by the strategy-diversity rule | "shown as a different kind of option" |
| `later_delivery` / `partial` | Strategy is later delivery / partial | "delivered {date}, after the requested date" / "covers {qty} of {requested}" |
| `complete_on_time` | Coverage 100 %, delivered by `deliverBy`, **and** it distinguishes the plan: the plan is the only one presented, or another presented plan is not complete and on time | "full quantity on time" |
| `single_product` / `split` | One product / several products in the line | "from one product" / "split into {n} products" |
| `only_deviation` | The plan deviates from the request in the listed attributes | "only the {attributes} differ(s)" |
| `highest_fit` / `closest_name` | Strictly highest Fit among substitution plans / strictly highest name similarity among presented plans | "closest match to the request" / "closest name match" |
| `highest_reliability` | Strictly highest reliability score among presented plans | "most reliable delivery" |
| `lowest_carbon` | Strictly highest sustainability score among presented plans | "lowest carbon footprint" |
| `most_expensive` | Highest total among several presented plans (never Best) | "most expensive" |

Why priority order: with a cap of four codes, a strict table order would drop the most important reason of a plan. For example, the split plan of the worked example would lose "keeps the requested product". Saying "full quantity on time" about every plan, when all of them are, adds no information, so that code appears only where it distinguishes.

**Selection rationale codes** (on `plan.selected`, or on the approval request):

| Code | Set when | Rendered as |
|---|---|---|
| `top_plan_allowed` | Selection step 2 | "the highest-ranked plan, and every guardrail rule passed" |
| `equivalent_plan_within_tolerance` | Selection step 3 | "the Best plan needed approval; this plan scores within {tolerance} of it and is within the agent's authority" |
| `approval_required` | Selection step 4 | "no plan within the agent's authority; sent to {role} for approval" |
| `approver_choice` | A human approved a specific plan | "chosen by {approver} ({role})" |
| `all_denied` | Selection step 5 | "every plan breaks a rule that no approver can override" |

Each plan shows at most **four** codes, the first applicable ones in priority order, so that the explanation stays short. New codes MAY be added. A code that a template does not know is rendered as its raw code, never silently dropped.

---

## 8. Verification

To verify a transaction or a range of the chain:

1. For each event in order, check that `seq` increases by 1 and that `prevHash` equals the previous event's `hash`.
2. Where the payload is present, recompute `payloadDigest` and compare.
3. Recompute `hash` (§4.1) and compare.
4. Find the next `chain.checkpoint` at or after the last event, and check that its JWS signature verifies against the published JWKS and that its `headHash` matches the chain.
5. Optionally, compare every stored receipt (`auditRef`) with the chain.

The report's Integrity section shows the result of steps 1–4. The same procedure is exposed as an API (§9), so that it can be run independently.

---

## 9. API

| Method and path | Purpose | Access |
|---|---|---|
| `GET /audit/transactions/{id}` | Transaction status and its events (in the view the caller is entitled to) | Buyer: own transactions; Valio: all |
| `GET /audit/transactions/{id}/report?view=buyer\|valio&format=md\|html` | The rendered report | `view=valio` for Valio staff only |
| `GET /audit/transactions?customer&from&to&outcome` | List transactions, e.g. all `DENIED` in a week | Buyer: own transactions; Valio: all |
| `GET /audit/verify?fromSeq&toSeq` | Run the verification of §8 | Anyone authenticated |

---

## 10. Acceptance test cases

| # | Scenario | Expected |
|---|---|---|
| AT01 | Auto-approved order (guardrails scenario 2) | Outcome `ORDERED`; report Approval section says "Not required" |
| AT02 | Human-approved order | Outcome `ORDERED`; the report names the approver, role, time and chosen plan |
| AT03 | Allergen safety (guardrails scenario 6) | A request excluding milk (`AM`) is offered only products declaring `AM: FREE_FROM`, and the report shows them. A plan that still contained milk would be `DENY` under GR-S1 with the observed allergen state (guardrails T06). |
| AT04 | Approval rejected | Outcome `REJECTED`; the reason appears in the report |
| AT05 | Approval expired, re-quote used up | Outcome `EXPIRED`; timeline shows `approval.expired` and `requote.started` |
| AT06 | No candidates | Outcome `UNFULFILLABLE`; candidate counts show where the funnel became empty |
| AT07 | Upstream API returns HTTP 500 | Outcome `FAILED` / `upstream_unavailable`; the report is still generated |
| AT08 | Process killed mid-transaction | Events up to the crash are present; the watchdog later closes with `FAILED` / `abandoned` |
| AT09 | One payload byte changed in the database | Verification fails at that `seq` |
| AT10 | One event deleted | Verification fails (gap in `seq` / `prevHash` mismatch) |
| AT11 | Buyer view of a transaction with `valio` events | Stubs have no payload, and the chain still verifies |
| AT12 | Rendering the same transaction twice | Byte-identical output |
| AT13 | Search the stored payloads for the API key and access tokens | No match |
| AT14 | `UPDATE audit_events …` executed directly | Rejected by trigger |
| AT15 | Report of guardrails scenario 2 | Every presented plan has a rationale; the selected plan has a selection rationale; 464398 appears under "not presented" with the diversity reason |
| AT16 | A plan carries a rationale code that the template does not know | The raw code is shown; rendering does not fail |

---

## 11. Implementation notes

| Topic | Guidance |
|---|---|
| Module layout | `backend/app/audit/`: `events.py` (envelope and payload models), `chain.py` (JCS, hashing), `store.py` (SQLite, single writer, triggers), `checkpoint.py`, `verify.py`, `render.py` (Jinja2 templates in `templates/`), `watchdog.py` |
| Single entry point | All modules log through one function, `audit.append(type, transactionId, actor, payload, visibility)`. No module writes to the table directly. |
| Canonical JSON | Use an RFC 8785 implementation. Money is serialised as strings (`"1010.00"`) so canonicalisation never sees binary floats. |
| Clock | Inject the clock, so that tests are deterministic and reports byte-identical (AT12) |
| Performance | Appending is synchronous: it is cheap and guarantees L1. Report rendering runs after `transaction.closed` and MUST NOT delay the response to the agent. |

# Guardrails and Human Approval

> Which purchasing decisions an agent may take on its own, which need a person's sign-off, and which are never allowed. Every case is defined precisely enough to implement and test.

This document is the **implementation baseline** for the guardrail layer. It builds on two earlier documents:

- [`trust-protocol.md`](trust-protocol.md) defines the **mandate**: the buyer organisation's signed grant of authority to its agent, including its `limits`.
- [`fulfilment-and-substitution.md`](fulfilment-and-substitution.md) produces the **plans** (Best / Second / Third) together with their `flags`, `deviations` and `scores`.

The guardrail layer sits between the two. It takes a plan and decides whether the agent may place it as an order.

The key words **MUST**, **MUST NOT**, **SHOULD** and **MAY** are used as defined in RFC 2119.

---

## 1. Position in the flow

```
 Purchase request
      │
      ▼
 Fulfilment & substitution  ──►  ranked plans (flags, deviations, scores)
      │
      ▼
 ┌──────────────── Guardrail engine (this document) ────────────────┐
 │  inputs: plan · request · mandate · policy · context             │
 │  output: ALLOW  |  ESCALATE(role)  |  DENY   + reasons           │
 └───────┬──────────────────────┬──────────────────────┬────────────┘
         │ ALLOW                │ ESCALATE             │ DENY
         ▼                      ▼                      ▼
   Order placed           Approval request       Not orderable;
   autonomously           to a person (§8)       reason returned
```

---

## 2. Decision model

### 2.1 Three outcomes

| Outcome | Meaning | Who may proceed |
|---|---|---|
| `ALLOW` | Within the agent's delegated authority | The agent, autonomously |
| `ESCALATE` | Acceptable, but beyond the agent's authority | A person holding the required role (§2.2) |
| `DENY` | Not acceptable for this order, whoever approves it | No one, through this flow. The plan must change. |

**`DENY` is not a stronger form of `ESCALATE`.** Escalation is about *authority*: a person may accept a larger spend or a brand change. Denial is about *safety and validity*: no approver can make an allergen-unsafe plan safe, or an expired offer valid.

### 2.2 Approver roles

| Role | Typical holder | May approve |
|---|---|---|
| `approver` | Kitchen manager, head chef | Every escalation that requires `approver` |
| `admin` | Procurement manager, finance | Every escalation, including those that require `admin` |

Roles are ordered `approver < admin`. A person with a higher role MAY approve anything a lower role may.

### 2.3 Principles

| # | Principle | Consequence |
|---|---|---|
| G1 | **Fail closed** | Missing or invalid input produces `DENY` (for validity) or `ESCALATE` (for authority), never `ALLOW`. |
| G2 | **Deny dominates** | One `DENY` rule makes the whole outcome `DENY`. Otherwise one `ESCALATE` makes it `ESCALATE`. |
| G3 | **Evaluate everything** | Every rule is evaluated, with no short-circuiting, so the explanation lists *all* reasons, not only the first. |
| G4 | **Silence is not consent** | An approval request that is not answered expires. It is never approved by timeout. |
| G5 | **Deterministic** | The same inputs always produce the same outcome. Rules are pure functions of their inputs. |
| G6 | **Everything is logged** | Every evaluation and every human decision is written to the audit log (trust protocol, §7). |
| G7 | **Defence in depth** | Some rules repeat checks the fulfilment layer already performs, such as allergens. The guardrail layer MUST NOT assume an upstream filter worked. |

---

## 3. Inputs

The engine is a pure function:

```
evaluate(plan, request, mandate, policy, context) -> Decision
```

| Input | Source | Fields used |
|---|---|---|
| `plan` | Fulfilment output (§11 of that document) | `items[]` (`productId`, `category`, `salesUnits`, `quantity`, `availableDate`, `unitPrice`, `lineTotal`, `status`, `tier`, `sim`, `allergens`, `claims`, `reliability`, `offerId`, `offerValidUntil`, `closingTime`, `confirmedSalesUnits`), `total`, `strategy`, `coverage`, `flags[]`, `deviations[]`, `scores.total`, `rank` |
| `request` | Standard purchase request | `lines[].quantity`, `lines[].spec.requiredAttributes`, `lines[].spec.excludedAllergens`, `lines[].maxUnitPrice` (optional), `deliverBy` |
| `mandate` | Verified mandate (trust protocol, §4.2) | `exp`, `revoked`, `authorization_details[].actions`, `.limits` |
| `policy` | Buyer organisation's guardrail policy (§4) | All parameters |
| `context` | Runtime state | `now`, `autoOrdersLast24h`, `periodSpendEUR`, `referenceUnitCost` per line |

Lines are evaluated individually, and order-level rules (spend, velocity) are evaluated on the assembled order (§6.2).

**Contract with the fulfilment layer.** The plan output shown in the fulfilment document (its §11) is a summary. For the guardrail engine, every plan item MUST also carry the item fields listed above: `category`, `status`, `tier` (`exact`, `S0`–`S3`), `sim`, the four-state `allergens`, `claims`, `reliability`, `confirmedSalesUnits`, `offerId`, `offerValidUntil` and `closingTime`. The guardrail engine MUST NOT look these values up itself. It judges exactly the plan it was given.

---

## 4. Policy configuration

The policy is owned by the **buyer organisation**. The mandate carries the core limits, and the policy adds the finer rules. Where both define a value, **the mandate wins**, because it is the signed statement of authority.

```json
{
  "policyId": "pol_hotel123_v1",
  "version": 1,
  "spend": {
    "autoLimitEUR": 2000,
    "approverLimitEUR": 5000,
    "periodBudgetEUR": null,
    "maxUnitPriceIncreasePct": 10
  },
  "quantity": {
    "maxQtyPerLine": 1500,
    "maxAutoProductsPerLine": 2
  },
  "delivery": {
    "deliverWithinDays": 14,
    "minReliabilityForUnconfirmed": 0.95
  },
  "substitution": {
    "autoSubstitution": true,
    "autoTiers": ["S0", "S1"],
    "minSimilarity": 0.80,
    "flexibleAttributes": ["brand", "pack_size"]
  },
  "scope": {
    "categories": ["104"]
  },
  "selection": {
    "toleranceScore": 0.05
  },
  "velocity": {
    "maxAutoOrdersPerDay": 10
  },
  "approval": {
    "deadlineBufferMinutes": 30,
    "maxRequoteAttempts": 1
  }
}
```

| Parameter | Default | Mandate field that overrides it |
|---|---|---|
| `spend.autoLimitEUR` | 2000 | `limits.maxOrderValueEUR` |
| `spend.approverLimitEUR` | 5000 | — |
| `spend.periodBudgetEUR` | `null` (rule disabled) | — |
| `spend.maxUnitPriceIncreasePct` | 10 | — |
| `quantity.maxQtyPerLine` | none (rule disabled) | `limits.maxQtyPerLine` |
| `quantity.maxAutoProductsPerLine` | 2 | — |
| `delivery.deliverWithinDays` | 14 | `limits.deliverWithinDays` |
| `delivery.minReliabilityForUnconfirmed` | 0.95 | — |
| `substitution.autoSubstitution` | `true` | — |
| `substitution.autoTiers` | `["S0", "S1"]` | — |
| `substitution.minSimilarity` | 0.80 | — |
| `substitution.flexibleAttributes` | `["brand", "pack_size"]` | — |
| `scope.categories` | none (all allowed) | `limits.categories` |
| `selection.toleranceScore` | 0.05 | — |
| `velocity.maxAutoOrdersPerDay` | 10 | — |
| `approval.deadlineBufferMinutes` | 30 | — |
| `approval.maxRequoteAttempts` | 1 | — |

`quantity.maxQtyPerLine` is expressed in the **unit of the request line** (L, KG or PCS). Entries in `scope.categories` match category codes by **prefix**: `"104"` covers every 5-digit category starting with `104`, and `"10400"` covers that category only.

---

## 5. Rule catalogue

Every rule has a stable **ID** (used in code, tests and logs), a **scope** (`order`, `line` or `item`), a precise **trigger**, an **outcome**, and a **reason code** returned to the agent and the human.

### 5.1 Authority: is the agent allowed to act at all?

| ID | Scope | Trigger | Outcome | Reason code |
|---|---|---|---|---|
| GR-A1 | order | Mandate missing, signature invalid, `exp` ≤ `now`, or revoked | `DENY` | `mandate_invalid` |
| GR-A2 | order | `"order.place"` not in mandate `actions` | `DENY` | `action_not_permitted` |
| GR-A3 | item | `scope.categories` is set and the item's `category` matches no entry | `ESCALATE(admin)` | `category_out_of_scope` |
| GR-A4 | item | `availableDate` > `now` + `deliverWithinDays` | `ESCALATE(approver)` | `beyond_delivery_horizon` |

### 5.2 Safety: never negotiable

| ID | Scope | Trigger | Outcome | Reason code |
|---|---|---|---|---|
| GR-S1 | item | For any allergen in the line's `excludedAllergens`, the item's state is `contains`, `may_contain` or `not_declared` | `DENY` | `allergen_violation` |
| GR-S2 | item | The item's claims do not include every entry in the line's `requiredAttributes` | `DENY` | `required_attribute_missing` |

### 5.3 Validity: can this plan actually be ordered?

| ID | Scope | Trigger | Outcome | Reason code |
|---|---|---|---|---|
| GR-V1 | item | `now` ≥ `offerValidUntil` | `DENY` (remedy: `requote`) | `offer_expired` |
| GR-V2 | item | `status` ∈ {`not_deliverable`, `blocked`, `no_price`}, or `tier` = `S3` | `DENY` | `item_not_orderable` |
| GR-V3 | item | `salesUnits` > `confirmedSalesUnits` (when the quantity is known) | `DENY` | `exceeds_confirmed_quantity` |
| GR-V4 | item | The item has the flag `cutoff_passed` | `ESCALATE(approver)` | `cutoff_passed` |

`offer_expired` carries the remedy `requote`: the agent MAY re-run fulfilment autonomously, up to `maxRequoteAttempts` times, and then re-evaluate. No human decision is needed for that.

### 5.4 Money

| ID | Scope | Trigger | Outcome | Reason code |
|---|---|---|---|---|
| GR-M1 | order | `orderTotal` > `autoLimitEUR` | `ESCALATE(approver)` | `spend_over_auto_limit` |
| GR-M2 | order | `orderTotal` > `approverLimitEUR` | `ESCALATE(admin)` | `spend_over_approver_limit` |
| GR-M3 | line | The line's effective unit cost (per L, KG or PCS) > `referenceUnitCost` × (1 + `maxUnitPriceIncreasePct` / 100) | `ESCALATE(approver)` | `unit_price_increase` |
| GR-M4 | order | `periodBudgetEUR` is set and `periodSpendEUR` + `orderTotal` > `periodBudgetEUR` | `ESCALATE(admin)` | `period_budget_exceeded` |

`orderTotal` excludes VAT, matching the prices in the plans. The **reference unit cost** for GR-M3 is, in order of precedence:

1. the line's `maxUnitPrice` from the request;
2. the quoted unit cost of the requested product (`productId`), even if that product cannot deliver;
3. the cheapest quoted exact-match product.

If none of these exists, GR-M3 is not evaluated, and the decision records that it was skipped.

### 5.5 Quantity and fulfilment

| ID | Scope | Trigger | Outcome | Reason code |
|---|---|---|---|---|
| GR-Q1 | line | The requested quantity > `maxQtyPerLine` | `ESCALATE(approver)` | `quantity_over_mandate` |
| GR-Q2 | line | Plan `coverage` < 100 % (flag `partial`) | `ESCALATE(approver)` | `partial_fulfilment` |
| GR-Q3 | item | The item has the flag `overfill` (beyond silent tolerance) | `ESCALATE(approver)` | `excess_overfill` |
| GR-Q4 | line | Number of distinct products in the line > `maxAutoProductsPerLine` | `ESCALATE(approver)` | `too_many_products` |

### 5.6 Delivery

| ID | Scope | Trigger | Outcome | Reason code |
|---|---|---|---|---|
| GR-D1 | item | `availableDate` > `deliverBy` (flag `later_delivery`) | `ESCALATE(approver)` | `later_delivery` |
| GR-D2 | item | The item has the flag `quantity_unconfirmed`, and its reliability is missing or < `minReliabilityForUnconfirmed` | `ESCALATE(approver)` | `unconfirmed_low_reliability` |

### 5.7 Substitution: "outside stated preferences"

These rules apply only to items that are substitutes, meaning their `tier` is not `exact`.

| ID | Scope | Trigger | Outcome | Reason code |
|---|---|---|---|---|
| GR-X1 | item | `autoSubstitution` = `false` | `ESCALATE(approver)` | `substitution_needs_approval` |
| GR-X2 | item | `tier` ∉ `autoTiers` (by default this means `S2`) | `ESCALATE(approver)` | `substitution_tier` |
| GR-X3 | item | `sim` < `minSimilarity` | `ESCALATE(approver)` | `low_similarity` |
| GR-X4 | item | The item has a `deviation` on an attribute that is **not** in `flexibleAttributes` | `ESCALATE(approver)` | `inflexible_deviation` |

This is the challenge's "substitutions outside stated preferences". The buyer states in advance which attributes may change without asking (`flexibleAttributes`), and anything else needs sign-off.

### 5.8 Data quality and anomalies

| ID | Scope | Trigger | Outcome | Reason code |
|---|---|---|---|---|
| GR-T1 | item | The item has the flag `content_uncertain` | `ESCALATE(approver)` | `content_uncertain` |
| GR-T2 | order | `autoOrdersLast24h` ≥ `maxAutoOrdersPerDay` | `ESCALATE(admin)` | `unusual_order_velocity` |

`reliability_no_data` is **informational only**. It is shown to the human but does not trigger a rule, because the fulfilment ranking already penalises it.

---

## 6. Evaluation algorithm

### 6.1 Single plan

```
function evaluate(plan, request, mandate, policy, context):
    limits  = merge(policy, mandate.limits)         # mandate wins (§4)
    results = []
    for rule in RULES ordered by ID:                 # G3: no short-circuit
        if rule.scope == "order": results += rule.check(plan, ...)
        if rule.scope == "line":  results += [rule.check(line, ...) for line in plan.lines]
        if rule.scope == "item":  results += [rule.check(item, ...) for item in plan.items]
    triggered = [r for r in results if r.triggered]

    if any(r.outcome == DENY for r in triggered):
        outcome, role = DENY, null
    elif any(r.outcome == ESCALATE for r in triggered):
        outcome, role = ESCALATE, max(r.role for r in triggered if r.outcome == ESCALATE)
    else:
        outcome, role = ALLOW, null

    return Decision(outcome, role, triggered, skipped, policyVersion, inputsDigest)
```

Each rule result records its ID, its outcome, its role, its reason code, the line or item it concerns, the observed value and the limit, so that every message can be rendered precisely. For example: *"Order total €3,030.00 exceeds the autonomous limit of €2,000.00."*

### 6.2 Multi-line orders

1. Run plan selection (§7) **per line**, using line- and item-scope rules only.
2. Assemble the order from the selected plan of each line.
3. Evaluate the order-scope rules (GR-A1, GR-A2, GR-M1, GR-M2, GR-M4, GR-T2) on the assembled order.
4. The order's outcome is the aggregate (G2) of all line outcomes and the order-level outcome. If any line or the order escalates, **the whole order** goes to approval. Partially auto-ordering some lines is out of scope for version 1.

---

## 7. Plan selection: which plan may the agent order on its own?

The fulfilment layer ranks plans by quality. The guardrail layer decides which of them the agent may act on. For each line:

1. Evaluate the guardrails for every plan. A fulfilled line has one plan; a substitution line has up to three.
2. **If the top-ranked plan is `ALLOW`**, select it autonomously.
3. **Else, if a lower-ranked plan is `ALLOW`** and its `scores.total` ≥ the top plan's score − `selection.toleranceScore`, select that plan autonomously. The reason is recorded as `equivalent_plan_within_tolerance`.
4. **Else, if any plan is not `DENY`**, create an approval request (§8) that contains every non-`DENY` plan. The recommended plan is the highest-ranked non-`DENY` plan, and the required role is the highest role among the presented plans' escalations.
5. **Else** (every plan is `DENY`): the line is `unfulfillable`. If a denial carries the remedy `requote`, re-quote first (§5.3).

Step 3 lets the agent avoid needless escalation when an almost-as-good plan is within its authority. The tolerance keeps the agent from trading away real quality just to stay autonomous.

---

## 8. Approval workflow

### 8.1 States

```
                ┌──────────────► AUTO_APPROVED ──────────────┐
                │                                            ▼
 DRAFT ──► EVALUATED ──► PENDING_APPROVAL ──► APPROVED ──► ORDER_SUBMITTED
                │              │   │   │
                │              │   │   └──► REJECTED
                │              │   └──────► EXPIRED  ──► (re-quote → new DRAFT)
                │              └──────────► SUPERSEDED (modified → new DRAFT)
                └──────────────► DENIED
```

| State | Entered when |
|---|---|
| `EVALUATED` | Guardrails have run on the selected plan(s) |
| `AUTO_APPROVED` | Selection resolved to an `ALLOW` plan (§7, steps 2–3) |
| `PENDING_APPROVAL` | Selection reached step 4 |
| `APPROVED` | A person with a sufficient role approved one of the presented plans, and re-evaluation passed (§8.3) |
| `REJECTED` | The person rejected the request. A reason is required. |
| `EXPIRED` | The deadline (§8.2) passed without a decision (G4) |
| `SUPERSEDED` | The person changed the request, for example the quantity or the date. A new draft is created and evaluated from scratch. |
| `DENIED` | Every plan was `DENY` |
| `ORDER_SUBMITTED` | The order was placed with references to the signed offers |

### 8.2 Approval request

```json
{
  "approvalId": "apr_5c21",
  "orderDraftId": "ord_d_88",
  "requiredRole": "approver",
  "deadline": "2026-11-15T16:30:00+02:00",
  "recommendedPlanRank": 1,
  "plans": [{
    "rank": 1, "label": "best", "strategy": "full_substitute", "total": 1010.00,
    "guardrail": { "outcome": "ESCALATE", "requiredRole": "approver",
      "reasons": [{ "rule": "GR-X4", "code": "inflexible_deviation",
                    "message": "Brand changes from Arla to Valio; brand is not a flexible attribute in your policy." }] }
  }],
  "createdAt": "2026-11-14T21:10:00+02:00"
}
```

The **deadline** is the earliest of every presented item's `offerValidUntil` and `closingTime`, minus `deadlineBufferMinutes`. An approval that arrives after the cut-off could not be delivered on time anyway.

### 8.3 Human decisions

| Action | Effect |
|---|---|
| `approve(planRank)` | The engine **re-evaluates** that plan with the approver's role in `context`. `ESCALATE` rules whose required role ≤ the approver's role are satisfied. Any `DENY`, for example an offer that expired while waiting, still blocks the order. In that case the request moves to `EXPIRED`, and the agent re-quotes. |
| `reject(reason)` | The request is closed. The agent MUST NOT place any of the presented plans. |
| `modify(changes)` | The request becomes `SUPERSEDED`. A new draft goes through fulfilment and guardrails from scratch. |

An approver MUST NOT approve a request whose `requiredRole` is above their own role. Every decision records the approver's identity, role, time and the chosen plan.

### 8.4 Order submission

The challenge's mock environment offers price and availability APIs but no ordering API. In the demo, the gateway therefore records submitted orders itself, with references to the signed offers (trust protocol, §6.1) and the approval record. In production, this step would call Valio Aimo's order system.

---

## 9. Decision output

```json
{
  "decisionId": "dec_7a10",
  "planRef": { "requestId": "req_001", "lineId": "L1", "rank": 1 },
  "outcome": "ESCALATE",
  "requiredRole": "approver",
  "triggered": [{
    "rule": "GR-M1", "scope": "order", "outcome": "ESCALATE", "role": "approver",
    "code": "spend_over_auto_limit",
    "observed": 3030.00, "limit": 2000.00, "unit": "EUR",
    "message": "Order total €3,030.00 exceeds the autonomous limit of €2,000.00."
  }],
  "skipped": [],
  "informational": ["reliability_no_data"],
  "policy": { "policyId": "pol_hotel123_v1", "version": 1 },
  "mandate": "mdt_7f3c9a",
  "inputsDigest": "sha256:…",
  "evaluatedAt": "2026-11-14T21:10:00+02:00"
}
```

`inputsDigest` is a hash of the canonical JSON (RFC 8785) of the plan, request, policy and the relevant part of the context. Together with `policy.version`, it lets anyone reproduce and verify the decision later.

---

## 10. Audit

These events are appended to the hash-chained audit log (trust protocol, §7):

| Event | Content |
|---|---|
| `guardrail.evaluated` | The full Decision (§9) |
| `plan.selected` | Selected plan, selection step (§7), and the reason |
| `approval.requested` | Approval request (§8.2) |
| `approval.decided` | Approver identity and role, action, chosen plan, time |
| `approval.expired` | Approval ID and deadline |
| `order.submitted` | Order ID, offer IDs, approval ID (or `auto`) |

Together these give both the buyer and Valio Aimo one readable answer to *"why was this ordered, and who allowed it?"*.

---

## 11. Worked scenarios: real data

Data: the milk example from the fulfilment document, live prices from 2026-11-14 (VAT excluded), and the default policy from §4. `deliverBy` is 2026-11-16. The requested product's reference unit cost is €2.48/L.

| # | Request | Selected / presented plan | Rules triggered | Outcome |
|---|---|---|---|---|
| 1 | 1,000 L lactose-free semi-skimmed milk (spec only) | Fulfilled: 1,000 L of 464306, €1,010.00 | — | **`ALLOW`**: ordered autonomously |
| 2 | 1,000 L of Arla 469363 specifically (384 L available) | Best: full substitute 464306, €1,010.00. Deviation: brand. `sim` 0.82, tier S1, €1.01/L. | — (brand is flexible; unit cost below €2.48 × 1.10) | **`ALLOW`**: ordered autonomously |
| 3 | As #2, but the policy has `flexibleAttributes: []` | All three plans deviate on brand | GR-X4 on every plan | **`ESCALATE(approver)`**: approval request with all three plans; Best recommended |
| 4 | 3,000 L (spec only) | Fulfilled: 3,000 L of 464306, €3,030.00 | GR-M1 (€3,030 > €2,000); GR-Q1 (3,000 L > 1,500 L) | **`ESCALATE(approver)`** |
| 5 | 6,000 L (spec only) | Fulfilled: 6,000 L of 464306, €6,060.00 | GR-M1, GR-M2 (€6,060 > €5,000), GR-Q1 | **`ESCALATE(admin)`** |
| 6 | 1,000 L lactose-free milk for a guest with a **milk allergy** (`excludedAllergens: ["AM"]`) | Any milk plan. 464306 declares `AM: CONTAINS`. | GR-S1 | **`DENY`**: lactose-free is not milk-free. No approver can override this. |
| 7 | As #4, but no one responds before the approval deadline (2026-11-15 16:30, i.e. 30 minutes before the 17:00 cut-off) | Pending request | G4 | **`EXPIRED`**: never approved by silence. The agent re-quotes and creates a new approval request. |

Scenario 6 shows why safety rules are `DENY` and not `ESCALATE`. A tired approver clicking "approve" must not be able to send milk to a milk-allergic guest.

---

## 12. Acceptance test cases

Unless stated otherwise, each case starts from scenario 1 in §11 (`ALLOW`) and changes one input. The implementation MUST pass all of them.

| # | Change from baseline | Expected outcome | Expected rules |
|---|---|---|---|
| T01 | None | `ALLOW` | — |
| T02 | Mandate `exp` in the past | `DENY` | GR-A1 |
| T03 | Mandate `actions` lacks `order.place` | `DENY` | GR-A2 |
| T04 | `scope.categories = ["106"]` | `ESCALATE(admin)` | GR-A3 |
| T05 | `availableDate` = `now` + 20 days, `deliverBy` = `now` + 30 days | `ESCALATE(approver)` | GR-A4 |
| T06 | `excludedAllergens: ["AM"]` | `DENY` | GR-S1 |
| T07 | Item allergen state `not_declared` for an excluded allergen | `DENY` | GR-S1 |
| T08 | `requiredAttributes: ["FREE_FROM_GLUTEN"]`; the item lacks it | `DENY` | GR-S2 |
| T09 | `now` > `offerValidUntil` | `DENY` (remedy `requote`) | GR-V1 |
| T10 | Item status `not_deliverable` | `DENY` | GR-V2 |
| T11 | `salesUnits` 1,000 > `confirmedSalesUnits` 384 | `DENY` | GR-V3 |
| T12 | Item flag `cutoff_passed` | `ESCALATE(approver)` | GR-V4 |
| T13 | `orderTotal` = 2,000.00 (exactly the limit) | `ALLOW` | — (the limit is inclusive) |
| T14 | `orderTotal` = 2,000.01 | `ESCALATE(approver)` | GR-M1 |
| T15 | `orderTotal` = 5,000.01 | `ESCALATE(admin)` | GR-M1, GR-M2 |
| T16 | Unit cost €2.73/L against reference €2.48/L (+10.1 %) | `ESCALATE(approver)` | GR-M3 |
| T17 | No reference unit cost available | `ALLOW`, with GR-M3 in `skipped` | — |
| T18 | `periodBudgetEUR` 5,000, `periodSpendEUR` 4,500, order €1,010 | `ESCALATE(admin)` | GR-M4 |
| T19 | Requested 1,600 L, `maxQtyPerLine` 1,500 | `ESCALATE(approver)` | GR-Q1 |
| T20 | Plan `coverage` 38.4 % | `ESCALATE(approver)` | GR-Q2 |
| T21 | Three products in one line | `ESCALATE(approver)` | GR-Q4 |
| T22 | `availableDate` one day after `deliverBy` | `ESCALATE(approver)` | GR-D1 |
| T23 | `quantity_unconfirmed`, reliability missing | `ESCALATE(approver)` | GR-D2 |
| T24 | `quantity_unconfirmed`, reliability 0.97 | `ALLOW` | — |
| T25 | Substitute with `autoSubstitution: false` | `ESCALATE(approver)` | GR-X1 |
| T26 | Substitute of tier S2 | `ESCALATE(approver)` | GR-X2 |
| T27 | Substitute with `sim` 0.79 | `ESCALATE(approver)` | GR-X3 |
| T28 | Substitute deviating on `origin` (not flexible) | `ESCALATE(approver)` | GR-X4 |
| T29 | Substitute deviating on `brand` (flexible), `sim` 0.82, tier S1 | `ALLOW` | — |
| T30 | `autoOrdersLast24h` = 10 | `ESCALATE(admin)` | GR-T2 |
| T31 | GR-S1 and GR-M1 both triggered | `DENY`, and **both** rules listed | GR-S1, GR-M1 (G2, G3) |
| T32 | Best plan `ESCALATE` (score 0.92); second plan `ALLOW` (score 0.88) | Second plan selected autonomously | Selection step 3 |
| T33 | Best plan `ESCALATE` (score 0.92); second plan `ALLOW` (score 0.81) | Approval request with both plans | Selection step 4 |
| T34 | Approver with role `approver` approves a request requiring `admin` | Refused | §8.3 |
| T35 | Approval arrives after the offer expired | `EXPIRED`, followed by a re-quote | GR-V1, §8.3 |
| T36 | No decision before the deadline | `EXPIRED`, never `APPROVED` | G4 |

Limits are **inclusive**: a value equal to a limit is within it (T13). Every comparison of money uses amounts rounded to cents.

---

## 13. Implementation notes

| Topic | Guidance |
|---|---|
| Module layout | `backend/app/guardrails/`: `models.py` (Decision, RuleResult, Policy), `rules.py` (one pure function per rule ID), `engine.py` (`evaluate`, aggregation), `selection.py` (§7), `approvals.py` (state machine, §8) |
| Rule registry | Rules are registered by ID in a single ordered list. Adding a rule means adding one function and its test cases. No other code changes. |
| Policy loading | Policies are versioned JSON validated against a JSON Schema. Unknown fields are rejected, so a typo cannot silently disable a rule. |
| Money | Use `Decimal`, never binary floats, for all monetary comparisons. |
| Time | Use timezone-aware datetimes. API times carry an offset (e.g. `+0200`). `now` is injected through `context` so tests are deterministic. |
| Tests | Every case in §12 is one automated test, named after its number (`test_T14_spend_just_over_auto_limit`). |
| Messages | Reason codes are stable API values. Human-readable messages are templates filled with `observed` and `limit`, and may be localised (fi / sv / en). |

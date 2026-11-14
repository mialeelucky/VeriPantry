# Fulfilment and Substitution Algorithm

> Given a standardised purchase request, find the best way to fulfil it. If the request cannot be met as asked, propose a ranked **Best / Second best / Third best** set of alternatives, each with a clear explanation of how it differs from what was asked.

This document describes the decision logic only. Human approval and guardrails are a separate layer, added later. To prepare for it, every plan produced here carries the flags that layer will need (§12).

The algorithm is **deterministic**. The same request, static data and API responses always produce the same plans in the same order. An LLM may be used upstream, to turn natural language into the standard request, and downstream, to phrase explanations. It plays no part in selecting or ranking plans.

---

## 1. Pipeline overview

```
 Standard request (§2)
   │
   ▼
 1. Normalise        quantities → measurable units; dates; hard vs soft constraints
 2. Retrieve         static catalog → "exact-match set" for each line
 3. Hard-filter      allergens, required claims, unit convertibility
 4. Shortlist + live lookup    ≤ N candidates → availability + price APIs (batched)
 5. Assess feasibility         per product: on time? how much? confirmed?
 6. Optimal plan     can the exact-match set fulfil the line? → cheapest valid plan
        │ yes → return it (status: fulfilled)
        │ no  ↓
 7. Substitution     find compatible substitutes, score similarity
 8. Plan generation + ranking  → Best / Second / Third, with explanations
   │
   ▼
 Response to customer (§11)
```

Stages 1–3 use only the static data in `data/` and cost nothing. Stage 4 is the only stage that calls the live APIs. It is called only for a short, pre-filtered list, as the API provider requires. Stage 7 may trigger one additional live lookup, for the substitute shortlist.

---

## 2. Input: the standard purchase request

A request has one or more **lines**. Each line describes *what* is needed, either as a specific product or as a specification, plus *how much* and *by when*.

```json
{
  "requestId": "req_001",
  "customer": "HOTEL-123",
  "deliverBy": "2026-11-16",
  "lines": [{
    "lineId": "L1",
    "productId": "469363",
    "spec": {
      "query": "semi-skimmed milk",
      "category": "10400",
      "requiredAttributes": ["FREE_FROM_LACTOSE"],
      "excludedAllergens": [],
      "preferredAttributes": ["brand:Arla", "fat:1.5"]
    },
    "quantity": { "value": 1000, "unit": "L" }
  }],
  "preferences": {
    "weights": { "fit": 0.45, "cost": 0.30, "reliability": 0.15, "sustainability": 0.10 },
    "allowSplit": true,
    "allowLaterDelivery": true
  }
}
```

| Field | Meaning |
|---|---|
| `productId` | Optional. The buyer wants this exact product. If it is absent, any product matching `spec` is an exact match. |
| `spec.requiredAttributes` | **Hard constraints.** Never relaxed, not even for a substitute. |
| `spec.excludedAllergens` | **Hard constraints.** GS1 allergen codes, e.g. `AM` (milk) or `AW` (gluten cereals). |
| `spec.preferredAttributes` | **Soft constraints.** Respected where possible. A deviation lowers the score and is reported in the explanation. |
| `quantity.unit` | `L`, `KG` or `PCS` (consumer units). |
| `deliverBy` | The latest acceptable delivery date. |
| `preferences` | Optional overrides of the default weights and allowed strategies. |

**The hard/soft split is the core of the substitution logic.** Hard constraints define what is *safe and acceptable*. Soft constraints define what is *preferred*. A substitute must satisfy every hard constraint, and the soft constraints decide how good it is.

---

## 3. Data used and how it behaves

### 3.1 Static data (`data/`)

| Purpose | Source fields |
|---|---|
| Identity and text matching | `id`; `synkkaData.names[]` (fi / en / sv); `synkkaData.brand` |
| Category hierarchy | `category`: a 5-digit code. 349 categories group into 43 families by their first 3 digits (e.g. `104xx` = milk, cream and dairy alternatives). |
| Dietary claims (hard or soft) | `classifications[name=nutritionalClaim]`, e.g. `FREE_FROM_LACTOSE` (4,178 products), `FREE_FROM_GLUTEN`, `VEGAN`, `LOW_LACTOSE` |
| Allergens (hard) | `classifications[name=allergen / nonAllergen]`: GS1 codes with `CONTAINS`, `MAY_CONTAIN`, `FREE_FROM` or `UNDECLARED` |
| Labels (soft) | `classifications[name=packagingMarkedLabel]`, e.g. `EU_ORGANIC_FARMING`, `GOODS_FROM_FINLAND_BLUE_SWAN`, `MARINE_STEWARDSHIP_COUNCIL_LABEL` |
| Nutrition (similarity) | `nutritionalContent[]` per 100 g/ml: `FAT`, `PRO-`, `CHOAVL`, `SUGAR-`, `LACS` (lactose) |
| Quantity conversion | `salesUnit`, `baseUnit`, `units[].sizeInBaseUnits`, `allowedLotSize`, `unitConversions[BASE_UNIT_OR_EACH].volume / netWeight` |
| Official substitutes | `substitutions[]`: 250 links on 189 products, mostly fresh produce; 230 of them stay within the same category |
| Delivery reliability | `delivery_reliability.csv`: 0–1, available for 4,425 products |
| Carbon footprint | `carbon_footprint.csv`: kg CO₂-eq per kg, available for 11,033 products |

### 3.2 Live APIs: observed behaviour

We probed the availability and price APIs on 2026-11-14, using a random sample of 300 products and three requested dates. The algorithm is built on the observed behaviour below, not only on the documentation.

| Observation | Algorithm rule |
|---|---|
| `availableDate` is the **earliest** possible date and does not depend on `requestedDate`. Asking for an earlier date returns a later date; asking for a later date returns the same earliest date. | The line is on time when `availableDate ≤ deliverBy`. |
| About 14 % of products return **no schedule line** and no `logisticModel`. | `not_deliverable` |
| Some schedule lines have `availableAmount = 0` and no date. | `not_deliverable` |
| Supplier-direct (`Terminal`) products always report `999999`, a placeholder meaning the quantity is unknown. | `quantity_unconfirmed`: usable, but penalised (§9) |
| Some stocked (`Stock`) products report sentinel values such as `9999999999` or `666666666`. | Values ≥ 10⁸ are treated as *ample stock*. |
| Many `closingTime` values (the order cut-off) are **already in the past** while the product still shows a date. | `cutoff_passed`: the date is no longer guaranteed (§7.2) |
| `comparisonPrice` (per L or KG) is missing for about 25 % of products, typically those sold by the piece. | Quantity conversion falls back to static data (§4). |
| Price `error = true` is possible. | `no_price`: the product is excluded from plans. |

---

## 4. Stage 1: normalise the request

### 4.1 Content per sales unit

To compare a request in litres with products sold in cartons, the algorithm needs the content of one sales unit, `content(SU)`, in L, KG or PCS. Sources are tried in this order, and the first that succeeds wins:

1. **Static unit data:** base-unit volume or net weight from `unitConversions[BASE_UNIT_OR_EACH]` × `sizeInBaseUnits` of the sales unit in `units[]`.
   *Example: 469330 has `KI` = 5 × `ST`, and a 1 L `ST` → 5 L per `KI`.*
2. **Product name parsing:** size tokens such as `1 l`, `5 dl`, `2,5 dl`, `200g`, `10 L novobox`, `12x397g`. About 81 % of names contain one.
3. **Price ratio (live):** `catalogPrice ÷ comparisonPrice`, when the price API returns a comparison price. This is used as a cross-check of sources 1–2. A disagreement above 5 % sets the flag `content_uncertain`.
4. Otherwise the product is usable only for `PCS` requests.

L and KG are **never** converted into each other, because density is unknown.

### 4.2 Order quantity

```
units_needed(product) = ceil_to_lot( required_quantity / content(SU), allowedLotSize )
overfill              = units_needed × content(SU) − required_quantity
```

An overfill of up to `max(5 %, one sales unit)` is accepted silently. A larger overfill is allowed, but it is reported, and its cost counts against the plan.

---

## 5. Stage 2: retrieve candidates (static)

For each line, the **exact-match set** is defined as:

- if `productId` is given: just that product;
- otherwise: every product that is in `spec.category` (or in the category of `productId`), satisfies all `requiredAttributes`, and matches `spec.query` in at least one language (fi / en / sv), using token match on names with simple Finnish stems, e.g. *maito* = milk.

The **substitute pool** is built later (§8.1), and only if it is needed.

## 6. Stage 3: hard filters

A product is removed from both the exact-match set and the substitute pool if any of these is true:

| Filter | Rule |
|---|---|
| Required attribute missing | The product's claims do not include every item in `requiredAttributes` |
| Excluded allergen | The allergen is `CONTAINS` or `MAY_CONTAIN`, **or is not declared at all**. Only an explicit `FREE_FROM` passes. "Unknown" never counts as safe. |
| Unit not convertible | `content(SU)` cannot be expressed in the requested unit (§4.1) |

---

## 7. Stages 4–5: shortlist, live lookup and feasibility

### 7.1 Shortlist and batching

- The exact-match set is capped at **N = 30** per line, ranked by static similarity (§8.2) and then by name-match strength.
- All lines in a request share **one** availability call and **one** price call, well within the 1,000-product limit per call.
- Responses are cached for 5 minutes per (product, date), so repeated plan generation does not re-query.

This keeps API usage proportional to the request, never to the catalog.

### 7.2 Feasibility status per product

| Status | Condition | Usable in plans? |
|---|---|---|
| `on_time` | `availableDate ≤ deliverBy`, cut-off not passed, quantity known | Yes |
| `on_time_partial` | As above, but the confirmed quantity is less than `units_needed` | Yes, for the confirmed quantity |
| `quantity_unconfirmed` | `Terminal` product (`999999`), date OK | Yes, with a penalty and a flag |
| `cutoff_passed` | `closingTime` < now: the stated date is no longer guaranteed | Only in *later-delivery* plans |
| `late` | `availableDate > deliverBy` | Only in *later-delivery* plans |
| `not_deliverable` | No schedule line, or amount 0 | No |
| `blocked` | `salesBlock = true` | No |
| `no_price` | Price `error = true` | No |

**Cut-off interpretation.** The API documentation defines `closingTime` as the latest order time for delivery on `availableDate`. When it has passed, we do not promise that date. This is the *strict* policy, which is the default and follows the trust principle "never promise what is not confirmed". The mock environment appears to keep cut-off times static, so a `lenient` setting exists for demonstrations. Under `lenient`, such products are treated as `on_time` but keep the `cutoff_passed` flag.

---

## 8. Stages 6–7: optimal plan, then substitution

### 8.1 When the request can be met: optimal plan

If products in the exact-match set can together deliver the full quantity on time, the line is **fulfilled**, and no substitution is proposed.

The optimal plan minimises total cost, excluding VAT, subject to quantity and date:

1. Sort the usable exact-match products by **effective unit cost**: price per sales unit ÷ `content(SU)`, including overfill.
2. Take the cheapest product up to its confirmed quantity. If more is needed and `allowSplit` is true, continue with the next cheapest.
3. Apply a **split penalty** (§9). A one-product plan that is less than 3 % more expensive beats a two-product plan.
4. Tie-breakers, in order: higher reliability, lower carbon footprint, fewer order lines, then lower product id (for determinism).

When `productId` names a specific product and that product can deliver everything, it is the plan. Cheaper equivalents are reported as information only and are never swapped in silently.

### 8.2 When it cannot: building the substitute pool

Substitution is triggered when the exact-match set cannot deliver the full quantity on time, because it is short on quantity, late, not deliverable, or blocked. Substitute candidates are collected in tiers, from closest to furthest:

| Tier | Source | Example |
|---|---|---|
| **S0: Official** | `substitutions[]` links from the requested product | Tomato NL/BE/ES → Tomato Finland |
| **S1: Same category** | Same 5-digit `category`, all hard constraints met | Arla lactose-free semi-skimmed 1 L → Valio lactose-free semi-skimmed 1 L |
| **S2: Same family** | Same 3-digit category family, all hard constraints met | Category 10400 (milk) → 10406 (plant-based cooking products), only if the product passes every hard constraint |
| **S3: Cross-family** | **Not used automatically.** Different families rarely serve the same kitchen purpose. | — |

The pool is hard-filtered (§6), ranked by static similarity, and capped at **N = 30**. It then gets one live lookup (§7.1) and a feasibility assessment (§7.2).

### 8.3 Similarity score `sim(candidate, reference)` ∈ [0, 1]

The reference is the requested product, or, for a spec-only request, the best exact-match product.

| Component | Weight | Computation |
|---|---|---|
| Category | 0.30 | 1 for the same category or an official S0 link; 0.5 for the same family; 0 otherwise |
| Attributes | 0.25 | Share of the reference's soft attributes preserved: claims, labels, origin, preferred attributes in the request |
| Nutrition | 0.15 | 1 − normalised distance over `FAT`, `PRO-`, `CHOAVL`, `SUGAR-` per 100 g/ml; 0.5 if data is missing |
| Pack format | 0.10 | 1 − min(1, \|log₁₀(size ratio)\|). Portion packs and 10 L bag-in-box are different products for a kitchen, even when the content is identical. |
| Name | 0.10 | Token overlap of names after removing brand and size tokens |
| Brand | 0.10 | 1 for the same brand, 0 otherwise. If the request makes brand a *hard* constraint, other brands never enter the pool. |

An official S0 link gets a floor of `sim ≥ 0.8`, because Valio Aimo has already approved it as a substitute.

---

## 9. Stage 8: plan generation and ranking

### 9.1 Plan strategies

Alternatives are complete **plans**, not single products. A plan may combine products:

| Strategy | Description |
|---|---|
| **Split** | Take everything the exact-match set can deliver on time, and fill the remainder with the best substitute |
| **Full substitute** | Fill the whole quantity with one substitute, avoiding a split delivery |
| **Multi-substitute** | Fill the remainder with two substitutes, when no single substitute has enough quantity |
| **Later delivery** | The exact product, delivered on its earliest available date after `deliverBy` (if `allowLaterDelivery`) |
| **Partial** | Deliver only what is possible on time. This is offered only when nothing better exists, and it is always flagged. |

### 9.2 Plan score

Each plan receives four component scores, each normalised to [0, 1]:

| Component | Definition |
|---|---|
| **Fit** | Quantity-weighted `sim` over the plan's lines. Exact-match lines count as 1. |
| **Cost** | `cheapest plan cost ÷ this plan cost`, across all generated plans for the line |
| **Reliability** | Quantity-weighted delivery reliability. Missing data counts as **0.9**, a neutral value just below the data-set mean of 0.97, and the plan is flagged. `quantity_unconfirmed` lines are multiplied by 0.9. |
| **Sustainability** | Quantity-weighted `1 − CO₂ / 30.46`, where 30.46 kg CO₂-eq/kg is the data set's maximum, plus 0.1 for an eco or organic label, capped at 1. Missing data counts as 0.5. A fixed scale keeps the score comparable between requests. |

```
score = w_fit·Fit + w_cost·Cost + w_rel·Reliability + w_sus·Sustainability
        − 0.03 × (number of products − 1)              # split penalty
```

The default weights are `fit 0.45, cost 0.30, reliability 0.15, sustainability 0.10`. The customer can override them through `preferences.weights`, and a buyer agent can expose them as "what matters most to you".

### 9.3 Ranking rules

Ranking is lexicographic. Score alone never puts an incomplete plan above a complete one:

1. **Complete and on time**, ranked by score
2. **Complete but later**, ranked by delivery date, then score
3. **Partial**, ranked by covered quantity, then score

The top three plans become **Best / Second best / Third best**. Three rules keep the three useful:

- **Product diversity.** Two plans must differ in at least one product that covers ≥ 20 % of the quantity. Near-duplicates are dropped.
- **Strategy diversity.** At most two of the three plans may use the same strategy. If another strategy produced a valid plan, the best such plan takes the third place. This way the customer always sees a genuinely different trade-off, for example "keep your brand for part of the order", rather than three variations of one idea.
- **Honesty.** If fewer than three acceptable plans exist, fewer are returned, together with the reason. Plans are never padded with poor options.

---

## 10. Worked example: real data

The buyer asks for 1,000 L of a specific product, **469363 Arla semi-skimmed milk drink 1 L UHT lactose-free**, by Monday 2026-11-16. The live data below was queried on 2026-11-14 at 21:00. Prices exclude VAT.

**Stages 4–5: the requested product is only partly available.** 469363 is a stocked product with 384 units (= 384 L) available on 2026-11-16 and a cut-off at 2026-11-15 17:00, which has not passed. Its status is `on_time_partial`, short by 616 L. Because the request names a specific product, the exact-match set contains only 469363 (§5), and **substitution is triggered**. Two other Arla lactose-free semi-skimmed products exist (469330, 5 × 1 L, and 464179, 10 L bag-in-box). Both are supplier-direct products whose cut-off (2026-11-12) has already passed, so they are `cutoff_passed` and can appear only in later-delivery plans.

**Stage 7: substitute pool (S1, category 10400, `FREE_FROM_LACTOSE`).** All candidates have the same fat content (1.5 g/100 ml), the same Finnish-origin label and a 1 L pack. The brand differs from the request, and names and minor nutrition values differ slightly. `sim` is computed with the weights in §8.3:

| Product | Status | Price / L | Reliability | `sim` |
|---|---|---|---|---|
| 464306 Valio Arki Eila semi-skimmed milk drink 1 L, lactose-free | on time, ample stock | €1.01 | 1.00 | 0.82 |
| 464201 Valio semi-skimmed milk 1 L UHT, lactose-free | on time, ample stock | €1.56 | 1.00 | 0.83 |
| 464398 Valio Eila semi-skimmed milk drink 1 L UHT, lactose-free | on time, ample stock | €1.65 | 1.00 | 0.84 |

**Stage 8: plans.** All products have the same carbon footprint (1.1 kg CO₂-eq/kg), so every plan gets the same sustainability score (0.96).

| Rank | Plan | Cost | Fit | Cost score | Reliability | Score |
|---|---|---|---|---|---|---|
| **Best** | Full substitute: 1,000 L of 464306 (Valio Arki Eila) | €1,010.00 | 0.82 | 1.00 | 1.00 | **0.92** |
| **Second** | Full substitute: 1,000 L of 464201 (Valio, UHT) | €1,560.00 | 0.83 | 0.65 | 1.00 | **0.81** |
| **Third** | Split: 384 L of 469363 (Arla, as requested) + 616 L of 464306 | €1,574.48 | 0.89 | 0.64 | 0.96 | **0.80** |
| *(not shown)* | Full substitute: 1,000 L of 464398 (Valio Eila, UHT) | €1,650.00 | 0.84 | 0.61 | 1.00 | 0.81 |

Scores use the default weights and include the split penalty. They are rounded to two decimals.

Plan 464398 scores marginally higher than the split plan (0.809 against 0.805). It is not shown because of the **strategy-diversity rule** (§9.3): two full-substitute plans are already listed, and the split plan is the only option that keeps the requested brand.

What the customer is told:

- **Best:** a different brand (Valio instead of Arla) with the same lactose-free, 1.5 % fat, 1 L specification. One product, delivered in full on Monday, and the cheapest option by €550 or more.
- **Second:** a Valio UHT (long-life) product with the same specification and the closest name match. Choose this if long shelf life matters.
- **Third:** the only option that keeps the requested brand, for 38 % of the quantity. It costs more and arrives as two product lines. The Arla part has no delivery-reliability data.

If the buyer had made *brand: Arla* a **hard** constraint, the Valio products would never enter the pool. The result would then be a **partial** plan (384 L on time) plus a **later-delivery** plan for the remainder, both flagged for the buyer's decision.

---

## 11. Output to the customer

```json
{
  "requestId": "req_001",
  "lines": [{
    "lineId": "L1",
    "status": "substitution_proposed",
    "reason": { "code": "insufficient_quantity", "requested": 1000, "availableOnTime": 384, "unit": "L" },
    "plans": [{
      "rank": 1, "label": "best", "strategy": "full_substitute",
      "items": [{ "productId": "464306", "salesUnits": 1000, "salesUnit": "ST",
                  "quantity": { "value": 1000, "unit": "L" }, "availableDate": "2026-11-16",
                  "unitPrice": 1.01, "lineTotal": 1010.00 }],
      "total": { "value": 1010.00, "currency": "EUR", "vatExcluded": true },
      "scores": { "fit": 0.82, "cost": 1.00, "reliability": 1.00, "sustainability": 0.96, "total": 0.92 },
      "deviations": [ { "attribute": "brand", "requested": "Arla", "proposed": "Valio" } ],
      "flags": ["substitution"],
      "explanation": "Same lactose-free 1.5 % 1 L milk from Valio; full quantity on Monday; lowest cost."
    }]
  }]
}
```

| Line `status` | Meaning |
|---|---|
| `fulfilled` | The exact-match set covers the line in full and on time. One optimal plan is returned. |
| `substitution_proposed` | Not possible as asked. Up to three ranked alternative plans are returned. |
| `unfulfillable` | No acceptable plan exists within the hard constraints. The reasons are given per candidate status. |

Every plan states its **deviations** from the request and its **flags**, so a person can see the trade-off at a glance.

---

## 12. Hooks for the later approval and guardrails layer

The ranking is independent of authorisation. The approval layer will consume these plan flags and decide what the agent may accept on its own:

| Flag | Raised when |
|---|---|
| `substitution` | Any line uses a product other than the exact match |
| `split` | A line uses more than one product |
| `later_delivery` | Any item arrives after `deliverBy` |
| `partial` | The plan covers less than the requested quantity |
| `quantity_unconfirmed` | A supplier-direct item's quantity is unknown |
| `cutoff_passed` | Lenient cut-off policy was applied |
| `reliability_no_data`, `content_uncertain`, `overfill` | Data-quality warnings |

---

## 13. Parameters (defaults)

| Parameter | Default |
|---|---|
| Plan weights (fit / cost / reliability / sustainability) | 0.45 / 0.30 / 0.15 / 0.10 |
| Similarity weights (category / attributes / nutrition / pack / name / brand) | 0.30 / 0.25 / 0.15 / 0.10 / 0.10 / 0.10 |
| Shortlist size per line (exact / substitute) | 30 / 30 |
| Split penalty per extra product | 0.03 |
| Silent overfill tolerance | max(5 %, 1 sales unit) |
| Sentinel threshold for "ample stock" | ≥ 10⁸ |
| Missing reliability / missing carbon | 0.9 / 0.5 |
| Cut-off policy | `strict` |
| Availability cache TTL | 5 minutes |

All parameters are configuration values, not code. They are published so that buyers and their agents can understand, and challenge, how plans are ranked.

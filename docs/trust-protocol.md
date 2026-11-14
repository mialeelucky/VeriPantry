# VeriPantry Trust Protocol

> How an external purchasing agent and Valio Aimo can trust each other, without Valio Aimo giving its data away.

---

## 1. The problem

When a purchasing agent (not a person) orders from a wholesaler, both sides need to answer questions that a human buyer answers by habit:

| Direction | Question | Answered by |
|---|---|---|
| Valio Aimo → agent | *Who are you, who do you act for, and what are you allowed to do?* | Identity and mandate (§4) |
| Valio Aimo's data | *What may this agent see, and how much of it?* | Data tiers and disclosure rules (§5) |
| Agent → Valio Aimo | *Can I rely on this price, stock and origin claim without a human checking it?* | Signed offers and provenance (§6) |
| Both | *What happened, and can anyone rewrite that record later?* | Tamper-evident audit log (§7) |

A plain API key answers none of these. It identifies a *caller*, not a *principal*. It carries no limits. It proves nothing about the responses. And it lets any holder pull as much data as rate limits allow. The VeriPantry Trust Protocol is the set of rules that does answer them, built only from open, documented standards.

---

## 2. Design principles

| # | Principle | What it means in practice |
|---|---|---|
| P1 | **Structured interface; natural language at the edge** | Valio Aimo exposes typed, schema-described operations. Natural language is turned into structured requests on the *buyer's* side, by the buyer's agent. The wholesaler never executes free text. |
| P2 | **Answer questions; don't hand over data** | An agent asks *"can you deliver 1,000 L by Monday?"*, not *"how much stock do you have?"*. The answer reveals no more than the question needs. |
| P3 | **Every commitment is signed** | A price or availability statement the agent may act on is a signed, time-limited offer. Anyone can verify it with Valio Aimo's public key. |
| P4 | **"Unknown" is a first-class value** | Missing data is reported as unknown. It is never silently turned into a reassuring default such as "allergen-free" or "in stock". |
| P5 | **Least privilege, explicit limits** | An agent can do only what its buyer organisation granted it, within stated amounts, quantities and dates. |
| P6 | **Open standards only** | OAuth 2.x, JOSE (JWS/JWK), OpenAPI 3.1, JSON Schema and GS1 identifiers. No proprietary token or envelope formats. |
| P7 | **Content is data, never instructions** | Supplier-written text (marketing copy, instructions) is returned in clearly typed fields and marked untrusted. This protects the agent from prompt injection. |

---

## 3. Architecture and roles

```
 Buyer organisation (e.g. hotel chain)
   │  issues a signed MANDATE to its own agent  (§4)
   ▼
 Buyer agent  ── natural language from humans is parsed HERE (P1)
   │  structured, signed, key-bound requests over HTTPS
   ▼
┌──────────────── VeriPantry Gateway (Valio Aimo side) ────────────────┐
│ 1 Authenticate   2 Authorise    3 Minimise      4 Sign      5 Log    │
│   agent key        mandate        data tiers     offers      hash    │
│   + mandate        + limits       + disclosure   (JWS)       chain   │
└───────────────────────────────┬──────────────────────────────────────┘
                                │  Valio Aimo's own credentials (never shared)
                                ▼
            Upstream systems: price & availability APIs, static catalog,
            delivery-reliability and carbon-footprint data sets
```

| Role | Responsibility |
|---|---|
| **Buyer organisation** | A Valio Aimo customer. It registers a signing key once and issues mandates to its agents. |
| **Buyer agent** | Any third-party software agent. It holds its own key pair and acts only within its mandate. |
| **VeriPantry Gateway** | The single entry point for agents. It is deterministic code with no LLM in the decision path. It enforces every rule in this document. |
| **Upstream systems** | Valio Aimo's internal price, availability and catalog sources. Agents never reach them directly. |

**Why the gateway matters.** The upstream APIs are protected by a single Valio Aimo API key. They return raw values, such as exact stock amounts, and are meant to be queried only for narrowed-down product lists. Giving that key to external agents would expose everything to everyone. The gateway keeps the key server-side and decides, per request, what a given agent may learn.

**About the demo's agent.** For the demo we ship a *reference buyer agent*. It uses an LLM to turn a buyer's sentence, for example "1,000 litres of lactose-free milk by Monday", into a structured request. It talks to the gateway **only through the same public interface any third-party agent would use**. It holds no privileged access, so it can be replaced by anyone else's agent.

---

## 4. Identity and delegated authority

### 4.1 One-time onboarding (out of band)

1. The buyer organisation is an existing Valio Aimo customer. It registers a public signing key (JWK, RFC 7517) with Valio Aimo, for example through the webshop admin.
2. Each buyer agent generates its own key pair. The private key never leaves the agent.

### 4.2 The mandate

A **mandate** is a signed statement from the buyer organisation. In effect it says: *"this agent may act for us, and only like this."* It is a JWT (RFC 7519) signed by the buyer organisation's key. Its permissions use the OAuth Rich Authorization Requests structure (`authorization_details`, RFC 9396).

```json
{
  "iss": "customer:HOTEL-123",
  "sub": "agent:hotel-123-procurement-01",
  "aud": "https://api.veripantry.example",
  "jti": "mdt_7f3c9a",
  "iat": 1794787200,
  "exp": 1795392000,
  "cnf": { "jkt": "0ZcOCORZNYy-DWpqq30jZyJGHTN0d2HglBV3uiguA4I" },
  "authorization_details": [{
    "type": "veripantry_procurement",
    "actions": ["catalog.search", "offer.request", "order.place"],
    "limits": {
      "maxOrderValueEUR": 2000,
      "maxQtyPerLine": 1500,
      "categories": ["10400"],
      "deliverWithinDays": 14
    }
  }]
}
```

| Claim | Purpose |
|---|---|
| `iss` | The buyer organisation that grants authority. Optionally a `did:web` identifier. |
| `sub` | The agent receiving authority. |
| `cnf.jkt` | Thumbprint (RFC 7638) of the agent's public key. A stolen mandate is useless without the matching private key. |
| `exp` | Mandates are short-lived and renewable, not permanent. |
| `authorization_details` | What the agent may do (`actions`) and within which bounds (`limits`). |

### 4.3 Session tokens

1. The agent presents its mandate to the gateway's token endpoint, using the JWT bearer grant (RFC 7523).
2. The gateway checks the mandate's signature against the buyer organisation's registered key. It also checks expiry, audience and revocation.
3. The gateway issues a **short-lived access token** (minutes, not days). The token is bound to the agent's key with **DPoP** (RFC 9449). Every request carries a fresh DPoP proof signed by the agent, so an intercepted token cannot be replayed by someone else.

### 4.4 Enforcement and machine-readable refusals

On every call the gateway checks that the action is in `actions` and that the request falls within `limits`. A request that exceeds the mandate is refused with an RFC 9457 *Problem Details* response that says exactly why:

```json
{
  "type": "https://api.veripantry.example/problems/mandate-limit-exceeded",
  "title": "Request exceeds mandate limit",
  "status": 403,
  "limit": "maxQtyPerLine",
  "allowed": 1500,
  "requested": 2400,
  "mandate": "mdt_7f3c9a"
}
```

A precise refusal is what allows a **human-approval step** later: the buyer's agent knows exactly which limit it hit and can route the decision to a person instead of failing blindly. The buyer organisation can **revoke** a mandate at any time, and the gateway checks revocation on every token issuance.

---

## 5. Data access: tiers and disclosure rules

### 5.1 Three data tiers

Field names below are those of the challenge's product data set (17,546 products).

| Tier | Who sees it | Fields |
|---|---|---|
| **T0: Catalog** | Any registered agent | `id`; product names (fi / en / sv); `category`; `brand`; `salesUnit`, `baseUnit`, `units[]`, `allowedLotSize`; GTINs; allergen, nutrition, label and claim classifications; nutrition facts; ingredients; storage temperature class; country of origin; deposits; carbon footprint (kg CO₂-eq/kg) |
| **T1: Customer** | Agents holding a valid mandate with the matching action | Price (`catalogPrice`, tax, comparison price); availability expressed as *fulfilment* (§5.3); order cut-off (`closingTime`); delivery-reliability band; Valio Aimo's own substitution suggestions |
| **T2: Internal** | Never exposed to agents | `vendorName`; producer location numbers (`producers[].id`); exact stock quantities of stocked products; raw delivery-reliability scores; upstream credentials |

**Why T2 stays internal.**

- **`vendorName` and producer IDs.** These would let an agent bypass the wholesaler and contact suppliers directly. Who owns the customer relationship is exactly what the challenge brief calls existential. Brand and origin, which buyers legitimately need, remain visible.
- **Exact stock levels.** They are commercially sensitive and change constantly. Agents need to know whether an order can be fulfilled, not the warehouse count.
- **Raw reliability scores.** A band such as *high / medium / low* is enough to support a decision. Precise per-product scores expose internal logistics performance.

### 5.2 Why tiers alone are not enough

A tiered catalog still lets a well-authorised agent scrape every price, or probe stock levels by asking repeatedly. The disclosure rules below close those gaps. They also turn the upstream system's own guidance ("query only the products you need") into enforced protocol.

### 5.3 Disclosure rules

| Rule | Description |
|---|---|
| **R1: Question-shaped availability** | Availability is requested *for a quantity and a date*. The answer is a fulfilment status: `full`, `partial`, `none` or `unconfirmed`. The quantity disclosed is **at most the quantity requested**, and the requested quantity cannot exceed the mandate's `maxQtyPerLine`. An agent therefore learns whether its need can be met, never the full stock level. |
| **R2: Bounded search** | Searches require a query or filter and return a capped number of results (e.g. 25). There is no "list everything with prices" operation. |
| **R3: Session-bound pricing** | Prices and offers can be requested only for products that appeared in a search earlier in the same session (`searchId`), and only in small batches. Bulk price harvesting becomes impossible, not merely rate-limited. |
| **R4: Published budgets** | Each mandate has query quotas (searches per hour, offer lines per day). They are published in the discovery document (§8), so agents can plan around them. |
| **R5: Declared purpose** | Each request states a purpose (e.g. `quote_for_order`). The purpose is recorded in the audit log (§7). |

### 5.4 Example: the same fact, before and after the gateway

Upstream availability response (internal, simplified):

```json
{ "productId": "469330", "logisticModel": "Stock",
  "scheduleLines": [{ "availableAmount": 4812, "availableDate": "2026-11-16", "salesUnit": "KI" }] }
```

What the buyer agent receives for *"1,000 L by 2026-11-16"*:

```json
{ "productId": "469330", "fulfilment": "full",
  "requested": { "value": 1000, "unit": "L" },
  "confirmed": { "value": 1000, "unit": "L", "salesUnits": 200, "salesUnit": "KI" },
  "availableDate": "2026-11-16", "stockBasis": "warehouse" }
```

Product 469330 in the data set is a 1 L lactose-free semi-skimmed milk sold in cartons (`KI`) of five 1 L packs (`units[].sizeInBaseUnits = 5`), so 1,000 L = 200 cartons. The stock amount and date are illustrative. The agent gets everything it needs to decide, and nothing it doesn't need.

For products delivered directly from a supplier's warehouse, the upstream system reports a placeholder amount (`999999`) because the real figure is not known. The gateway reports these honestly as `"fulfilment": "unconfirmed", "stockBasis": "supplier-direct"`, together with the product's delivery-reliability band (see P4).

---

## 6. Verifiable claims: why the agent can trust Valio Aimo

### 6.1 Signed offers

Every price and availability answer that an agent may act on is returned as an **offer**: a JSON object signed with JWS (RFC 7515, algorithm EdDSA/Ed25519).

```json
{
  "offerId": "off_2b81d4",
  "iss": "https://api.veripantry.example",
  "sub": "customer:HOTEL-123",
  "aud": "agent:hotel-123-procurement-01",
  "mandate": "mdt_7f3c9a",
  "productId": "469330",
  "quantity": { "value": 200, "salesUnit": "KI" },
  "unitPrice": { "value": 14.20, "valueWithTax": 16.12, "currency": "EUR" },
  "tax": { "taxRate": 13.5 },
  "fulfilment": "full",
  "availableDate": "2026-11-16",
  "closingTime": "2026-11-14T14:00:00+02:00",
  "validUntil": "2026-11-14T14:00:00+02:00",
  "auditRef": { "seq": 1042, "hash": "b6e1…" }
}
```

(Values are illustrative.) Valio Aimo publishes its public keys at `/.well-known/jwks.json`, identified by `kid` so keys can be rotated. To trust an offer, an agent:

1. verifies the JWS signature against the published key;
2. checks that `aud` and `sub` are itself and its customer, so offers cannot be transplanted between buyers;
3. checks that `validUntil` has not passed;
4. stores the signed offer as evidence.

**Commitment semantics.** An order that references a valid `offerId` before `validUntil` is accepted at the offered price. This is the challenge's *fixed price, not negotiated quote* model: the signed offer *is* the price commitment. No human has to re-check it, and neither side can later dispute what was offered.

### 6.2 Provenance on product claims

Catalog data comes from sources with different levels of authority. The gateway labels each claim group with its **source** and **as-of time** instead of presenting everything as equally certain:

| Source label | Covers | Meaning |
|---|---|---|
| `valio-master-data` | Units, lot sizes, temperature class, category | Valio Aimo's own operational data |
| `gs1-synkka` | Names, allergens, nutrition, ingredients, origin, labels | Declared by the manufacturer through GS1 Synkka. Includes the manufacturer's `lastUpdated` timestamp. Valio Aimo relays it; it does not certify it. |
| `valio-delivery-stats` | Delivery-reliability band | Historical delivery performance |
| `carbon-dataset` | kg CO₂-eq per kg | Product-level footprint data set provided for the challenge |

Catalog responses can be signed in the same way as offers. An agent can then show an auditor exactly which origin or allergen statement it relied on.

### 6.3 Four-state allergen claims

In the data, allergen information is a list of declarations, each marked `CONTAINS`, `MAY_CONTAIN` or `FREE_FROM`. If an allergen is simply not mentioned, that is **not** evidence that the product is free from it. The gateway therefore reports every allergen in one of four states:

| State | Meaning |
|---|---|
| `contains` | The manufacturer declares the allergen is present |
| `may_contain` | The manufacturer warns of possible cross-contamination |
| `free_from` | The manufacturer declares the product is free from it |
| `not_declared` | No statement either way. An agent with a strict allergen constraint (school, hospital) must treat this as unsafe. |

### 6.4 Honest uncertainty

| Situation in the data | How the gateway reports it |
|---|---|
| Supplier-direct products with unknown stock (`999999`) | `unconfirmed`, plus the delivery-reliability band |
| Delivery-reliability data exists for only ~25 % of products (4,425 of 17,546) | `reliability: "no_data"`, never an assumed 100 % |
| Carbon footprint available for ~63 % of products (11,033) | `carbonFootprint: null` with reason, never an estimate presented as fact |
| Catalog VAT codes are inconsistent (e.g. `"MEDIUM MEDIUM"`, empty values) | The tax rate is taken only from the price system and is labelled as authoritative there |

---

## 7. Audit trail

Every gateway decision is appended to a **hash-chained log**. This includes authentications, searches, offers issued, refusals and (later) orders and approvals.

```
entry_n = { seq, time, customer, agent, mandate, action, purpose,
            requestDigest, outcome, offerId?, reason? }
hash_n  = SHA-256( hash_{n-1} || JCS(entry_n) )      # JCS = RFC 8785 canonical JSON
```

- **Receipts.** Every response carries `auditRef = { seq, hash }`. The buyer agent keeps these as receipts.
- **Tamper evidence.** Changing or deleting any past entry breaks every later hash. A buyer can verify that their receipts still match the chain.
- **Checkpoints.** The gateway periodically signs the latest hash. These signed checkpoints let a third party verify the log without seeing its contents.
- **Two audiences.** The same log can be rendered as a readable timeline for the buyer ("what did my agent do, and why?") and for Valio Aimo ("what did this agent ask for, and what did we disclose?").

---

## 8. Discovery: the rules are published, not hidden

Agents should not need a sales call to learn the rules. The gateway publishes a machine-readable description at `/.well-known/agent-interface.json`:

```json
{
  "issuer": "https://api.veripantry.example",
  "openapi": "https://api.veripantry.example/openapi.json",
  "jwks_uri": "https://api.veripantry.example/.well-known/jwks.json",
  "token_endpoint": "https://api.veripantry.example/oauth/token",
  "grant_types": ["urn:ietf:params:oauth:grant-type:jwt-bearer"],
  "token_binding": "DPoP",
  "authorization_details_types": ["veripantry_procurement"],
  "actions": ["catalog.search", "offer.request", "order.place"],
  "data_tiers": { "T0": "catalog", "T1": "customer", "T2": "internal" },
  "limits": { "search_results_max": 25, "offer_lines_per_request_max": 50 },
  "offer_signing": { "format": "JWS", "alg": "EdDSA" },
  "audit": { "chain": "sha256+jcs", "receipts": true },
  "terms": "https://api.veripantry.example/terms"
}
```

The full operation set is described in OpenAPI 3.1, with JSON Schema for every request and response.

---

## 9. Threat model

| Threat | Mitigation |
|---|---|
| An agent impersonates a customer | Mandate signed by the customer's registered key (§4.2) |
| A stolen token or mandate is reused | Key binding through `cnf.jkt` and DPoP; short token lifetime; revocation (§4.3–4.4) |
| An authorised agent exceeds its authority | Per-request checks against `actions` and `limits`; precise refusals (§4.4) |
| Bulk scraping of the price list | Bounded search, session-bound pricing, published quotas (R2–R4) |
| Probing exact stock levels | Question-shaped availability with disclosure capped at the requested quantity (R1) |
| Bypassing the wholesaler to reach suppliers | `vendorName` and producer IDs stay internal (T2) |
| A forged or altered offer | JWS signature verifiable with published keys (§6.1) |
| An offer replayed by another buyer | `sub` and `aud` bind the offer to one customer and one agent |
| A dispute over what was offered or done | Signed offers plus a hash-chained audit log with receipts (§6.1, §7) |
| Prompt injection through supplier-written product text | Free text returned only in typed, untrusted fields; the gateway never interprets agent free text (P1, P7) |
| Misleading safety claims from missing data | Four-state allergens; explicit `unknown` / `no_data` (§6.3–6.4) |

---

## 10. Standards used

| Need | Standard |
|---|---|
| Interface description | OpenAPI 3.1, JSON Schema 2020-12 |
| Keys and signatures | JWK (RFC 7517), JWS (RFC 7515), EdDSA (RFC 8037), JWK thumbprint (RFC 7638) |
| Delegation and tokens | JWT (RFC 7519), JWT bearer grant (RFC 7523), Rich Authorization Requests (RFC 9396), DPoP (RFC 9449) |
| Errors | Problem Details (RFC 9457) |
| Canonical hashing | JSON Canonicalization Scheme (RFC 8785), SHA-256 |
| Product identity and data | GS1 GTIN; GS1 Synkka product attributes |
| Optional decentralised identity | `did:web`; W3C Verifiable Credentials 2.0 as a drop-in mandate format |

Every element can be implemented with off-the-shelf libraries in any mainstream language. A buyer agent does not need any VeriPantry-specific SDK.

---

## 11. Assumptions and limitations

- **Customer-specific data.** In the challenge's mock environment, prices and availability do not depend on the customer number. The protocol nevertheless treats them as customer-specific (T1), because they are in production.
- **Onboarding.** Registering a buyer organisation's key happens out of band, through the existing customer relationship. This document does not define a self-service onboarding flow.
- **Manufacturer data.** GS1 Synkka attributes are declared by manufacturers. Valio Aimo labels their source; it does not independently verify them.
- **The data set itself.** It is synthetic and inspired by real data, provided for Junction 2026 only.
- **Tier choices are proposals.** Which fields belong in T1 or T2 is ultimately a business decision for Valio Aimo. The tier model makes that decision explicit and configurable rather than accidental.

---

## 12. Demo scope and path to production

| Component | Junction demo | Production |
|---|---|---|
| Mandate | Ed25519-signed JWT with RAR-style `authorization_details` | Same format; optionally issued as a W3C Verifiable Credential |
| Agent authentication | Mandate plus key check | Adds the full DPoP proof on every request and mTLS between known partners |
| Data tiers and disclosure rules | Implemented in the gateway | Same rules, managed as configurable policy |
| Signed offers | Ed25519 JWS; keys in configuration | Keys in an HSM or cloud KMS, with scheduled rotation |
| Audit log | Hash chain in a local database, with receipts | Append-only store with externally anchored checkpoints |
| Discovery | Static `agent-interface.json` and OpenAPI | Versioned, with a deprecation policy |
| Buyer agent | Reference LLM agent that uses only the public interface | Any third-party agent; optional MCP adapter over the same operations |

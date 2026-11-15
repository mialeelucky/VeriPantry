import { describe, expect, it } from "vitest";
import { ApiProblem } from "../api/client";
import type { TransactionSummary } from "../api/types";
import { deviationValue, money, preferenceLabel, qty } from "./format";
import { verifyOffer } from "./jws";
import { problemMessage } from "./problems";
import { outcomeBadge, summaryPill } from "./status";

describe("status mapping (one colour per meaning)", () => {
  it("maps guardrail outcomes to tones and words", () => {
    expect(outcomeBadge("ALLOW")).toEqual({ tone: "ok", text: "Within your agent's authority" });
    expect(outcomeBadge("ESCALATE", "admin")).toEqual({ tone: "attention", text: "Needs Finance Lead" });
    expect(outcomeBadge("DENY").tone).toBe("stop");
  });

  it("names who decided an order", () => {
    const base = { outcome: "ORDERED", decidedBy: "agent" } as TransactionSummary;
    expect(summaryPill(base).text).toBe("Ordered by agent");
    expect(summaryPill({ ...base, decidedBy: "Head Chef" }).text).toBe("Approved by Head Chef");
    expect(summaryPill({ ...base, outcome: "PENDING_APPROVAL", requiredRole: "approver" }).tone).toBe("attention");
  });
});

describe("problem messages", () => {
  it("turns gateway problems into sentences", () => {
    const p = new ApiProblem(403, { type: "https://api.veripantry.example/problems/insufficient-role", title: "x", detail: "Requires admin." });
    expect(problemMessage(p)).toBe("This needs a higher role. Requires admin.");
    expect(problemMessage(new ApiProblem(409, { type: ".../approval-not-pending" }))).toMatch(/already decided/);
    expect(problemMessage(new Error("boom"))).toBe("Something went wrong. Try again.");
  });
});

describe("formatting", () => {
  it("formats money and quantities with units", () => {
    expect(money("3030.00")).toBe("€3,030.00");
    expect(qty({ value: "1000.0", unit: "L" })).toBe("1,000 L");
    expect(preferenceLabel("brand:Arla")).toBe("Arla");
    expect(preferenceLabel("fat:1.5")).toBe("1.5 % fat");
    expect(deviationValue("fat", "0.0")).toBe("0.0 % fat");
  });
});

describe("offer signature check", () => {
  const b64url = (bytes: ArrayBuffer | Uint8Array) =>
    btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

  async function signedOffer(payload: object) {
    const pair = (await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"])) as CryptoKeyPair;
    const jwk = { ...(await crypto.subtle.exportKey("jwk", pair.publicKey)), kid: "gw-test" };
    const h = b64url(new TextEncoder().encode(JSON.stringify({ alg: "EdDSA", kid: "gw-test" })));
    const p = b64url(new TextEncoder().encode(JSON.stringify(payload)));
    const s = b64url(await crypto.subtle.sign({ name: "Ed25519" }, pair.privateKey, new TextEncoder().encode(`${h}.${p}`)));
    return { jws: `${h}.${p}.${s}`, jwk };
  }

  it("accepts a valid signature and rejects a changed payload", async () => {
    const { jws, jwk } = await signedOffer({ offerId: "off_1", unitPrice: { value: "1.01" } });
    expect((await verifyOffer(jws, [jwk])).valid).toBe(true);
    const [h, , s] = jws.split(".");
    const forged = `${h}.${b64url(new TextEncoder().encode(JSON.stringify({ offerId: "off_1", unitPrice: { value: "0.01" } })))}.${s}`;
    expect((await verifyOffer(forged, [jwk])).valid).toBe(false);
    expect((await verifyOffer(jws, [])).reason).toBe("Unknown signing key");
  });
});

// Verify a signed offer (compact JWS, EdDSA/Ed25519) in the browser against the
// gateway's published keys (frontend.md §5.1, "Offer check"). Web Crypto only.

const b64urlToBytes = (s: string): Uint8Array<ArrayBuffer> => {
  const pad = "=".repeat((4 - (s.length % 4)) % 4);
  const bin = atob((s + pad).replace(/-/g, "+").replace(/_/g, "/"));
  const out = new Uint8Array(new ArrayBuffer(bin.length));
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
};

export interface OfferCheck {
  valid: boolean;
  payload?: Record<string, any>;
  reason?: string;
}

export async function verifyOffer(jws: string, keys: JsonWebKey[]): Promise<OfferCheck> {
  try {
    const [h, p, s] = jws.split(".");
    const header = JSON.parse(new TextDecoder().decode(b64urlToBytes(h)));
    const jwk = keys.find((k: any) => k.kid === header.kid);
    if (!jwk) return { valid: false, reason: "Unknown signing key" };
    if (header.alg !== "EdDSA") return { valid: false, reason: "Unexpected algorithm" };
    const key = await crypto.subtle.importKey("jwk", { kty: "OKP", crv: "Ed25519", x: (jwk as any).x }, { name: "Ed25519" }, false, ["verify"]);
    const ok = await crypto.subtle.verify({ name: "Ed25519" }, key, b64urlToBytes(s), new TextEncoder().encode(`${h}.${p}`));
    const payload = JSON.parse(new TextDecoder().decode(b64urlToBytes(p)));
    return ok ? { valid: true, payload } : { valid: false, reason: "Signature does not match" };
  } catch (e) {
    return { valid: false, reason: e instanceof Error ? e.message : "Could not check the signature" };
  }
}

export { b64urlToBytes };

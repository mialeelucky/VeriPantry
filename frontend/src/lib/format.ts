// Formatting (frontend.md §10): money always with currency, quantities with units.

const eur = new Intl.NumberFormat("en-GB", { style: "currency", currency: "EUR", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const eurShort = new Intl.NumberFormat("en-GB", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
const num = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 2 });

export const money = (v: string | number | null | undefined) => (v == null ? "—" : eur.format(Number(v)));
export const moneyShort = (v: string | number | null | undefined) => (v == null ? "—" : eurShort.format(Number(v)));
export const amount = (v: string | number) => num.format(Number(v));
export const qty = (q: { value: string | number; unit: string } | null | undefined) => (q ? `${amount(q.value)} ${q.unit}` : "—");

export function day(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso.length === 10 ? `${iso}T12:00:00` : iso);
  return d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
}

export function time(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

export function preciseTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) + "." + String(d.getMilliseconds()).padStart(3, "0");
}

export function duration(ms: number): string {
  if (ms <= 0) return "0 min";
  const h = Math.floor(ms / 3_600_000);
  const m = Math.floor((ms % 3_600_000) / 60_000);
  const s = Math.floor((ms % 60_000) / 1000);
  if (h > 0) return `${h} h ${m} min`;
  if (m > 0) return `${m} min`;
  return `${s} s`;
}

export const capitalize = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);

const ATTRIBUTE_LABELS: Record<string, string> = {
  FREE_FROM_LACTOSE: "Lactose-free",
  FREE_FROM_GLUTEN: "Gluten-free",
  VEGAN: "Vegan",
  VEGETARIAN: "Vegetarian",
  LOW_LACTOSE: "Low lactose",
  EU_ORGANIC_FARMING: "Organic",
};
const ALLERGEN_LABELS: Record<string, string> = { AM: "milk", AW: "gluten", AE: "egg", AN: "nuts", AY: "fish", AP: "peanuts", AS: "sesame", SH: "shellfish" };

export const attributeLabel = (a: string) => ATTRIBUTE_LABELS[a] ?? capitalize(a.toLowerCase().replace(/_/g, " "));
export const allergenLabel = (code: string) => ALLERGEN_LABELS[code] ?? code;

export function preferenceLabel(p: string): string {
  const [key, value] = p.includes(":") ? p.split(":", 2) : ["attr", p];
  if (key === "brand") return value;
  if (key === "fat") return `${value} % fat`;
  if (key === "origin") return `From ${value.toUpperCase()}`;
  return attributeLabel(value);
}

export function deviationLabel(attribute: string): string {
  if (attribute === "pack_size") return "Pack size";
  if (attribute.startsWith("claim:") || attribute.startsWith("label:")) return attributeLabel(attribute.split(":")[1]);
  return capitalize(attribute.replace(/_/g, " "));
}

export function deviationValue(attribute: string, v: unknown): string {
  if (v === true) return "Yes";
  if (v === false || v == null) return "No";
  if (attribute === "fat") return `${v} % fat`;
  if (attribute === "pack_size") return `${v} L`;
  return String(v);
}

export const planName = (items: { name: string; quantity: { value: string | number; unit: string } }[]) =>
  items.length === 1 ? items[0].name : items.map((i) => `${amount(i.quantity.value)} ${i.quantity.unit} ${i.name}`).join(" + ");

export const shortName = (name: string, max = 46) => (name.length > max ? name.slice(0, max - 1).trimEnd() + "…" : name);

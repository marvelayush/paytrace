/**
 * Display helpers. The API always speaks integer paise and basis points (A10);
 * conversion to ₹ and % happens only here, at the edge.
 */

const inrFormatter = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const inrWholeFormatter = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});

const countFormatter = new Intl.NumberFormat("en-IN");

/** ₹1,23,456.00 in Indian digit grouping. */
export function formatINR(paise: number): string {
  return inrFormatter.format(paise / 100);
}

/** ₹1,23,456 (no paise), for KPIs and large summary numbers. */
export function formatINRWhole(paise: number): string {
  return inrWholeFormatter.format(Math.round(paise / 100));
}

/** Compact Indian units for headline numbers: ₹12.4 L, ₹1.2 Cr. */
export function formatINRCompact(paise: number): string {
  const rupees = paise / 100;
  const sign = rupees < 0 ? "−" : "";
  const absolute = Math.abs(rupees);
  if (absolute >= 1e7) return `${sign}₹${(absolute / 1e7).toFixed(2)} Cr`;
  if (absolute >= 1e5) return `${sign}₹${(absolute / 1e5).toFixed(2)} L`;
  return `${sign}${inrWholeFormatter.format(absolute)}`;
}

/** Signed money for differences: "+₹12.00" / "−₹37.00" (true minus sign, not a hyphen). */
export function formatSignedINR(paise: number): string {
  if (paise === 0) return formatINR(0);
  const text = inrFormatter.format(Math.abs(paise) / 100);
  return paise < 0 ? `−${text}` : `+${text}`;
}

export function formatCount(value: number): string {
  return countFormatter.format(value);
}

/** 1 → "order", 2 → "orders": the noun only, so the number can be styled separately. */
export function plural(count: number, noun: string): string {
  return count === 1 ? noun : `${noun}s`;
}

/** 2000 bp → "20.00%" */
export function formatPercentBp(bp: number): string {
  return `${(bp / 100).toFixed(2)}%`;
}

/** 500 → "0.5 kg", 1000 → "1 kg" */
export function formatWeight(grams: number): string {
  if (grams < 1000) return `${grams} g`;
  return `${Number((grams / 1000).toFixed(2))} kg`;
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
  return date.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

// ---------- parsing form input back into API units ----------

/** "1,234.5" → 123450 paise. Returns null for anything that is not a non-negative amount. */
export function parseRupeesToPaise(text: string): number | null {
  const cleaned = text.replace(/[₹,\s]/g, "");
  if (!/^\d+(\.\d{1,2})?$/.test(cleaned)) return null;
  return Math.round(Number(cleaned) * 100);
}

/** "20" or "20.5%" → 2000 / 2050 bp. Returns null when not a percentage between 0 and 100. */
export function parsePercentToBp(text: string): number | null {
  const cleaned = text.replace(/[%\s]/g, "");
  if (!/^\d+(\.\d{1,2})?$/.test(cleaned)) return null;
  const bp = Math.round(Number(cleaned) * 100);
  return bp <= 10_000 ? bp : null;
}

export function paiseToInput(paise: number): string {
  return (paise / 100).toFixed(2);
}

export function bpToInput(bp: number): string {
  return (bp / 100).toFixed(2);
}

/**
 * Fractional-index keys, mirroring the server's seltzer/ordering.py. Used only
 * for optimistic placement; the server computes the stored key.
 */
const DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
const BASE = DIGITS.length;

function midpoint(a: string, b: string | null): string {
  if (b !== null) {
    let n = 0;
    while (n < b.length && (a[n] ?? DIGITS[0]) === b[n]) n++;
    if (n > 0) return b.slice(0, n) + midpoint(a.slice(n), b.slice(n));
  }
  const da = a ? DIGITS.indexOf(a[0]!) : 0;
  const db = b !== null ? DIGITS.indexOf(b[0]!) : BASE;
  if (db - da > 1) return DIGITS[Math.floor((da + db + 1) / 2)]!;
  if (b !== null && b.length > 1) return b.slice(0, 1);
  return DIGITS[da]! + midpoint(a.slice(1), null);
}

export function keyBetween(before: string | null | undefined, after: string | null | undefined): string {
  if (before && after && before >= after) return before + "V";
  return midpoint(before ?? "", after ?? null);
}

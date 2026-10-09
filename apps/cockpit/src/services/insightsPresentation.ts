export type InsightDay = { date: string; orders: number; bookedMinor: string; sessions: number };

const dayMilliseconds = 86_400_000;

export function minorMoney(minor: string, currency: string): string {
  if (!/^\d+$/.test(minor)) throw new Error('Gold money must be exact nonnegative minor units.');
  const format = new Intl.NumberFormat('en', { style: 'currency', currency });
  const digits = format.resolvedOptions().maximumFractionDigits ?? 2;
  const divisor = 10n ** BigInt(digits);
  const exact = BigInt(minor);
  const fraction = (exact % divisor).toString().padStart(digits, '0');
  return format.formatToParts(exact / divisor)
    .map(part => part.type === 'fraction' ? fraction : part.value).join('');
}

export function share(value: number | string, total: number | string): number {
  const numerator = BigInt(value);
  const denominator = BigInt(total);
  if (numerator < 0n || denominator < 0n) throw new Error('Gold chart values cannot be negative.');
  return denominator === 0n ? 0 : Number(numerator * 10_000n / denominator) / 100;
}

export function percent(value: number, total: number): string {
  return total ? `${new Intl.NumberFormat('en', { maximumFractionDigits: 1 }).format(share(value, total))}%` : 'Not recorded';
}

export function addDays(date: string, amount: number): string {
  const timestamp = Date.parse(`${date}T00:00:00Z`);
  if (!Number.isFinite(timestamp) || !Number.isInteger(amount)) throw new Error('Invalid Gold date window.');
  return new Date(timestamp + amount * dayMilliseconds).toISOString().slice(0, 10);
}

export function daysBetween(from: string, to: string): number {
  return Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / dayMilliseconds) + 1;
}

export function shortDay(date: string): string {
  return new Intl.DateTimeFormat('en', { month: 'short', day: 'numeric', timeZone: 'UTC' })
    .format(new Date(`${date}T00:00:00Z`));
}

export function dailySeries(rows: InsightDay[], from: string, to: string): InsightDay[] {
  const length = daysBetween(from, to);
  if (!Number.isInteger(length) || length < 1 || length > 366) throw new Error('Gold chart window must contain 1–366 days.');
  const byDate = new Map(rows.map(row => [row.date, row]));
  return Array.from({ length }, (_, offset) => {
    const date = addDays(from, offset);
    return byDate.get(date) ?? { date, orders: 0, bookedMinor: '0', sessions: 0 };
  });
}

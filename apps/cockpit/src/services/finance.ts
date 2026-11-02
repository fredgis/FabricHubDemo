import { getRayfinClient } from './rayfinClient';
import type { SapFinance, SapFinanceFilters } from '../../rayfin/functions/src/sap-finance-contract';

export type { SapFinance, SapFinanceFilters };

export async function loadSapFinance(filters: Partial<SapFinanceFilters> = {}): Promise<SapFinance> {
  return getRayfinClient().functions.businessFinance.invoke({ filtersJson: JSON.stringify(filters) });
}

export function financeMoney(value: number, currency: string): string {
  try {
    return new Intl.NumberFormat('en', { style: 'currency', currency, minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
  } catch {
    return `${value.toFixed(2)} ${currency}`;
  }
}

export function monthLabel(year: number, month: number): string {
  return new Date(Date.UTC(year, month - 1, 1)).toLocaleDateString('en', { month: 'short', year: 'numeric', timeZone: 'UTC' });
}

/** Last calendar day of the month containing an ISO date, YYYY-MM-DD. */
export function monthEnd(isoDate: string): string {
  const year = Number(isoDate.slice(0, 4)), month = Number(isoDate.slice(5, 7));
  return new Date(Date.UTC(year, month, 0)).toISOString().slice(0, 10);
}

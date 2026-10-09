import { describe, expect, it } from 'vitest';
import { addDays, currencyLabel, dailySeries, daysBetween, minorMoney, percent, share } from '../../apps/cockpit/src/services/insightsPresentation';

describe('Insights exact amounts and date series', () => {
  it('formats minor amounts without losing large integer precision', () => {
    expect(minorMoney('900719925474099301', 'EUR')).toBe('€9,007,199,254,740,993.01');
    expect(minorMoney('123', 'JPY')).toBe('¥123');
    expect(minorMoney('1234', 'KWD')).toBe('KWD 1.234');
    expect(() => minorMoney('1.2', 'EUR')).toThrow();
  });
  it('formats ALL nominal units exactly without a currency symbol or confusing the Albanian lek', () => {
    expect(currencyLabel('*')).toBe('ALL · nominal, no FX');
    expect(minorMoney('144900', '*')).toBe('14.49');
    expect(minorMoney('0', '*')).toBe('0.00');
    expect(minorMoney('123400', '*')).toBe('12.34');
    expect(minorMoney('123410', '*')).toBe('12.341');
    expect(minorMoney('123401', '*')).toBe('12.3401');
    expect(minorMoney('9007199254740993012345', '*')).toBe('900,719,925,474,099,301.2345');
    expect(minorMoney('0', 'ALL')).toBe(new Intl.NumberFormat('en', { style: 'currency', currency: 'ALL' }).format(0));
    expect(currencyLabel('ALL')).toBe('ALL (Albanian lek)');
  });
  it('computes chart proportions with exact integers and handles empty denominators', () => {
    expect(share('9007199254740993', '18014398509481986')).toBe(50);
    expect(share(0, 0)).toBe(0);
    expect(percent(0, 0)).toBe('Not recorded');
    expect(percent(1, 4)).toBe('25%');
    expect(() => share(-1, 10)).toThrow();
  });
  it('keeps calendar windows in UTC across month, leap-day and daylight-saving changes', () => {
    expect(addDays('2024-03-01', -1)).toBe('2024-02-29');
    expect(addDays('2026-03-29', 1)).toBe('2026-03-30');
    expect(daysBetween('2026-03-28', '2026-03-30')).toBe(3);
  });
  it('fills absent days with genuine zero observations rather than interpolating activity', () => {
    expect(dailySeries([{ date: '2026-10-08', orders: 2, bookedMinor: '1200', sessions: 1 }], '2026-10-07', '2026-10-09'))
      .toEqual([
        { date: '2026-10-07', orders: 0, bookedMinor: '0', sessions: 0 },
        { date: '2026-10-08', orders: 2, bookedMinor: '1200', sessions: 1 },
        { date: '2026-10-09', orders: 0, bookedMinor: '0', sessions: 0 },
      ]);
    expect(() => dailySeries([], '2025-01-01', '2026-10-09')).toThrow();
    expect(() => dailySeries([], '2026-10-09', '2026-10-08')).toThrow();
  });
});

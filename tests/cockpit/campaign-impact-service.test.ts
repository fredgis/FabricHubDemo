import { beforeEach, expect, it, vi } from 'vitest';
import { campaignImpactFixture } from './campaign-impact-fixture';

const invoke = vi.hoisted(() => vi.fn());
vi.mock('../../apps/cockpit/src/services/rayfinClient', () => ({ getRayfinClient: () => ({ functions: { getCampaignImpact: { invoke } } }) }));
import { loadCampaignImpact } from '../../apps/cockpit/src/services/campaignImpact';
import { campaignMoney, largestMinor, titleContributions } from '../../apps/cockpit/src/services/campaignImpactPresentation';

beforeEach(() => { invoke.mockReset(); invoke.mockResolvedValue(campaignImpactFixture()); });

it('requests observed analysis by default and preserves explicit recorded-attribution selections', async () => {
  expect(await loadCampaignImpact()).toEqual(campaignImpactFixture());
  expect(invoke).toHaveBeenLastCalledWith({ filtersJson: '{"analysisMode":"post_contact"}' });
  const filters = { analysisMode: 'recorded' as const, from: '2026-10-07', to: '2026-10-08', territory: 'FR', campaignKey: 'test-campaign-1', currency: 'EUR' };
  await loadCampaignImpact(filters);
  expect(invoke).toHaveBeenLastCalledWith({ filtersJson: JSON.stringify(filters) });
  await loadCampaignImpact({ currency: 'JPY' });
  expect(invoke).toHaveBeenLastCalledWith({ filtersJson: '{"analysisMode":"post_contact","currency":"JPY"}' });
});

it('uses published currency exponents and preserves real zero and unavailable values', () => {
  expect(campaignMoney('JPY', 0)('1234')).toBe('¥1,234');
  expect(campaignMoney('EUR', 2)('1234')).toBe('€12.34');
  expect(campaignMoney('USD', 3)('1234')).toBe('$1.234');
  expect(campaignMoney('EUR', 2)('0')).toBe('€0.00');
  expect(campaignMoney('EUR', 2)(null)).toBe('Not available');
  expect(campaignMoney('EUR', undefined)('1234')).toBe('Not available');
});

it('keeps amounts beyond Number precision exact, including signed minor units', () => {
  expect(campaignMoney('EUR', 2)('900719925474099312345')).toBe('€9,007,199,254,740,993,123.45');
  expect(campaignMoney('USD', 3)('-101')).toBe('-$0.101');
  expect(largestMinor(['900719925474099312344', '900719925474099312345', null])).toBe('900719925474099312345');
});

it('groups only returned film money without rounding or summing distinct contacts', () => {
  const titles = [
    { content_key: 'test-film-a', title: 'Test film A', genre: 'Drama', distributor: 'Test distributor', orders: 1, engaged_orders: 1, booked_minor: '900719925474099312345', engaged_minor: '900719925474099312345' },
    { content_key: 'test-film-b', title: 'Test film B', genre: 'Drama', distributor: 'Test distributor', orders: 1, engaged_orders: 1, booked_minor: '1', engaged_minor: '1' },
  ];
  expect(titleContributions(titles, 'films').map(row => row.name)).toEqual(['Test film A', 'Test film B']);
  const genres = titleContributions(titles, 'genres');
  expect(genres).toHaveLength(1);
  expect(genres[0]).toMatchObject({ name: 'Drama', engagedMinor: '900719925474099312346', bookedMinor: '900719925474099312346' });
  expect(genres[0]).not.toHaveProperty('contacted_customers');
  expect(titleContributions(titles, 'distributors')[0].name).toBe('Test distributor');
});

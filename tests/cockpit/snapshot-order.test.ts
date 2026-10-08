import { describe, expect, it, vi } from 'vitest';

const orderBy = vi.hoisted(() => vi.fn());
vi.mock('../../apps/cockpit/src/services/rayfinClient', () => ({
  getRayfinClient: () => {
    const query = {
      orderBy: (order: unknown) => { orderBy(order); return query; },
      first: () => query,
      execute: async () => [],
      executePaginated: async () => ({ items: [], hasNextPage: false }),
    };
    const entity = { select: () => query };
    return { data: {
      Content: entity, Customer: entity, Offer: entity, Rental: entity,
      Playback: entity, Outbox: entity, ControlCommand: entity,
      Campaign: entity, CampaignMember: entity, IntegrationLink: entity,
    } };
  },
}));
import { loadSnapshot } from '../../apps/cockpit/src/services/business';

describe('recent event evidence', () => {
  it('orders the bounded outbox window by occurrence instead of unrelated entity sequences', async () => {
    await loadSnapshot();
    expect(orderBy).toHaveBeenCalledWith({ occurred_at: 'desc' });
    expect(orderBy).not.toHaveBeenCalledWith({ source_sequence: 'desc' });
  });
});

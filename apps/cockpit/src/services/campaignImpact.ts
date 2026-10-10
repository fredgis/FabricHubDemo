import { getRayfinClient } from './rayfinClient';
import type { CampaignImpact, CampaignImpactFilters, CampaignImpactMetrics } from '../../rayfin/functions/src/gold-campaign-contract';

export type { CampaignImpact, CampaignImpactFilters, CampaignImpactMetrics };

export async function loadCampaignImpact(filters: Partial<CampaignImpactFilters> = {}): Promise<CampaignImpact> {
  return getRayfinClient().functions.getCampaignImpact.invoke({ filtersJson: JSON.stringify(filters) });
}

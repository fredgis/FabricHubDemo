import { getRayfinClient } from './rayfinClient';
import type { GoldInsights, GoldInsightsFilters } from '../../rayfin/functions/src/gold-insights-contract';

export type { GoldInsights, GoldInsightsFilters };

export async function loadGoldInsights(filters: Partial<GoldInsightsFilters> = {}): Promise<GoldInsights> {
  return getRayfinClient().functions.businessInsights.invoke({ filtersJson: JSON.stringify(filters) });
}

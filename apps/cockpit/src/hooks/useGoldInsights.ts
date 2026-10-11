import { useCachedAnalysis } from '@/hooks/useCachedAnalysis';
import { loadGoldInsights, type GoldInsights, type GoldInsightsFilters } from '@/services/insights';

export function useGoldInsights(active: boolean, refreshKey: number) {
  return useCachedAnalysis<GoldInsightsFilters, GoldInsights>(active, refreshKey, 'insights', loadGoldInsights);
}

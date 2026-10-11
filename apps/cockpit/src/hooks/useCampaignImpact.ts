import { useCachedAnalysis } from '@/hooks/useCachedAnalysis';
import { loadCampaignImpact, type CampaignImpact, type CampaignImpactFilters } from '@/services/campaignImpact';

export function useCampaignImpact(active: boolean, refreshKey: number) {
  return useCachedAnalysis<CampaignImpactFilters, CampaignImpact>(active, refreshKey, 'campaign', loadCampaignImpact);
}

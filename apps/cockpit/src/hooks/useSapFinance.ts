import { useCachedAnalysis } from '@/hooks/useCachedAnalysis';
import { loadSapFinance, type SapFinance, type SapFinanceFilters } from '@/services/finance';

export function useSapFinance(active: boolean, refreshKey: number) {
  return useCachedAnalysis<SapFinanceFilters, SapFinance>(active, refreshKey, 'finance', loadSapFinance);
}

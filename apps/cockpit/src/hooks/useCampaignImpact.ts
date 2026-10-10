import { useCallback, useEffect, useRef, useState } from 'react';
import { safeError } from '@/services/business';
import { loadCampaignImpact, type CampaignImpact, type CampaignImpactFilters } from '@/services/campaignImpact';

type Selection = Partial<CampaignImpactFilters>;

export function useCampaignImpact(active: boolean, refreshKey: number) {
  const [data, setData] = useState<CampaignImpact | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const mounted = useRef(false);
  const sequence = useRef(0);
  const lastRead = useRef(0);
  const selection = useRef<Selection>({});
  const lastRefresh = useRef(refreshKey);
  const pending = useRef<{ key: string; promise: Promise<void> } | null>(null);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const apply = useCallback((filters: Selection) => {
    const key = JSON.stringify(filters);
    if (pending.current?.key === key) return pending.current.promise;
    selection.current = filters;
    const current = ++sequence.current;
    setLoading(true);
    setError('');
    const promise = loadCampaignImpact(filters).then(result => {
      if (!mounted.current || current !== sequence.current) return;
      lastRead.current = Date.now();
      selection.current = result.filters;
      setData(result);
    }).catch(cause => {
      if (mounted.current && current === sequence.current) setError(safeError(cause));
    }).finally(() => {
      if (current !== sequence.current) return;
      pending.current = null;
      if (mounted.current) setLoading(false);
    });
    pending.current = { key, promise };
    return promise;
  }, []);

  const refresh = useCallback(() => apply(selection.current), [apply]);

  useEffect(() => {
    if (!active) return;
    const explicitRefresh = refreshKey !== lastRefresh.current;
    lastRefresh.current = refreshKey;
    if (explicitRefresh || !lastRead.current || Date.now() - lastRead.current > 30_000) void refresh();
  }, [active, refreshKey, refresh]);

  return { data, loading, error, apply, refresh };
}

export const loadGraphCode = () => import('@/components/OntologyGraph').then(module => ({ default: module.OntologyGraph }));
export const loadInsightsCode = () => import('@/pages/InsightsPage').then(module => ({ default: module.InsightsPage }));
export const loadCampaignCode = () => import('@/pages/CampaignImpactPage').then(module => ({ default: module.CampaignImpactPage }));
export const loadMarkdownCode = () => import('@/components/FlixyMarkdown');

export function canPrefetch(): boolean {
  const connection = (navigator as Navigator & { connection?: { saveData?: boolean; effectiveType?: string } }).connection;
  return document.visibilityState !== 'hidden' && !connection?.saveData
    && !['slow-2g', '2g'].includes(connection?.effectiveType ?? '');
}

export function duringIdle(work: () => void): () => void {
  if ('requestIdleCallback' in window) {
    const id = window.requestIdleCallback(work);
    return () => window.cancelIdleCallback(id);
  }
  const id = globalThis.setTimeout(work, 1000);
  return () => globalThis.clearTimeout(id);
}

import { useState } from 'react';
import { catalogArt } from '@/assets/catalog-art.generated';
import { catalogArtVariants } from '@/assets/catalog-art-variants.generated';
import { dateLabel } from '@/services/business';
import { currencyLabel, minorMoney, shortDay } from '@/services/insightsPresentation';
import type { GoldInsights } from '@/services/insights';

const art = catalogArt.find(item => item.content_key === 'MSF-FILM-BUNNY');
const variants = catalogArtVariants.find(item => item.content_key === 'MSF-FILM-BUNNY');
const largest = variants?.variants.at(-1);
const count = new Intl.NumberFormat('en');

export function InsightsCinema({ data }: { data: GoldInsights }) {
  const [failed, setFailed] = useState(false);
  return <section className={`insights-cinema${failed || !art ? ' insights-cinema-no-art' : ''}`} aria-label="Sales to screen summary">
    {art && !failed && <div className="insights-cinema-art" aria-hidden="true">
      <img src={largest?.path ?? art.imagepath} alt=""
        srcSet={variants?.variants.map(image => `${image.path} ${image.width}w`).join(', ')}
        sizes="(max-width: 760px) 100vw, 70vw" width={largest?.width} height={largest?.height}
        decoding="async" fetchPriority="high" onError={() => setFailed(true)} />
    </div>}
    <div className="insights-cinema-copy">
      <p className="insights-kicker">Sales to screen</p>
      <p className="insights-cinema-window">{shortDay(data.filters.from)} to {shortDay(data.filters.to)}, UTC · {data.filters.territory || 'All territories'}</p>
      <p className="insights-sales" aria-label="Booked sales">{minorMoney(data.summary.bookedMinor, data.filters.currency)}</p>
      <p className="insights-sales-note">Booked sales · {currencyLabel(data.filters.currency)}. Recorded orders, not bank payments.</p>
      <dl className="insights-kpis">
        <div><dt>Distinct orders</dt><dd>{count.format(data.summary.orders)}</dd></div>
        <div><dt>Customers</dt><dd>{count.format(data.summary.customers)}</dd></div>
        <div><dt>Titles ordered</dt><dd>{count.format(data.summary.titles)}</dd></div>
        <div><dt>Playback sessions</dt><dd>{count.format(data.summary.sessions)}</dd></div>
      </dl>
      <p className="insights-cohort-note">Oracle catalogue · Salesforce customers · RTI transactions<br />
        Gold published {data.freshness.published_at ? dateLabel(data.freshness.published_at) : 'not yet'}.</p>
    </div>
    {art && <details className="insights-cinema-credit"><summary>Backdrop: Big Buck Bunny · Image credits</summary>
      <p>{art.attribution}</p><p>{variants?.modifications} Display cropped and darkened for readability.</p>
      <p><a href="https://studio.blender.org/projects/big-buck-bunny/" target="_blank" rel="noreferrer">Film source</a>
        <a href="https://creativecommons.org/licenses/by/3.0/" target="_blank" rel="noreferrer">CC BY 3.0</a></p>
      <p>Catalogue backdrop, not the selected cohort or a distribution-rights claim.</p>
      {failed && <p>Backdrop unavailable. All figures remain available.</p>}
    </details>}
  </section>;
}

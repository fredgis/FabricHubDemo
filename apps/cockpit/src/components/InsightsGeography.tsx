import { useId, useState } from 'react';
import geography from '@/assets/insights-world.generated.json';
import { minorMoney, share } from '@/services/insightsPresentation';
import type { GoldInsights } from '@/services/insights';

const count = new Intl.NumberFormat('en');
const countries = new Map(geography.countries.filter(country => country.code).map(country => [country.code, country]));
const views = { world: '-180 -150 360 270', europe: '-16 -76 51 39' };
const palette = ['#764136', '#945142', '#b45e4d', '#d46b58'];
type Metric = 'customers' | 'bookedMinor';
type MapView = keyof typeof views;

export function InsightsGeography({ data, disabled, onSelect }: {
  data: GoldInsights; disabled: boolean; onSelect: (territory: string) => void;
}) {
  const id = useId();
  const [metric, setMetric] = useState<Metric>('customers');
  const [chosenView, setChosenView] = useState<MapView | null>(null);
  const [highlighted, setHighlighted] = useState<string | null>(null);
  const rows = [...data.territories].sort((a, b) => BigInt(a[metric]) === BigInt(b[metric])
    ? a.territory.localeCompare(b.territory) : BigInt(a[metric]) > BigInt(b[metric]) ? -1 : 1);
  const lookup = new Map(rows.map(row => [row.territory, row]));
  const mapped = rows.filter(row => countries.has(row.territory));
  const unmapped = rows.filter(row => !countries.has(row.territory));
  const view = chosenView ?? (mapped.length > 0 && mapped.every(row => countries.get(row.territory)!.continent === 'Europe') ? 'europe' : 'world');
  const largest = rows.reduce((max, row) => BigInt(row[metric]) > max ? BigInt(row[metric]) : max, 0n);
  const valueLabel = (value: string | number | bigint) => metric === 'customers' ? count.format(BigInt(value)) : minorMoney(String(value), data.filters.currency);
  const level = (value: number | string) => Math.min(palette.length - 1, Math.max(0, Math.ceil(share(value, largest.toString()) / 25) - 1));
  const colour = (row: GoldInsights['territories'][number]) => BigInt(row[metric]) === 0n ? '#34353a' : palette[level(row[metric])];
  return <section className="insights-geography" aria-labelledby={`${id}-heading`}>
    <div className="insights-panel-heading"><div><p className="insights-kicker">Audience atlas</p>
      <h2 id={`${id}-heading`}>Where are customers buying?</h2>
      <p>Customers and booked sales by order territory. Choose a territory to filter the whole dashboard.</p></div>
      <div className="insights-map-total" aria-label="Cohort distinct customers"><strong>{count.format(data.summary.customers)}</strong><span>distinct customers<br />in this selection</span></div>
    </div>
    {!rows.length ? <p className="insights-empty-note">No territory breakdown is available for this selection.</p> : <>
      <div className="insights-map-layout">
        <figure className="insights-map-figure">
          <div className="insights-map-controls">
            <div className="insights-chart-tools" role="group" aria-label="Map measure">
              <button type="button" aria-pressed={metric === 'customers'} onClick={() => setMetric('customers')}>Customers</button>
              <button type="button" aria-pressed={metric === 'bookedMinor'} onClick={() => setMetric('bookedMinor')}>Booked sales</button>
            </div>
            <div className="insights-chart-tools" role="group" aria-label="Map view">
              <button type="button" aria-pressed={view === 'europe'} onClick={() => setChosenView('europe')}>Europe</button>
              <button type="button" aria-pressed={view === 'world'} onClick={() => setChosenView('world')}>World</button>
            </div>
          </div>
          <svg className="insights-map" viewBox={views[view]} role="img" aria-labelledby={`${id}-map-title ${id}-map-desc`}>
            <title id={`${id}-map-title`}>{metric === 'customers' ? 'Customers' : `Booked sales in ${data.filters.currency}`} by commercial territory, {view === 'europe' ? 'Europe' : 'world'} view</title>
            <desc id={`${id}-map-desc`}>Shading compares territories within this selection. Exact customers, booked sales, orders and sessions are in the territory list. Country outlines do not locate customer residences.</desc>
            {geography.countries.map(country => {
              const row = country.code ? lookup.get(country.code) : undefined;
              return <path key={country.id} d={country.path} className="insights-map-country" fillRule="evenodd"
                data-active={!!row} data-highlighted={!!row && row.territory === highlighted}
                style={row ? { fill: colour(row) } : undefined}>
                <title>{country.name}{row ? `: ${count.format(row.customers)} customers, ${minorMoney(row.bookedMinor, data.filters.currency)}` : ': outside this order selection'}</title>
              </path>;
            })}
            {mapped.map(row => {
              if (view === 'world' && mapped.length > 1 && highlighted !== row.territory) return null;
              const country = countries.get(row.territory)!;
              const [x, y] = country.label;
              const [left, top, width, height] = views[view].split(' ').map(Number);
              if (x < left || x > left + width || y < top || y > top + height) return null;
              return <text key={row.territory} x={x} y={y} className="insights-map-label" textAnchor="middle"
                style={{ fontSize: view === 'europe' ? '2.1px' : '8px', strokeWidth: view === 'europe' ? '.65px' : '2px' }}>{row.territory}</text>;
            })}
          </svg>
          <figcaption className="insights-map-legend"><span className="insights-map-key" aria-hidden="true" />
            <span>{metric === 'customers' ? 'Customers' : `Booked sales · ${data.filters.currency}`}: 0 to {valueLabel(largest)} per territory</span>
            <span>Light outline: matching orders. Other countries: outside this selection.</span></figcaption>
        </figure>
        <div className="insights-map-ledger">
          <h3>Territory figures</h3>
          <ul aria-label="Territory figures">{rows.map(row => {
            const country = countries.get(row.territory);
            return <li key={row.territory}>
              <button type="button" className="insights-map-territory" disabled={disabled}
                onPointerEnter={() => setHighlighted(row.territory)} onPointerLeave={() => setHighlighted(null)}
                onFocus={() => setHighlighted(row.territory)} onBlur={() => setHighlighted(null)}
                onClick={() => onSelect(row.territory)} aria-label={`Filter territory ${row.territory}: ${country?.name ?? 'not mapped'}, ${count.format(row.customers)} customers, ${minorMoney(row.bookedMinor, data.filters.currency)} booked sales, ${count.format(row.orders)} orders, ${count.format(row.sessions)} associated sessions`}>
                <span className="insights-map-territory-name"><strong>{country?.name ?? row.territory}</strong><span>{country ? row.territory : 'Not mapped'}</span></span>
                <span className="insights-map-values"><span><strong>{count.format(row.customers)}</strong><small>customers</small></span>
                  <span><strong>{minorMoney(row.bookedMinor, data.filters.currency)}</strong><small>booked sales · {data.filters.currency}</small></span></span>
                <span className="insights-map-row-bar" aria-hidden="true"><span style={{ width: `${Math.min(100, share(row[metric], largest.toString()))}%` }} /></span>
                <span className="insights-map-activity">{count.format(row.orders)} orders · {count.format(row.sessions)} associated sessions</span>
              </button>
            </li>;
          })}</ul>
        </div>
      </div>
      {!!unmapped.length && <p className="insights-map-note">Not drawn on this map: {unmapped.map(row => row.territory).join(', ')}. Their figures remain in the list and the cohort totals.</p>}
      {view === 'europe' && mapped.some(row => countries.get(row.territory)!.continent !== 'Europe') && <p className="insights-map-note">Some selected territories are outside Europe. Switch to World to see them; their figures remain in the list.</p>}
    </>}
    <p className="insights-map-note">Order territory, not customer residence. A customer can buy in more than one territory; territory counts must not be added as unique people.
      {' '}RTI-derived transactions are published Gold data, not a live Eventhouse feed.</p>
    <p className="insights-map-attribution">Made with <a href={geography.licenseUrl} target="_blank" rel="noreferrer">Natural Earth</a>. Public-domain, simplified country outlines; small territories may be absent. Map view changes do not change the filters.</p>
  </section>;
}

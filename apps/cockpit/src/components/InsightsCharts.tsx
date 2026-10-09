import { useEffect, useId, useRef, useState, type CSSProperties } from 'react';
import { currencyLabel, minorMoney, percent, share, shortDay, type InsightDay } from '@/services/insightsPresentation';

const count = new Intl.NumberFormat('en');
type TrendMetric = 'orders' | 'bookedMinor' | 'sessions';
const metrics: { key: TrendMetric; label: string }[] = [
  { key: 'orders', label: 'Orders' },
  { key: 'bookedMinor', label: 'Booked sales' },
  { key: 'sessions', label: 'Playback sessions' },
];

export function DailyChart({ days, currency }: { days: InsightDay[]; currency: string }) {
  const id = useId();
  const [metric, setMetric] = useState<TrendMetric>('orders');
  const [inspected, setInspected] = useState<number | null>(null);
  const [width, setWidth] = useState(800);
  const svg = useRef<SVGSVGElement>(null);
  useEffect(() => {
    if (!svg.current || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry.contentRect.width > 0) setWidth(Math.max(240, Math.round(entry.contentRect.width)));
    });
    observer.observe(svg.current);
    return () => observer.disconnect();
  }, [days.length]);
  const selectedIndex = Math.min(inspected ?? days.length - 1, days.length - 1);
  const selected = days[selectedIndex];
  if (!selected) return <p className="insights-empty-note">No dated activity in this selection.</p>;
  const largest = days.reduce((max, row) => BigInt(row[metric]) > max ? BigInt(row[metric]) : max, 0n);
  const ceiling = largest ? ((largest + 3n) / 4n) * 4n : 4n;
  const x = (index: number) => 84 + (days.length === 1 ? 0.5 : index / (days.length - 1)) * (width - 120);
  const y = (value: number | string) => 218 - share(value, ceiling.toString()) * 1.7;
  const path = days.map((row, index) => `${index ? 'L' : 'M'}${x(index)},${y(row[metric])}`).join(' ');
  const valueLabel = (value: number | string | bigint) => metric === 'bookedMinor'
    ? minorMoney(String(value), currency) : count.format(BigInt(value));
  const metricName = metrics.find(item => item.key === metric)!.label;
  const ticks = [...new Set(width < 440 ? [0, days.length - 1] : [0, Math.floor((days.length - 1) / 3), Math.floor((days.length - 1) * 2 / 3), days.length - 1])];
  return <>
    <div className="insights-chart-tools" role="group" aria-label="Trend metric">
      {metrics.map(item => <button key={item.key} type="button" aria-pressed={metric === item.key}
        onClick={() => setMetric(item.key)}>{item.label}</button>)}
    </div>
    {currency === '*' && <p className="insights-empty-note">Sales combine currencies at nominal value, without exchange-rate conversion.</p>}
    <div className="insights-trend-readout" aria-live="polite" aria-atomic="true">
      <span>{shortDay(selected.date)} <small>UTC · order cohort</small></span>
      <strong>{valueLabel(selected[metric])} <small>{metricName.toLowerCase()}</small></strong>
    </div>
    <svg ref={svg} className="insights-trend" viewBox={`0 0 ${width} 258`} role="img" aria-labelledby={`${id}-title ${id}-description`}>
      <title id={`${id}-title`}>{metricName} by order date</title>
      <desc id={`${id}-description`}>Daily values from {days[0].date} to {days.at(-1)!.date}, UTC. Use the day slider or the Daily figures table for exact values.</desc>
      <defs><linearGradient id={`${id}-fill`} x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor="#ed6757" stopOpacity=".24" /><stop offset="100%" stopColor="#ed6757" stopOpacity=".01" />
      </linearGradient></defs>
      {[0, 1, 2, 3, 4].map(index => {
        const value = ceiling * BigInt(index) / 4n;
        const position = 218 - index * 42.5;
        return <g key={index}><line x1="84" x2={width - 36} y1={position} y2={position} className="insights-gridline" />
          <text x="72" y={position + 4} textAnchor="end">{valueLabel(value)}</text></g>;
      })}
      <path d={`${path} L${x(days.length - 1)},218 L${x(0)},218 Z`} fill={`url(#${id}-fill)`} />
      <path d={path} className="insights-trend-line" />
      <line x1={x(selectedIndex)} x2={x(selectedIndex)} y1="40" y2="218" className="insights-cursor-line" />
      <circle cx={x(selectedIndex)} cy={y(selected[metric])} r="5" className="insights-trend-dot" />
      {ticks.map(index => <text key={index} x={x(index)} y="246" textAnchor={index === 0 ? 'start' : index === days.length - 1 ? 'end' : 'middle'}>
        {shortDay(days[index].date)}</text>)}
    </svg>
    <label className="insights-day-slider" htmlFor={`${id}-day`}>Inspect a day
      <input id={`${id}-day`} type="range" min="0" max={Math.max(0, days.length - 1)} step="1"
        value={selectedIndex} onChange={event => setInspected(Number(event.target.value))}
        aria-valuetext={`${shortDay(selected.date)}: ${valueLabel(selected[metric])} ${metricName.toLowerCase()}`} />
    </label>
    <details className="insights-data-table"><summary>Daily figures</summary>
      <div className="table-scroll" role="region" aria-label="Daily figures" tabIndex={0}>
        <table><caption className="sr-only">Full daily series for the selected order cohort</caption>
          <thead><tr><th scope="col">Date (UTC)</th><th scope="col">Orders</th><th scope="col">Booked sales ({currencyLabel(currency)})</th><th scope="col">Associated sessions</th></tr></thead>
          <tbody>{days.map(row => <tr key={row.date}><th scope="row">{row.date}</th><td>{count.format(row.orders)}</td>
            <td>{minorMoney(row.bookedMinor, currency)}</td><td>{count.format(row.sessions)}</td></tr>)}</tbody></table>
      </div></details>
  </>;
}

export type HeatCell = { territory: string; genre: string; orders: number; bookedMinor: string };
export function TerritoryHeatmap({ cells, currency, onSelect, disabled }: {
  cells: HeatCell[]; currency: string; onSelect: (territory: string, genre: string) => void; disabled: boolean;
}) {
  const [metric, setMetric] = useState<'orders' | 'bookedMinor'>('orders');
  const territories = [...new Set(cells.map(cell => cell.territory))].sort();
  const genres = [...new Set(cells.map(cell => cell.genre))];
  const lookup = new Map(cells.map(cell => [JSON.stringify([cell.territory, cell.genre]), cell]));
  const maximum = cells.reduce((max, cell) => BigInt(cell[metric]) > max ? BigInt(cell[metric]) : max, 0n);
  const palette = ['#242529', '#442724', '#64362f', '#85463b', '#a25244', '#ed6757'];
  return <>
    <div className="insights-chart-tools" role="group" aria-label="Heatmap metric">
      <button type="button" aria-pressed={metric === 'orders'} onClick={() => setMetric('orders')}>Order volume</button>
      <button type="button" aria-pressed={metric === 'bookedMinor'} onClick={() => setMetric('bookedMinor')}>Booked sales</button>
    </div>
    {!cells.length ? <p className="insights-empty-note">No territory and genre combinations for these filters.</p> :
      <div className="insights-heat-scroll" role="region" aria-label="Territory and genre heatmap" tabIndex={0}>
        <table className="insights-heatmap"><caption className="sr-only">{metric === 'orders' ? 'Orders' : `Booked sales (${currencyLabel(currency)})`} by territory and genre. Select a cell to filter the dashboard.</caption>
          <thead><tr><th scope="col">Genre</th>{territories.map(territory => <th key={territory} scope="col">{territory}</th>)}</tr></thead>
          <tbody>{genres.map(genre => <tr key={genre}><th scope="row">{genre}</th>{territories.map(territory => {
            const cell = lookup.get(JSON.stringify([territory, genre]));
            const value = cell?.[metric] ?? 0;
            const level = BigInt(value) === 0n ? 0 : Math.max(1, Math.ceil(share(value, maximum.toString()) / 20));
            const label = metric === 'orders' ? count.format(Number(value)) : minorMoney(String(value), currency);
            return <td key={territory}><button type="button" disabled={disabled}
              style={{ background: palette[Math.min(5, level)], color: level >= 5 ? '#121315' : '#f1f0ee' }}
              aria-label={`${territory}, ${genre}: ${label}${metric === 'orders' ? ' orders' : ''}. Filter this combination`}
              onClick={() => onSelect(territory, genre)}>{label}</button></td>;
          })}</tr>)}</tbody></table>
      </div>}
    <div className="insights-heat-legend"><span>Less</span>{palette.map(color => <span key={color} style={{ background: color }} aria-hidden="true" />)}<span>More</span>
      <small>{currency === '*' && 'Nominal sales, no FX conversion. '}Exact values in every cell. Select one to filter.</small></div>
  </>;
}

export function PlaybackArc({ playedOrders, orders, sessions, completedSessions }: {
  playedOrders: number; orders: number; sessions: number; completedSessions: number;
}) {
  const rate = Math.min(100, share(playedOrders, orders));
  return <div className="insights-playback">
    <div className="insights-ring" style={{ '--played': `${rate}%` } as CSSProperties}>
      <div><strong>{percent(playedOrders, orders)}</strong><span>orders with playback</span></div>
    </div>
    <dl><div><dt>Played orders</dt><dd>{count.format(playedOrders)} <span>/ {count.format(orders)}</span></dd></div>
      <div><dt>Associated sessions</dt><dd>{count.format(sessions)}</dd></div>
      <div><dt>Completed sessions</dt><dd>{count.format(completedSessions)} <span>/ {count.format(sessions)}</span></dd></div></dl>
  </div>;
}

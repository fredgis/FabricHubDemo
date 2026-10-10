import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { ArrowRight, ArrowsClockwise, Broadcast, ChartBar, FilmSlate, Graph, House,
  Play, ShoppingBag, SignOut, Target, UsersThree } from '@phosphor-icons/react';
import { useAuth } from '@/hooks/AuthContext';
import { getRayfinClient } from '@/services/rayfinClient';
import { dateLabel, money, safeError, safeUrl, type Snapshot } from '@/services/business';
import {GoldBusinessDashboard}from'@/components/GoldBusinessDashboard';
import{OntologyGraph}from'@/components/OntologyGraph';
import { useCockpitReads } from '@/hooks/useCockpitReads';
import type{GoldPages}from'../../rayfin/functions/src/gold-pages';
import{catalogArt}from'@/assets/catalog-art.generated';
import { catalogArtVariants } from '@/assets/catalog-art-variants.generated';
import { DemoPage } from '@/pages/DemoPage';
import { InsightsPage, type InsightsReadState } from '@/pages/InsightsPage';
import { CampaignImpactPage, type CampaignImpactReadState } from '@/pages/CampaignImpactPage';
import { FlixyAssistant } from '@/components/FlixyAssistant';
import { Artwork } from '@/components/CatalogArtwork';
import { askFlixy } from '@/services/flixy';
import type { Rental } from '../../rayfin/data/schema';
import type { Capabilities, CommandResult, Health } from '../../rayfin/functions/src/domain';

const sections = [
  { key: 'overview', name: 'Overview', icon: House },
  { key: 'catalog', name: 'Catalog', icon: FilmSlate },
  { key: 'orders', name: 'Rentals & Purchases', icon: ShoppingBag },
  { key: 'audiences', name: 'Audiences & Campaigns', icon: UsersThree },
  { key: 'graph', name: 'Business Graph', icon: Graph },
  { key: 'insights', name: 'MSFlix Insights', icon: ChartBar },
  { key: 'campaign-impact', name: 'Campaign Impact', icon: Target },
  { key: 'demo', name: 'Demo', icon: Play },
  { key: 'operations', name: 'Operations', icon: Broadcast },
] as const;
type Section = typeof sections[number]['key'];
type Command = (idempotencyKey: string) => Promise<CommandResult>;

export function Empty({ title, children }: { title: string; children: ReactNode }) {
  return <div className="empty-state"><FilmSlate size={34} aria-hidden="true" />
    <h2>{title}</h2><p>{children}</p></div>;
}
export function ErrorState({ message, retry }: { message: string; retry: () => void }) {
  return <div className="error-state" role="alert"><h2>Connection needs attention</h2>
    <p>{message}</p><button onClick={retry}><ArrowsClockwise aria-hidden="true" /> Retry connection</button></div>;
}
export function LoadingState() {
  return <div aria-busy="true" aria-label="Loading MSFlix data" className="loading-state">
    <p role="status">Reading persisted business activity…</p>
    <div className="skeleton wide" /><div className="skeleton-row">
      <div className="skeleton" /><div className="skeleton" /><div className="skeleton" /></div></div>;
}
function Status({ value }: { value: string }) {
  return <span className={`status status-${value}`}>{value.replaceAll('_', ' ')}</span>;
}
export { Artwork } from '@/components/CatalogArtwork';

export function HomePage({ route = '/', onNavigate }: {
  route?: '/' | '/campaign-impact'; onNavigate?: (path: '/' | '/campaign-impact') => void;
}) {
  const { user, signOut } = useAuth();
  const [localSection, setSection] = useState<Section>('overview');
  const section = route === '/campaign-impact' ? 'campaign-impact' : localSection;
  const [graphVisited, setGraphVisited] = useState(false);
  const [graphRefreshKey, setGraphRefreshKey] = useState(0);
  const [insightsVisited, setInsightsVisited] = useState(false);
  const [insightsRefreshKey, setInsightsRefreshKey] = useState(0);
  const [insightsRead, setInsightsRead] = useState<InsightsReadState>({ loading: false, queriedAt: null });
  const [campaignVisited, setCampaignVisited] = useState(route === '/campaign-impact');
  const [campaignRefreshKey, setCampaignRefreshKey] = useState(0);
  const [campaignRead, setCampaignRead] = useState<CampaignImpactReadState>({ loading: false, queriedAt: null });
  const { snapshot, loading, error, updated, refresh, gold, goldLoading, goldError, hasReadGold } = useCockpitReads(section);
  const [capabilities, setCapabilities] = useState<Capabilities>({ can_operate: false, reason: 'Checking command permissions…' });
  const [permissionError, setPermissionError] = useState('');
  const [busy, setBusy] = useState(false);
  const [commandError, setCommandError] = useState('');
  const [receipt, setReceipt] = useState<CommandResult>();
  const commandKeys = useRef(new Map<string, string>());
  const inFlight = useRef(false);
  useEffect(() => {
    let active = true;
    getRayfinClient().functions.capabilities.invoke().then(result => {
      if (active) setCapabilities(result);
    }).catch(err => {
      if (active) { setPermissionError(safeError(err)); setCapabilities({ can_operate: false, reason: 'Permissions could not be verified.' }); }
    });
    return () => { active = false; };
  }, []);

  const command = async (identity: string, action: Command) => {
    if (inFlight.current || !capabilities.can_operate) return;
    inFlight.current = true; setBusy(true); setCommandError(''); setReceipt(undefined);
    const id = commandKeys.current.get(identity) ?? crypto.randomUUID();
    commandKeys.current.set(identity, id);
    try {
      const result = await action(id);
      setReceipt(result); commandKeys.current.delete(identity);
      await refresh();
    } catch (err) { setCommandError(safeError(err)); }
    finally { inFlight.current = false; setBusy(false); }
  };
  const canOperate = capabilities.can_operate && !busy && !loading && !error;
  const context = { snapshot, canOperate, busy, command };
  const selected = sections.find(s => s.key === section)!;
  const readAt = section === 'campaign-impact' ? campaignRead.queriedAt : section === 'insights' ? insightsRead.queriedAt : gold?.pages.dashboard.freshness.queried_at ?? updated;
  const refreshing = section === 'campaign-impact' ? campaignRead.loading : section === 'insights' ? insightsRead.loading : loading || goldLoading;
  const refreshSection = () => {
    if (section === 'graph') setGraphRefreshKey(value => value + 1);
    else if (section === 'insights') setInsightsRefreshKey(value => value + 1);
    else if (section === 'campaign-impact') setCampaignRefreshKey(value => value + 1);
    else void refresh();
  };
  const selectSection = (next: Section) => {
    if (next === 'graph') setGraphVisited(true);
    if (next === 'insights') setInsightsVisited(true);
    if (next === 'campaign-impact') {
      setCampaignVisited(true);
      if (onNavigate) { onNavigate('/campaign-impact'); return; }
    }
    setSection(next);
    if (route === '/campaign-impact') onNavigate?.('/');
  };
  const heroVariants=catalogArtVariants.find(item=>item.content_key==='MSF-FILM-BUNNY')?.variants;
  return <div className="app-shell">
    {heroVariants&&<link rel="preload" as="image" href={heroVariants.at(-1)?.path}
      imageSrcSet={heroVariants.map(item=>`${item.path} ${item.width}w`).join(', ')}
      imageSizes="(max-width: 760px) 100vw, 75vw" fetchPriority="high"/>}
    <a className="skip-link" href="#main">Skip to business content</a>
    <aside className="sidebar">
      <a className="brand" href="/" aria-label="MSFlix home">MS<span>FLIX</span><small>BUSINESS CONTROL</small></a>
      <nav aria-label="Main navigation">{sections.map(({ key, name, icon: Icon }) =>
        <button key={key} aria-current={section === key ? 'page' : undefined}
          onClick={() => selectSection(key)}><Icon size={20} weight={section === key ? 'fill' : 'regular'} aria-hidden="true" />{name}</button>)}</nav>
      <div className="sidebar-bottom"><span className="workspace-label">MSFlix workspace</span>
        <strong>{user?.name}</strong><p>{capabilities.can_operate ? 'Operator' : 'Viewer'}</p>
        <button onClick={() => void signOut()}><SignOut aria-hidden="true" /> Sign out</button></div>
    </aside>
    <div className="workspace">
      <header className="topbar"><span>MSFlix <span className="muted">/ {selected.name}</span></span>
        <button onClick={refreshSection} disabled={refreshing || busy}>
          <ArrowsClockwise aria-hidden="true" />{refreshing ? 'Refreshing…' : section === 'graph' ? 'Refresh graph' : section === 'insights' ? 'Refresh insights' : section === 'campaign-impact' ? 'Refresh campaign impact' : 'Refresh data'}</button></header>
      <main id="main" tabIndex={-1}>
        <div className="page-heading"><div><p className="eyebrow">ENTERTAINMENT BUSINESS</p>
          <h1>{section === 'overview' ? 'The business behind the stories.' : selected.name}</h1>
          <p>{section === 'overview' ? 'Curated Gold performance, sourced catalog and business controls.'
            : section === 'orders' ? 'Persisted demo transactions and time-bound viewing rights. No bank charges.'
              : section === 'audiences' ? 'Fictional customer identities, stored in actual Salesforce CRM records.'
                : section === 'graph' ? 'Read the actual consolidated business ontology.'
                  : section === 'insights' ? 'From catalogue to customer to screen. One connected view of published Gold data.'
                  : section === 'campaign-impact' ? 'Campaign contacts, recorded orders and playback progression in one Gold view.'
                  : section === 'demo' ? 'Bounded real rental, purchase, and playback journeys. Delivery and publication are separate.'
                  : section === 'operations' ? 'Real connections, command receipts and delivery acknowledgements.'
                    : 'Sourced film metadata, explicit demo offers and traceable artwork rights.'}</p></div>
          <div className="view-context"><Status value={capabilities.can_operate ? 'operator' : 'viewer'} />
            <small>{readAt ? `Read ${dateLabel(readAt)}` : 'No data read yet'}</small></div></div>
        {permissionError && <p role="alert" className="notice">Permission check failed: {permissionError}</p>}
        {!capabilities.can_operate && <p className="permission-note">{capabilities.reason}</p>}
        {commandError && <p className="notice" role="alert">{commandError} Retrying the same command reuses its idempotency key.</p>}
        {receipt && <div className="receipt" role="status"><strong>Command persisted: {receipt.status}</strong>
          <span>Entity {receipt.entity_key}</span><span>{receipt.event_ids.length} returned event receipts. Broker delivery is separate.</span></div>}
        {!['insights', 'campaign-impact'].includes(section) && error && <ErrorState message={`${snapshot ? 'Refresh failed. The records below are from the last successful read. ' : ''}${error}`} retry={() => void refresh()} />}
        {['overview','catalog','audiences'].includes(section)&&<>
          {goldLoading&&!gold&&<LoadingState/>}
          {goldError&&<ErrorState message={`Gold business read failed: ${goldError} ${gold?'The last successful Gold read remains visible.':'No operational fallback.'}`} retry={()=>void refresh()}/>}
          {goldLoading&&gold&&<p className="permission-note" role="status">Refreshing Gold. The last successful read remains visible.</p>}
          {gold&&<>{section!=='overview'&&<p className="permission-note">Source: MSFlixGold. Published {gold.pages.dashboard.freshness.published_at?dateLabel(gold.pages.dashboard.freshness.published_at):'not yet published'}.
            {section==='audiences'&&` Activity window: latest ${gold.pages.window.orders} order lines.`}</p>}
            {section==='overview'&&<Overview data={gold.snapshot} navigate={selectSection}
              metrics={<GoldBusinessDashboard dashboard={gold.pages.dashboard} onRefresh={()=>void refresh()}/>}/>}
            {section==='catalog'&&<Catalog data={gold.snapshot} navigate={selectSection}/>}
            {section==='audiences'&&<Audiences data={gold.snapshot} dashboard={gold.pages.dashboard}/>}
          </>}</>}
        {(graphVisited||hasReadGold)&&<div hidden={section!=='graph'}><OntologyGraph active={section==='graph'}
          prefetch={hasReadGold} renderCanvas={graphVisited} refreshKey={graphRefreshKey}/></div>}
        {insightsVisited && <div hidden={section !== 'insights'}><InsightsPage active={section === 'insights'}
          refreshKey={insightsRefreshKey} onRead={setInsightsRead} /></div>}
        {(campaignVisited || section === 'campaign-impact') && <div hidden={section !== 'campaign-impact'}><CampaignImpactPage active={section === 'campaign-impact'}
          refreshKey={campaignRefreshKey} onRead={setCampaignRead} /></div>}
        <div hidden={section !== 'demo'}><DemoPage snapshot={snapshot} capabilities={capabilities}
          loading={loading} readError={error} busy={busy} snapshotUpdatedAt={updated}
          gold={gold?.pages} goldLoading={goldLoading} goldError={goldError} onRefresh={refresh} /></div>
        {['orders','operations'].includes(section)&&(loading&&!snapshot?<LoadingState/>:snapshot&&<>
          {section === 'orders' && <Orders {...context} snapshot={snapshot} />}
          {section === 'operations' && <Operations {...context} snapshot={snapshot} />}
        </>)}
      </main>
      <footer>MSFlix business demonstration. Sourced film metadata and licensed reference artwork; fictional CRM identities.
        <span>Commercial amounts are recorded sales, not bank payments or invoices.</span></footer>
    </div>
    {user && <FlixyAssistant ask={askFlixy} userKey={user.id} />}
  </div>;
}

function Overview({ data, navigate, metrics }: { data: Snapshot; navigate: (section: Section) => void; metrics:ReactNode }) {
  const film = data.content.find(f=>f.content_key==='MSF-FILM-BUNNY')
    ?? data.content.find(f=>catalogArt.some(art=>art.content_key===f.content_key&&art.kind==='licensed-reference'))
    ?? data.content[0];
  return <>
    {film ? <section className="cinema-hero" aria-label="Catalog spotlight"><Artwork key={film.content_key} film={film} hero />
      <div className="hero-copy"><p>In the MSFlix catalog</p><h2>{film.title}</h2>
        <p>{film.genre} <span className="separator">/</span> {Math.round(film.duration_seconds / 60)} min</p>
        <button className="primary" onClick={() => navigate('catalog')}>Explore catalog <ArrowRight aria-hidden="true" /></button></div>
      <div className="hero-credit">{film.attribution}</div></section>
      : <Empty title="Your catalog starts here">Load the sourced catalog into the Gold Warehouse to see the featured film.</Empty>}
    {metrics}
    <div className="overview-grid"><section><h2>Curated commercial activity</h2><p className="muted">Actual Gold order-line facts. Write commands remain in the operational app ledger.</p><OrderTable data={data} limit={6} />
      {!!data.rentals.length && <button className="text-button" onClick={() => navigate('orders')}>Manage orders <ArrowRight aria-hidden="true" /></button>}</section>
      <section className="activity-panel"><h2>Curated playback activity</h2><p className="muted">Latest Gold playback-session facts.</p>{data.playback.length ? <ul className="event-list">
        {data.playback.slice(0,6).map(session=><li key={session.session_id}><div><strong>{data.content.find(f=>f.content_key===session.content_key)?.title??session.content_key}</strong>
          <small>{session.position_seconds}s recorded</small></div><Status value={session.status}/></li>)}</ul>
        :<p className="muted">No playback facts in the current Gold publication.</p>}</section></div>
  </>;
}
function Catalog({ data, navigate }: { data: Snapshot; navigate: (section: Section) => void }) {
  const [query, setQuery] = useState('');
  const films = data.content.filter(f => `${f.title} ${f.genre}`.toLowerCase().includes(query.toLowerCase()));
  return <><label className="search-label" htmlFor="catalog-search">Find a film<input id="catalog-search" type="search" value={query}
    onChange={e => setQuery(e.target.value)} placeholder="Title or genre" /></label>
    {!films.length ? <Empty title={query ? 'No matching films' : 'Catalog not imported'}>{query ? 'Try a different title or genre.' : 'Run the trusted catalog import hook. Artwork, licenses and sources are required.'}</Empty>
      : <div className="catalog-grid">{films.map(film => <article className="film-card" key={film.content_key}>
        <Artwork film={film} /><div className="film-copy"><div className="film-meta"><span>{film.genre}</span><span>{Math.round(film.duration_seconds / 60)} min</span></div>
          <h2>{film.title}</h2><p className="muted">Released {new Date(film.release_date).getUTCFullYear()}</p>
          <div className="offer-list">{data.offers.filter(o => o.content_key === film.content_key).map(o =>
            <div key={o.offer_key}><span>{o.transaction_type === 'TVOD' ? 'Rental' : o.transaction_type === 'EST' ? 'Purchase' : 'Subscription reference'} / {o.territory}</span>
              <strong>{money(o.price_minor, o.currency)}</strong>{o.transaction_type === 'TVOD' &&
              <small>Start within {o.start_window_hours}h. Watch within {o.play_window_hours}h after first play.</small>}</div>)}</div>
          {!data.offers.some(o => o.content_key === film.content_key) && <p className="muted">No commercial offers imported.</p>}
          <button className="text-button" onClick={() => navigate('orders')}>Open commerce <ArrowRight aria-hidden="true" /></button>
          <details className="attribution"><summary>Source & license</summary><p>{film.attribution}</p>
            {catalogArt.find(item=>item.content_key===film.content_key)&&<p>
              Presentation: {catalogArt.find(item=>item.content_key===film.content_key)?.attribution}
              <br/>{catalogArt.find(item=>item.content_key===film.content_key)?.license}</p>}
            {catalogArtVariants.find(item=>item.content_key===film.content_key)&&<p>
              {catalogArtVariants.find(item=>item.content_key===film.content_key)?.modifications}</p>}
            <p>Metadata: {film.metadata_license ?? film.license}</p>
            {film.metadata_date_precision === 'source-not-qualified' && <p>Release-date precision is not qualified. Only the source-reported year is displayed.</p>}
            <p>{film.artwork_available === false || film.image_url === '/catalog-unavailable.svg'
              ? 'Visuel non disponible. No artwork rights are assumed.'
              : `Artwork: ${film.artwork_license ?? film.license}`}</p>
            {film.artwork_author && <p>Artwork credit: {film.artwork_author}</p>}
            {safeUrl(film.source_url) && <a href={film.source_url} target="_blank" rel="noreferrer">Original film source</a>}
            {film.artwork_source_url && safeUrl(film.artwork_source_url) && <p><a href={film.artwork_source_url} target="_blank" rel="noreferrer">Artwork source & attribution</a></p>}
            <p>Reference assets do not imply commercial distribution rights.</p></details></div></article>)}</div>}</>;
}

type CommandContext = { snapshot: Snapshot | null; canOperate: boolean; busy: boolean;
  command: (identity: string, action: Command) => Promise<void> };
function Orders({ snapshot: data, canOperate, busy, command }: CommandContext & { snapshot: Snapshot }) {
  const [customer, setCustomer] = useState('');
  const [offerKey, setOfferKey] = useState('');
  const selectedCustomer = data.customers.find(c => c.customer_key === customer);
  const offers = data.offers.filter(o => ['TVOD', 'EST'].includes(o.transaction_type) && o.territory === selectedCustomer?.territory);
  const offer = offers.find(o => o.offer_key === offerKey);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!offer) return;
    void command(`order:${customer}:${offerKey}`, id => getRayfinClient().functions.placeOrder.invoke({ input: {
      customer_key: customer, offer_key: offerKey, idempotency_key: id,
    } }));
  };
  return <><section className="commerce-form"><h2>Record a commercial transaction</h2><form onSubmit={submit}>
    <label htmlFor="customer">CRM customer<select id="customer" required value={customer}
      onChange={e => { setCustomer(e.target.value); setOfferKey(''); }}><option value="">Select customer</option>
      {data.customers.map(c => <option key={c.customer_key} value={c.customer_key}>{c.name} ({c.territory})</option>)}</select></label>
    <label htmlFor="offer">Available offer<select id="offer" required value={offerKey} onChange={e => setOfferKey(e.target.value)}>
      <option value="">Select offer</option>{offers.map(o => <option key={o.offer_key} value={o.offer_key}>
        {data.content.find(f => f.content_key === o.content_key)?.title ?? o.content_key} / {o.transaction_type} / {money(o.price_minor, o.currency)}</option>)}</select></label>
    <button className="primary" disabled={!canOperate || !offer} aria-describedby="commerce-policy">
      <ShoppingBag aria-hidden="true" />{busy ? 'Persisting…' : 'Record order'}</button>
    <p id="commerce-policy">The backend chooses the price, currency and expiry from the persisted offer. Operator permission is required.</p>
    {offer && <p className="offer-confirmation">{money(offer.price_minor, offer.currency)} recorded.
      {offer.transaction_type === 'TVOD' ? ` Start within ${offer.start_window_hours}h; ${offer.play_window_hours}h from first playback.` : ' Purchase entitlement has no rental expiry.'}</p>}
  </form></section>
    <section><h2>Orders & entitlements</h2><OrderTable data={data} renderAction={order =>
      <button disabled={!canOperate || !['booked', 'active', 'purchased'].includes(order.status)}
        onClick={() => void command(`play:${order.order_id}`, id => getRayfinClient().functions.startPlayback.invoke({ input: {
          order_id: order.order_id, idempotency_key: id,
        } }))}><Play aria-hidden="true" /> Start playback</button>} /></section>
    <section className="playback-section"><h2>Playback ledger</h2>{data.playback.length ?
      <div className="playback-grid">{data.playback.map(session => <PlaybackControl key={session.session_id}
        data={data} session={session} canOperate={canOperate} command={command} />)}</div>
      : <p className="muted">No playback sessions. Start an eligible persisted entitlement above.</p>}</section>
  </>;
}

function PlaybackControl({ data, session, canOperate, command }: {
  data: Snapshot; session: Snapshot['playback'][number]; canOperate: boolean; command: CommandContext['command'];
}) {
  const film = data.content.find(f => f.content_key === session.content_key);
  const [position, setPosition] = useState(session.position_seconds);
  return <article className="playback-card"><h3>{film?.title ?? session.content_key}</h3><Status value={session.status} />
    <p>{session.position_seconds}s recorded / {film?.duration_seconds ?? 'unknown'}s duration</p>
    <form onSubmit={e => { e.preventDefault(); void command(`progress:${session.session_id}:${position}`, id =>
      getRayfinClient().functions.recordProgress.invoke({ input: { session_id: session.session_id, position_seconds: position, idempotency_key: id } })); }}>
      <label htmlFor={`position-${session.session_id}`}>Playback position (seconds)<input id={`position-${session.session_id}`}
        type="number" min={session.position_seconds} max={film?.duration_seconds} step="1" required value={position}
        onChange={e => setPosition(Number(e.target.value))} /></label>
      <button disabled={!canOperate || session.status !== 'playing'}>Record progress</button></form></article>;
}

function OrderTable({ data, limit, renderAction }: { data: Snapshot; limit?: number; renderAction?: (order: Rental) => ReactNode }) {
  if (!data.rentals.length) return <p className="muted table-empty">No orders yet. An authorized operator can record a rental or purchase.</p>;
  const rows = [...data.rentals].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
  return <div className="table-scroll"><table><caption className="sr-only">Persisted commercial orders</caption>
    <thead><tr><th scope="col">Film / customer</th><th scope="col">Amount</th><th scope="col">Entitlement</th><th scope="col">Viewing boundary</th>{renderAction && <th scope="col">Command</th>}</tr></thead>
    <tbody>{(limit ? rows.slice(0, limit) : rows).map(order => {
      const offer = data.offers.find(o => o.offer_key === order.offer_key);
      return <tr key={order.order_id}><td><strong>{data.content.find(f => f.content_key === offer?.content_key)?.title ?? order.offer_key}</strong>
        <small>{data.customers.find(c => c.customer_key === order.customer_key)?.name ?? order.customer_key}</small>
        <small className="identifier">{order.order_id}</small></td><td className="numeric">{money(order.amount_minor, order.currency)}</td>
        <td><Status value={order.status} /></td><td>{offer?.transaction_type === 'EST' ? 'Purchase (no rental expiry)'
          : dateLabel(order.first_play_at ? order.expires_at : order.start_deadline)}</td>{renderAction && <td>{renderAction(order)}</td>}</tr>;
    })}</tbody></table></div>;
}

function Audiences({ data, dashboard }: { data: Snapshot; dashboard: GoldPages['dashboard'] }) {
  const territories = [...new Set(data.customers.map(c => c.territory))].sort();
  return <><GoldBusinessDashboard dashboard={dashboard}/><p className="muted">Audience directory and campaigns below are read from Gold dimensions and facts.</p><div className="audience-grid">{territories.map(territory => {
    const customers = data.customers.filter(c => c.territory === territory);
    const keys = new Set(customers.map(c => c.customer_key));
    return <section className="audience-segment" key={territory}><UsersThree size={25} aria-hidden="true" /><h2>{territory}</h2>
      <strong className="segment-number">{customers.length} customers</strong>
      <p>{data.rentals.filter(r => keys.has(r.customer_key)).length} Gold order lines in this read window</p>
      <details><summary>CRM identities</summary><ul>{customers.map(c => <li key={c.customer_key}>{c.name}<small>{c.customer_key}</small></li>)}</ul></details></section>;
  })}</div>{!territories.length && <Empty title="No CRM audience imported">Import the actual Salesforce export. Fictional names must come from persisted CRM records, not browser fixtures.</Empty>}
    <section className="campaigns"><h2>Salesforce campaigns</h2>{data.campaigns.length ? <div className="campaign-grid">
      {data.campaigns.map(c => <article key={c.campaign_key}><ChartBar size={25} aria-hidden="true" /><h3>{c.name}</h3>
        <Status value={c.status} /><p>{c.type}</p>
        <small>{c.campaign_key}</small></article>)}</div>
      : <p className="muted">No campaign records imported. Conversion rates and delivery results are not invented.</p>}</section></>;
}

function Operations({ snapshot: data, canOperate, busy, command }: CommandContext & { snapshot: Snapshot }) {
  const [health, setHealth] = useState<Health>();
  const [error, setError] = useState('');
  const [checking, setChecking] = useState(false);
  const [limit, setLimit] = useState(10);
  const check = useCallback(async () => {
    setChecking(true); setError(''); setHealth(undefined);
    try { setHealth(await getRayfinClient().functions.health.invoke()); }
    catch (err) { setError(safeError(err)); }
    finally { setChecking(false); }
  }, []);
  useEffect(() => { void check(); }, [check]);
  return <><section className="operations-health"><h2>Connection verification</h2>
    <button onClick={() => void check()} disabled={checking}>{checking ? 'Checking…' : 'Check health'}</button>
    {error && <p role="alert" className="notice">{error}</p>}
    {health && <dl><dt>Data</dt><dd>{health.database}</dd><dt>Functions</dt><dd>{health.functions}</dd>
      <dt>Outbox pending</dt><dd>{health.outbox_pending}</dd><dt>Event delivery</dt><dd>{health.broker}</dd></dl>}
    {!health && !error && <p role="status">Invoking native health function…</p>}</section>
    <section className="control-panel"><h2>Bounded producer controls</h2>
      <p>Commands are requests until the authorized worker claims and completes them. A queued request is not a running service.</p>
      <label htmlFor="control-limit">Maximum work items<input id="control-limit" type="number" min="1" max="100" step="1" value={limit}
        onChange={e => setLimit(Number(e.target.value))} aria-describedby="control-help" /></label>
      <p id="control-help">Allowed range: 1-100. Duplicate pending commands are rejected by the backend.</p>
      <div className="control-buttons">{(['simulate', 'start', 'stop', 'refresh'] as const).map(type =>
        <button key={type} disabled={!canOperate || !Number.isInteger(limit) || limit < 1 || limit > 100}
          onClick={() => void command(`control:${type}:${limit}`, id => getRayfinClient().functions.requestControl.invoke({ input: {
            type, limit, idempotency_key: id,
          } }))}>{busy ? 'Submitting…' : `Request ${type}`}</button>)}
        <button disabled={!canOperate} onClick={() => void command('expiry', id =>
          getRayfinClient().functions.expireRentals.invoke({ idempotency_key: id }))}>Expire due rentals</button></div>
    </section>
    <section><h2>Command ledger</h2>{data.commands.length ? <div className="table-scroll"><table>
      <thead><tr><th scope="col">Command</th><th scope="col">State</th><th scope="col">Requested</th><th scope="col">Completed / error</th></tr></thead>
      <tbody>{data.commands.map(c => <tr key={c.id}><td><strong>{c.type}</strong><small>{c.id}</small></td>
        <td><Status value={c.status} /></td><td>{dateLabel(c.requested_at)}</td><td>{c.error ?? (c.completed_at ? dateLabel(c.completed_at) : 'Awaiting worker')}</td></tr>)}</tbody></table></div>
      : <p className="muted">No control requests persisted.</p>}</section>
    <section className="integration-links"><h2>Verified Fabric resources</h2>{data.links.length ? data.links.map(link =>
      safeUrl(link.url) && <a key={link.link_key} href={link.url} target="_blank" rel="noreferrer"><span>{link.name}<small>{link.description}</small></span><ArrowRight aria-hidden="true" /></a>)
      : <p className="muted">No resource links registered by deployment. No successful connection is assumed.</p>}</section>
  </>;
}

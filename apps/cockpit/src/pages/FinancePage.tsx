import { useEffect, useId, useMemo, useState, type FormEvent } from 'react';
import { ArrowsClockwise, Bank, CalendarBlank, Info } from '@phosphor-icons/react';
import { useSapFinance } from '@/hooks/useSapFinance';
import { dateLabel } from '@/services/business';
import { financeMoney, monthEnd, monthLabel, type SapFinance } from '@/services/finance';
import type { SapFinanceMonth, SapFinanceOpenItem } from '../../rayfin/functions/src/sap-finance-contract';
import './InsightsPage.css';
import './FinancePage.css';

export type FinanceReadState = { loading: boolean; queriedAt: string | null };
const count = new Intl.NumberFormat('en');
const percent = new Intl.NumberFormat('en', { style: 'percent', maximumFractionDigits: 1 });
const todayUtc = () => new Date().toISOString().slice(0, 10);

function Controls({ data, loading, company, onCompany, onApply }: {
  data: SapFinance; loading: boolean; company: string; onCompany: (code: string) => void; onApply: (asOf: string) => void;
}) {
  const id = useId();
  const [draft, setDraft] = useState(data.filters.asOf);
  useEffect(() => { setDraft(data.filters.asOf); }, [data.filters.asOf]);
  const submit = (event: FormEvent) => { event.preventDefault(); if (draft) onApply(draft); };
  return <form className="insights-filter finance-controls" onSubmit={submit} aria-label="Finance selection">
    <div className="insights-filter-heading"><div><h2><Bank size={20} aria-hidden="true" />SAP company code and as-of date</h2>
      <p>Amounts stay in each company-code currency. No FX conversion, no cross-currency totals.</p></div></div>
    <div className="finance-companies" role="radiogroup" aria-label="Company code">
      {data.companies.map(item => <button key={item.code} type="button" role="radio" aria-checked={company === item.code}
        className={company === item.code ? 'primary' : undefined} onClick={() => onCompany(item.code)}>
        <strong>{item.code}</strong><span>{item.name} · {item.currency}</span></button>)}
    </div>
    <div className="insights-filter-actions">
      <label className="finance-asof" htmlFor={`${id}-asof`}><span><CalendarBlank size={16} aria-hidden="true" /> As of</span>
        <input id={`${id}-asof`} type="date" value={draft} min="2020-01-01" max="2035-12-31" required
          onChange={event => setDraft(event.target.value)} /></label>
      <button type="button" disabled={loading} onClick={() => onApply(todayUtc())}>Today</button>
      <button type="button" disabled={loading} onClick={() => onApply(monthEnd(data.filters.asOf))}>Month end</button>
      <button type="submit" className="primary" disabled={loading || !draft}>{loading ? 'Reading SAP…' : 'Apply date'}</button>
    </div>
  </form>;
}

function Kpi({ label, value, note }: { label: string; value: string; note?: string }) {
  return <div className="finance-kpi"><dt>{label}</dt><dd>{value}</dd>{note && <small>{note}</small>}</div>;
}

function RevenueMix({ months, currency }: { months: SapFinanceMonth[]; currency: string }) {
  const max = Math.max(1, ...months.map(month => month.total_revenue));
  return <section className="finance-panel" aria-labelledby="finance-mix-title">
    <div className="insights-panel-heading"><div><h2 id="finance-mix-title">Recognized revenue by month</h2>
      <p>SAP leading ledger 0L. Subscription, rental (TVOD) and purchase (EST) revenue.</p></div></div>
    <div className="finance-legend" aria-hidden="true"><span className="svod">Subscription</span><span className="tvod">TVOD</span><span className="est">EST</span></div>
    {months.length === 0 ? <p className="insights-muted">No posted months up to this date.</p> :
      <ul className="finance-bars">{months.map(month => <li key={`${month.year}-${month.month}`}>
        <span className="finance-bar-label">{monthLabel(month.year, month.month)}</span>
        <span className="finance-bar-track" aria-hidden="true">
          <span className="svod" style={{ width: `${(month.subscription_revenue / max) * 100}%` }} />
          <span className="tvod" style={{ width: `${(month.tvod_revenue / max) * 100}%` }} />
          <span className="est" style={{ width: `${(month.est_revenue / max) * 100}%` }} /></span>
        <span className="finance-bar-value">{financeMoney(month.total_revenue, currency)}
          <small>Sub {financeMoney(month.subscription_revenue, currency)} · TVOD {financeMoney(month.tvod_revenue, currency)} · EST {financeMoney(month.est_revenue, currency)}</small></span>
      </li>)}</ul>}
  </section>;
}

function OpenItems({ title, items, empty, party }: { title: string; items: SapFinanceOpenItem[]; empty: string; party: string }) {
  return <section className="finance-panel" aria-label={title}>
    <div className="insights-panel-heading"><div><h2>{title}</h2><p>{count.format(items.length)} open line{items.length === 1 ? '' : 's'}</p></div></div>
    {items.length === 0 ? <p className="insights-muted">{empty}</p> : <div className="finance-table-wrap"><table className="finance-table">
      <thead><tr><th scope="col">Document</th><th scope="col">{party}</th><th scope="col">Due</th><th scope="col">Text</th><th scope="col" className="num">Amount</th></tr></thead>
      <tbody>{items.map(item => <tr key={`${item.document}-${item.amount}-${item.due_date}`}>
        <td>{item.document}</td><td>{item.customer_key ?? item.party_name ?? item.party}<small>{item.customer_key || item.party_name ? item.party : ''}</small></td>
        <td>{item.due_date ?? '—'}</td><td>{item.text ?? '—'}</td><td className="num">{financeMoney(item.amount, item.currency)}</td></tr>)}</tbody>
    </table></div>}
  </section>;
}

function Sources({ data }: { data: SapFinance }) {
  return <section className="finance-sources" aria-label="Finance sources">
    <Info size={20} aria-hidden="true" />
    <p><strong>Source: {data.source.name} · schema {data.source.schema}</strong>. Live SAP S/4HANA mirror read through
      monthly_finance, balances, ar_open_items, ap_open_items, customer_invoice_item, rights_contract, contract_charge and subscription_contract,
      as of {data.filters.asOf}. Read {dateLabel(data.freshness.queried_at)}. SAP company codes, suppliers and contracts are fictional demo data;
      customer keys link to Salesforce CRM.</p>
  </section>;
}

export function FinancePage({ active, refreshKey, onRead }: {
  active: boolean; refreshKey: number; onRead?: (state: FinanceReadState) => void;
}) {
  const { data, loading, error, apply, refresh } = useSapFinance(active, refreshKey);
  const queriedAt = data?.freshness.queried_at ?? null;
  useEffect(() => { onRead?.({ loading, queriedAt }); }, [loading, queriedAt, onRead]);
  const [selected, setSelected] = useState('');
  const company = data?.companies.find(item => item.code === selected) ?? data?.companies[0];
  const view = useMemo(() => {
    if (!data || !company) return null;
    const months = data.months.filter(month => month.company === company.code);
    const asOfMonth = Number(data.filters.asOf.slice(0, 4)) * 100 + Number(data.filters.asOf.slice(5, 7));
    const current = months.find(month => month.year * 100 + month.month === asOfMonth) ?? null;
    const sum = (key: 'total_revenue' | 'contribution' | 'net_bank_movement') => months.reduce((total, month) => total + month[key], 0);
    return {
      months, current, revenue12: sum('total_revenue'), contribution12: sum('contribution'), cash12: sum('net_bank_movement'),
      latest: months.at(-1) ?? null,
      balance: data.balances.find(item => item.company === company.code) ?? null,
      receivables: data.receivables.filter(item => item.company === company.code),
      payables: data.payables.filter(item => item.company === company.code),
      billing: data.billing.filter(item => item.company === company.code),
      rights: data.rights.map(item => ({ ...item, charges: item.charges.filter(charge => charge.company === company.code) }))
        .filter(item => item.charges.length > 0 || item.currency === company.currency),
      subscriptions: data.subscriptions.filter(item => item.currency === company.currency),
    };
  }, [data, company]);

  return <div className="insights-page finance-page" aria-label="MSFlix SAP finance" aria-busy={loading}>
    {!data && !error && <section className="insights-initial"><h2>Reading the SAP ledger</h2>
      <p role="status">Querying the live SAP mirror (schema sap_live) in the Gold Warehouse: ledger months, open items, billing and contracts. No sample is substituted.</p>
      <div className="insights-loading-lines" aria-hidden="true"><span /><span /><span /><span /><span /><span /></div></section>}
    {error && <section className="insights-status insights-status-error" role="alert"><h2>SAP finance could not be read</h2>
      <p>{data ? 'The last successful read remains below. ' : 'No sample or fallback is shown. '}{error}</p>
      <button type="button" disabled={loading} onClick={() => void refresh()}><ArrowsClockwise aria-hidden="true" />Retry SAP read</button></section>}
    {data && company && view && <>
      <Controls data={data} loading={loading} company={company.code} onCompany={setSelected} onApply={asOf => void apply({ asOf })} />
      {loading && <p className="insights-status" role="status">Updating SAP figures. The last successful read remains visible.</p>}
      <p className="finance-disclaimer"><strong>Simulated SAP data.</strong> Postings are generated from MSFlix demo orders and subscriptions into fictional company codes. Figures are not audited.</p>
      <section aria-label={`Key figures for ${company.code}`}>
        <dl className="finance-kpis">
          <Kpi label={`Revenue ${view.current ? monthLabel(view.current.year, view.current.month) : 'this month'}`}
            value={financeMoney(view.current?.total_revenue ?? 0, company.currency)} note={view.current ? `${count.format(view.current.journal_lines)} journal lines` : 'No postings yet this month'} />
          <Kpi label="Revenue, 12 months" value={financeMoney(view.revenue12, company.currency)} note="Recognized, ledger 0L" />
          <Kpi label="Contribution after content cost" value={financeMoney(view.contribution12, company.currency)}
            note={view.revenue12 ? `${percent.format(view.contribution12 / view.revenue12)} of revenue` : undefined} />
          <Kpi label="Net bank movement" value={financeMoney(view.cash12, company.currency)} note="Cash, 12 months" />
          <Kpi label="Receivables outstanding" value={financeMoney(view.balance?.receivables ?? 0, company.currency)} note={`As of ${data.filters.asOf}`} />
          <Kpi label="Payables outstanding" value={financeMoney(view.balance?.payables ?? 0, company.currency)} note={`As of ${data.filters.asOf}`} />
          <Kpi label="Deferred revenue" value={financeMoney(view.latest?.deferred_liability ?? 0, company.currency)} note="Liability, latest month" />
          <Kpi label="Net VAT liability" value={financeMoney(view.latest?.net_vat_liability ?? 0, company.currency)} note="Latest month" />
        </dl>
        {view.latest && <p className="finance-badge"><span>{view.latest.completeness.replaceAll('_', ' ')}</span>
          {view.balance && view.balance.missing_amount_rows > 0 && <span>{count.format(view.balance.missing_amount_rows)} open items without amount</span>}</p>}
      </section>
      <div className="finance-grid">
        <RevenueMix months={view.months} currency={company.currency} />
        <section className="finance-panel" aria-labelledby="finance-billing-title">
          <div className="insights-panel-heading"><div><h2 id="finance-billing-title">Invoiced to customers</h2>
            <p>SAP billing documents up to {data.filters.asOf}, by origin.</p></div></div>
          {view.billing.length === 0 ? <p className="insights-muted">No billing documents for this company code.</p> :
            <div className="finance-table-wrap"><table className="finance-table">
              <thead><tr><th scope="col">Origin</th><th scope="col" className="num">Invoices</th><th scope="col" className="num">Customers</th>
                <th scope="col" className="num">Net</th><th scope="col" className="num">VAT</th><th scope="col" className="num">Gross</th></tr></thead>
              <tbody>{view.billing.map(row => <tr key={row.linkage}>
                <td>{row.linkage === 'operational_order' ? 'Rentals & purchases' : row.linkage === 'subscription' ? 'Subscriptions' : row.linkage}</td>
                <td className="num">{count.format(row.documents)}</td><td className="num">{count.format(row.customers)}</td>
                <td className="num">{financeMoney(row.net, row.currency)}</td><td className="num">{financeMoney(row.tax, row.currency)}</td>
                <td className="num">{financeMoney(row.gross, row.currency)}</td></tr>)}</tbody>
            </table></div>}
        </section>
      </div>
      <div className="finance-grid">
        <OpenItems title="Open receivables" items={view.receivables} party="Customer" empty="No open customer items at this date." />
        <OpenItems title="Open payables" items={view.payables} party="Supplier" empty="No open supplier items at this date." />
      </div>
      <div className="finance-grid">
        <section className="finance-panel" aria-labelledby="finance-rights-title">
          <div className="insights-panel-heading"><div><h2 id="finance-rights-title">Content rights contracts</h2>
            <p>Distributor contracts and the charges SAP computed from them.</p></div></div>
          {view.rights.length === 0 ? <p className="insights-muted">No rights contract for this company code.</p> : view.rights.map(contract =>
            <article key={contract.contract_id} className="finance-contract">
              <h3>{contract.contract_id}</h3>
              <p>{contract.supplier_name ?? contract.supplier} · {contract.valid_from ?? '—'} to {contract.valid_to_exclusive ?? 'open'} (exclusive)</p>
              <p className="insights-muted">Fixed {contract.fixed_net === null ? '—' : financeMoney(contract.fixed_net, contract.currency)}
                {contract.revenue_share !== null && ` + ${percent.format(contract.revenue_share)} of ${contract.revenue_basis?.replaceAll('_', ' ').toLowerCase() ?? 'revenue'}`}</p>
              {contract.charges.length > 0 && <ul className="finance-charges">{contract.charges.map(charge =>
                <li key={`${charge.period_start}-${charge.type}`}><span>{charge.type === 'FIXED' ? 'Fixed fee' : 'Revenue share'} · {charge.period_start ?? '—'}</span>
                  <strong>{financeMoney(charge.charge_net, contract.currency)}</strong>
                  {charge.type !== 'FIXED' && charge.basis_net !== null && charge.rate !== null &&
                    <small>{percent.format(charge.rate)} × {financeMoney(charge.basis_net, contract.currency)}</small>}</li>)}</ul>}
            </article>)}
        </section>
        <section className="finance-panel" aria-labelledby="finance-subs-title">
          <div className="insights-panel-heading"><div><h2 id="finance-subs-title">Subscription contracts</h2>
            <p>SAP subscription billing, linked to Salesforce customers.</p></div></div>
          {view.subscriptions.length === 0 ? <p className="insights-muted">No subscription contracts in {company.currency}.</p> :
            <div className="finance-table-wrap"><table className="finance-table">
              <thead><tr><th scope="col">Subscription</th><th scope="col">Customer</th><th scope="col">Plan</th><th scope="col">Service period</th><th scope="col" className="num">Monthly net</th></tr></thead>
              <tbody>{view.subscriptions.map(item => <tr key={item.subscription_id}>
                <td>{item.subscription_id}<small>{item.active ? 'Active at date' : item.status ?? '—'}</small></td>
                <td>{item.customer_key ?? '—'}</td><td>{item.plan_id ?? '—'}</td>
                <td>{item.service_from ?? '—'} to {item.service_to_exclusive ?? 'open'}</td>
                <td className="num">{item.monthly_net === null ? '—' : financeMoney(item.monthly_net, item.currency ?? company.currency)}</td></tr>)}</tbody>
            </table></div>}
        </section>
      </div>
      <Sources data={data} />
    </>}
    {data && data.companies.length === 0 && <section className="insights-initial"><h2>No SAP company codes</h2>
      <p>The sap_live mirror returned no company codes. Check the SAP mirroring status.</p></section>}
  </div>;
}

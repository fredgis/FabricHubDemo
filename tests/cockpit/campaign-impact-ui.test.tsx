import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { campaignImpactFixture, campaignMetrics } from './campaign-impact-fixture';

const load = vi.hoisted(() => vi.fn());
vi.mock('../../apps/cockpit/src/services/campaignImpact', () => ({ loadCampaignImpact: load }));
import { CampaignImpactPage } from '../../apps/cockpit/src/pages/CampaignImpactPage';

const rateLabel = 'Engaged revenue per 100 contacted customers';
const page = () => render(<CampaignImpactPage active refreshKey={0} />);
const rate = () => screen.getByLabelText(rateLabel, { selector: 'p' });
const coverage = () => screen.getByRole('region', { name: 'Outside the attribution boundary' });

afterEach(cleanup);
beforeEach(() => { load.mockReset(); load.mockResolvedValue(campaignImpactFixture()); });

it('shows honest loading without substituting sample figures', () => {
  load.mockReturnValue(new Promise(() => {}));
  page();
  expect(screen.getByRole('status')).toHaveTextContent('Reading the published Gold contact cohorts');
  expect(screen.getByLabelText('MSFlix campaign impact')).toHaveAttribute('aria-busy', 'true');
  expect(screen.queryByLabelText(rateLabel, { selector: 'p' })).not.toBeInTheDocument();
});

it('shows received zero impact, all 600 contacts and nonzero exclusions without inventing film orders', async () => {
  page();
  await screen.findByRole('form', { name: 'Filter campaign impact' });
  expect(rate()).toHaveTextContent(/^€0\.00$/);
  const spotlight = screen.getByRole('region', { name: rateLabel });
  expect(within(spotlight).getByText('Contacted customers').nextElementSibling).toHaveTextContent('600');
  for (const label of ['Buyers', 'All eligible orders', 'Started orders', 'Engaged orders']) {
    expect(within(spotlight).getByText(label).nextElementSibling).toHaveTextContent(/^0$/);
  }
  expect(spotlight).toHaveTextContent('No eligible campaign-linked orders are recorded');
  expect(screen.getByText('No eligible film orders for this contact cohort.')).toBeInTheDocument();
  expect(within(screen.getByRole('region', { name: 'Campaign comparison figures' })).getAllByRole('row')).toHaveLength(7);
  expect(coverage()).toHaveTextContent('1,043');
  expect(coverage()).toHaveTextContent('€1,043.00');
  expect(coverage()).toHaveTextContent('separate from the first-contact cohort');
  expect(screen.getByText(/This is progression, not watch time/)).toBeInTheDocument();
  expect(screen.getByText(/not a direct Eventhouse real-time feed/)).toBeInTheDocument();
});

it('validates and forwards date, territory, campaign and single-currency filters, then resets to server defaults', async () => {
  page();
  const form = await screen.findByRole('form', { name: 'Filter campaign impact' });
  const currency = screen.getByLabelText('Currency');
  expect(within(currency).queryByRole('option', { name: /^ALL/ })).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('From (UTC)'), { target: { value: '2024-01-01' } });
  fireEvent.submit(form);
  expect(screen.getByRole('alert')).toHaveTextContent('1 to 366 days');
  expect(screen.getByLabelText('From (UTC)')).toHaveAccessibleDescription('Choose an inclusive date range of 1 to 366 days.');
  expect(screen.getByLabelText('To (UTC)')).toHaveAttribute('aria-invalid', 'true');
  expect(load).toHaveBeenCalledTimes(1);
  const filters = { analysisMode: 'recorded' as const, from: '2026-10-07', to: '2026-10-08', territory: 'FR', campaignKey: 'test-campaign-1', currency: 'JPY' };
  fireEvent.change(screen.getByLabelText('From (UTC)'), { target: { value: filters.from } });
  fireEvent.change(screen.getByLabelText('To (UTC)'), { target: { value: filters.to } });
  fireEvent.change(screen.getByLabelText('Territory'), { target: { value: filters.territory } });
  fireEvent.change(screen.getByLabelText('Campaign'), { target: { value: filters.campaignKey } });
  fireEvent.change(currency, { target: { value: filters.currency } });
  expect(load).toHaveBeenCalledTimes(1);
  load.mockResolvedValueOnce(campaignImpactFixture({ filters }));
  fireEvent.click(screen.getByRole('button', { name: 'Apply filters' }));
  await waitFor(() => expect(rate()).toHaveTextContent(/^¥0$/));
  expect(load).toHaveBeenLastCalledWith(filters);
  expect(screen.getByLabelText('Applied campaign filters')).toHaveTextContent('JPY only');
  expect(screen.getByLabelText('Applied campaign filters')).toHaveTextContent('Test campaign 1');
  expect(within(screen.getByRole('region', { name: rateLabel })).getByText('Contacted customers').nextElementSibling).toHaveTextContent('600');
  fireEvent.click(screen.getByRole('button', { name: 'Reset filters' }));
  await waitFor(() => expect(load).toHaveBeenLastCalledWith({}));
  await waitFor(() => expect(rate()).toHaveTextContent(/^€0\.00$/));
});

it('switches to observed analysis explicitly and retains the successful mode when another read fails', async () => {
  page();
  await screen.findByRole('form', { name: 'Filter campaign impact' });
  const fixture = campaignImpactFixture();
  const filters = { ...fixture.filters, analysisMode: 'post_contact' as const };
  load.mockResolvedValueOnce(campaignImpactFixture({
    filters,
    methodology: { ...fixture.methodology, attribution: 'observed_post_contact' },
    coverage: { unattributed_orders: 0, ambiguous_orders: 12, linked_without_touch_orders: 3, excluded_minor: '1500' },
  }));
  fireEvent.change(screen.getByLabelText('Analysis'), { target: { value: 'post_contact' } });
  expect(load).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Apply filters' }));
  await waitFor(() => expect(screen.getByLabelText('Applied campaign filters')).toHaveTextContent('After contact (observed)'));
  expect(load).toHaveBeenLastCalledWith(filters);
  expect(screen.getByRole('region', { name: rateLabel })).toHaveTextContent('Observed association, not marketing attribution');
  expect(screen.getByText(/not marketing attribution or proof of campaign effect/)).toBeInTheDocument();
  expect(screen.getByText(/even after the selected To date/)).toBeInTheDocument();
  const exclusions = screen.getByRole('region', { name: 'Outside the analysis boundary' });
  expect(exclusions).toHaveTextContent('across all campaigns');
  expect(within(exclusions).getByText('Multiple prior campaigns').nextElementSibling).toHaveTextContent('12');
  expect(within(exclusions).getByText('No prior campaign contact').nextElementSibling).toHaveTextContent('3');
  expect(within(exclusions).queryByText('Unattributed orders')).not.toBeInTheDocument();
  load.mockRejectedValueOnce(new Error('Test recorded-mode read failed'));
  fireEvent.change(screen.getByLabelText('Analysis'), { target: { value: 'recorded' } });
  fireEvent.click(screen.getByRole('button', { name: 'Apply filters' }));
  await screen.findByRole('alert');
  expect(load).toHaveBeenLastCalledWith({ ...filters, analysisMode: 'recorded' });
  expect(screen.getByLabelText('Applied campaign filters')).toHaveTextContent('After contact (observed)');
  expect(screen.getByRole('region', { name: rateLabel })).toHaveTextContent('Observed association, not marketing attribution');
});

it('offers real retries on first-read and refresh failures while retaining successful data', async () => {
  load.mockRejectedValueOnce(new Error('Test SQL unavailable'));
  const view = page();
  expect(await screen.findByRole('alert')).toHaveTextContent('Test SQL unavailable');
  fireEvent.click(screen.getByRole('button', { name: 'Retry campaign impact' }));
  await screen.findByRole('form', { name: 'Filter campaign impact' });
  expect(rate()).toHaveTextContent('€0.00');
  load.mockRejectedValueOnce(new Error('Test refresh failed'));
  view.rerender(<CampaignImpactPage active refreshKey={1} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('last successful selection and figures remain below');
  expect(rate()).toHaveTextContent('€0.00');
  fireEvent.click(screen.getByRole('button', { name: 'Retry campaign impact' }));
  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
  expect(load).toHaveBeenCalledTimes(4);
  expect(load).toHaveBeenLastCalledWith(campaignImpactFixture().filters);
});

it('keeps nonzero coverage in an empty selection and treats unpublished Gold separately', async () => {
  load.mockResolvedValueOnce(campaignImpactFixture({ state: 'empty', summary: campaignMetrics({ contacted_customers: 0, touches: 0, engaged_per_100_minor: null }), campaigns: [], trend: [] }));
  const view = page();
  await screen.findByRole('heading', { name: 'No contacts or eligible orders match this cohort' });
  expect(screen.getByText(/Not available\. There are no contacted customers for the denominator/)).toBeInTheDocument();
  expect(coverage()).toHaveTextContent('1,043');
  expect(coverage()).toHaveTextContent('€1,043.00');
  expect(screen.getByRole('button', { name: 'Use latest contact window' })).toBeEnabled();
  view.unmount();
  load.mockResolvedValueOnce(campaignImpactFixture({ state: 'unpublished', freshness: { queried_at: '2026-10-09T12:01:00Z', published_at: null, publication_run_id: null } }));
  page();
  await screen.findByRole('heading', { name: 'Campaign impact is not published yet' });
  expect(screen.queryByRole('form')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Check publication again' }));
  await screen.findByRole('form', { name: 'Filter campaign impact' });
  expect(load).toHaveBeenCalledTimes(3);
});

it('renders exact cohort figures, grouped returned-film value and null rates without invented watch time', async () => {
  const metrics = campaignMetrics({ contacted_customers: 3, buyers: 2, orders: 4, played_orders: 3, engaged_orders: 2, unknown_duration_orders: 1, booked_minor: '3000', engaged_minor: '1500', not_started_minor: '500', engaged_per_100_minor: '50000' });
  load.mockResolvedValueOnce(campaignImpactFixture({
    summary: metrics, campaigns: [{ ...metrics, campaign_key: 'test-campaign-1', name: 'Test campaign 1' }], trend: [{ ...metrics, date: '2026-10-07' }],
    titles: [
      { content_key: 'a', title: 'Test film A', genre: 'Drama', distributor: 'Test distributor', orders: 2, engaged_orders: 1, booked_minor: '2000', engaged_minor: '1000' },
      { content_key: 'b', title: 'Test film B', genre: 'Drama', distributor: 'Test distributor', orders: 2, engaged_orders: 1, booked_minor: '1000', engaged_minor: '500' },
    ],
  }));
  const view = page();
  await screen.findByRole('form', { name: 'Filter campaign impact' });
  expect(rate()).toHaveTextContent(/^€500\.00$/);
  const details = screen.getByText('Exact cohort figures').closest('details')!;
  details.open = true;
  expect(within(details).getByRole('table')).toHaveTextContent('2026-10-07');
  expect(within(details).getByRole('table')).toHaveTextContent('€500.00');
  expect(screen.getByText(/Genre and distributor totals cover only these films/)).toBeInTheDocument();
  for (const name of ['Genres', 'Distributors']) {
    fireEvent.click(screen.getByRole('button', { name }));
    expect(screen.getByRole('button', { name })).toHaveAttribute('aria-pressed', 'true');
    const contribution = screen.getByRole('region', { name: 'Film contribution figures' });
    expect(within(contribution).getAllByRole('row')).toHaveLength(2);
    expect(contribution).toHaveTextContent('€15.00');
    expect(contribution).toHaveTextContent('€30.00');
  }
  load.mockResolvedValueOnce(campaignImpactFixture({ summary: campaignMetrics({ contacted_customers: 0, engaged_per_100_minor: null }) }));
  view.rerender(<CampaignImpactPage active refreshKey={1} />);
  await waitFor(() => expect(rate()).toHaveTextContent(/^Not available$/));
  expect(screen.getByText(/Denominator: 0 unique contacted customers/)).toBeInTheDocument();
  expect(screen.queryByText(/Infinity|NaN/)).not.toBeInTheDocument();
});

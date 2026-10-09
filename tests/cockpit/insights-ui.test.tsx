import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { insightsFixture } from './insights-fixture';

const load = vi.hoisted(() => vi.fn());
vi.mock('../../apps/cockpit/src/services/insights', () => ({ loadGoldInsights: load }));
import { InsightsPage } from '../../apps/cockpit/src/pages/InsightsPage';
import { DailyChart, TerritoryHeatmap } from '../../apps/cockpit/src/components/InsightsCharts';

afterEach(cleanup);
beforeEach(() => { load.mockReset(); load.mockResolvedValue(insightsFixture()); });

const page = () => render(<InsightsPage active refreshKey={0} />);

describe('Gold insights controls and honest states', () => {
  it('shows loading without made-up numbers or a fallback source', async () => {
    load.mockReturnValue(new Promise(() => {}));
    page();
    expect(screen.getByRole('status')).toHaveTextContent('Reading the published Gold Warehouse');
    expect(screen.queryByLabelText('Booked sales')).not.toBeInTheDocument();
    expect(screen.getByLabelText('MSFlix Gold insights')).toHaveAttribute('aria-busy', 'true');
  });
  it('applies the full date, genre, territory, type and single-currency selection only on submit', async () => {
    page();
    await screen.findByRole('form', { name: 'Filter Gold analysis' });
    fireEvent.change(screen.getByLabelText('Territory'), { target: { value: 'FR' } });
    fireEvent.change(screen.getByLabelText('Genre'), { target: { value: 'Animation' } });
    fireEvent.change(screen.getByLabelText('Transaction'), { target: { value: 'EST' } });
    fireEvent.change(screen.getByLabelText('Currency'), { target: { value: 'GBP' } });
    fireEvent.change(screen.getByRole('slider', { name: /Window ending/ }), { target: { value: '7' } });
    expect(load).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Apply filters' }));
    await waitFor(() => expect(load).toHaveBeenLastCalledWith({
      from: '2026-10-03', to: '2026-10-09', territory: 'FR', genre: 'Animation', transactionType: 'EST', currency: 'GBP',
    }));
  });
  it('rejects an excessive date window and associates the error with both date fields', async () => {
    page();
    const form = await screen.findByRole('form', { name: 'Filter Gold analysis' });
    fireEvent.change(screen.getByLabelText('From (UTC)'), { target: { value: '2024-01-01' } });
    fireEvent.submit(form);
    expect(await screen.findByRole('alert')).toHaveTextContent('1 to 366 days');
    expect(screen.getByLabelText('From (UTC)')).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByLabelText('To (UTC)')).toHaveAttribute('aria-describedby');
    expect(load).toHaveBeenCalledTimes(1);
  });
  it('cross-filters from a heatmap cell and resets to server-derived defaults', async () => {
    page();
    fireEvent.click(await screen.findByRole('button', { name: 'FR, Drama: 2 orders. Filter this combination' }));
    await waitFor(() => expect(load).toHaveBeenLastCalledWith({ ...insightsFixture().filters, territory: 'FR', genre: 'Drama' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Reset filters' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Reset filters' }));
    await waitFor(() => expect(load).toHaveBeenLastCalledWith({}));
  });
  it('distinguishes a published empty selection from an unpublished warehouse', async () => {
    load.mockResolvedValueOnce(insightsFixture({ state: 'empty', titles: [], daily: [], heatmap: [] }));
    const view = page();
    await screen.findByRole('heading', { name: 'No orders match this selection' });
    expect(screen.queryByLabelText('Booked sales')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Use latest data window' })).toBeEnabled();
    view.unmount();
    load.mockResolvedValueOnce(insightsFixture({ state: 'unpublished' }));
    page();
    await screen.findByRole('heading', { name: 'Gold is not published yet' });
    expect(screen.queryByRole('form')).not.toBeInTheDocument();
  });
  it('offers a real retry and preserves the previous successful figures on refresh error', async () => {
    const view = page();
    await screen.findByLabelText('Booked sales');
    load.mockRejectedValueOnce(new Error('Test SQL read failure'));
    view.rerender(<InsightsPage active refreshKey={1} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('last successful selection');
    expect(screen.getByLabelText('Booked sales')).toHaveTextContent('€30.00');
    fireEvent.click(screen.getByRole('button', { name: 'Retry Gold analysis' }));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    expect(load).toHaveBeenCalledTimes(3);
  });
  it('states the source boundary and labels unavailable artwork honestly', async () => {
    page();
    await screen.findByRole('heading', { name: 'Where the picture comes from' });
    expect(screen.getByText('SAP').closest('li')).toHaveTextContent('Not published');
    expect(screen.getByText('SAP').closest('li')).toHaveTextContent('Local integration contract only');
    expect(screen.getByRole('img', { name: 'Visuel non disponible : Fixture film' })).toBeInTheDocument();
    expect(screen.getByText(/not time watched/)).toBeInTheDocument();
  });
});

describe('accessible chart alternatives', () => {
  it('switches trend measures and exposes exact values through a keyboard-ready day slider and table', () => {
    render(<DailyChart days={insightsFixture().daily} currency="EUR" />);
    const controls = screen.getByRole('group', { name: 'Trend metric' });
    fireEvent.click(within(controls).getByRole('button', { name: 'Booked sales' }));
    const slider = screen.getByRole('slider', { name: 'Inspect a day' });
    fireEvent.change(slider, { target: { value: '0' } });
    expect(slider).toHaveAttribute('aria-valuetext', 'Oct 8: €20.00 booked sales');
    expect(within(controls).getByRole('button', { name: 'Booked sales' })).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(screen.getByText('Daily figures'));
    expect(screen.getByRole('table')).toHaveTextContent('2026-10-08');
    expect(screen.getByRole('table')).toHaveTextContent('€20.00');
  });
  it('renders heatmap values as accessible buttons, including zero combinations', () => {
    const select = vi.fn();
    render(<TerritoryHeatmap cells={[...insightsFixture().heatmap, { territory: 'FR', genre: 'Animation', orders: 1, bookedMinor: '999' }]}
      currency="EUR" onSelect={select} disabled={false} />);
    fireEvent.click(screen.getByRole('button', { name: 'GB, Animation: 0 orders. Filter this combination' }));
    expect(select).toHaveBeenCalledWith('GB', 'Animation');
    fireEvent.click(screen.getByRole('button', { name: 'Booked sales' }));
    expect(screen.getByRole('button', { name: 'FR, Animation: €9.99. Filter this combination' })).toBeInTheDocument();
  });
});

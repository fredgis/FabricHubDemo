import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { InsightsGeography } from '../../apps/cockpit/src/components/InsightsGeography';
import { insightsFixture } from './insights-fixture';

// All business values in this file are test fixtures, never application fallback data.
afterEach(cleanup);
const atlas = (data = insightsFixture(), disabled = false) => {
  const onSelect = vi.fn();
  return { ...render(<InsightsGeography data={data} disabled={disabled} onSelect={onSelect} />), onSelect };
};

describe('commercial territory atlas', () => {
  it('maps France using Natural Earth country codes and exposes both exact measures with the filter action', () => {
    const { container, onSelect } = atlas();
    expect(screen.getByRole('img', { name: /^Customers by commercial territory, Europe view/ })).toBeInTheDocument();
    expect(container.querySelectorAll('path[data-active="true"]')).toHaveLength(2);
    const france = screen.getByRole('button', { name: /^Filter territory FR: France, 1 customers, €20.00 booked sales, 2 orders, 1 associated sessions/ });
    expect(france).toHaveTextContent('FranceFR1customers€20.00booked sales');
    fireEvent.focus(france);
    expect(container.querySelectorAll('path[data-highlighted="true"]')).toHaveLength(1);
    fireEvent.click(france);
    expect(onSelect).toHaveBeenCalledWith('FR');
    fireEvent.blur(france);
    expect(container.querySelectorAll('path[data-highlighted="true"]')).toHaveLength(0);
  });
  it('switches measure and map extent locally, without changing filters or rounding large amounts', () => {
    const fixture = insightsFixture();
    const { container, onSelect } = atlas(insightsFixture({ territories: [
      { ...fixture.territories[0], bookedMinor: '900719925474099301' }, fixture.territories[1],
    ] }));
    fireEvent.click(within(screen.getByRole('group', { name: 'Map measure' })).getByRole('button', { name: 'Booked sales' }));
    expect(screen.getByRole('img', { name: /^Booked sales in EUR by commercial territory, Europe view/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Filter territory FR:/ })).toHaveTextContent('€9,007,199,254,740,993.01');
    fireEvent.click(screen.getByRole('button', { name: 'World' }));
    expect(screen.getByRole('img', { name: /^Booked sales in EUR by commercial territory, world view/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'World' })).toHaveAttribute('aria-pressed', 'true');
    expect(container.querySelectorAll('.insights-map-label')).toHaveLength(0);
    const france = screen.getByRole('button', { name: /^Filter territory FR:/ });
    fireEvent.focus(france);
    expect(container.querySelectorAll('.insights-map-label')).toHaveLength(1);
    expect(container.querySelector('.insights-map-label')).toHaveTextContent('FR');
    fireEvent.blur(france);
    fireEvent.click(screen.getByRole('button', { name: 'Europe' }));
    fireEvent.click(within(screen.getByRole('group', { name: 'Map measure' })).getByRole('button', { name: 'Customers' }));
    expect(onSelect).not.toHaveBeenCalled();
  });
  it('uses cohort distinct customers, not a sum of overlapping territory counts', () => {
    const fixture = insightsFixture();
    atlas(insightsFixture({ territories: fixture.territories.map(row => ({ ...row, customers: 2 })) }));
    expect(screen.getByLabelText('Cohort distinct customers').querySelector('strong')).toHaveTextContent(/^2$/);
    expect(screen.getByText(/territory counts must not be added as unique people/)).toBeInTheDocument();
    expect(screen.getByText(/not a live Eventhouse feed/)).toBeInTheDocument();
  });
  it('keeps unsupported geography and zero observations visible and filterable', () => {
    const fixture = insightsFixture();
    const { container, onSelect } = atlas(insightsFixture({ territories: [
      { ...fixture.territories[0], territory: 'Unknown', bookedMinor: '0', customers: 0 },
    ] }));
    expect(container.querySelectorAll('path[data-active="true"]')).toHaveLength(0);
    expect(screen.getByText(/Not drawn on this map: Unknown/)).toBeInTheDocument();
    const unknown = screen.getByRole('button', { name: /^Filter territory Unknown: not mapped/ });
    expect(unknown).toHaveTextContent('0customers€0.00');
    fireEvent.click(unknown);
    expect(onSelect).toHaveBeenCalledWith('Unknown');
    expect(container.querySelector('.insights-map-row-bar > span')).toHaveStyle({ width: '0%' });
  });
  it('defaults Canadian cohorts to the world and explains an explicitly narrowed view', () => {
    const fixture = insightsFixture();
    atlas(insightsFixture({ filters: { ...fixture.filters, currency: 'CAD' }, territories: [
      { ...fixture.territories[0], territory: 'CA' },
    ] }));
    expect(screen.getByRole('button', { name: 'World' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: /^Filter territory CA: Canada/ })).toHaveTextContent('CA$20.00');
    fireEvent.click(screen.getByRole('button', { name: 'Europe' }));
    expect(screen.getByText(/Some selected territories are outside Europe/)).toBeInTheDocument();
  });
  it('disables cross-filters during native reads and gives an explicit missing-breakdown state', () => {
    const view = atlas(insightsFixture(), true);
    const france = screen.getByRole('button', { name: /^Filter territory FR:/ });
    expect(france).toBeDisabled();
    fireEvent.click(france);
    expect(view.onSelect).not.toHaveBeenCalled();
    view.unmount();
    atlas(insightsFixture({ territories: [] }));
    expect(screen.getByText('No territory breakdown is available for this selection.')).toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });
});

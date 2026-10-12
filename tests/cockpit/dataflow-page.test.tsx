import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { DataFlowPage } from '../../apps/cockpit/src/pages/DataFlowPage';
import documentHtml from '../../apps/cockpit/src/assets/msflix-dataflow-en.html?raw';

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });

function completeLoad(frame: HTMLIFrameElement) {
  const embedded = document.implementation.createHTMLDocument('Test Data Flow');
  embedded.documentElement.dataset.explorerReady = 'true';
  // jsdom does not implement srcDoc initialization.
  vi.spyOn(frame, 'contentDocument', 'get').mockReturnValue(embedded);
  fireEvent.load(frame);
}

it('embeds the whole supplied document and only reveals it after explorer initialization', async () => {
  render(<DataFlowPage onRetry={vi.fn()} />);
  const frame = screen.getByTitle<HTMLIFrameElement>('MSFlix data flow explorer');
  expect(frame).toHaveAttribute('srcdoc', documentHtml);
  expect(frame).toHaveAttribute('allow', 'clipboard-write');
  expect(frame).not.toHaveAttribute('sandbox');
  expect(screen.getByRole('status')).toHaveTextContent('Loading the MSFlix data flow explorer');
  expect(frame).not.toBeVisible();
  await act(async () => { completeLoad(frame); });
  expect(frame).toBeVisible();
  expect(screen.getByRole('region', { name: 'Data Flow' })).toHaveAttribute('aria-busy', 'false');
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
});

it('removes a document that fails to initialize and offers an isolated retry', () => {
  const retry = vi.fn();
  render(<DataFlowPage onRetry={retry} />);
  fireEvent.load(screen.getByTitle('MSFlix data flow explorer'));
  expect(screen.getByRole('alert')).toHaveTextContent('Data flow could not load');
  expect(screen.queryByTitle('MSFlix data flow explorer')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Retry data flow' }));
  expect(retry).toHaveBeenCalledOnce();
});

it('offers recovery if the loaded document cannot be inspected', () => {
  render(<DataFlowPage onRetry={vi.fn()} />);
  const frame = screen.getByTitle<HTMLIFrameElement>('MSFlix data flow explorer');
  vi.spyOn(frame, 'contentDocument', 'get').mockImplementation(() => { throw new DOMException('Access denied'); });
  fireEvent.load(frame);
  expect(screen.getByRole('alert')).toHaveTextContent('Data flow could not load');
});

it('offers recovery when the document never signals load', () => {
  vi.useFakeTimers();
  render(<DataFlowPage onRetry={vi.fn()} />);
  act(() => { vi.advanceTimersByTime(15_000); });
  expect(screen.getByRole('button', { name: 'Retry data flow' })).toBeInTheDocument();
  expect(screen.queryByTitle('MSFlix data flow explorer')).not.toBeInTheDocument();
});

it('cancels the initialization timeout after a successful load', () => {
  vi.useFakeTimers();
  render(<DataFlowPage onRetry={vi.fn()} />);
  const frame = screen.getByTitle<HTMLIFrameElement>('MSFlix data flow explorer');
  completeLoad(frame);
  act(() => { vi.advanceTimersByTime(30_000); });
  expect(frame).toBeVisible();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

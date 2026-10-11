import { afterEach, beforeAll, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { FlixyAssistant } from '../../apps/cockpit/src/components/FlixyAssistant';
import type { FlixyAnswer, FlixyAsk } from '../../apps/cockpit/src/domain/flixy-chat';
import { loadMarkdownCode } from '../../apps/cockpit/src/services/deferred';

beforeAll(async () => { await loadMarkdownCode(); });
afterEach(cleanup);

function deferredAnswer() {
  let resolve!: (answer: FlixyAnswer) => void;
  const promise = new Promise<FlixyAnswer>(accept => { resolve = accept; });
  return { promise, resolve };
}

it('restores focus, retains chat on reopen, and isolates a new user from stale answers', async () => {
  // Component-only fixtures at the ask boundary, not native Data Agent verification.
  const stale = deferredAnswer();
  const current = deferredAnswer();
  const firstQuestion = 'Question de test sur les revenus.';
  const firstAnswer = 'Réponse de test du premier utilisateur.';
  const pendingQuestion = 'Autre question de test du premier utilisateur.';
  const currentQuestion = 'Question de test du nouvel utilisateur.';
  const staleAnswer = 'Réponse tardive de test à ignorer.';
  const currentAnswer = 'Réponse de test du nouvel utilisateur.';
  const ask = vi.fn<FlixyAsk>()
    .mockResolvedValueOnce({ text: firstAnswer, sources: [] })
    // Deliberately resolve even after abort to exercise stale-response protection.
    .mockReturnValueOnce(stale.promise)
    .mockReturnValueOnce(current.promise);
  const view = render(<FlixyAssistant ask={ask} userKey="test-user-a" />);

  const trigger = screen.getByRole('button', { name: 'Open Flixy' });
  expect(ask).not.toHaveBeenCalled();
  fireEvent.click(trigger);
  const panel = screen.getByRole('dialog', { name: 'Flixy' });
  const input = within(panel).getByRole('textbox', { name: 'Your question' });
  expect(input.tagName).toBe('TEXTAREA');
  expect(input).toHaveFocus();
  expect(panel).not.toHaveAttribute('aria-modal');

  fireEvent.change(input, { target: { value: firstQuestion } });
  fireEvent.click(within(panel).getByRole('button', { name: 'Send' }));
  expect(await within(panel).findByText(firstAnswer)).toBeVisible();

  fireEvent.keyDown(input, { key: 'Escape' });
  expect(panel).not.toBeVisible();
  expect(trigger).toHaveAttribute('aria-expanded', 'false');
  expect(trigger).toHaveFocus();
  fireEvent.click(trigger);
  expect(input).toHaveFocus();
  const log = within(panel).getByRole('log', { name: 'Conversation with Flixy' });
  expect(within(log).getByText(firstQuestion)).toBeVisible();
  expect(within(log).getByText(firstAnswer)).toBeVisible();
  expect(ask).toHaveBeenCalledOnce();

  fireEvent.change(input, { target: { value: pendingQuestion } });
  fireEvent.click(within(panel).getByRole('button', { name: 'Send' }));
  expect(ask).toHaveBeenCalledTimes(2);
  expect(ask.mock.calls[1][1]).toEqual([
    { role: 'user', text: firstQuestion },
    { role: 'assistant', text: firstAnswer },
  ]);
  const oldSignal = ask.mock.calls[1][2];
  expect(oldSignal.aborted).toBe(false);

  view.rerender(<FlixyAssistant ask={ask} userKey="test-user-b" />);
  expect(oldSignal.aborted).toBe(true);
  expect(screen.queryByText(firstQuestion)).not.toBeInTheDocument();
  expect(screen.queryByText(firstAnswer)).not.toBeInTheDocument();
  expect(screen.queryByText(pendingQuestion)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Open Flixy' }));
  const newInput = screen.getByRole('textbox', { name: 'Your question' });
  const newLog = screen.getByRole('log', { name: 'Conversation with Flixy' });
  expect(newInput).toHaveFocus();
  expect(newInput).toHaveValue('');
  expect(newLog).toHaveAttribute('aria-busy', 'false');
  expect(within(newLog).queryAllByRole('listitem')).toHaveLength(0);
  expect(ask).toHaveBeenCalledTimes(2);

  fireEvent.change(newInput, { target: { value: currentQuestion } });
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));
  expect(ask).toHaveBeenCalledTimes(3);
  expect(ask.mock.calls[2][0]).toBe(currentQuestion);
  expect(ask.mock.calls[2][1]).toEqual([]);
  await act(async () => {
    stale.resolve({ text: staleAnswer, sources: [] });
    await stale.promise;
  });
  expect(screen.queryByText(staleAnswer)).not.toBeInTheDocument();
  expect(within(newLog).getByText(currentQuestion)).toBeVisible();
  expect(newLog).toHaveAttribute('aria-busy', 'true');
  expect(ask.mock.calls[2][2].aborted).toBe(false);

  await act(async () => {
    current.resolve({ text: currentAnswer, sources: [] });
    await current.promise;
  });
  expect(within(newLog).getByText(currentAnswer)).toBeVisible();
  expect(within(newLog).getAllByRole('listitem')).toHaveLength(2);
  expect(newLog).toHaveAttribute('aria-busy', 'false');
  expect(screen.queryByText(staleAnswer)).not.toBeInTheDocument();
  expect(ask).toHaveBeenCalledTimes(3);
});

it('renders formatted English-interface answers while accepting French questions', async () => {
  const markdown = [
    '## Locations',
    '',
    '**305 films** et *700 clients*.',
    '',
    '| Devise | Film | Commandes |',
    '| --- | --- | ---: |',
    '| EUR | Ghost | 12 |',
    '',
    '- Premier point',
    '- Deuxième point',
    '',
    'Source : `gold.fact_order_line`.',
    '',
    '```sql',
    'SELECT COUNT(*) FROM gold.fact_order_line;',
    '```',
    '',
    '[Fabric](https://app.fabric.microsoft.com/)',
  ].join('\n');
  const ask = vi.fn<FlixyAsk>().mockResolvedValue({ text: markdown, sources: [] });
  render(<FlixyAssistant ask={ask} userKey="test-user" />);
  fireEvent.click(screen.getByRole('button', { name: 'Open Flixy' }));
  expect(screen.getByText('Read-only · no transactions')).toBeVisible();
  expect(screen.getByRole('button', { name: 'Clear conversation' })).toBeVisible();
  const input = screen.getByRole('textbox', { name: 'Your question' });
  fireEvent.change(input, { target: { value: 'Quels films sont les plus loués ?' } });
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));

  const table = await screen.findByRole('table');
  expect(within(table).getAllByRole('columnheader')).toHaveLength(3);
  expect(within(table).getByRole('cell', { name: 'Ghost' })).toBeVisible();
  expect(screen.getByRole('region', { name: 'Response table' })).toHaveAttribute('tabindex', '0');
  expect(screen.getByText('305 films').tagName).toBe('STRONG');
  expect(screen.getByText('700 clients').tagName).toBe('EM');
  expect(screen.getByRole('heading', { name: 'Locations', level: 3 })).toBeVisible();
  expect(screen.getByText('Premier point').closest('ul')).not.toBeNull();
  expect(screen.getByText('gold.fact_order_line').tagName).toBe('CODE');
  expect(screen.getByText('SELECT COUNT(*) FROM gold.fact_order_line;').closest('pre')).not.toBeNull();
  expect(screen.getByRole('link', { name: /Fabric/ })).toHaveAttribute('rel', 'noopener noreferrer');
  expect(screen.queryByText('**305 films**')).not.toBeInTheDocument();
  expect(ask.mock.calls[0][0]).toBe('Quels films sont les plus loués ?');
});

it('does not execute answer HTML, load images, or link unsafe Markdown URLs', async () => {
  const text = [
    '<script>window.evil = true</script>',
    '<iframe src="https://example.org"></iframe>',
    '![tracker](https://example.org/track.png)',
    '[unsafe](javascript:alert%281%29)',
    '[local](file:///etc/passwd)',
    '[credentials](https://name:password@example.org/)',
    '[safe](https://learn.microsoft.com/en-us/fabric/)',
  ].join('\n\n');
  const ask = vi.fn<FlixyAsk>().mockResolvedValue({ text, sources: [] });
  render(<FlixyAssistant ask={ask} userKey="test-user" />);
  fireEvent.click(screen.getByRole('button', { name: 'Open Flixy' }));
  const input = screen.getByRole('textbox', { name: 'Your question' });
  fireEvent.change(input, { target: { value: '**Show sources literally**' } });
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));
  const safe = await screen.findByRole('link', { name: /safe \(opens/ });
  expect(safe).toHaveAttribute('href', 'https://learn.microsoft.com/en-us/fabric/');
  const log = screen.getByRole('log');
  expect(within(log).getAllByRole('link')).toHaveLength(1);
  expect(log.querySelector('script,iframe,img')).toBeNull();
  expect(within(log).getByText('unsafe').tagName).toBe('SPAN');
  expect(within(log).getByText('local').tagName).toBe('SPAN');
  expect(within(log).getByText('credentials').tagName).toBe('SPAN');
  expect(within(log).getByText('**Show sources literally**').tagName).toBe('P');
});

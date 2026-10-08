import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { FlixyAssistant } from '../../apps/cockpit/src/components/FlixyAssistant';
import type { FlixyAnswer, FlixyAsk } from '../../apps/cockpit/src/domain/flixy-chat';

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

  const trigger = screen.getByRole('button', { name: 'Ouvrir Flixy' });
  expect(ask).not.toHaveBeenCalled();
  fireEvent.click(trigger);
  const panel = screen.getByRole('dialog', { name: 'Flixy' });
  const input = within(panel).getByRole('textbox', { name: 'Votre question' });
  expect(input.tagName).toBe('TEXTAREA');
  expect(input).toHaveFocus();
  expect(panel).not.toHaveAttribute('aria-modal');

  fireEvent.change(input, { target: { value: firstQuestion } });
  fireEvent.click(within(panel).getByRole('button', { name: 'Envoyer' }));
  expect(await within(panel).findByText(firstAnswer)).toBeVisible();

  fireEvent.keyDown(input, { key: 'Escape' });
  expect(panel).not.toBeVisible();
  expect(trigger).toHaveAttribute('aria-expanded', 'false');
  expect(trigger).toHaveFocus();
  fireEvent.click(trigger);
  expect(input).toHaveFocus();
  const log = within(panel).getByRole('log', { name: 'Conversation avec Flixy' });
  expect(within(log).getByText(firstQuestion)).toBeVisible();
  expect(within(log).getByText(firstAnswer)).toBeVisible();
  expect(ask).toHaveBeenCalledOnce();

  fireEvent.change(input, { target: { value: pendingQuestion } });
  fireEvent.click(within(panel).getByRole('button', { name: 'Envoyer' }));
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
  fireEvent.click(screen.getByRole('button', { name: 'Ouvrir Flixy' }));
  const newInput = screen.getByRole('textbox', { name: 'Votre question' });
  const newLog = screen.getByRole('log', { name: 'Conversation avec Flixy' });
  expect(newInput).toHaveFocus();
  expect(newInput).toHaveValue('');
  expect(newLog).toHaveAttribute('aria-busy', 'false');
  expect(within(newLog).queryAllByRole('listitem')).toHaveLength(0);
  expect(ask).toHaveBeenCalledTimes(2);

  fireEvent.change(newInput, { target: { value: currentQuestion } });
  fireEvent.click(screen.getByRole('button', { name: 'Envoyer' }));
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

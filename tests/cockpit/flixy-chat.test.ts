import { describe, expect, it } from 'vitest';
import {
  boundFlixyHistory,
  MAX_CONTEXT_CHARACTERS,
  MAX_CONTEXT_MESSAGES,
  MAX_QUESTION_CHARACTERS,
  safeFlixySourceUrl,
  type FlixyMessage,
} from '../../apps/cockpit/src/domain/flixy-chat';

describe('Flixy history bounds', () => {
  it('exports the agreed request limits', () => {
    expect(MAX_QUESTION_CHARACTERS).toBe(2000);
    expect(MAX_CONTEXT_CHARACTERS).toBe(12000);
    expect(MAX_CONTEXT_MESSAGES).toBe(12);
  });

  it('returns no context for empty or whitespace-only messages', () => {
    expect(boundFlixyHistory([])).toEqual([]);
    expect(boundFlixyHistory([
      { role: 'user', text: '' },
      { role: 'assistant', text: ' \n\t ' },
    ])).toEqual([]);
  });

  it('keeps only the latest twelve nonblank messages in chronological order', () => {
    const history: FlixyMessage[] = Array.from({ length: 16 }, (_, index) => ({
      role: index % 2 ? 'assistant' : 'user',
      text: `Message ${index}`,
    }));
    expect(boundFlixyHistory([...history, { role: 'user', text: ' ' }]))
      .toEqual(history.slice(-MAX_CONTEXT_MESSAGES));
  });

  it('trims boundaries, preserves internal line breaks and never mutates input', () => {
    const history: readonly FlixyMessage[] = Object.freeze([
      Object.freeze({ role: 'user' as const, text: '  Question\nsur MSFlix  ' }),
      Object.freeze({ role: 'assistant' as const, text: '\nRéponse\nsur deux lignes\n' }),
    ]);
    const result = boundFlixyHistory(history);
    expect(result).toEqual([
      { role: 'user', text: 'Question\nsur MSFlix' },
      { role: 'assistant', text: 'Réponse\nsur deux lignes' },
    ]);
    expect(result[0]).not.toBe(history[0]);
    expect(history[0].text).toBe('  Question\nsur MSFlix  ');
  });

  it('prioritizes recent text and truncates the oldest retained message to the remaining budget', () => {
    const result = boundFlixyHistory([
      { role: 'user', text: 'No longer in context' },
      { role: 'assistant', text: 'a'.repeat(7000) },
      { role: 'user', text: 'b'.repeat(7000) },
    ]);
    expect(result).toEqual([
      { role: 'assistant', text: 'a'.repeat(5000) },
      { role: 'user', text: 'b'.repeat(7000) },
    ]);
    expect(result.reduce((total, message) => total + message.text.length, 0))
      .toBe(MAX_CONTEXT_CHARACTERS);
  });

  it('handles a single oversized answer without losing the latest context or exceeding the limit', () => {
    const result = boundFlixyHistory([
      { role: 'user', text: 'Older question' },
      { role: 'assistant', text: 'x'.repeat(MAX_CONTEXT_CHARACTERS + 1000) },
    ]);
    expect(result).toEqual([{ role: 'assistant', text: 'x'.repeat(MAX_CONTEXT_CHARACTERS) }]);
    expect(boundFlixyHistory(result)).toEqual(result);
  });

  it('keeps an exact-budget message without admitting any older text', () => {
    expect(boundFlixyHistory([
      { role: 'user', text: 'Older' },
      { role: 'assistant', text: 'x'.repeat(MAX_CONTEXT_CHARACTERS) },
    ])).toEqual([{ role: 'assistant', text: 'x'.repeat(MAX_CONTEXT_CHARACTERS) }]);
  });

  it('does not split a surrogate pair when truncating a long answer', () => {
    const text = 'a'.repeat(MAX_CONTEXT_CHARACTERS - 1);
    expect(boundFlixyHistory([{ role: 'assistant', text: `${text}😀` }]))
      .toEqual([{ role: 'assistant', text }]);
  });

  it('does not add a partial emoji when only one code unit remains', () => {
    const latest: FlixyMessage = { role: 'assistant', text: 'x'.repeat(MAX_CONTEXT_CHARACTERS - 1) };
    expect(boundFlixyHistory([{ role: 'user', text: '😀' }, latest])).toEqual([latest]);
  });
});

describe('Flixy source URLs', () => {
  it('accepts and normalizes absolute HTTPS links while preserving query and fragment', () => {
    expect(safeFlixySourceUrl('HTTPS://EXAMPLE.COM/report?q=MSFlix%20Gold#sources'))
      .toBe('https://example.com/report?q=MSFlix%20Gold#sources');
  });

  it.each([
    undefined,
    '',
    'http://example.com',
    'javascript:alert(1)',
    'data:text/html,<script>alert(1)</script>',
    'blob:https://example.com/id',
    'file:///report',
    '//example.com/report',
    '/relative/report',
    'https:example.com',
    'https://',
    'https:///example.com',
    'https://[invalid',
    'https://reader:secret@example.com/report',
    'https://reader@example.com/report',
    ' https://example.com',
    'https://example.com/a b',
    'https://exam\nple.com',
    'https://example.com/\u0000',
    'https://example.com/\u007F',
    'https://example.com\\@other.example',
  ])('leaves unsafe or malformed source %j unlinked', url => {
    expect(safeFlixySourceUrl(url)).toBeUndefined();
  });
});

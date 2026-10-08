export interface FlixyMessage {
  role: 'user' | 'assistant';
  text: string;
}

export interface FlixySource {
  label: string;
  url?: string;
}

export interface FlixyAnswer {
  text: string;
  sources: FlixySource[];
}

export type FlixyAsk = (
  question: string,
  history: FlixyMessage[],
  signal: AbortSignal,
) => Promise<FlixyAnswer>;

export const MAX_QUESTION_CHARACTERS = 2000;
export const MAX_CONTEXT_CHARACTERS = 12000;
export const MAX_CONTEXT_MESSAGES = 12;

/**
 * Keep the newest nonblank messages, trimmed and in chronological order.
 * Text budgets use UTF-16 code units, like textarea.maxLength. The oldest
 * retained message may keep only its prefix; never split a surrogate pair.
 * Only prior messages belong here: the current question is sent separately.
 */
export function boundFlixyHistory(history: readonly FlixyMessage[]): FlixyMessage[] {
  const bounded: FlixyMessage[] = [];
  let remaining = MAX_CONTEXT_CHARACTERS;

  for (let index = history.length - 1; index >= 0 && remaining > 0; index--) {
    if (bounded.length === MAX_CONTEXT_MESSAGES) break;
    const original = history[index].text.trim();
    if (!original) continue;

    let text = original.slice(0, remaining);
    if (text.length < original.length && /[\uD800-\uDBFF]$/.test(text)) {
      text = text.slice(0, -1);
    }
    if (text) {
      bounded.push({ role: history[index].role, text });
      remaining -= text.length;
    }
    if (text.length < original.length) break;
  }
  return bounded.reverse();
}

/** Allow only absolute HTTPS links without credentials or ambiguous URL syntax. */
export function safeFlixySourceUrl(url?: string): string | undefined {
  if (!url || !/^https:\/\/[^/?#]/i.test(url) || /[\s\\\p{Cc}]/u.test(url)) {
    return undefined;
  }
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== 'https:' || !parsed.hostname || parsed.username || parsed.password) {
      return undefined;
    }
    return parsed.href;
  } catch {
    return undefined;
  }
}

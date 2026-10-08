import type { FlixyAsk } from '@/domain/flixy-chat';
import { getRayfinClient } from './rayfinClient';

export const askFlixy: FlixyAsk = (question, history, signal) => {
  if (signal.aborted) return Promise.reject(new DOMException('Attente arretee.', 'AbortError'));
  return new Promise((resolve, reject) => {
    const abort = () => reject(new DOMException('Attente arretee.', 'AbortError'));
    signal.addEventListener('abort', abort, { once: true });
    getRayfinClient().functions.flixyAsk.invoke({
      question, historyJson: JSON.stringify(history),
    }, { timeoutMs: 200000 }).then(
      answer => { if (!signal.aborted) resolve(answer); },
      error => { if (!signal.aborted) reject(error); },
    ).finally(() => signal.removeEventListener('abort', abort));
  });
};

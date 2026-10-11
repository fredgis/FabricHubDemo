import { lazy, useCallback, useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { DeferredPanel } from '@/components/DeferredPanel';
import { canPrefetch, loadMarkdownCode } from '@/services/deferred';
import { ArrowCounterClockwise, ArrowUpRight, ChatCircleDots, PaperPlaneRight, Stop, Trash, X } from '@phosphor-icons/react';
import {
  boundFlixyHistory,
  MAX_QUESTION_CHARACTERS,
  safeFlixySourceUrl,
  type FlixyAsk,
  type FlixyMessage,
  type FlixySource,
} from '@/domain/flixy-chat';
import './FlixyAssistant.css';

export interface FlixyAssistantProps {
  ask: FlixyAsk;
  userKey: string;
}

type TranscriptMessage = FlixyMessage & { sources?: FlixySource[] };
type Attempt = { question: string } & (
  | { status: 'pending' | 'stopped' }
  | { status: 'error'; message: string }
);
type ActiveRequest = { controller: AbortController; question: string };
const Markdown = lazy(loadMarkdownCode);

const SUGGESTIONS = [
  'Which films have the most rentals?',
  'Show recorded sales by currency.',
  'Show a real customer-to-film journey.',
];

function TranscriptItem({ role, text, sources = [] }: TranscriptMessage) {
  return <li className={`flixy-assistant__message flixy-assistant__message--${role}`}>
    <span className="flixy-assistant__speaker">{role === 'user' ? 'You' : 'Flixy'}</span>
    {role === 'user' ? <p className="flixy-assistant__message-text">{text}</p>
      : <div className="flixy-assistant__markdown">
        <DeferredPanel label="Flixy formatting" fallback={<p className="flixy-assistant__message-text">{text}</p>}>
          <Markdown text={text} />
        </DeferredPanel>
      </div>}
    {sources.length > 0 && <div className="flixy-assistant__sources">
      <p>Sources</p>
      <ul aria-label="Answer sources">
        {sources.map((source, index) => {
          const href = safeFlixySourceUrl(source.url);
          const label = source.label.trim() || `Source ${index + 1}`;
          return <li key={index}>{href
            ? <a href={href} target="_blank" rel="noopener noreferrer">
              {label}<ArrowUpRight size={14} aria-hidden="true" />
              <span className="flixy-assistant__sr-only"> (opens in a new tab)</span>
            </a>
            : <span>{label}</span>}</li>;
        })}
      </ul>
    </div>}
  </li>;
}

/** Parent mounts this inside the authenticated shell and supplies the transport. */
export function FlixyAssistant({ ask, userKey }: FlixyAssistantProps) {
  // A keyed session prevents even a transient render of the previous user's chat.
  return <FlixySession key={userKey} ask={ask} />;
}

function FlixySession({ ask }: Pick<FlixyAssistantProps, 'ask'>) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState('');
  const [messages, setMessages] = useState<TranscriptMessage[]>([]);
  const [attempt, setAttempt] = useState<Attempt | null>(null);
  const [announcement, setAnnouncement] = useState('');
  const triggerRef = useRef<HTMLButtonElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const activeRequest = useRef<ActiveRequest | null>(null);
  const pending = attempt?.status === 'pending';
  const error = attempt?.status === 'error' ? attempt.message : '';
  const tooLong = draft.length > MAX_QUESTION_CHARACTERS;
  const empty = !draft.trim();
  const status = pending
    ? 'Reading MSFlix data… You can keep using the cockpit.'
    : announcement;
  const sendHint = tooLong
    ? 'Questions are limited to 2,000 characters.'
    : empty ? 'Enter a question to send.' : 'Review answers and their sources.';

  const close = useCallback(() => {
    setOpen(false);
    triggerRef.current?.focus({ preventScroll: true });
  }, []);

  useEffect(() => {
    if (open && canPrefetch()) void loadMarkdownCode().catch(() => {});
  }, [open]);

  useEffect(() => {
    if (!open) return;
    inputRef.current?.focus({ preventScroll: true });
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !event.defaultPrevented && !event.isComposing) {
        event.preventDefault();
        close();
      }
    };
    document.addEventListener('keydown', onEscape);
    return () => document.removeEventListener('keydown', onEscape);
  }, [open, close]);

  useEffect(() => {
    if (open && threadRef.current) {
      // Scroll the transcript, never the page; no motion or focus stealing.
      threadRef.current.scrollTop = threadRef.current.scrollHeight;
    }
  }, [open, messages, attempt]);

  useEffect(() => () => {
    const request = activeRequest.current;
    activeRequest.current = null;
    request?.controller.abort();
  }, []);

  function clearConversation() {
    const request = activeRequest.current;
    activeRequest.current = null;
    request?.controller.abort();
    setMessages([]);
    setAttempt(null);
    setDraft('');
    setAnnouncement('Conversation cleared.');
    inputRef.current?.focus({ preventScroll: true });
  }

  function stopWaiting() {
    const request = activeRequest.current;
    if (!request) return;
    activeRequest.current = null;
    request.controller.abort();
    setAttempt({ question: request.question, status: 'stopped' });
    setDraft(request.question);
    setAnnouncement('Stopped waiting in the cockpit. The service may still be processing your question.');
    inputRef.current?.focus({ preventScroll: true });
  }

  async function send(value: string) {
    const question = value.trim();
    // The ref closes the same-tick double-submit race before React re-renders.
    if (pending || activeRequest.current || !question || value.length > MAX_QUESTION_CHARACTERS) return;
    const request = { controller: new AbortController(), question };
    activeRequest.current = request;
    setDraft(question);
    setAttempt({ question, status: 'pending' });
    setAnnouncement('');

    try {
      // Failed/stopped attempts never enter context or duplicate a retried turn.
      const answer = await ask(question, boundFlixyHistory(messages), request.controller.signal);
      if (activeRequest.current !== request || request.controller.signal.aborted) return;
      setMessages(previous => [
        ...previous,
        { role: 'user', text: question },
        { role: 'assistant', text: answer.text, sources: answer.sources },
      ]);
      setDraft('');
      setAttempt(null);
      setAnnouncement('Answer received.');
    } catch (failure) {
      if (activeRequest.current !== request || request.controller.signal.aborted) return;
      const detail = failure instanceof Error ? failure.message : typeof failure === 'string' ? failure : '';
      setAttempt({
        question,
        status: 'error',
        message: detail.trim()
          ? `Flixy could not answer: ${detail}`
          : 'Flixy could not answer. Try again or check your connection.',
      });
    } finally {
      if (activeRequest.current === request) activeRequest.current = null;
    }
  }

  return createPortal(<div className="flixy-assistant" lang="en">
    <button
      ref={triggerRef}
      type="button"
      className="flixy-assistant__trigger"
      aria-label={open ? 'Close Flixy' : 'Open Flixy'}
      aria-expanded={open}
      aria-controls={`${id}-panel`}
      aria-haspopup="dialog"
      onClick={() => open ? close() : setOpen(true)}
    >
      <ChatCircleDots size={24} weight="fill" aria-hidden="true" />Flixy
    </button>

    <div
      id={`${id}-panel`}
      className="flixy-assistant__panel"
      role="dialog"
      aria-labelledby={`${id}-title`}
      aria-describedby={`${id}-description`}
      hidden={!open}
    >
      <div className="flixy-assistant__header">
        <ChatCircleDots className="flixy-assistant__mark" size={28} aria-hidden="true" />
        <div className="flixy-assistant__identity">
          <span className="flixy-assistant__eyebrow">MSFLIX</span>
          <h2 id={`${id}-title`}>Flixy</h2>
          <p id={`${id}-description`}>Read-only · no transactions</p>
        </div>
        <button type="button" className="flixy-assistant__close" aria-label="Close Flixy panel" onClick={close}>
          <X size={20} aria-hidden="true" />
        </button>
      </div>
      <div className="flixy-assistant__toolbar">
        <button type="button" onClick={clearConversation}>
          <Trash size={16} aria-hidden="true" />Clear conversation
        </button>
      </div>

      <div className="flixy-assistant__thread" ref={threadRef}>
        {messages.length === 0 && !attempt && <div className="flixy-assistant__empty">
          <h3>What would you like to know?</h3>
          <p>Explore the catalogue, sales and customer activity. Ask in English or French.</p>
          <ul className="flixy-assistant__suggestions" aria-label="Suggested questions">
            {SUGGESTIONS.map(question => <li key={question}>
              <button type="button" onClick={() => {
                setDraft(question);
                inputRef.current?.focus({ preventScroll: true });
              }}>{question}<ArrowUpRight size={16} aria-hidden="true" /></button>
            </li>)}
          </ul>
        </div>}
        <div role="log" aria-label="Conversation with Flixy" aria-live="polite" aria-relevant="additions" aria-busy={pending}>
          <ol className="flixy-assistant__messages">
            {messages.map((message, index) => <TranscriptItem key={index} {...message} />)}
            {attempt && <TranscriptItem role="user" text={attempt.question} />}
          </ol>
        </div>
      </div>

      <form className="flixy-assistant__composer" onSubmit={event => {
        event.preventDefault();
        void send(draft);
      }}>
        <p id={`${id}-status`} role="status" aria-atomic="true"
          className={status ? 'flixy-assistant__status' : 'flixy-assistant__sr-only'}>{status}</p>
        {attempt && attempt.status !== 'pending' && <div className="flixy-assistant__recovery">
          {error && <p id={`${id}-error`} role="alert">{error}</p>}
          <button type="button" aria-describedby={error ? `${id}-error` : `${id}-status`}
            onClick={() => {
              void send(attempt.question);
              inputRef.current?.focus({ preventScroll: true });
            }}>
            <ArrowCounterClockwise size={16} aria-hidden="true" />Try again
          </button>
        </div>}
        <div className="flixy-assistant__field-heading">
          <label htmlFor={`${id}-question`}>Your question</label>
          <span id={`${id}-count`}>{draft.length} / 2,000 characters</span>
        </div>
        <textarea
          id={`${id}-question`}
          ref={inputRef}
          value={draft}
          required
          rows={3}
          maxLength={MAX_QUESTION_CHARACTERS}
          readOnly={pending}
          aria-invalid={tooLong || undefined}
          aria-describedby={`${id}-hint ${id}-count ${pending ? `${id}-status` : `${id}-send-hint`}${error ? ` ${id}-error` : ''}`}
          placeholder="Ask about MSFlix data…"
          onChange={event => setDraft(event.target.value)}
          onKeyDown={event => {
            if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing
              || event.nativeEvent.keyCode === 229) return;
            event.preventDefault();
            if (!event.repeat) void send(draft);
          }}
        />
        <p id={`${id}-hint`} className="flixy-assistant__hint">Enter to send · Shift+Enter for a new line.</p>
        <div className="flixy-assistant__actions">
          {pending
            ? <button type="button" onClick={stopWaiting}>
              <Stop size={16} aria-hidden="true" />Stop waiting
            </button>
            : <p id={`${id}-send-hint`} className="flixy-assistant__hint">{sendHint}</p>}
          <button type="submit" className="flixy-assistant__send" disabled={pending || empty || tooLong}
            aria-describedby={pending ? `${id}-status` : `${id}-send-hint`}>
            Send<PaperPlaneRight size={16} aria-hidden="true" />
          </button>
        </div>
      </form>
    </div>
  </div>, document.body);
}

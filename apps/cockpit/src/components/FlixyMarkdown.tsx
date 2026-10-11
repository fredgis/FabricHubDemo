import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { safeFlixySourceUrl } from '@/domain/flixy-chat';

export default function FlixyMarkdown({ text }: { text: string }) {
  return <Markdown remarkPlugins={[remarkGfm]} skipHtml
    allowedElements={['p', 'br', 'strong', 'em', 'del', 'ul', 'ol', 'li', 'blockquote',
      'pre', 'code', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'table', 'thead', 'tbody',
      'tr', 'th', 'td', 'a', 'hr']}
    urlTransform={url => safeFlixySourceUrl(url) ?? ''}
    components={{
      a: ({ href, children }) => href
        ? <a href={href} target="_blank" rel="noopener noreferrer">{children}
          <span className="flixy-assistant__sr-only"> (opens in a new tab)</span></a>
        : <span>{children}</span>,
      h1: ({ children }) => <h3>{children}</h3>,
      h2: ({ children }) => <h3>{children}</h3>,
      h3: ({ children }) => <h3>{children}</h3>,
      h4: ({ children }) => <h4>{children}</h4>,
      h5: ({ children }) => <h4>{children}</h4>,
      h6: ({ children }) => <h4>{children}</h4>,
      table: ({ children }) => <div className="flixy-assistant__table-scroll"
        role="region" aria-label="Response table" tabIndex={0}><table>{children}</table></div>,
    }}>{text}</Markdown>;
}

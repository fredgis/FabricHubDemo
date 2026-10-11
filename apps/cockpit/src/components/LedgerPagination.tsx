import './LedgerPagination.css';

type Props = {
  label: 'Orders' | 'Playback';
  page: number; pageSize: number; total: number;
  disabled: boolean; onPage: (page: number) => void;
};

export function LedgerPagination({ label, page, pageSize, total, disabled, onPage }: Props) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const subject = label.toLowerCase();
  return <nav className="ledger-pagination" aria-label={`${label} pagination`}>
    <p role="status" aria-atomic="true">{label}: {total.toLocaleString('en')} total
      <span>Page {page.toLocaleString('en')} of {pages.toLocaleString('en')}</span></p>
    <div>
      <button type="button" aria-label={`Previous ${subject} page`} aria-controls={`${subject}-ledger`}
        disabled={disabled || page <= 1} onClick={() => onPage(page - 1)}>Previous</button>
      <button type="button" aria-label={`Next ${subject} page`} aria-controls={`${subject}-ledger`}
        disabled={disabled || page >= pages} onClick={() => onPage(page + 1)}>Next</button>
    </div>
  </nav>;
}

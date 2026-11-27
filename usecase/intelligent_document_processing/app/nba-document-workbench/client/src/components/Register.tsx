import { Search } from 'lucide-react';
import { useMemo, useState } from 'react';
import { DOC_TYPES } from '../../../shared/contracts';
import { useDecisionsContext } from '../lib/data';
import { money, received } from '../lib/format';
import type { RegisterRow } from '../lib/types';
import { Empty, ErrorNotice, PanelHead, SkeletonRows, StatusText } from './primitives';

const PAGE = 30;

export function Register({
  rows,
  loading,
  error,
  onRetry,
  onOpen,
}: {
  rows: RegisterRow[] | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  onOpen: (id: string) => void;
}) {
  const decisions = useDecisionsContext();
  const [type, setType] = useState('all');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const shown = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (rows ?? []).filter(
      (r) =>
        (type === 'all' || r.doc_type === type) &&
        (!q ||
          [r.doc_id, r.supplier_name, r.invoice_number, r.sender, r.subject].some((v) =>
            (v ?? '').toLowerCase().includes(q)
          ))
    );
  }, [rows, type, search]);
  const pages = Math.max(1, Math.ceil(shown.length / PAGE));
  const current = Math.min(page, pages - 1);

  const outcome = (r: RegisterRow) => {
    const d = decisions.byDoc.get(r.doc_id);
    if (d) return `${d.decision} by ${d.decided_by.split('@')[0]}`;
    if (r.decision) return `${r.decision} (simulated)`;
    return r.queue_state === 'open'
      ? 'Open'
      : r.doc_type && !['tax_invoice', 'adjustment_note'].includes(r.doc_type)
        ? r.in_live_window
          ? 'In intake'
          : 'Filed (simulated)'
        : '-';
  };

  return (
    <div className="content">
      <div className="page-head">
        <div>
          <h1>Document register</h1>
          <p className="page-intro">
            Every document that has landed in the inbox volume, its classified type, machine status and outcome.
            Governed in Unity Catalog; rows you cannot see are not shown.
          </p>
        </div>
      </div>
      {error && <ErrorNotice message={error} onRetry={onRetry} />}
      <section className="card" aria-labelledby="register-title">
        <PanelHead
          id="register-title"
          title={`${shown.length.toLocaleString('en-AU')} documents`}
          copy="Newest first."
        />
        <div className="filter-row" role="group" aria-label="Filter by document type">
          {[['all', 'All types'], ...Object.entries(DOC_TYPES)].map(([k, v]) => (
            <button
              key={k}
              className="filter"
              aria-pressed={type === k}
              onClick={() => {
                setType(k);
                setPage(0);
              }}
            >
              {v}
            </button>
          ))}
          <label className="search">
            <span className="sr-only">Search the register</span>
            <Search aria-hidden="true" />
            <input
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(0);
              }}
              placeholder="Document, supplier or invoice"
            />
          </label>
        </div>
        {loading ? (
          <SkeletonRows rows={10} height={30} />
        ) : !shown.length ? (
          <Empty title="No documents match">Clear the search or choose another type.</Empty>
        ) : (
          <div className="table-wrap">
            <table className="data numeric">
              <thead>
                <tr>
                  <th scope="col">Document</th>
                  <th scope="col">Received</th>
                  <th scope="col">Type</th>
                  <th scope="col">From</th>
                  <th scope="col" className="num">
                    Amount
                  </th>
                  <th scope="col">Status</th>
                  <th scope="col">Outcome</th>
                </tr>
              </thead>
              <tbody>
                {shown.slice(current * PAGE, current * PAGE + PAGE).map((r) => (
                  <tr key={r.doc_id} className="clickable" onClick={() => onOpen(r.doc_id)}>
                    <td>
                      <button
                        className="link-button mono"
                        onClick={(e) => {
                          e.stopPropagation();
                          onOpen(r.doc_id);
                        }}
                      >
                        {r.doc_id}
                      </button>
                      <div className="doc-meta">{r.attachment_name}</div>
                    </td>
                    <td style={{ whiteSpace: 'nowrap' }}>{received(r.arrival_ts)}</td>
                    <td>{r.doc_type_label ?? 'Processing'}</td>
                    <td>
                      {r.supplier_name ?? r.sender}
                      {r.invoice_number && <div className="doc-meta">{r.invoice_number}</div>}
                    </td>
                    <td className="num mono">{r.total_inc_gst != null ? money(r.total_inc_gst) : ''}</td>
                    <td>
                      <StatusText status={r.status} label={r.status_label} />
                    </td>
                    <td style={{ textTransform: 'capitalize' }}>{outcome(r)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {!loading && shown.length > PAGE && (
          <div className="pager">
            <span>
              {current * PAGE + 1}-{Math.min(shown.length, current * PAGE + PAGE)} of {shown.length}
            </span>
            <span style={{ display: 'flex', gap: 8 }}>
              <button className="button small" disabled={current === 0} onClick={() => setPage(current - 1)}>
                Previous
              </button>
              <button className="button small" disabled={current >= pages - 1} onClick={() => setPage(current + 1)}>
                Next
              </button>
            </span>
          </div>
        )}
      </section>
    </div>
  );
}

import { sql } from '@databricks/appkit-ui/js';
import { ShieldAlert } from 'lucide-react';
import { useMemo, useState } from 'react';
import { DOC_TYPES } from '../../../shared/contracts';
import { list, postJson, useBaseParams, useDecisionsContext, useRows, useSessionInfo } from '../lib/data';
import { money, received, weekday } from '../lib/format';
import type { DocumentRow, IntakeRow } from '../lib/types';
import { DocumentViewer } from './DocumentViewer';
import { Empty, ErrorNotice, PanelHead, SkeletonRows } from './primitives';

function needsAttention(r: IntakeRow) {
  return (
    r.intent === 'bank_details_change' ||
    r.intent === 'delivery_dispute' ||
    r.intent === 'payment_query' ||
    list(r.unmatched_invoices).length > 0
  );
}

function tagsFor(r: IntakeRow) {
  const tags: { text: string; kind: string }[] = [
    { text: DOC_TYPES[r.doc_type as keyof typeof DOC_TYPES] ?? r.doc_type, kind: 'neutral' },
  ];
  if (r.intent_label) tags.push({ text: r.intent_label, kind: r.intent === 'bank_details_change' ? 'fail' : 'held' });
  const unmatched = list(r.unmatched_invoices).length;
  if (unmatched) tags.push({ text: `${unmatched} not in our inbox`, kind: 'held' });
  if (list(r.linked_doc_ids).length) tags.push({ text: `${list(r.linked_doc_ids).length} linked`, kind: 'neutral' });
  return tags;
}

export function Intake({
  rows,
  loading,
  error,
  onRetry,
  onOpen,
  onDecided,
}: {
  rows: IntakeRow[] | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  onOpen: (id: string) => void;
  onDecided: (m: string) => void;
}) {
  const decisions = useDecisionsContext();
  const session = useSessionInfo();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const open = useMemo(
    () => (rows ?? []).filter((r) => r.in_live_window && !decisions.byDoc.has(r.doc_id)),
    [rows, decisions.byDoc]
  );
  const attention = open.filter(needsAttention);
  const rest = open.filter((r) => !needsAttention(r));
  const selected = open.find((r) => r.doc_id === selectedId) ?? attention[0] ?? rest[0] ?? null;

  const base = useBaseParams();
  const params = useMemo(
    () => ({ ...base, doc_id: sql.string(selected?.doc_id ?? 'DOC-000000') }),
    [base, selected?.doc_id]
  );
  const doc = useRows<DocumentRow>('document', params, { autoStart: Boolean(selected) });
  const d = doc.data?.[0];

  async function actioned() {
    if (!selected) return;
    setBusy(true);
    setProblem(null);
    try {
      await postJson(`/api/documents/${selected.doc_id}/decision`, {
        decision: 'actioned',
        note: selected.next_action ?? '',
      });
      decisions.reload();
      onDecided(`${selected.subject} marked as actioned.`);
      setSelectedId(null);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'Could not record it');
    } finally {
      setBusy(false);
    }
  }

  const row = (r: IntakeRow) => (
    <button
      key={r.doc_id}
      className="intake-row"
      aria-pressed={selected?.doc_id === r.doc_id}
      onClick={() => setSelectedId(r.doc_id)}
    >
      <span style={{ minWidth: 0 }}>
        <span className="doc-title">{r.supplier_name ?? r.subject}</span>
        <span className="doc-meta">{r.summary ?? r.subject}</span>
      </span>
      <span className="doc-meta" style={{ marginTop: 0 }}>
        {received(r.arrival_ts)}
      </span>
      <span className="tags">
        {tagsFor(r).map((t) => (
          <span key={t.text} className={`tag ${t.kind}`}>
            {t.text}
          </span>
        ))}
      </span>
    </button>
  );

  return (
    <div className="content">
      <div className="page-head">
        <div>
          <h1>Intake</h1>
          <p className="page-intro">
            Everything in the inbox that is not an invoice: statements to reconcile, supplier letters and quotes that
            were sent to the wrong place. Classified by ai_classify; what they ask for comes from ai_extract.
          </p>
        </div>
      </div>
      {error && <ErrorNotice message={error} onRetry={onRetry} />}
      <div className="intake-grid">
        <section className="card" aria-labelledby="intake-title">
          <PanelHead
            id="intake-title"
            title="Open correspondence"
            copy={`${open.length} items received in the last two weeks`}
          />
          {loading ? (
            <SkeletonRows rows={6} />
          ) : !open.length ? (
            <Empty title="Nothing to action">Statements, letters and quotes appear here as they arrive.</Empty>
          ) : (
            <>
              {attention.length > 0 && <div className="section-title">Needs attention · {attention.length}</div>}
              {attention.map(row)}
              {rest.length > 0 && <div className="section-title">To file · {rest.length}</div>}
              {rest.map(row)}
            </>
          )}
        </section>

        {selected && (
          <div className="stack">
            <section className="card" aria-labelledby="intake-detail">
              <PanelHead
                id="intake-detail"
                title={selected.supplier_name ?? selected.subject}
                copy={`${selected.supplier_name ? selected.subject : selected.sender} · ${weekday(selected.arrival_ts)}`}
              />
              {selected.risk_flag && (
                <div className="risk" role="note">
                  <ShieldAlert aria-hidden="true" />
                  <span>
                    <strong>Possible payment redirection.</strong> {selected.risk_flag}
                    {selected.bank_details_differ ? ' The details in this letter differ from the vendor master.' : ''}
                  </span>
                </div>
              )}
              <dl className="facts" style={{ margin: 0 }}>
                <div className="fact wide prose">
                  <dt>What they are asking</dt>
                  <dd>{selected.summary ?? '-'}</dd>
                </div>
                <div className="fact wide prose">
                  <dt>Next action</dt>
                  <dd>{selected.next_action ?? '-'}</dd>
                </div>
                {selected.balance_due != null && (
                  <>
                    <div className="fact">
                      <dt>Balance on statement</dt>
                      <dd className="mono">{money(selected.balance_due)}</dd>
                    </div>
                    <div className="fact">
                      <dt>Shown as overdue</dt>
                      <dd className="mono">{money(selected.overdue_amount)}</dd>
                    </div>
                  </>
                )}
                {list(selected.referenced_invoices).length > 0 && (
                  <div className="fact wide">
                    <dt>Invoices referred to</dt>
                    <dd>
                      {list(selected.referenced_invoices).map((n) => {
                        const linkedIdx = list(selected.unmatched_invoices).includes(n);
                        return (
                          <span key={n} className={`tag ${linkedIdx ? 'held' : 'neutral'}`} style={{ marginRight: 6 }}>
                            {n}
                            {linkedIdx ? ' · not received' : ''}
                          </span>
                        );
                      })}
                      {list(selected.linked_doc_ids).length > 0 && (
                        <small style={{ marginTop: 6 }}>
                          Open:{' '}
                          {list(selected.linked_doc_ids).map((id) => (
                            <button
                              key={id}
                              className="link-button"
                              style={{ marginRight: 10 }}
                              onClick={() => onOpen(id)}
                            >
                              {id}
                            </button>
                          ))}
                        </small>
                      )}
                    </dd>
                  </div>
                )}
              </dl>
              <div className="review-actions">
                <span className="hint" role={problem ? 'alert' : undefined}>
                  {problem ? (
                    <span className="form-error">{problem}</span>
                  ) : (
                    'Mark it actioned once the next action is done.'
                  )}
                </span>
                <button className="button" onClick={() => onOpen(selected.doc_id)}>
                  Open document
                </button>
                <button
                  className="button primary"
                  onClick={() => void actioned()}
                  disabled={busy || !session.decisionsEnabled}
                >
                  {busy ? 'Recording' : 'Mark actioned'}
                </button>
              </div>
            </section>
            {d && (
              <DocumentViewer
                docId={selected.doc_id}
                pageCount={d.page_count ?? 1}
                enabled={session.pagesEnabled}
                selected={null}
                others={[]}
                caption="As received."
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

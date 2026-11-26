import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { CircleCheck, Flag, X } from 'lucide-react';
import { NOTES_MAX, NOTES_MIN, REASONS, reasonLabel, type Outcome } from '../../../shared/contracts';
import { useCaseHistory, type CaseStates } from '../lib/caseState';
import { sql, useBaseParams, useRows, useScope } from '../lib/data';
import { dateTime, days, money, pct, personName, plural, shortDate } from '../lib/format';
import type { GraphEdge, GraphNode } from '../lib/graphLayout';
import type { QueueCase } from '../lib/queue';
import { EntityGraph } from './EntityGraph';
import { ErrorNotice, RiskBadge, Skeleton, StatusLabel, useToast } from './primitives';

interface FactorRow {
  rank: number;
  factor_code: string;
  title: string;
  detail: string;
  contribution: number;
  source: string;
}
interface PaymentRow {
  payment_id: string;
  payment_date: string;
  amount: number;
  invoice_ref: string;
  approver: string;
  flagged: boolean;
}

const CLOSE_MS = 200;

export function CaseDrawer({
  caseId,
  item,
  loadingQueue,
  caseStates,
  onClose,
}: {
  caseId: string;
  item: QueueCase | null;
  loadingQueue: boolean;
  caseStates: CaseStates;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const opener = useRef<Element | null>(null);
  const [closing, setClosing] = useState(false);
  const titleId = useId();

  useEffect(() => {
    const el = ref.current;
    opener.current = document.activeElement;
    if (el && !el.open) el.showModal();
    return () => {
      // Return focus to the row that opened the case (or its replacement after a re-render).
      const row = document.querySelector<HTMLElement>(`[data-case="${caseId}"]`);
      (row ?? (opener.current as HTMLElement | null))?.focus?.();
    };
  }, [caseId]);

  const requestClose = useCallback(() => {
    if (closing) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return onClose();
    setClosing(true);
    window.setTimeout(onClose, CLOSE_MS);
  }, [closing, onClose]);

  return (
    <dialog
      ref={ref}
      className={`drawer${closing ? ' closing' : ''}`}
      aria-labelledby={titleId}
      onCancel={(e) => {
        e.preventDefault();
        requestClose();
      }}
      onClick={(e) => {
        if (e.target === ref.current) requestClose();
      }}
    >
      <div className="drawer-head">
        <div className="drawer-title">
          <h2 id={titleId}>{item?.entity_label ?? (loadingQueue ? 'Loading case…' : 'Case not found')}</h2>
          <div className="drawer-meta">
            <span className="case-id">{caseId}</span>
            {item && (
              <>
                <span className="meta-seg">{item.program_label}</span>
                <span className="meta-seg">{item.entity_sub}</span>
              </>
            )}
          </div>
        </div>
        <button type="button" className="icon-button" aria-label="Close case review" onClick={requestClose} autoFocus>
          <X className="icon" aria-hidden="true" />
        </button>
      </div>
      {item ? (
        <CaseBody item={item} caseStates={caseStates} onDone={requestClose} />
      ) : loadingQueue ? (
        <div className="drawer-body">
          <Skeleton height={72} />
          <Skeleton height={160} />
        </div>
      ) : (
        <div className="drawer-body">
          <div className="empty">
            <strong>{caseId} is not in the governed queue</strong>
            <p>It may have been rescored below the case threshold, or you may not have access to it in Unity Catalog.</p>
          </div>
        </div>
      )}
    </dialog>
  );
}

function CaseBody({ item, caseStates, onDone }: { item: QueueCase; caseStates: CaseStates; onDone: () => void }) {
  const base = useBaseParams();
  const { user } = useScope();
  const params = useMemo(() => ({ ...base, case_id: sql.string(item.case_id) }), [base, item.case_id]);
  const factors = useRows('case_factors', params);
  const nodes = useRows('case_graph_nodes', params);
  const edges = useRows('case_graph_edges', params);
  const payments = useRows('case_payments', params);
  const history = useCaseHistory(item.case_id, `${item.status}|${item.updated_at ?? ''}`, caseStates.enabled);
  const factorRows = (factors.data ?? []) as FactorRow[];
  // Rule factors and model (SHAP) factors are in different units, so they are never drawn on one
  // scale: a model factor shows its share of the model's own contribution; a rule is a rule.
  const modelTotal = factorRows.filter((f) => f.source !== 'rule').reduce((n, f) => n + Math.abs(f.contribution), 0);
  const paymentRows = (payments.data ?? []) as PaymentRow[];

  return (
    <div className="drawer-body">
      <div className="case-summary">
        <div className="mini">
          <span>Risk score</span>
          <strong>{item.risk_score} / 100</strong>
        </div>
        <div className="mini">
          <span>Payment value</span>
          <strong>{money(item.payment_value)}</strong>
        </div>
        <div className="mini">
          <span>Queue age</span>
          <strong>{days(item.age_days)}</strong>
        </div>
      </div>

      <Holder item={item} caseStates={caseStates} user={user} />

      <section className="evidence" aria-labelledby="factors-h">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <h3 id="factors-h">Why this case was prioritised</h3>
          <RiskBadge score={item.risk_score} band={item.risk_band} />
        </div>
        {factors.loading && !factors.data ? (
          <div className="stack" style={{ marginTop: 16 }}>
            <Skeleton width="70%" />
            <Skeleton width="90%" />
            <Skeleton width="60%" />
          </div>
        ) : factors.error ? (
          <div style={{ marginTop: 16 }}>
            <ErrorNotice title="Contributing factors could not be loaded" message={factors.error} />
          </div>
        ) : (
          <ol className="evidence-list">
            {factorRows.map((f) => (
              <li className="evidence-item" key={f.rank}>
                <span className="evidence-index" aria-hidden="true">
                  {String(f.rank).padStart(2, '0')}
                </span>
                <div>
                  <strong>{f.title}</strong>
                  <p>{f.detail}</p>
                  {f.source === 'rule' ? (
                    <div className="weight">
                      <span className="weight-tag">Rule signal</span>
                      <span>A defined pattern matched in the source records</span>
                    </div>
                  ) : (
                    <div className="weight">
                      <span className="weight-track" aria-hidden="true">
                        <span className="weight-fill" style={{ display: 'block', width: `${modelTotal > 0 ? (Math.abs(f.contribution) / modelTotal) * 100 : 0}%` }} />
                      </span>
                      <span>
                        Model pattern · {modelTotal > 0 ? pct(Math.abs(f.contribution) / modelTotal) : '–'} of the model’s contribution here
                      </span>
                    </div>
                  )}
                </div>
              </li>
            ))}
            {factorRows.length === 0 && <li className="muted">No contributing factors were retained for this score.</li>}
          </ol>
        )}
      </section>

      <section className="evidence" aria-labelledby="graph-h">
        <h3 id="graph-h">Linked entity view</h3>
        <p className="muted">The resolved records and shared attributes that contributed to this score.</p>
        {(nodes.loading && !nodes.data) || (edges.loading && !edges.data) ? (
          <Skeleton height={220} style={{ marginTop: 16, borderRadius: 16 }} />
        ) : nodes.error || edges.error ? (
          <div style={{ marginTop: 16 }}>
            <ErrorNotice title="The linked entity view could not be loaded" message={nodes.error ?? edges.error} />
          </div>
        ) : (
          <EntityGraph nodes={(nodes.data ?? []) as GraphNode[]} edges={(edges.data ?? []) as GraphEdge[]} />
        )}
      </section>

      <section className="evidence" aria-labelledby="payments-h">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <h3 id="payments-h">Payments in this case</h3>
          <span className="muted xs">{plural(item.payment_count, 'flagged payment')}</span>
        </div>
        {payments.loading && !payments.data ? (
          <Skeleton height={120} style={{ marginTop: 16 }} />
        ) : payments.error ? (
          <div style={{ marginTop: 16 }}>
            <ErrorNotice title="Payments could not be loaded" message={payments.error} />
          </div>
        ) : (
          <div className="table-wrap" style={{ marginTop: 12 }}>
            <table className="payments-table">
              <thead>
                <tr>
                  <th scope="col">Date</th>
                  <th scope="col">Invoice</th>
                  <th scope="col">Approved by</th>
                  <th scope="col" className="num-col">
                    Amount
                  </th>
                </tr>
              </thead>
              <tbody>
                {paymentRows.slice(0, 8).map((p) => (
                  <tr key={p.payment_id}>
                    <td className="mono">{shortDate(p.payment_date)}</td>
                    <td className="mono">
                      {p.flagged && <span className="flag-dot" aria-hidden="true" />}
                      {p.invoice_ref}
                      {p.flagged && <span className="sr-only"> (flagged)</span>}
                    </td>
                    <td>{p.approver}</td>
                    <td className="money">{money(p.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {paymentRows.length > 8 && <p className="muted xs" style={{ padding: '8px 12px 0' }}>{plural(paymentRows.length - 8, 'earlier payment')} not shown.</p>}
            {paymentRows.some((p) => p.flagged) && (
              <p className="muted xs" style={{ padding: '8px 12px 0' }}>
                <span className="flag-dot" aria-hidden="true" />
                Flagged by the scoring model
              </p>
            )}
          </div>
        )}
      </section>

      <div className="assurance">
        <strong>Decision support only.</strong> The risk score does not establish wrongdoing. Verify source records, follow procedural fairness
        requirements, and record the basis for any escalation.
      </div>

      {item.status === 'closed' ? (
        <Decision history={history.data} />
      ) : (
        <OutcomeForm item={item} caseStates={caseStates} user={user} onDone={onDone} />
      )}

      {caseStates.enabled && history.data && history.data.events.length > 0 && (
        <section className="evidence" aria-labelledby="record-h">
          <h3 id="record-h">Case record</h3>
          <ul className="history">
            {history.data.events.map((e) => (
              <li key={e.event_id}>
                <time dateTime={e.created_at}>{dateTime(e.created_at)}</time>
                <span>
                  {e.event_type === 'assigned' && `Assigned to ${personName(e.actor)}`}
                  {e.event_type === 'released' && `Returned to the queue by ${personName(e.actor)}`}
                  {e.event_type === 'outcome' && `${(e.detail ?? '').startsWith('escalated') ? 'Escalated for assessment' : 'Indicator cleared'} by ${personName(e.actor)}`}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function Holder({ item, caseStates, user }: { item: QueueCase; caseStates: CaseStates; user: string | null }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  if (!caseStates.enabled || item.status === 'closed') return null;
  const mine = item.status === 'review' && item.assignee === user;
  const run = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true);
    try {
      await fn();
      toast(done);
    } catch (e) {
      toast(e instanceof Error ? e.message : 'That did not work. Try again.', 'error');
      caseStates.refresh();
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="holder">
      <StatusLabel status={item.status} assignee={item.assignee} user={user} />
      {item.status === 'unassigned' && (
        <button type="button" className="button small" disabled={busy} onClick={() => void run(() => caseStates.assign(item.case_id), `${item.case_id} is now in review with you.`)}>
          {busy ? 'Assigning…' : 'Assign to me'}
        </button>
      )}
      {mine && (
        <button type="button" className="button small ghost" disabled={busy} onClick={() => void run(() => caseStates.release(item.case_id), `${item.case_id} is back in the queue.`)}>
          Return to queue
        </button>
      )}
    </div>
  );
}

function OutcomeForm({ item, caseStates, user, onDone }: { item: QueueCase; caseStates: CaseStates; user: string | null; onDone: () => void }) {
  const toast = useToast();
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [reason, setReason] = useState('');
  const [notes, setNotes] = useState('');
  const [errors, setErrors] = useState<{ outcome?: string; reason?: string; notes?: string; form?: string }>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<Outcome | null>(null);
  const notesRef = useRef<HTMLTextAreaElement>(null);
  const reasonRef = useRef<HTMLSelectElement>(null);
  const heldByOther = item.status === 'review' && item.assignee !== user;
  const disabled = !caseStates.enabled || heldByOther || saving || saved != null;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const next: typeof errors = {};
    if (!outcome) next.outcome = 'Choose whether to clear the indicator or escalate the case.';
    if (outcome && !reason) next.reason = 'Choose the reason for this outcome.';
    if (notes.trim().length < NOTES_MIN) next.notes = 'Summarise the checks completed and evidence considered.';
    setErrors(next);
    if (next.notes) notesRef.current?.focus();
    else if (next.reason) reasonRef.current?.focus();
    if (Object.keys(next).length || !outcome) return;
    setSaving(true);
    try {
      await caseStates.recordOutcome(item.case_id, { outcome, reasonCode: reason, notes: notes.trim() });
      setSaved(outcome);
      toast(outcome === 'escalated' ? `${item.case_id} escalated for assessment.` : `Indicator cleared on ${item.case_id}.`);
      window.setTimeout(onDone, 600);
    } catch (error) {
      setErrors({ form: error instanceof Error ? error.message : 'The outcome could not be recorded. Try again.' });
      caseStates.refresh();
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="outcome" onSubmit={(e) => void submit(e)} noValidate aria-labelledby="outcome-h">
      <h3 id="outcome-h">Record investigation outcome</h3>
      {!caseStates.enabled && (
        <div className="notice">Outcome capture is not connected in this environment. The case can be reviewed but not decided.</div>
      )}
      {heldByOther && <div className="notice">This case is in review with {personName(item.assignee)}. Only they can record its outcome.</div>}
      <fieldset style={{ border: 0, margin: 0, padding: 0 }} disabled={disabled}>
        <legend className="sr-only">Outcome</legend>
        <div className="choice-row">
          {(
            [
              ['cleared', 'Clear indicator'],
              ['escalated', 'Escalate for assessment'],
            ] as const
          ).map(([value, label]) => (
            <label className="choice" key={value}>
              <input
                type="radio"
                name="outcome"
                value={value}
                checked={outcome === value}
                onChange={() => {
                  setOutcome(value);
                  setReason('');
                  setErrors((er) => ({ ...er, outcome: undefined }));
                }}
              />
              {label}
            </label>
          ))}
        </div>
        {errors.outcome && <p className="field-error" style={{ marginTop: 6 }}>{errors.outcome}</p>}
      </fieldset>
      <div className="field">
        <label htmlFor="reason">Reason</label>
        <select
          id="reason"
          ref={reasonRef}
          className="control"
          value={reason}
          disabled={disabled || !outcome}
          aria-invalid={errors.reason ? true : undefined}
          aria-describedby={errors.reason ? 'reason-error' : undefined}
          onChange={(e) => {
            setReason(e.target.value);
            setErrors((er) => ({ ...er, reason: undefined }));
          }}
        >
          <option value="">{outcome ? 'Choose a reason' : 'Choose an outcome first'}</option>
          {outcome && REASONS[outcome].map((r) => <option key={r.code} value={r.code}>{r.label}</option>)}
        </select>
        {errors.reason && <p className="field-error" id="reason-error">{errors.reason}</p>}
      </div>
      <div className="field">
        <label htmlFor="caseNotes">Investigator notes</label>
        <textarea
          id="caseNotes"
          ref={notesRef}
          className="control"
          rows={4}
          maxLength={NOTES_MAX}
          placeholder="Summarise checks completed and evidence considered"
          value={notes}
          disabled={disabled}
          aria-invalid={errors.notes ? true : undefined}
          aria-describedby="notes-hint"
          onChange={(e) => {
            setNotes(e.target.value);
            if (errors.notes && e.target.value.trim().length >= NOTES_MIN) setErrors((er) => ({ ...er, notes: undefined }));
          }}
        />
        <div className="field-hint" id="notes-hint">
          <span className={errors.notes ? 'field-error' : undefined}>{errors.notes ?? 'Required. Recorded against your name with the score shown here.'}</span>
          <span className="mono">
            {notes.length}/{NOTES_MAX}
          </span>
        </div>
      </div>
      {errors.form && (
        <div className="notice error" role="alert">
          {errors.form}
        </div>
      )}
      <div className="outcome-actions">
        <button type="submit" className="button primary" disabled={disabled}>
          {saved === 'escalated' ? 'Escalation recorded' : saved === 'cleared' ? 'Indicator cleared' : saving ? 'Recording…' : outcome === 'cleared' ? 'Clear indicator' : outcome === 'escalated' ? 'Escalate for assessment' : 'Record outcome'}
        </button>
      </div>
    </form>
  );
}

function Decision({ history }: { history: ReturnType<typeof useCaseHistory>['data'] }) {
  const o = history?.outcome;
  if (!o) return <Skeleton height={96} />;
  const escalated = o.outcome === 'escalated';
  return (
    <section className={`decision ${o.outcome}`} aria-label="Recorded outcome">
      <div className="decision-head">
        {escalated ? <Flag className="icon" aria-hidden="true" /> : <CircleCheck className="icon" aria-hidden="true" />}
        {escalated ? 'Escalated for assessment' : 'Indicator cleared'}
      </div>
      <div className="muted xs">
        {reasonLabel(o.reason_code)} · {personName(o.decided_by)} · {dateTime(o.decided_at)}
      </div>
      <blockquote>{o.notes}</blockquote>
    </section>
  );
}

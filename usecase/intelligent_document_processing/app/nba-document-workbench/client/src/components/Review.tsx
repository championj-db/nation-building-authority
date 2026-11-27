import { sql } from '@databricks/appkit-ui/js';
import {
  ArrowLeft,
  CheckCircle2,
  CircleAlert,
  CircleCheck,
  CircleDashed,
  CircleHelp,
  ChevronRight,
  CircleX,
  Clock3,
  Pencil,
  Truck,
} from 'lucide-react';
import { useContext, useEffect, useMemo, useRef, useState } from 'react';
import {
  CHECK_LABELS,
  decisionProblem,
  DOC_TYPES,
  OVERRIDE_NOTE_MIN,
  returnNotice,
  SUPPLIER_FAULT_CHECKS,
  type CorrectionRecord,
  type DecisionInput,
  type DecisionRecord,
  type GovernedSnapshot,
} from '../../../shared/contracts';
import {
  DataVersionContext,
  fetchDocumentDecision,
  list,
  postJson,
  useBaseParams,
  useDecisionsContext,
  useRows,
  useSessionInfo,
} from '../lib/data';
import { day, money, pct, received, weekday } from '../lib/format';
import { clockText } from '../lib/queue';
import type { CheckRow, DocumentRow, FieldRow, InvoiceRow, Region } from '../lib/types';
import { recheck } from '../../../shared/recheck';
import { DocumentViewer } from './DocumentViewer';
import { ErrorNotice, PanelHead, Skeleton, SkeletonRows, StatusText } from './primitives';

const regionsOf = (f: FieldRow | undefined): Region[] => {
  const raw: unknown = f?.regions_json;
  if (!raw) return [];
  // The JSON transport may already have parsed the column.
  if (Array.isArray(raw)) return raw as Region[];
  try {
    return typeof raw === 'string' ? (JSON.parse(raw) as Region[]) : [];
  } catch {
    return [];
  }
};

function display(f: FieldRow, value: string | null): string | null {
  if (value == null || value === '') return null;
  if (f.field_type === 'number') return money(value);
  if (f.field === 'invoice_date') return day(value, true);
  if (f.field.endsWith('_abn') && value.length === 11)
    return `${value.slice(0, 2)} ${value.slice(2, 5)} ${value.slice(5, 8)} ${value.slice(8)}`;
  return value;
}

export function Review({
  docId,
  onBack,
  onOpen,
  onDecided,
}: {
  docId: string;
  onBack: () => void;
  onOpen: (id: string) => void;
  onDecided: (message: string) => void;
}) {
  const base = useBaseParams();
  const session = useSessionInfo();
  const decisions = useDecisionsContext();
  const params = useMemo(() => ({ ...base, doc_id: sql.string(docId) }), [base, docId]);
  const doc = useRows<DocumentRow>('document', params);
  const inv = useRows<InvoiceRow>('invoice', params);
  const fieldsQ = useRows<FieldRow>('fields', params);
  const checksQ = useRows<CheckRow>('checks', params);

  const d = doc.data?.[0];
  const invoice = inv.data?.[0];
  const fields = useMemo(() => fieldsQ.data ?? [], [fieldsQ.data]);
  const checks = checksQ.data ?? [];
  const isInvoice = d?.doc_type === 'tax_invoice' || d?.doc_type === 'adjustment_note';

  const [selected, setSelected] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState<Set<string>>(new Set());
  const [corrections, setCorrections] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [mode, setMode] = useState<'idle' | 'accept' | 'return' | 'reclassify'>('idle');
  const [reasons, setReasons] = useState<string[]>([]);
  const [note, setNote] = useState('');
  const [reclassifyTo, setReclassifyTo] = useState<string>('');
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [recorded, setRecorded] = useState<{ decision: DecisionRecord | null; corrections: CorrectionRecord[] } | null>(
    null
  );
  const opened = useRef(Date.now());
  const panelRef = useRef<HTMLElement>(null);
  const { bump: retry } = useContext(DataVersionContext);

  useEffect(() => {
    opened.current = Date.now();
    setSelected(null);
    setConfirmed(new Set());
    setCorrections({});
    setEditing(null);
    setMode('idle');
    setReasons([]);
    setNote('');
    setProblem(null);
    setRecorded(null);
    fetchDocumentDecision(docId)
      .then(setRecorded)
      .catch(() => setRecorded({ decision: null, corrections: [] }));
  }, [docId]);

  const held = useMemo(() => fields.filter((f) => f.below_threshold), [fields]);
  // Re-run the field-local checks against the officer's corrections.
  const effective = useMemo(
    () =>
      recheck(list(invoice?.failed_checks), Object.fromEntries(fields.map((f) => [f.field, f.value])), corrections, {
        docType: d?.doc_type ?? 'tax_invoice',
        vendorAbn: invoice?.vendor_abn ?? null,
        gstRegistered: invoice?.vendor_gst_registered !== false,
      }),
    [invoice, fields, corrections, d?.doc_type]
  );
  const shownChecks = checks.map((c) =>
    c.check_code in effective.rechecked
      ? ({
          ...c,
          result: effective.rechecked[c.check_code] ? 'pass' : 'fail',
          detail: `Rechecked with your correction: ${effective.rechecked[c.check_code] ? 'now passes.' : 'still fails.'}`,
        } as CheckRow)
      : c
  );
  const failed = shownChecks.filter((c) => c.result === 'fail');
  const supplierFails = failed.filter((c) => c.supplier_fault);
  const unknownChecks = shownChecks.filter((c) => c.result === 'unknown' && c.supplier_fault);
  // Pre-select the failed criteria when the officer opens the return form.
  useEffect(() => {
    if (mode === 'return' && !reasons.length) setReasons(supplierFails.map((c) => c.check_code));
    // An open form leaves the sticky bar and is brought into view where it sits.
    if (mode !== 'idle')
      requestAnimationFrame(() => panelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }));
  }, [mode]); // eslint-disable-line react-hooks/exhaustive-deps

  const decided = recorded?.decision ?? decisions.byDoc.get(docId) ?? null;
  const historical =
    invoice?.queue_state === 'decided' && invoice.decision_source === 'simulated_history' ? invoice : null;

  const snap: GovernedSnapshot | null = d
    ? {
        docId,
        docType: d.doc_type ?? '',
        status: d.status,
        lowestConfidence: invoice?.lowest_required_confidence ?? null,
        heldFields: list(invoice?.held_fields),
        failedChecks: effective.failed,
        invalidFields: fields.filter((f) => f.value != null && !f.type_valid).map((f) => f.field),
      }
    : null;
  const input: DecisionInput = {
    decision:
      mode === 'return'
        ? 'returned'
        : mode === 'reclassify'
          ? 'reclassified'
          : mode === 'accept'
            ? 'accepted'
            : 'accepted',
    reasonCodes: mode === 'return' ? reasons : [],
    note: note.trim(),
    corrections: Object.entries(corrections).map(([field, corrected]) => ({
      field,
      corrected,
      extracted: fields.find((f) => f.field === field)?.value ?? null,
    })),
    confirmedFields: [...confirmed],
    reclassifyTo: mode === 'reclassify' && reclassifyTo ? (reclassifyTo as DecisionInput['reclassifyTo']) : undefined,
    handlingSeconds: 0,
  };
  const acceptBlock = snap ? decisionProblem({ ...input, decision: 'accepted' }, snap) : 'Loading';
  const acceptNeedsNoteOnly = acceptBlock?.startsWith('A correctly rendered check failed');
  const formBlock = snap && mode !== 'idle' ? decisionProblem(input, snap) : null;

  async function submit() {
    if (!snap) return;
    const problemNow = decisionProblem(input, snap);
    if (problemNow) return setProblem(problemNow);
    setBusy(true);
    setProblem(null);
    try {
      const body = { ...input, handlingSeconds: Math.round((Date.now() - opened.current) / 1000) };
      await postJson<DecisionRecord>(`/api/documents/${docId}/decision`, body);
      decisions.reload();
      const r = await fetchDocumentDecision(docId).catch(() => null);
      if (r) setRecorded(r);
      setMode('idle');
      onDecided(
        input.decision === 'accepted'
          ? `${invoice?.invoice_number ?? docId} accepted as correctly rendered.`
          : input.decision === 'returned'
            ? `${invoice?.invoice_number ?? docId} recorded as returned to the supplier.`
            : `${docId} reclassified.`
      );
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'Could not record the decision');
    } finally {
      setBusy(false);
    }
  }

  const selectedField = fields.find((f) => f.field === selected);
  const others = useMemo(() => fields.filter((f) => f.field !== selected).flatMap(regionsOf), [fields, selected]);
  const loading = doc.loading || (isInvoice && (fieldsQ.loading || inv.loading));
  const error = doc.error || inv.error || fieldsQ.error || checksQ.error;

  if (!doc.loading && !d && !error) {
    return (
      <div className="content">
        <button className="button ghost back" onClick={onBack}>
          <ArrowLeft aria-hidden="true" /> Back to queue
        </button>
        <ErrorNotice message={`${docId} is not in the governed register, or you do not have access to it.`} />
      </div>
    );
  }

  const clock = invoice ? clockText(invoice) : null;
  const remaining =
    invoice?.po_value_inc_gst != null ? invoice.po_value_inc_gst - (invoice.po_billed_before_inc_gst ?? 0) : null;
  const useShare = invoice?.po_value_inc_gst
    ? Math.min(
        1,
        ((invoice.po_billed_before_inc_gst ?? 0) + Math.max(invoice.total_inc_gst ?? 0, 0)) / invoice.po_value_inc_gst
      )
    : null;

  const verdict = (() => {
    if (!invoice) return null;
    const heldN = held.length;
    if (invoice.status === 'ready')
      return {
        icon: <CircleCheck aria-hidden="true" />,
        title: 'Ready to accept',
        text: 'Every correctly rendered check passed and every required field is confident and found on the page.',
      };
    if (invoice.status === 'exception')
      return {
        icon: <CircleX aria-hidden="true" />,
        title: 'Not correctly rendered',
        text: `${supplierFails.map((c) => c.label).join(', ')}. Return it to the supplier; the payment clock has not started.`,
      };
    if (invoice.status === 'awaiting_delivery')
      return {
        icon: <Truck aria-hidden="true" />,
        title: 'Waiting for delivery to be acknowledged',
        text: `No goods or services receipt matches this invoice yet. The clock starts once ${invoice.contract_manager ?? 'the contract manager'} receipts it.`,
      };
    return {
      icon: <CircleAlert aria-hidden="true" />,
      title: heldN
        ? `${heldN} ${heldN === 1 ? 'field' : 'fields'} held for review`
        : `${unknownChecks.map((c) => c.label).join(', ') || 'A check'} could not be checked`,
      text: heldN
        ? 'Check each held field against the page, then confirm or correct it. If the invoice is correctly rendered, its clock has already been running since it arrived.'
        : `${unknownChecks.map((c) => c.detail).join(' ')} Check it yourself before you accept or return the invoice.`,
    };
  })();

  return (
    <div className="content">
      <button className="button ghost back" onClick={onBack}>
        <ArrowLeft aria-hidden="true" /> Back to queue
      </button>
      <div className="review-head">
        <div>
          <h1>{loading ? <Skeleton width={320} height={30} /> : (invoice?.supplier_name ?? d?.subject ?? docId)}</h1>
          <div className="review-meta">
            {d && (
              <span>
                {DOC_TYPES[d.doc_type as keyof typeof DOC_TYPES] ?? 'Document'}
                {invoice?.invoice_number ? ` ${invoice.invoice_number}` : ''}
              </span>
            )}
            {invoice && <span className="mono">{money(invoice.total_inc_gst)}</span>}
            {d && (
              <span>
                Received {received(d.arrival_ts)} by {d.channel === 'peppol' ? 'Peppol' : d.channel}
              </span>
            )}
            {d && <StatusText status={d.status} label={d.status_label} />}
            {clock && invoice?.queue_state === 'open' && !decided && (
              <span className={`clock ${invoice.clock_state}`} title={clock.long}>
                <Clock3 size={14} style={{ verticalAlign: -2, marginRight: 4 }} aria-hidden="true" />
                {clock.long}
              </span>
            )}
          </div>
        </div>
      </div>

      {error && <ErrorNotice message="Part of this document could not be loaded." onRetry={retry} />}

      <div className="workspace">
        {d ? (
          <DocumentViewer
            docId={docId}
            pageCount={d.page_count ?? 1}
            enabled={session.pagesEnabled}
            selected={
              selectedField
                ? {
                    label: selectedField.label,
                    regions: regionsOf(selectedField),
                    citedText: selectedField.cited_text,
                    value: selectedField.value,
                    elsewhere: selectedField.grounded && !selectedField.in_cited_region,
                  }
                : null
            }
            others={others}
            caption={isInvoice ? undefined : 'This document is not an invoice, so no invoice fields were extracted.'}
          />
        ) : (
          <div className="document-view">
            <Skeleton height={520} />
          </div>
        )}

        <div className="stack">
          {verdict && invoice && (
            <section className={`card verdict ${invoice.status}`} aria-live="polite">
              {verdict.icon}
              <div>
                <h2 style={{ fontSize: 'var(--text-lg)' }}>{verdict.title}</h2>
                <p>{verdict.text}</p>
              </div>
            </section>
          )}

          {isInvoice && (
            <section className="card field-list" aria-labelledby="fields-title">
              <PanelHead
                id="fields-title"
                title="Extracted fields"
                copy="Confirm the evidence, not just the value. Select a field to see where it sits on the page."
              >
                <span className="tag neutral">
                  {d?.doc_type === 'adjustment_note' ? 'Adjustment note' : 'Tax invoice'} schema
                </span>
              </PanelHead>
              {fieldsQ.loading ? (
                <SkeletonRows rows={8} height={30} />
              ) : (
                fields
                  .filter((f) => f.value != null || f.required || f.below_threshold)
                  .map((f) => {
                    const isHeld = f.below_threshold;
                    const corrected = corrections[f.field];
                    const isConfirmed = confirmed.has(f.field);
                    const canAct = !decided && !historical && isHeld;
                    return (
                      <div
                        key={f.field}
                        className={`field-row${isHeld ? ' held' : ''}${selected === f.field ? ' selected' : ''}`}
                        role="group"
                        aria-label={f.label}
                      >
                        <button
                          className="field-hit"
                          onClick={(e) => {
                            const row = e.currentTarget.closest('.field-row');
                            setSelected(selected === f.field ? null : f.field);
                            // Keep the whole row, reason and actions included, clear of the decision dock.
                            requestAnimationFrame(() => row?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }));
                          }}
                          aria-pressed={selected === f.field}
                          aria-label={`${f.label}: ${display(f, f.value) ?? 'not found'}. Show on page`}
                        >
                          <span className="field-name">
                            {f.label}
                            {isHeld && !corrected && !isConfirmed && <span className="tag held">Held</span>}
                            {isConfirmed && (
                              <span className="tag confirmed">
                                <CheckCircle2 aria-hidden="true" /> Confirmed
                              </span>
                            )}
                            {corrected != null && (
                              <span className="tag corrected">
                                <Pencil aria-hidden="true" /> Corrected
                              </span>
                            )}
                          </span>
                          <span
                            className={`field-value${f.value == null && corrected == null ? ' empty' : ''}${f.field_type === 'number' ? ' mono' : ''}`}
                          >
                            {corrected != null ? (
                              <>
                                {f.value && <s>{display(f, f.value)}</s>}
                                {display(f, corrected)}
                              </>
                            ) : (
                              (display(f, f.value) ?? 'Not found on the document')
                            )}
                          </span>
                        </button>
                        <span className={`field-score${f.routing_confidence < 0.85 ? ' low' : ''}`}>
                          {pct(f.routing_confidence)}
                          <small>
                            {f.value == null
                              ? 'missing'
                              : !f.grounded
                                ? 'not on page'
                                : f.routing_confidence < 0.85
                                  ? 'low'
                                  : 'confident'}
                          </small>
                        </span>
                        {selected === f.field && f.cited_text && f.grounded && f.in_cited_region !== false && (
                          <div className="printed">
                            <span className="printed-label">Printed on the page</span>
                            <span className="mono">
                              {f.cited_text
                                .replace(/<[^>]+>/g, ' ')
                                .replace(/\s+/g, ' ')
                                .trim()
                                .slice(0, 180)}
                            </span>
                          </div>
                        )}
                        {canAct && editing !== f.field && (
                          <div className="field-actions">
                            {f.value != null && !f.type_valid && (
                              <span className="check-detail field-reason">
                                Not a valid format for {f.label}, so it cannot be confirmed as read. Correct it to what
                                is printed.
                              </span>
                            )}
                            {f.value == null && (
                              <span className="check-detail field-reason">
                                Not found by the extractor. Enter it if it is on the page; if it is not, return the
                                invoice.
                              </span>
                            )}
                            <button
                              className="button small"
                              onClick={() => {
                                setSelected(f.field);
                                setConfirmed((s) => new Set(s).add(f.field));
                                setCorrections((c) => {
                                  const n = { ...c };
                                  delete n[f.field];
                                  return n;
                                });
                              }}
                              disabled={f.value == null || isConfirmed || !f.type_valid}
                            >
                              <CheckCircle2 aria-hidden="true" /> Matches the page
                            </button>
                            <button
                              className="button small"
                              onClick={() => {
                                setSelected(f.field);
                                setEditing(f.field);
                                setDraft(corrected ?? f.value ?? '');
                              }}
                            >
                              <Pencil aria-hidden="true" /> {corrected != null ? 'Edit correction' : 'Correct'}
                            </button>
                          </div>
                        )}
                        {editing === f.field && (
                          <form
                            className="field-actions"
                            onSubmit={(e) => {
                              e.preventDefault();
                              if (!draft.trim()) return;
                              setCorrections((c) => ({ ...c, [f.field]: draft.trim() }));
                              setConfirmed((s) => {
                                const n = new Set(s);
                                n.delete(f.field);
                                return n;
                              });
                              setEditing(null);
                            }}
                          >
                            <label className="sr-only" htmlFor={`fix-${f.field}`}>
                              Corrected {f.label}
                            </label>
                            <input
                              id={`fix-${f.field}`}
                              className="input"
                              autoFocus
                              value={draft}
                              onChange={(e) => setDraft(e.target.value)}
                              placeholder={`${f.label} as printed`}
                            />
                            <button className="button small" type="submit" disabled={!draft.trim()}>
                              Save
                            </button>
                            <button className="button small ghost" type="button" onClick={() => setEditing(null)}>
                              Cancel
                            </button>
                          </form>
                        )}
                      </div>
                    );
                  })
              )}
            </section>
          )}

          {isInvoice && (
            <section className="card" aria-labelledby="checks-title">
              <PanelHead
                id="checks-title"
                title="Correctly rendered checks"
                copy="RMG 417, the Commonwealth Contracting Suite and ATO tax invoice rules."
              />
              {checksQ.loading ? (
                <SkeletonRows rows={4} height={30} />
              ) : (
                <>
                  {shownChecks
                    .filter((c) => c.result !== 'pass')
                    .map((c) => (
                      <CheckLine key={c.check_code} c={c} />
                    ))}
                  {shownChecks.length > 0 && shownChecks.every((c) => c.result === 'pass') && (
                    <CheckLine
                      c={
                        {
                          ...shownChecks[0],
                          result: 'pass',
                          label: 'All eleven criteria passed',
                          detail: 'Expand the list to see each one.',
                          source_url: null,
                        } as CheckRow
                      }
                    />
                  )}
                  <details className="passed-checks">
                    <summary>
                      <ChevronRight aria-hidden="true" className="disclosure" />
                      {shownChecks.filter((c) => c.result === 'pass').length} passed
                    </summary>
                    {shownChecks
                      .filter((c) => c.result === 'pass')
                      .map((c) => (
                        <CheckLine key={c.check_code} c={c} />
                      ))}
                  </details>
                </>
              )}
            </section>
          )}

          {invoice && (
            <section className="card" aria-labelledby="context-title">
              <PanelHead
                id="context-title"
                title="Order, delivery and clock"
                copy="Three-way match: the invoice, the purchase order and the goods receipt."
              />
              <dl className="facts" style={{ margin: 0 }}>
                <div className="fact">
                  <dt>Purchase order</dt>
                  <dd>
                    {invoice.po_number ??
                      (invoice.po_number_quoted ? `${invoice.po_number_quoted} (no match)` : 'None quoted')}
                    {invoice.contract_id && (
                      <small>
                        {invoice.contract_id} · {invoice.contract_category}
                      </small>
                    )}
                  </dd>
                </div>
                <div className="fact">
                  <dt>Remaining on the order before this invoice</dt>
                  <dd className="mono">
                    {remaining == null ? '-' : money(remaining)}
                    {useShare != null && (
                      <span className="meter" aria-hidden="true">
                        <span
                          className={useShare >= 1 && (invoice.total_inc_gst ?? 0) > (remaining ?? 0) ? 'over' : ''}
                          style={{ width: `${Math.round(useShare * 100)}%` }}
                        />
                      </span>
                    )}
                    {invoice.po_value_inc_gst != null && <small>of {money(invoice.po_value_inc_gst)} ordered</small>}
                  </dd>
                </div>
                <div className="fact">
                  <dt>Delivery acknowledged</dt>
                  <dd>
                    {invoice.receipt_date ? weekday(invoice.receipt_date) : 'Not yet'}
                    <small>
                      {invoice.receipt_id
                        ? `${invoice.receipt_id} · ${invoice.contract_manager}`
                        : `Contract manager: ${invoice.contract_manager ?? '-'}`}
                    </small>
                  </dd>
                </div>
                <div className="fact">
                  <dt>Clock started</dt>
                  <dd>
                    {invoice.trigger_date ? `Day after ${weekday(invoice.trigger_date)}` : 'Not started'}
                    <small>
                      {invoice.trigger_date
                        ? 'Both delivery and a correctly rendered invoice in hand'
                        : invoice.status === 'exception'
                          ? 'Not correctly rendered'
                          : 'Waiting on delivery'}
                    </small>
                  </dd>
                </div>
                <div className="fact">
                  <dt>Pay by</dt>
                  <dd>
                    {invoice.pay_by_date ? weekday(invoice.pay_by_date) : '-'}
                    <small>
                      {invoice.term_label
                        ? `${invoice.term_label}, terms in force when the clock started`
                        : 'Set once the clock starts'}
                      {invoice.channel === 'peppol' && !invoice.einvoice && invoice.term_label
                        ? '. Sent through Peppol, but the supplier is not registered for e-invoicing with the Authority, so the 5-day term does not apply.'
                        : ''}
                    </small>
                  </dd>
                </div>
                <div className="fact">
                  <dt>Under the 1 January 2027 terms</dt>
                  <dd>
                    {invoice.pay_by_2027_date ? weekday(invoice.pay_by_2027_date) : '-'}
                    <small>
                      10 business days
                      {invoice.business_days_left_2027 != null && invoice.queue_state === 'open'
                        ? `, ${invoice.business_days_left_2027} left`
                        : ''}
                    </small>
                  </dd>
                </div>
                {invoice.contract_description && (
                  <div className="fact wide">
                    <dt>Contract</dt>
                    <dd>
                      {invoice.contract_description}
                      <small>
                        Description and value from a public AusTender notice; supplier replaced with a synthetic one.
                      </small>
                    </dd>
                  </div>
                )}
                {invoice.duplicate_of && (
                  <div className="fact wide">
                    <dt>Already received</dt>
                    <dd>
                      <button className="link-button" onClick={() => onOpen(invoice.duplicate_of!)}>
                        Open {invoice.duplicate_of}
                      </button>
                      <small>Same supplier and invoice number.</small>
                    </dd>
                  </div>
                )}
              </dl>
            </section>
          )}

          {/* Decision */}
          <section
            ref={panelRef}
            className={`card decision-panel${mode !== 'idle' ? ' expanded' : ''}`}
            aria-labelledby="decision-title"
          >
            <h2 id="decision-title" className="sr-only">
              Decision
            </h2>
            {decided ? (
              <div className="recorded">
                <CheckCircle2 aria-hidden="true" />
                <div>
                  <h3>
                    {decided.decision === 'accepted'
                      ? 'Accepted as correctly rendered'
                      : decided.decision === 'returned'
                        ? 'Returned to the supplier'
                        : decided.decision === 'reclassified'
                          ? `Reclassified as ${DOC_TYPES[decided.reclassify_to as keyof typeof DOC_TYPES] ?? decided.reclassify_to}`
                          : 'Actioned'}
                  </h3>
                  <p>
                    By {decided.decided_by} on {weekday(decided.decided_at)}
                    {decided.reason_codes.length
                      ? ` · ${decided.reason_codes.map((c) => CHECK_LABELS[c] ?? c).join(', ')}`
                      : ''}
                    {recorded?.corrections.length
                      ? ` · ${recorded.corrections.length} field ${recorded.corrections.length === 1 ? 'correction' : 'corrections'}`
                      : ''}
                  </p>
                  {decided.note && <p>&ldquo;{decided.note}&rdquo;</p>}
                </div>
              </div>
            ) : historical ? (
              <div className="recorded">
                <CircleDashed aria-hidden="true" style={{ color: 'var(--fg-muted)' }} />
                <div>
                  <h3>{historical.decision === 'accepted' ? 'Accepted' : 'Returned'} in the simulated history</h3>
                  <p>
                    Recorded {weekday(historical.decided_at)} by {historical.decided_by} (synthetic). This document is
                    outside the live queue window.
                  </p>
                </div>
              </div>
            ) : !session.decisionsEnabled ? (
              <div className="review-actions">
                <span className="hint">
                  Read only: the review store is not connected, so decisions cannot be recorded here.
                </span>
              </div>
            ) : (
              <>
                {mode === 'return' && invoice && (
                  <div className="decision-form">
                    <div>
                      <span className="form-label">Criteria the invoice does not meet</span>
                      <div className="reason-list">
                        {SUPPLIER_FAULT_CHECKS.map((code) => {
                          const failedHere = supplierFails.some((c) => c.check_code === code);
                          if (!failedHere && !reasons.includes(code) && supplierFails.length) return null;
                          return (
                            <label key={code} className="reason">
                              <input
                                type="checkbox"
                                checked={reasons.includes(code)}
                                onChange={(e) =>
                                  setReasons((r) => (e.target.checked ? [...r, code] : r.filter((x) => x !== code)))
                                }
                              />
                              <span>
                                {CHECK_LABELS[code]}
                                {failedHere && (
                                  <span className="tag fail" style={{ marginLeft: 8 }}>
                                    failed check
                                  </span>
                                )}
                              </span>
                            </label>
                          );
                        })}
                        <label className="reason">
                          <input
                            type="checkbox"
                            checked={reasons.includes('other')}
                            onChange={(e) =>
                              setReasons((r) => (e.target.checked ? [...r, 'other'] : r.filter((x) => x !== 'other')))
                            }
                          />
                          <span>Another reason (explain below)</span>
                        </label>
                      </div>
                    </div>
                    <div>
                      <label className="form-label" htmlFor="return-note">
                        Note to the supplier (optional)
                      </label>
                      <textarea
                        id="return-note"
                        className="input"
                        value={note}
                        onChange={(e) => setNote(e.target.value)}
                        placeholder="Anything the supplier needs to know to reissue it"
                      />
                    </div>
                    <div>
                      <span className="form-label">Notice that will accompany the return</span>
                      <div className="notice">
                        {returnNotice(invoice.supplier_name, invoice.invoice_number, reasons, note)}
                      </div>
                    </div>
                  </div>
                )}
                {mode === 'accept' && acceptNeedsNoteOnly && (
                  <div className="decision-form">
                    <div>
                      <label className="form-label" htmlFor="override-note">
                        Why it is acceptable despite the failed check
                      </label>
                      <textarea
                        id="override-note"
                        className="input"
                        value={note}
                        onChange={(e) => setNote(e.target.value)}
                        placeholder={`At least ${OVERRIDE_NOTE_MIN} characters, e.g. "Contract manager confirmed the PO by email"`}
                        aria-invalid={note.trim().length < OVERRIDE_NOTE_MIN}
                      />
                    </div>
                  </div>
                )}
                {mode === 'reclassify' && (
                  <div className="decision-form">
                    <div>
                      <label className="form-label" htmlFor="reclassify">
                        This document is really a
                      </label>
                      <select
                        id="reclassify"
                        className="input"
                        value={reclassifyTo}
                        onChange={(e) => setReclassifyTo(e.target.value)}
                      >
                        <option value="">Choose a type</option>
                        {Object.entries(DOC_TYPES)
                          .filter(([k]) => k !== d?.doc_type)
                          .map(([k, v]) => (
                            <option key={k} value={k}>
                              {v}
                            </option>
                          ))}
                      </select>
                    </div>
                  </div>
                )}
                <div className="review-actions">
                  <span className="hint" role={problem ? 'alert' : undefined}>
                    <span>
                      {problem ? (
                        <span className="form-error">{problem}</span>
                      ) : mode !== 'idle' ? (
                        (formBlock ?? 'Ready to record.')
                      ) : isInvoice ? (
                        (acceptBlock ??
                        'Every held field is resolved. Accepting confirms the invoice is correctly rendered.')
                      ) : (
                        'Not an invoice. Reclassify it if the type is wrong.'
                      )}
                    </span>
                    {mode === 'idle' && (
                      <button className="link-button" onClick={() => setMode('reclassify')}>
                        Wrong document type?
                      </button>
                    )}
                  </span>
                  {mode !== 'idle' ? (
                    <>
                      <button
                        className="button"
                        onClick={() => {
                          setMode('idle');
                          setProblem(null);
                        }}
                        disabled={busy}
                      >
                        Cancel
                      </button>
                      <button
                        className="button primary"
                        onClick={() => void submit()}
                        disabled={busy || Boolean(formBlock)}
                      >
                        {busy
                          ? 'Recording'
                          : mode === 'return'
                            ? 'Record return to supplier'
                            : mode === 'reclassify'
                              ? 'Reclassify'
                              : 'Accept as correctly rendered'}
                      </button>
                    </>
                  ) : (
                    <>
                      {isInvoice && (
                        <button className="button" onClick={() => setMode('return')}>
                          <span>
                            Return<span className="wide-only"> to supplier</span>
                          </span>
                        </button>
                      )}
                      {isInvoice && (
                        <button
                          className="button primary"
                          disabled={Boolean(acceptBlock) && !acceptNeedsNoteOnly}
                          onClick={() => (acceptNeedsNoteOnly ? setMode('accept') : void submit())}
                        >
                          {acceptNeedsNoteOnly ? (
                            'Accept with override'
                          ) : (
                            <span>
                              Accept<span className="wide-only"> as correctly rendered</span>
                            </span>
                          )}
                        </button>
                      )}
                    </>
                  )}
                </div>
              </>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

function CheckLine({ c }: { c: CheckRow }) {
  const icon =
    c.result === 'pass' ? (
      <CircleCheck aria-hidden="true" />
    ) : c.result === 'fail' ? (
      <CircleX aria-hidden="true" />
    ) : (
      <CircleHelp aria-hidden="true" />
    );
  return (
    <div className={`check-row ${c.result}`}>
      {icon}
      <div>
        <div className="check-label">
          <span className="sr-only">
            {c.result === 'pass' ? 'Passed: ' : c.result === 'fail' ? 'Failed: ' : 'Could not check: '}
          </span>
          {c.label}
        </div>
        <div className="check-detail">
          {c.detail}
          {c.source_url ? (
            <>
              {' '}
              <a href={c.source_url} target="_blank" rel="noreferrer">
                {c.source}
              </a>
            </>
          ) : c.source ? (
            ` ${c.source}.`
          ) : null}
        </div>
      </div>
    </div>
  );
}

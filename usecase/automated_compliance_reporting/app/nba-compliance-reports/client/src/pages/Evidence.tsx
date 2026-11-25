import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router';
import {
  Alert,
  AlertDescription,
  Button,
  Label,
  Tabs,
  TabsList,
  TabsTrigger,
  Textarea,
  useAnalyticsQuery,
} from '@databricks/appkit-ui/react';
import { CheckCircle2, Download, ShieldAlert, Sparkles } from 'lucide-react';
import { api, useApi, useConfig, useDocumentTitle, useUrlState } from '../lib/api';
import {
  bool,
  downloadCsv,
  formatDate,
  formatDateTime,
  formatNumber,
  formatPercent,
  formatShortDateTime,
  list,
  num,
  plural,
  shortHash,
} from '../lib/format';
import type { QueryRow } from '../lib/types';
import {
  CopyValue,
  DataTable,
  DetailPanel,
  Field,
  FilterSelect,
  PageHeader,
  Panel,
  QueryState,
  SearchBox,
  Status,
  Toolbar,
  matches,
  uniqueOptions,
  type Column,
} from '../components/common';

type Evidence = QueryRow<'evidence'>;
interface Decision {
  review_id: string;
  evidence_id: string;
  decision: 'confirm' | 'reject';
  artefact_type: string | null;
  reviewer: string;
  reviewed_at: string;
  comment: string | null;
  pending: boolean;
}

const TABS = ['Needs review', 'Unmapped', 'Mapped', 'Rejected', 'all'] as const;

export function EvidencePage() {
  useDocumentTitle('Evidence mapping');
  const { parameters, ready } = useConfig();
  const evidence = useAnalyticsQuery('evidence', parameters, { autoStart: ready });
  const sources = useAnalyticsQuery('sources', parameters, { autoStart: ready });
  const decisions = useApi<{ decisions: Decision[] }>(ready ? '/api/evidence/decisions' : null);
  const [filters, setFilters] = useUrlState({ q: '', tab: '', source: '', freshness: '', id: '' });

  const all = useMemo(() => evidence.data ?? [], [evidence.data]);
  const counts = useMemo(() => {
    const result: Record<string, number> = { all: all.length };
    for (const row of all) result[row.mapping_state] = (result[row.mapping_state] ?? 0) + 1;
    return result;
  }, [all]);
  const tab = filters.tab || (counts['Needs review'] ? 'Needs review' : 'all');
  const latestDecision = useMemo(() => {
    const map = new Map<string, Decision>();
    for (const d of decisions.data?.decisions ?? []) if (!map.has(d.evidence_id)) map.set(d.evidence_id, d);
    return map;
  }, [decisions.data]);
  const pendingCount = (decisions.data?.decisions ?? []).filter((d) => d.pending).length;

  const rows = useMemo(
    () =>
      all.filter(
        (row) =>
          (tab === 'all' || row.mapping_state === tab) &&
          matches(
            filters.q,
            row.evidence_id,
            row.title,
            row.source_name,
            row.artefact_type,
            list(row.mapped_obligations).join(' ')
          ) &&
          (!filters.source || row.source_id === filters.source) &&
          (!filters.freshness || row.freshness_status === filters.freshness)
      ),
    [all, tab, filters]
  );
  const selected = all.find((row) => row.evidence_id === filters.id) ?? null;

  const columns: Column<Evidence>[] = [
    {
      key: 'artefact',
      header: 'Artefact',
      cell: (row) => (
        <span className="cell-stack">
          <strong>{row.title}</strong>
          <small>
            {row.evidence_id} · {row.file_format} · v{row.latest_version} · {row.source_name}
          </small>
          {!bool(row.integrity_verified) && (
            <small className="integrity bad">
              <ShieldAlert size={14} aria-hidden="true" /> Checksum mismatch
            </small>
          )}
        </span>
      ),
    },
    { key: 'collected', header: 'Collected', className: 'nowrap', cell: (row) => formatDate(row.collected_at) },
    {
      key: 'mapping',
      header: 'Mapping',
      cell: (row) => {
        const decision = latestDecision.get(row.evidence_id);
        return (
          <span className="cell-stack">
            <Status value={row.mapping_state} />
            <small>
              {decision?.pending
                ? `You ${decision.decision === 'confirm' ? 'confirmed' : 'rejected'} · applies at next run`
                : list(row.mapped_obligations).join(', ') || row.artefact_type || '—'}
            </small>
          </span>
        );
      },
    },
    {
      key: 'freshness',
      header: 'Freshness',
      cell: (row) => (
        <span className="cell-stack">
          <Status value={row.freshness_status} />
          {row.expires_on && <small className="nowrap">Expires {formatDate(row.expires_on)}</small>}
        </span>
      ),
    },
  ];

  return (
    <div className="page">
      <PageHeader
        title="Evidence mapping"
        detail="Collected artefacts and how they map to obligations. AI suggestions count as coverage only once a person confirms them."
        actions={
          <Button
            variant="outline"
            disabled={!rows.length}
            onClick={() => downloadCsv('evidence-manifest.csv', rows as unknown as Record<string, unknown>[])}
          >
            <Download /> Export manifest
          </Button>
        }
      />

      <section aria-label="Source systems">
        <QueryState
          loading={!ready || sources.loading}
          error={sources.error}
          empty={!sources.data?.length}
          rows={1}
          emptyTitle="No source systems registered"
        >
          <ul className="source-strip">
            {sources.data?.map((source) => {
              const active = filters.source === source.source_id;
              const failures = num(source.consecutive_failures) ?? 0;
              return (
                <li key={source.source_id}>
                  <button
                    type="button"
                    className={`source-chip ${active ? 'active' : ''}`}
                    aria-pressed={active}
                    onClick={() => setFilters({ source: active ? '' : source.source_id })}
                    title={source.last_error ?? undefined}
                  >
                    <span className="source-name">
                      <Status value={source.health} label="" />
                      <strong>{source.source_name}</strong>
                      <span className="sr-only">{source.health}</span>
                    </span>
                    <small>
                      {failures
                        ? `${source.health} · ${plural(failures, 'failed run')} since ${formatDate(source.failing_since)}`
                        : `${formatNumber(source.records_last_30d)} in 30 days · last ${formatDate(source.last_success_date)}`}
                    </small>
                  </button>
                </li>
              );
            })}
          </ul>
        </QueryState>
      </section>

      {pendingCount > 0 && (
        <Alert className="info-alert" role="status">
          <CheckCircle2 />
          <AlertDescription>
            {plural(pendingCount, 'decision')} recorded since coverage was last refreshed. Decisions are in the audit
            record now; coverage and gap alerts update at the next compliance_daily run.
          </AlertDescription>
        </Alert>
      )}

      <section className="split-detail">
        <Panel title="Evidence inbox" note="Automated collections, with items awaiting a decision first." flush>
          <Tabs
            value={tab}
            onValueChange={(value) =>
              setFilters({ tab: value === (counts['Needs review'] ? 'Needs review' : 'all') ? '' : value })
            }
          >
            <TabsList className="inbox-tabs" aria-label="Mapping state">
              {TABS.map((t) => (
                <TabsTrigger key={t} value={t}>
                  {t === 'all' ? 'All' : t}{' '}
                  {evidence.data && <span className="tab-count">{formatNumber(counts[t] ?? 0)}</span>}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
          <Toolbar summary={evidence.data ? `${rows.length} artefacts` : null}>
            <SearchBox
              value={filters.q}
              onChange={(q) => setFilters({ q })}
              label="Search evidence"
              placeholder="Search by title, ID, type or obligation"
            />
            <FilterSelect
              label="Source system"
              allLabel="All sources"
              value={filters.source}
              onChange={(source) => setFilters({ source })}
              options={uniqueOptions(
                all,
                (r) => r.source_id,
                (r) => r.source_name
              )}
            />
            <FilterSelect
              label="Freshness"
              allLabel="Any freshness"
              value={filters.freshness}
              onChange={(freshness) => setFilters({ freshness })}
              options={uniqueOptions(all, (r) => r.freshness_status)}
            />
          </Toolbar>
          <QueryState
            loading={!ready || evidence.loading}
            error={evidence.error}
            empty={!rows.length}
            emptyTitle={tab === 'Needs review' ? 'Nothing awaiting review' : 'No artefacts match these filters'}
            emptyDetail={
              tab === 'Needs review' ? 'New AI suggestions appear here after each daily collection.' : undefined
            }
          >
            <DataTable
              caption="Evidence inbox"
              columns={columns}
              rows={rows}
              rowKey={(row) => row.evidence_id}
              selectedKey={filters.id}
              onSelect={(row) => setFilters({ id: row.evidence_id }, { replace: false })}
              limit={50}
            />
          </QueryState>
        </Panel>
        <DetailPanel
          open={Boolean(selected)}
          onClose={() => setFilters({ id: '' })}
          title={selected ? `${selected.evidence_id} · ${selected.title}` : 'Mapping review'}
          placeholder={<p>Select an artefact to review its mapping, provenance and freshness.</p>}
        >
          {selected && (
            <EvidenceDetail
              key={selected.evidence_id}
              item={selected}
              decision={latestDecision.get(selected.evidence_id) ?? null}
              onDecided={decisions.reload}
            />
          )}
        </DetailPanel>
      </section>
    </div>
  );
}

function EvidenceDetail({
  item,
  decision,
  onDecided,
}: {
  item: Evidence;
  decision: Decision | null;
  onDecided: () => void;
}) {
  const [mode, setMode] = useState<'idle' | 'reject'>('idle');
  const [comment, setComment] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => setError(null), [mode]);

  const suggested = list(item.suggested_obligations);
  const mapped = list(item.mapped_obligations);
  const confidence = num(item.ai_confidence);
  const pending = decision?.pending ? decision : null;
  const canConfirm = item.mapping_state === 'Needs review' && Boolean(item.artefact_type) && !pending;
  const canReject = (item.mapping_state === 'Needs review' || item.mapping_state === 'Mapped') && !pending;

  async function submit(choice: 'confirm' | 'reject') {
    setSaving(true);
    setError(null);
    try {
      await api(`/api/evidence/${item.evidence_id}/review`, {
        method: 'POST',
        json: { decision: choice, comment: comment.trim() || undefined },
      });
      setMode('idle');
      setComment('');
      onDecided();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The decision was not recorded.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="detail">
      <div className="detail-head">
        <div>
          <p className="eyebrow">
            {item.evidence_id} · {item.file_format} · version {item.latest_version} of {item.version_count}
          </p>
          <h2>{item.title}</h2>
        </div>
        <div className="detail-badges">
          <Status value={item.mapping_state} />
          <Status value={item.freshness_status} />
        </div>
      </div>

      <section className="detail-section" aria-labelledby="mapping-title">
        <h3 id="mapping-title">Mapping</h3>
        {item.mapping_state === 'Needs review' && (
          <div className="ai-suggestion">
            <p className="ai-label">
              <Sparkles size={14} aria-hidden="true" /> AI suggestion · not counted as coverage until confirmed
            </p>
            <p>
              <strong>{item.artefact_type ?? 'No artefact type suggested'}</strong>
              {suggested.length ? ` for ${suggested.join(', ')}` : ''}
              {confidence !== null ? ` · confidence ${formatPercent(confidence)}` : ''}
            </p>
            {item.ai_rationale && <blockquote>{item.ai_rationale}</blockquote>}
            <p className="muted">Model {item.model_endpoint ?? 'not recorded'}</p>
          </div>
        )}
        {item.mapping_state === 'Mapped' && (
          <p>
            Mapped as <strong>{item.artefact_type}</strong> to{' '}
            {mapped.length
              ? mapped.map((id, i) => (
                  <span key={id}>
                    {i > 0 && ', '}
                    <Link to={`/obligations?id=${id}`}>{id}</Link>
                  </span>
                ))
              : 'no current obligation'}{' '}
            <span className="muted">
              by{' '}
              {item.mapping_method === 'human'
                ? `${item.reviewer ?? 'a reviewer'} on ${formatDate(item.reviewed_at)}`
                : `${item.mapping_method} mapping`}
            </span>
          </p>
        )}
        {item.mapping_state === 'Rejected' && (
          <p>
            Rejected as not compliance evidence
            {item.reviewer ? ` by ${item.reviewer} on ${formatDate(item.reviewed_at)}` : ''}.
          </p>
        )}
        {item.mapping_state === 'Unmapped' && (
          <p>No rule or confident AI suggestion matched this artefact. It does not count towards any obligation.</p>
        )}

        {pending ? (
          <div className="callout good" role="status">
            <strong>
              You {pending.decision === 'confirm' ? 'confirmed this mapping' : 'rejected this artefact'} on{' '}
              {formatShortDateTime(pending.reviewed_at)}
            </strong>
            <p>
              Recorded as {pending.review_id}. Coverage updates at the next pipeline run, which also adds the decision
              to the hash-chained audit trail.
            </p>
          </div>
        ) : mode === 'reject' ? (
          <form
            className="decision-form"
            onSubmit={(event) => {
              event.preventDefault();
              void submit('reject');
            }}
          >
            <Label htmlFor="reject-reason">Reason for rejecting (kept in the audit trail)</Label>
            <Textarea
              id="reject-reason"
              value={comment}
              maxLength={500}
              required
              onChange={(event) => setComment(event.target.value)}
              placeholder="For example: draft copy, not the approved version"
            />
            <div className="inline-actions">
              <Button type="submit" variant="destructive" disabled={saving || !comment.trim()}>
                {saving ? 'Recording…' : 'Reject evidence'}
              </Button>
              <Button type="button" variant="outline" onClick={() => setMode('idle')} disabled={saving}>
                Cancel
              </Button>
            </div>
          </form>
        ) : (
          (canConfirm || canReject) && (
            <div className="inline-actions">
              {canConfirm && (
                <Button onClick={() => void submit('confirm')} disabled={saving}>
                  {saving ? 'Recording…' : 'Confirm mapping'}
                </Button>
              )}
              {canReject && (
                <Button variant="outline" onClick={() => setMode('reject')} disabled={saving}>
                  {item.mapping_state === 'Mapped' ? 'Reject this mapping' : 'Reject'}
                </Button>
              )}
            </div>
          )
        )}
        {error && (
          <Alert variant="destructive" className="inline-alert" role="alert">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {(canConfirm || canReject) && !pending && (
          <p className="panel-footnote">
            Decisions are recorded under your name with the time. They cannot be edited; a later decision supersedes an
            earlier one.
          </p>
        )}
      </section>

      {item.content_excerpt && (
        <section className="detail-section" aria-labelledby="excerpt-title">
          <h3 id="excerpt-title">Excerpt</h3>
          <p className="excerpt">{item.content_excerpt}</p>
        </section>
      )}

      <section className="detail-section" aria-labelledby="prov-title">
        <h3 id="prov-title">Provenance</h3>
        <dl className="fields">
          <Field label="Source">
            {item.source_name} <span className="muted">({item.connector})</span>
          </Field>
          <Field label="Collected">{formatDateTime(item.collected_at)}</Field>
          <Field label="Source modified">{formatDateTime(item.source_modified_at)}</Field>
          <Field label="Approval">
            {item.approval_status}
            {bool(item.signed) ? ' · signed' : ''}
            {item.approved_version ? ` · approved version ${item.approved_version}` : ''}
          </Field>
          <Field label="Integrity">
            {bool(item.integrity_verified)
              ? 'Checksum matches the source'
              : 'Checksum does not match the source. Do not rely on this artefact.'}
          </Field>
          <Field label="Checksum (SHA-256)">
            {item.checksum ? <CopyValue value={item.checksum} display={`${shortHash(item.checksum, 16)}…`} /> : '—'}
          </Field>
        </dl>
      </section>

      <section className="detail-section" aria-labelledby="fresh-title">
        <h3 id="fresh-title">Freshness</h3>
        <p>
          {item.expires_on
            ? `Expires ${formatDate(item.expires_on)}, ${formatNumber(item.freshness_threshold_days)} days after the source was last modified.`
            : item.freshness_threshold_days
              ? 'No approved version, so no expiry date applies.'
              : 'No freshness threshold is configured for this artefact type.'}
        </p>
      </section>
    </div>
  );
}

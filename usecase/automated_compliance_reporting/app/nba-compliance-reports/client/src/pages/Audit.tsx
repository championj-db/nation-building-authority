import { useMemo, useState } from 'react';
import { Link } from 'react-router';
import { Button, useAnalyticsQuery } from '@databricks/appkit-ui/react';
import { sql } from '@databricks/appkit-ui/js';
import { Download, ShieldAlert, ShieldCheck } from 'lucide-react';
import { api, useApi, useConfig, useDocumentTitle, useTrackedRun, useUrlState } from '../lib/api';
import {
  downloadCsv,
  formatDateTime,
  formatNumber,
  formatShortDateTime,
  json,
  num,
  plural,
  shortHash,
} from '../lib/format';
import type { QueryRow } from '../lib/types';
import {
  CopyValue,
  DataTable,
  DetailPanel,
  ErrorState,
  Field,
  FilterSelect,
  LoadingRows,
  PageHeader,
  Panel,
  QueryState,
  SearchBox,
  Status,
  Toolbar,
  matches,
  type Column,
} from '../components/common';
import { RunBanner } from './Reports';

type AuditEvent = QueryRow<'audit'>;

interface Verification {
  verification_id: string;
  verified_at: string;
  events_checked: string;
  head_seq: string;
  head_hash: string;
  status: string;
  first_broken_seq: string | null;
  detail: string | null;
  latest_seq: string | null;
}

const CATEGORIES: Record<string, string> = {
  register: 'Register changes',
  evidence: 'Evidence collection',
  collection: 'Collection runs',
  mapping: 'Mapping decisions',
  alert: 'Gap alerts',
  report: 'Reports',
  audit: 'Chain verification',
};

function entityLink(event: AuditEvent) {
  const id = event.entity_id;
  if (/^OBL-/.test(id)) return `/obligations?id=${id}`;
  if (/^EV-/.test(id)) return `/evidence?id=${id}`;
  if (/^REP-/.test(id)) return `/reports?id=${id}`;
  return null;
}

export function AuditPage() {
  useDocumentTitle('Audit trail');
  const { parameters, ready, refresh, bumpRefresh, config } = useConfig();
  const events = useAnalyticsQuery('audit', { ...parameters, refresh: sql.string(refresh) }, { autoStart: ready });
  const verification = useApi<{ verification: Verification | null }>(ready ? '/api/audit/verification' : null, [
    refresh,
  ]);
  const tracked = useTrackedRun('verify', () => bumpRefresh());
  const [filters, setFilters] = useUrlState({ q: '', category: '', id: '' });
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  const all = useMemo(() => events.data ?? [], [events.data]);
  const rows = useMemo(
    () =>
      all.filter(
        (event) =>
          (!filters.category || event.event_type.split('.')[0] === filters.category) &&
          matches(
            filters.q,
            event.event_id,
            event.entity_id,
            event.related_id,
            event.summary,
            event.actor,
            event.event_type
          )
      ),
    [all, filters]
  );
  const selected = all.find((event) => event.event_id === filters.id) ?? null;
  const previous = selected ? all.find((event) => num(event.event_seq) === (num(selected.event_seq) ?? 0) - 1) : null;
  const running = Boolean(tracked.runId && !tracked.run?.endedAt);

  async function verify() {
    setStarting(true);
    setStartError(null);
    try {
      const { runId } = await api<{ runId: number }>('/api/audit/verify', { method: 'POST' });
      tracked.track(runId);
    } catch (reason) {
      setStartError(reason instanceof Error ? reason.message : 'Verification could not be started.');
    } finally {
      setStarting(false);
    }
  }

  const columns: Column<AuditEvent>[] = [
    { key: 'seq', header: 'Seq', className: 'num', cell: (event) => <code>{event.event_seq}</code> },
    { key: 'when', header: 'Occurred', className: 'nowrap', cell: (event) => formatShortDateTime(event.occurred_at) },
    {
      key: 'event',
      header: 'Event',
      cell: (event) => (
        <span className="cell-stack">
          <strong>{event.summary}</strong>
          <small>
            {event.event_type} · {event.entity_id}
          </small>
        </span>
      ),
    },
    { key: 'actor', header: 'Actor', cell: (event) => event.actor },
  ];

  return (
    <div className="page">
      <PageHeader
        title="Audit trail"
        detail="Every collection, mapping, register change and report event, append-only and hash-chained to the one before it."
        actions={
          <>
            <Button
              variant="outline"
              disabled={!rows.length}
              onClick={() => downloadCsv('audit-trail.csv', rows as unknown as Record<string, unknown>[])}
            >
              <Download /> Export events
            </Button>
            <Button
              onClick={() => void verify()}
              disabled={!config?.capabilities.verifyChain || running || starting}
              title={!config?.capabilities.verifyChain ? 'The verification job is not bound to this app.' : undefined}
            >
              <ShieldCheck /> {starting ? 'Starting…' : 'Verify chain'}
            </Button>
          </>
        }
      />
      {startError && <ErrorState message={startError} />}
      {tracked.runId && <RunBanner run={tracked.run} kind="verify" onDismiss={tracked.dismiss} />}

      <VerificationSummary
        loading={!ready || verification.loading}
        error={verification.error}
        value={verification.data?.verification ?? null}
      />

      <section className="split-detail">
        <Panel title="Event history" note="Newest first. Showing the latest 1,000 events." flush>
          <Toolbar summary={events.data ? `${formatNumber(rows.length)} of ${formatNumber(all.length)} events` : null}>
            <SearchBox
              value={filters.q}
              onChange={(q) => setFilters({ q })}
              label="Search events"
              placeholder="Search by entity, actor or summary"
            />
            <FilterSelect
              label="Event category"
              allLabel="All events"
              value={filters.category}
              onChange={(category) => setFilters({ category })}
              options={Object.entries(CATEGORIES).map(([value, label]) => ({ value, label }))}
            />
          </Toolbar>
          <QueryState
            loading={!ready || events.loading}
            error={events.error}
            empty={!rows.length}
            emptyTitle={all.length ? 'No events match these filters' : 'No audit events yet'}
          >
            <DataTable
              caption="Audit events"
              columns={columns}
              rows={rows}
              rowKey={(event) => event.event_id}
              selectedKey={filters.id}
              onSelect={(event) => setFilters({ id: event.event_id }, { replace: false })}
              limit={50}
            />
          </QueryState>
        </Panel>
        <DetailPanel
          open={Boolean(selected)}
          onClose={() => setFilters({ id: '' })}
          title={selected ? selected.event_id : 'Event detail'}
          placeholder={<p>Select an event to see its payload and how it links to the previous event in the chain.</p>}
        >
          {selected && (
            <div className="detail">
              <div className="detail-head">
                <div>
                  <p className="eyebrow">
                    {selected.event_id} · sequence {selected.event_seq}
                  </p>
                  <h2>{selected.summary}</h2>
                </div>
              </div>
              <dl className="fields">
                <Field label="Event type">{selected.event_type}</Field>
                <Field label="Entity">
                  {entityLink(selected) ? (
                    <Link to={entityLink(selected)!}>{selected.entity_id}</Link>
                  ) : (
                    selected.entity_id
                  )}
                  <span className="muted"> ({selected.entity_type})</span>
                </Field>
                {selected.related_id && <Field label="Related">{selected.related_id}</Field>}
                <Field label="Actor">{selected.actor}</Field>
                <Field label="Occurred">{formatDateTime(selected.occurred_at)}</Field>
                <Field label="Recorded">{formatDateTime(selected.recorded_at)}</Field>
              </dl>
              <section className="detail-section" aria-labelledby="chain-title">
                <h3 id="chain-title">Hash chain</h3>
                <ol className="chain">
                  <li>
                    <span className="muted">Previous event {previous ? `#${previous.event_seq}` : ''}</span>
                    {previous ? (
                      <button
                        type="button"
                        className="text-button"
                        onClick={() => setFilters({ id: previous.event_id }, { replace: false })}
                      >
                        <code>{shortHash(selected.prev_hash, 24)}…</code>
                      </button>
                    ) : (
                      <code>{selected.prev_hash ? `${shortHash(selected.prev_hash, 24)}…` : 'genesis'}</code>
                    )}
                  </li>
                  <li>
                    <span className="muted">This event</span>
                    <CopyValue value={selected.event_hash} display={`${shortHash(selected.event_hash, 24)}…`} />
                  </li>
                </ol>
                <p className="panel-footnote">
                  event_hash = sha256(prev_hash ‖ canonical event). Changing any earlier event breaks every hash after
                  it.
                </p>
              </section>
              <section className="detail-section" aria-labelledby="payload-title">
                <h3 id="payload-title">Payload</h3>
                <pre className="payload">{JSON.stringify(json(selected.payload), null, 2)}</pre>
              </section>
            </div>
          )}
        </DetailPanel>
      </section>
    </div>
  );
}

function VerificationSummary({
  loading,
  error,
  value,
}: {
  loading: boolean;
  error: string | null;
  value: Verification | null;
}) {
  if (error) return <ErrorState message={error} />;
  if (loading) return <LoadingRows rows={1} />;
  if (!value)
    return (
      <div className="verification bad">
        <ShieldAlert size={28} aria-hidden="true" />
        <div>
          <strong>The chain has not been verified</strong>
          <p>Run Verify chain to check the audit trail.</p>
        </div>
      </div>
    );
  const verified = value.status === 'Verified';
  const detail = (json(value.detail) ?? {}) as {
    append_only?: boolean;
    history_versions?: number;
    rewrite_operations_in_history?: unknown[];
  };
  const since = Math.max((num(value.latest_seq) ?? 0) - (num(value.head_seq) ?? 0), 0);
  return (
    <section className={`verification ${verified ? 'good' : 'bad'}`} aria-label="Chain verification">
      {verified ? <ShieldCheck size={28} aria-hidden="true" /> : <ShieldAlert size={28} aria-hidden="true" />}
      <div>
        <strong>{verified ? 'Chain verified' : `Chain broken at event ${value.first_broken_seq ?? 'unknown'}`}</strong>
        <p>
          {formatNumber(value.events_checked)} events checked up to #{value.head_seq} on{' '}
          {formatDateTime(value.verified_at)}
          {' · '}
          {detail.append_only ? 'append-only enforced' : 'append-only NOT enforced'}
          {' · '}
          {plural(detail.rewrite_operations_in_history?.length ?? 0, 'rewrite operation')} in table history
        </p>
        {since > 0 && <p className="muted">{plural(since, 'event')} recorded since this verification.</p>}
      </div>
      <Status value={value.status} />
    </section>
  );
}

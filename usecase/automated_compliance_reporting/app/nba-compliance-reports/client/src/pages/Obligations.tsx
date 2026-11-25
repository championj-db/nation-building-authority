import { useMemo } from 'react';
import { Link } from 'react-router';
import { Badge, Button, useAnalyticsQuery } from '@databricks/appkit-ui/react';
import { Download, ExternalLink } from 'lucide-react';
import { useConfig, useDocumentTitle, useUrlState } from '../lib/api';
import { bool, downloadCsv, formatDate, formatDateTime, formatNumber, num, plural } from '../lib/format';
import type { QueryRow } from '../lib/types';
import {
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
  LoadingRows,
  type Column,
} from '../components/common';

type Obligation = QueryRow<'obligations'>;

export function ObligationsPage() {
  useDocumentTitle('Obligation register');
  const { parameters, ready } = useConfig();
  const register = useAnalyticsQuery('obligations', parameters, { autoStart: ready });
  const coverage = useAnalyticsQuery('overview_obligations', parameters, { autoStart: ready });
  const requirements = useAnalyticsQuery('requirement_coverage', parameters, { autoStart: ready });
  const history = useAnalyticsQuery('obligation_history', parameters, { autoStart: ready });
  const [filters, setFilters] = useUrlState({ q: '', gate: '', framework: '', state: '', id: '' });

  const all = useMemo(() => register.data ?? [], [register.data]);
  const statusById = useMemo(
    () => new Map((coverage.data ?? []).map((row) => [row.obligation_id, row])),
    [coverage.data]
  );
  const rows = useMemo(
    () =>
      all.filter(
        (row) =>
          matches(filters.q, row.obligation_id, row.title, row.owner_role, row.framework, row.description) &&
          (!filters.gate || row.gate_id === filters.gate) &&
          (!filters.framework || row.framework === filters.framework) &&
          (!filters.state || row.register_state === filters.state)
      ),
    [all, filters]
  );
  const selected = all.find((row) => row.obligation_id === filters.id) ?? null;

  const columns: Column<Obligation>[] = [
    {
      key: 'obligation',
      header: 'Obligation',
      cell: (row) => (
        <span className="cell-stack">
          <strong>{row.title}</strong>
          <small>
            {row.obligation_id} · v{row.version} · {row.owner_role}
          </small>
        </span>
      ),
    },
    { key: 'gate', header: 'Gate', className: 'nowrap', cell: (row) => row.gate_label },
    {
      key: 'framework',
      header: 'Framework',
      cell: (row) => (
        <span className="cell-stack">
          <span>{row.framework}</span>
          <small>{plural(num(row.requirement_count) ?? 0, 'evidence requirement')}</small>
        </span>
      ),
    },
    {
      key: 'coverage',
      header: 'Coverage',
      cell: (row) => <Status value={statusById.get(row.obligation_id)?.status ?? 'Not assessed'} />,
    },
    {
      key: 'state',
      header: 'Register state',
      cell: (row) =>
        row.draft_version ? (
          <Status value="Review" label={`Draft v${row.draft_version} pending`} />
        ) : (
          <Status value={row.register_state} />
        ),
    },
  ];

  return (
    <div className="page">
      <PageHeader
        title="Obligation register"
        detail="Versioned obligations, their owners and the evidence each one requires. The register models obligations; it does not interpret them."
        actions={
          <Button
            variant="outline"
            disabled={!all.length}
            onClick={() => downloadCsv('obligation-register.csv', all as unknown as Record<string, unknown>[])}
          >
            <Download /> Export register
          </Button>
        }
      />
      <section className="split-detail">
        <Panel title="Register entries" note="Current approved version of each obligation." flush>
          <Toolbar summary={register.data ? `${rows.length} of ${all.length} obligations` : null}>
            <SearchBox
              value={filters.q}
              onChange={(q) => setFilters({ q })}
              label="Search the register"
              placeholder="Search by title, ID, owner or description"
            />
            <FilterSelect
              label="Review gate"
              allLabel="All gates"
              value={filters.gate}
              onChange={(gate) => setFilters({ gate })}
              options={uniqueOptions(
                all,
                (o) => o.gate_id,
                (o) => `${o.gate_label} · ${o.gate_name}`
              )}
            />
            <FilterSelect
              label="Framework"
              allLabel="All frameworks"
              value={filters.framework}
              onChange={(framework) => setFilters({ framework })}
              options={uniqueOptions(all, (o) => o.framework)}
            />
            <FilterSelect
              label="Register state"
              allLabel="All states"
              value={filters.state}
              onChange={(state) => setFilters({ state })}
              options={[
                { value: 'Active', label: 'Active' },
                { value: 'Review', label: 'Revision pending' },
              ]}
            />
          </Toolbar>
          <QueryState
            loading={!ready || register.loading}
            error={register.error}
            empty={!rows.length}
            emptyTitle={all.length ? 'No obligations match these filters' : 'The register is empty'}
            emptyAction={
              all.length ? (
                <button
                  type="button"
                  className="text-button"
                  onClick={() => setFilters({ q: '', gate: '', framework: '', state: '' })}
                >
                  Clear filters
                </button>
              ) : undefined
            }
          >
            <DataTable
              caption="Obligation register"
              columns={columns}
              rows={rows}
              rowKey={(row) => row.obligation_id}
              selectedKey={filters.id}
              onSelect={(row) => setFilters({ id: row.obligation_id }, { replace: false })}
            />
          </QueryState>
        </Panel>
        <DetailPanel
          open={Boolean(selected)}
          onClose={() => setFilters({ id: '' })}
          title={selected ? `${selected.obligation_id} · ${selected.title}` : 'Obligation detail'}
          placeholder={
            <p>
              Select an obligation to see what evidence it needs, where that evidence stands, and how the obligation has
              changed.
            </p>
          }
        >
          {selected && (
            <ObligationDetail
              obligation={selected}
              status={statusById.get(selected.obligation_id)?.status ?? null}
              requirements={(requirements.data ?? []).filter((r) => r.obligation_id === selected.obligation_id)}
              requirementsLoading={requirements.loading}
              history={(history.data ?? []).filter((h) => h.obligation_id === selected.obligation_id)}
              historyLoading={!history.data}
            />
          )}
        </DetailPanel>
      </section>
    </div>
  );
}

function ObligationDetail({
  obligation,
  status,
  requirements,
  requirementsLoading,
  history,
  historyLoading,
}: {
  obligation: Obligation;
  status: string | null;
  requirements: QueryRow<'requirement_coverage'>[];
  requirementsLoading: boolean;
  history: QueryRow<'obligation_history'>[];
  historyLoading: boolean;
}) {
  return (
    <div className="detail">
      <div className="detail-head">
        <div>
          <p className="eyebrow">
            {obligation.obligation_id} · version {obligation.version}
          </p>
          <h2>{obligation.title}</h2>
        </div>
        <div className="detail-badges">
          <Badge variant="outline">{obligation.gate_label}</Badge>
          {status && <Status value={status} />}
        </div>
      </div>
      <p className="detail-lede">{obligation.description}</p>

      {obligation.draft_version && (
        <div className="callout warn">
          <strong>Draft version {obligation.draft_version} awaiting approval</strong>
          <p>
            Proposed {formatDate(obligation.draft_proposed_at)}:{' '}
            {(obligation.draft_change_reason ?? 'no reason recorded').replace(/^Proposed:\s*/i, '')}. Reports keep using
            version {obligation.version} until the draft is approved.
          </p>
        </div>
      )}

      <dl className="fields">
        <Field label="Owner">{obligation.owner_role}</Field>
        <Field label="Framework">
          {obligation.framework_url ? (
            <a href={obligation.framework_url} target="_blank" rel="noreferrer">
              {obligation.framework} <ExternalLink size={12} aria-label="(opens in a new tab)" />
            </a>
          ) : (
            obligation.framework
          )}
        </Field>
        <Field label="Review gate">
          {obligation.gate_label} · {obligation.gate_name}
        </Field>
        <Field label="Effective from">{formatDate(obligation.effective_from)}</Field>
        <Field label="Approved">
          {formatDate(obligation.approved_at)} by {obligation.approved_by ?? '—'}
        </Field>
        <Field label="Change reason">{obligation.change_reason ?? '—'}</Field>
      </dl>

      <section className="detail-section" aria-labelledby="req-title">
        <h3 id="req-title">Required evidence ({formatNumber(obligation.requirement_count)})</h3>
        <QueryState
          loading={requirementsLoading}
          error={null}
          empty={!requirements.length}
          rows={2}
          emptyTitle="No coverage assessed for this obligation yet"
        >
          <ul className="requirement-list">
            {requirements.map((req) => {
              return (
                <li key={req.requirement_id}>
                  <div className="requirement-head">
                    <strong>{req.artefact_type}</strong>
                    <Status value={req.status} />
                  </div>
                  <p className="muted">
                    {req.requirement_description} · from {req.expected_source_id} · valid for{' '}
                    {formatNumber(req.max_age_days)} days
                    {bool(req.mandatory) ? '' : ' · optional'}
                  </p>
                  {req.best_evidence_id ? (
                    <p>
                      <Link to={`/evidence?id=${req.best_evidence_id}`}>
                        {req.best_evidence_id} · {req.best_evidence_title}
                      </Link>{' '}
                      <span className="muted">
                        v{req.best_artefact_version} · expires {formatDate(req.expires_on)}
                      </span>
                    </p>
                  ) : (
                    <p className="gap-reason">{req.gap_reason ?? 'No evidence mapped'}</p>
                  )}
                  {num(req.pending_review_count) ? (
                    <p className="muted">
                      {plural(num(req.pending_review_count)!, 'artefact')} awaiting mapping review.{' '}
                      <Link to="/evidence?tab=Needs+review">Review evidence</Link>
                    </p>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </QueryState>
      </section>

      <section className="detail-section" aria-labelledby="history-title">
        <h3 id="history-title">Version history{historyLoading ? '' : ` (${history.length})`}</h3>
        {historyLoading && <LoadingRows rows={2} />}
        <ol className="timeline">
          {history.map((version) => (
            <li key={version.version}>
              <span className="timeline-marker" aria-hidden="true" />
              <div>
                <p>
                  <strong>Version {version.version}</strong> <Status value={version.approval_state} />
                  {version.retired_on ? (
                    <Status value="Retired" label={`Retired ${formatDate(version.retired_on)}`} />
                  ) : null}
                </p>
                <p className="muted">
                  {version.change_reason ?? 'No reason recorded'} ·{' '}
                  {plural(num(version.requirement_count) ?? 0, 'requirement')}
                </p>
                <p className="muted">
                  {version.effective_from
                    ? `Effective ${formatDate(version.effective_from)}${version.effective_to ? ` to ${formatDate(version.effective_to)}` : ' (current)'}`
                    : `Proposed ${formatDateTime(version.proposed_at)}`}
                  {version.approved_by ? ` · approved by ${version.approved_by}` : ''}
                </p>
              </div>
            </li>
          ))}
        </ol>
        <p className="panel-footnote">
          Reports use the version effective on their evidence date, so past reports reproduce exactly.
        </p>
      </section>
    </div>
  );
}

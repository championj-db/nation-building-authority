import { useMemo } from 'react';
import { Link, useNavigate } from 'react-router';
import { Alert, AlertDescription, AlertTitle, LineChart, useAnalyticsQuery } from '@databricks/appkit-ui/react';
import { AlertTriangle } from 'lucide-react';
import { useConfig, useDocumentTitle, useUrlState } from '../lib/api';
import {
  formatShortDate,
  daysFrom,
  downloadCsv,
  formatDate,
  formatDateTime,
  formatNumber,
  formatPercent,
  num,
  plural,
  relativeDays,
} from '../lib/format';
import {
  DataTable,
  FilterSelect,
  PageHeader,
  Panel,
  QueryState,
  SearchBox,
  StackedBar,
  Status,
  Toolbar,
  matches,
  uniqueOptions,
  type Column,
} from '../components/common';
import { GenerateReportButton } from './Reports';
import type { QueryRow } from '../lib/types';

type Obligation = QueryRow<'overview_obligations'>;

const STALE_AFTER_DAYS = 2;

const METHOD_LABELS: Record<string, string> = {
  resolved: 'Resolved mapping (what coverage uses)',
  rule: 'Rule (source document class)',
  ai: 'AI suggestion, all',
  ai_confident: 'AI suggestion, above confidence threshold',
  human: 'Human review',
};

export function OverviewPage() {
  useDocumentTitle('Overview');
  const navigate = useNavigate();
  const { parameters, ready } = useConfig();
  const overview = useAnalyticsQuery('overview', parameters, { autoStart: ready });
  const gates = useAnalyticsQuery('gate_coverage', parameters, { autoStart: ready });
  const attention = useAnalyticsQuery('attention', parameters, { autoStart: ready });
  const obligations = useAnalyticsQuery('overview_obligations', parameters, { autoStart: ready });
  const trend = useAnalyticsQuery('coverage_trend', parameters, { autoStart: ready });
  const accuracy = useAnalyticsQuery('accuracy', parameters, { autoStart: ready });
  const [filters, setFilters] = useUrlState({ q: '', gate: '', status: '' });

  const row = overview.data?.[0];
  const ageDays = row ? -(daysFrom(row.as_of_date) ?? 0) : 0;
  const all = useMemo(() => obligations.data ?? [], [obligations.data]);
  const rows = useMemo(
    () =>
      all.filter(
        (item) =>
          matches(filters.q, item.obligation_id, item.obligation_title, item.owner_role, item.framework) &&
          (!filters.gate || item.gate_id === filters.gate) &&
          (!filters.status || item.status === filters.status)
      ),
    [all, filters]
  );

  const kpis = row
    ? [
        {
          label: 'Obligations',
          value: formatNumber(row.obligations),
          detail: `${formatNumber(row.requirements_total)} evidence requirements`,
          status: '',
        },
        {
          label: 'Complete',
          value: formatNumber(row.obligations_complete),
          detail: `${formatNumber(row.requirements_met)} of ${formatNumber(row.requirements_total)} requirements met (${row.evidence_coverage_pct}%)`,
          status: 'Complete',
          tone: 'good',
        },
        {
          label: 'Expiring soon',
          value: formatNumber(row.obligations_expiring),
          detail: `Evidence expires within ${row.expiry_warning_days} days`,
          status: 'Expiring',
          tone: 'warn',
        },
        {
          label: 'Gaps',
          value: formatNumber(row.obligations_gap),
          detail: `${plural(num(row.open_high_alerts) ?? 0, 'high-severity alert')} open`,
          status: 'Gap',
          tone: 'bad',
        },
      ]
    : [];

  const columns: Column<Obligation>[] = [
    {
      key: 'obligation',
      header: 'Obligation',
      cell: (item) => (
        <span className="cell-stack">
          <strong>{item.obligation_title}</strong>
          <small>
            {item.obligation_id} · v{item.obligation_version} · {item.owner_role}
            {item.register_state === 'Review' ? ' · revision pending' : ''}
          </small>
        </span>
      ),
    },
    { key: 'gate', header: 'Gate', className: 'nowrap', cell: (item) => item.gate_label },
    {
      key: 'evidence',
      header: 'Requirements met',
      className: 'num',
      cell: (item) => (
        <span className="cell-stack">
          <span>
            {formatNumber(item.requirements_complete)} of {formatNumber(item.requirements_total)}
          </span>
          {num(item.pending_review_count) ? (
            <small>{formatNumber(item.pending_review_count)} awaiting review</small>
          ) : null}
        </span>
      ),
    },
    { key: 'status', header: 'Status', cell: (item) => <Status value={item.status} /> },
    {
      key: 'review',
      header: 'Next review',
      className: 'nowrap',
      cell: (item) => {
        if (!item.review_date) return <span className="muted">Not set</span>;
        const days = daysFrom(item.review_date) ?? 0;
        return (
          <span className="cell-stack">
            <span>{formatDate(item.review_date)}</span>
            {days < 0 ? (
              <small className="overdue">Overdue by {plural(-days, 'day')}</small>
            ) : (
              <small>{relativeDays(days)}</small>
            )}
          </span>
        );
      },
    },
  ];

  const attentionItems = attention.data ?? [];

  return (
    <div className="page">
      <PageHeader
        title="Compliance assurance"
        detail="Evidence coverage across the obligation register, so gaps are found when they open rather than at the reporting deadline."
        actions={
          <GenerateReportButton
            variant="primary"
            onCreated={() => void navigate('/reports')}
            preflight={{ gates: gates.data ?? [], overview: row ?? null }}
          />
        }
      />

      <QueryState
        loading={!ready || overview.loading}
        error={overview.error}
        empty={!row}
        rows={2}
        emptyTitle="No coverage has been computed yet"
        emptyDetail="Run the compliance_bootstrap job once, then compliance_daily on its schedule."
      >
        {row && (
          <>
            {ageDays > STALE_AFTER_DAYS ? (
              <Alert className="stale-alert">
                <AlertTriangle />
                <AlertTitle>Coverage is {ageDays} days old</AlertTitle>
                <AlertDescription>
                  Evidence was last assessed as at {formatDate(row.as_of_date)}. Gaps and expiries since then are not
                  shown. Check the compliance_daily job is scheduled and succeeding.
                </AlertDescription>
              </Alert>
            ) : null}
            <p className="freshness">
              Evidence as at <strong>{formatDate(row.as_of_date)}</strong> · coverage refreshed{' '}
              {formatDateTime(row.refreshed_at)} · last evidence collected {formatDateTime(row.last_collected_at)}
              {num(row.sources_not_online) ? ` · ${plural(num(row.sources_not_online)!, 'source')} not online` : ''}
            </p>
            <section className="kpi-grid" aria-label="Summary">
              {kpis.map((kpi) => {
                const active = kpi.status ? filters.status === kpi.status : !filters.status;
                return (
                  <button
                    type="button"
                    key={kpi.label}
                    className={`kpi ${kpi.tone ?? ''} ${active ? 'active' : ''}`}
                    aria-pressed={active}
                    onClick={() =>
                      setFilters({ status: kpi.status && filters.status !== kpi.status ? kpi.status : '' })
                    }
                  >
                    <span className="kpi-label">
                      {kpi.tone && <span className={`dot ${kpi.tone}`} aria-hidden="true" />}
                      {kpi.label}
                    </span>
                    <strong>{kpi.value}</strong>
                    <span className="kpi-detail">{kpi.detail}</span>
                  </button>
                );
              })}
            </section>
          </>
        )}
      </QueryState>

      <section className="two-col">
        <Panel
          id="coverage"
          title="Obligation coverage"
          note="Gaps first. Select an obligation to see its evidence requirements."
          flush
          actions={
            <button
              type="button"
              className="text-button"
              disabled={!rows.length}
              onClick={() => downloadCsv(`obligation-coverage-${row?.as_of_date ?? 'current'}.csv`, rows)}
            >
              Export CSV
            </button>
          }
        >
          <Toolbar summary={obligations.data ? `${rows.length} of ${all.length} obligations` : null}>
            <SearchBox
              value={filters.q}
              onChange={(q) => setFilters({ q })}
              label="Search obligations"
              placeholder="Search by title, ID or owner"
            />
            <FilterSelect
              label="Review gate"
              allLabel="All gates"
              value={filters.gate}
              onChange={(gate) => setFilters({ gate })}
              options={uniqueOptions(
                all,
                (o) => o.gate_id,
                (o) => o.gate_label
              )}
            />
            <FilterSelect
              label="Status"
              allLabel="All statuses"
              value={filters.status}
              onChange={(status) => setFilters({ status })}
              options={['Gap', 'Expiring', 'Complete'].map((s) => ({ value: s, label: s }))}
            />
          </Toolbar>
          <QueryState
            loading={!ready || obligations.loading}
            error={obligations.error}
            empty={!rows.length}
            emptyTitle={all.length ? 'No obligations match these filters' : 'No obligations in the register'}
            emptyAction={
              all.length ? (
                <button
                  type="button"
                  className="text-button"
                  onClick={() => setFilters({ q: '', gate: '', status: '' })}
                >
                  Clear filters
                </button>
              ) : undefined
            }
          >
            <DataTable
              caption="Obligation coverage"
              columns={columns}
              rows={rows}
              rowKey={(item) => item.obligation_id}
              onSelect={(item) => void navigate(`/obligations?id=${item.obligation_id}`)}
              limit={12}
            />
          </QueryState>
        </Panel>

        <div className="side-stack">
          <Panel title="Coverage by gate" note="Obligations by evidence status. Select a gate to filter.">
            <QueryState loading={!ready || gates.loading} error={gates.error} empty={!gates.data?.length} rows={3}>
              <ul className="gate-list">
                {gates.data?.map((gate) => {
                  const complete = num(gate.obligations_complete) ?? 0;
                  const expiring = num(gate.obligations_expiring) ?? 0;
                  const gap = num(gate.obligations_gap) ?? 0;
                  const active = filters.gate === gate.gate_id;
                  return (
                    <li key={gate.gate_id}>
                      <button
                        type="button"
                        className={`gate-row ${active ? 'active' : ''}`}
                        aria-pressed={active}
                        onClick={() => setFilters({ gate: active ? '' : gate.gate_id })}
                      >
                        <span className="gate-head">
                          <span>
                            <strong>{gate.gate_label}</strong> <span className="muted">{gate.gate_name}</span>
                          </span>
                          <code>
                            {complete}/{formatNumber(gate.obligations_total)}
                          </code>
                        </span>
                        <StackedBar
                          complete={complete}
                          expiring={expiring}
                          gap={gap}
                          label={`${gate.gate_label}: ${complete} complete, ${expiring} expiring, ${gap} with gaps`}
                        />
                        <span className="gate-foot">
                          {complete} complete · {expiring} expiring · {gap} {gap === 1 ? 'gap' : 'gaps'}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
              <p className="legend" aria-hidden="true">
                <span className="dot good" /> Complete <span className="dot warn" /> Expiring{' '}
                <span className="dot bad" /> Gap
              </p>
            </QueryState>
          </Panel>

          <Panel
            title="Needs attention"
            note={
              attentionItems.length
                ? `${plural(attentionItems.length, 'open alert')}, most severe first`
                : 'Open gap and expiry alerts'
            }
            flush
          >
            <QueryState
              loading={!ready || attention.loading}
              error={attention.error}
              empty={!attentionItems.length}
              emptyTitle="No open alerts"
              emptyDetail="Every obligation has current, mapped evidence."
              rows={3}
            >
              <ul className="alert-list">
                {attentionItems.slice(0, 6).map((item) => (
                  <li key={item.alert_id}>
                    <Link
                      to={
                        item.evidence_id ? `/evidence?id=${item.evidence_id}` : `/obligations?id=${item.obligation_id}`
                      }
                    >
                      <Status value={item.severity} label={item.severity} />
                      <strong>{item.headline}</strong>
                      <span className="muted">
                        {item.detail}
                        {item.due_date ? ` · due ${formatDate(item.due_date)}` : ''}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
              {attentionItems.length > 6 && (
                <p className="panel-footnote">
                  {attentionItems.length - 6} more. <Link to="/?status=Gap#coverage">Show obligations with gaps</Link>
                </p>
              )}
            </QueryState>
          </Panel>
        </div>
      </section>

      <section className="two-col even">
        <Panel
          title="Requirements met over time"
          note="Share of evidence requirements met at each assessed date, last 180 days."
        >
          <QueryState loading={!ready || trend.loading} error={trend.error} empty={!trend.data?.length} rows={3}>
            <LineChart
              data={(trend.data ?? []).map((point) => ({
                as_of_date: formatShortDate(point.as_of_date),
                coverage_pct: num(point.coverage_pct),
              }))}
              options={{
                grid: { left: 48, right: 16, top: 16, bottom: 32 },
                xAxis: { type: 'category', name: '', boundaryGap: false },
                yAxis: { name: '', min: 0, max: 100 },
              }}
              xKey="as_of_date"
              yKey="coverage_pct"
              height={220}
              colors={['#0B2026']}
              ariaLabel="Line chart of the percentage of evidence requirements met over the last 180 days"
              valueFormatter={(value) => `${value}%`}
            />
          </QueryState>
        </Panel>
        <Panel
          title="Mapping accuracy"
          note="Measured only against the labelled evaluation set. Synthetic titles are cleaner than real documents, so re-measure on real labelled evidence before relying on these figures."
          flush
        >
          <QueryState
            loading={!ready || accuracy.loading}
            error={accuracy.error}
            empty={!accuracy.data?.length}
            emptyTitle="No accuracy figure"
            emptyDetail="Accuracy is reported only when a labelled evaluation set exists."
            rows={3}
          >
            <table className="data-table compact">
              <caption className="sr-only">Mapping accuracy by method</caption>
              <thead>
                <tr>
                  <th scope="col">Method</th>
                  <th scope="col" className="num">
                    Labelled items
                  </th>
                  <th scope="col" className="num">
                    Accuracy
                  </th>
                </tr>
              </thead>
              <tbody>
                {accuracy.data?.map((item) => (
                  <tr key={item.method}>
                    <td>{METHOD_LABELS[item.method] ?? item.method}</td>
                    <td className="num">{formatNumber(item.labelled_items)}</td>
                    <td className="num">{formatPercent(item.accuracy)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="panel-footnote">
              Evaluated {formatDateTime(accuracy.data?.[0]?.evaluated_at)}. AI suggestions never count as coverage until
              a person confirms them.
            </p>
          </QueryState>
        </Panel>
      </section>
    </div>
  );
}

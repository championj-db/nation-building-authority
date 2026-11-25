import { useMemo, useState } from 'react';
import { Link } from 'react-router';
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  RadioGroup,
  RadioGroupItem,
  Textarea,
  useAnalyticsQuery,
} from '@databricks/appkit-ui/react';
import { sql } from '@databricks/appkit-ui/js';
import { ExternalLink, FileCheck2, FileDown, Sparkles } from 'lucide-react';
import {
  api,
  isRunSuccessful,
  useApi,
  useConfig,
  useDocumentTitle,
  useTrackedRun,
  useUrlState,
  type RunSummary,
} from '../lib/api';
import { bool, formatDate, formatDateTime, formatNumber, num, plural, shortHash, today } from '../lib/format';
import type { QueryRow } from '../lib/types';
import {
  CopyValue,
  DataTable,
  DetailPanel,
  Field,
  FilterSelect,
  InlineSpinner,
  PageHeader,
  Panel,
  QueryState,
  Status,
  Toolbar,
  type Column,
} from '../components/common';

type Report = QueryRow<'reports'>;
type Gate = QueryRow<'gate_coverage'>;
type Overview = QueryRow<'overview'>;
interface StatusEvent {
  report_id: string;
  status: string;
  changed_by: string;
  changed_at: string;
  comment: string | null;
}
interface Reproduction {
  reproduction_id: string;
  reproduced_at: string;
  matches: string;
  reproduced_by: string;
}
interface Workflow {
  reports: Record<string, { status: string; history: StatusEvent[]; reproductions: Reproduction[] }>;
}

const TYPE_LABELS: Record<string, string> = {
  monthly_summary: 'Monthly summary',
  gate_review: 'Gate review',
};

export function ReportsPage() {
  useDocumentTitle('Assurance reports');
  const { parameters, ready, refresh, bumpRefresh } = useConfig();
  const reports = useAnalyticsQuery('reports', { ...parameters, refresh: sql.string(refresh) }, { autoStart: ready });
  const gates = useAnalyticsQuery('gate_coverage', parameters, { autoStart: ready });
  const overview = useAnalyticsQuery('overview', parameters, { autoStart: ready });
  const workflow = useApi<Workflow>(ready ? '/api/reports/workflow' : null, [refresh]);
  const [filters, setFilters] = useUrlState({ status: '', type: '', id: '' });
  const tracked = useTrackedRun('report', () => bumpRefresh());

  const all = reports.data ?? [];
  const statusOf = (id: string) => workflow.data?.reports[id]?.status ?? (workflow.loading ? null : 'Draft');
  const rows = all.filter(
    (report) =>
      (!filters.status || statusOf(report.report_id) === filters.status) &&
      (!filters.type || report.report_type === filters.type)
  );
  const selected = all.find((report) => report.report_id === filters.id) ?? null;
  const awaiting = all.filter((report) => statusOf(report.report_id) === 'Ready for approval').length;

  const columns: Column<Report>[] = [
    {
      key: 'report',
      header: 'Report',
      cell: (report) => (
        <span className="cell-stack">
          <strong>{report.title}</strong>
          <small>
            {report.report_id} · v{report.report_version} · {TYPE_LABELS[report.report_type] ?? report.report_type}
          </small>
        </span>
      ),
    },
    { key: 'asof', header: 'Evidence as at', cell: (report) => formatDate(report.as_of_date) },
    {
      key: 'findings',
      header: 'Findings',
      cell: (report) => (
        <span className="cell-stack">
          <span className="nowrap">{plural(num(report.obligations_gap) ?? 0, 'gap')}</span>
          <small className="nowrap">
            {formatNumber(report.obligations_expiring)} expiring · {formatNumber(report.obligations_complete)}/
            {formatNumber(report.obligations_in_scope)} complete
          </small>
        </span>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      cell: (report) => {
        const status = statusOf(report.report_id);
        return status ? <Status value={status} /> : <span className="muted">…</span>;
      },
    },
  ];

  return (
    <div className="page">
      <PageHeader
        title="Assurance reports"
        detail="Reports are generated from point-in-time obligations and evidence, approved by a person, and can be reproduced exactly."
        actions={
          <GenerateReportButton
            variant={selected ? 'outline' : 'primary'}
            onCreated={(runId) => tracked.track(runId)}
            preflight={{ gates: gates.data ?? [], overview: overview.data?.[0] ?? null }}
            busy={Boolean(tracked.runId && !tracked.run?.endedAt)}
          />
        }
      />

      {tracked.runId && <RunBanner run={tracked.run} kind="report" onDismiss={tracked.dismiss} />}
      {awaiting > 0 && !filters.status && (
        <p className="freshness">
          {plural(awaiting, 'report')} awaiting approval.{' '}
          <button type="button" className="text-button" onClick={() => setFilters({ status: 'Ready for approval' })}>
            Show them
          </button>
        </p>
      )}

      <section className="split-detail">
        <Panel
          title="Report queue"
          note="Newest first. Each report preserves the register and evidence versions it used."
          flush
        >
          <Toolbar summary={reports.data ? `${rows.length} of ${all.length} reports` : null}>
            <FilterSelect
              label="Status"
              allLabel="All statuses"
              value={filters.status}
              onChange={(status) => setFilters({ status })}
              options={['Draft', 'Ready for approval', 'Issued'].map((s) => ({ value: s, label: s }))}
            />
            <FilterSelect
              label="Report type"
              allLabel="All report types"
              value={filters.type}
              onChange={(type) => setFilters({ type })}
              options={Object.entries(TYPE_LABELS).map(([value, label]) => ({ value, label }))}
            />
          </Toolbar>
          <QueryState
            loading={!ready || reports.loading}
            error={reports.error ?? workflow.error}
            empty={!rows.length}
            emptyTitle={all.length ? 'No reports match these filters' : 'No reports yet'}
            emptyDetail={
              all.length ? undefined : 'Generate a monthly summary or gate review to create the first draft.'
            }
          >
            <DataTable
              caption="Report queue"
              columns={columns}
              rows={rows}
              rowKey={(report) => report.report_id}
              selectedKey={filters.id}
              onSelect={(report) => setFilters({ id: report.report_id }, { replace: false })}
            />
          </QueryState>
        </Panel>
        <DetailPanel
          open={Boolean(selected)}
          onClose={() => setFilters({ id: '' })}
          title={selected ? `${selected.report_id} · ${selected.title}` : 'Report detail'}
          placeholder={<p>Select a report to review its findings, approve it, download its package or reproduce it.</p>}
        >
          {selected && (
            <ReportDetail
              key={selected.report_id}
              report={selected}
              workflow={workflow.data?.reports[selected.report_id] ?? null}
              onChanged={() => {
                workflow.reload();
              }}
              onReproduce={(runId) => tracked.track(runId)}
            />
          )}
        </DetailPanel>
      </section>
    </div>
  );
}

function ReportDetail({
  report,
  workflow,
  onChanged,
  onReproduce,
}: {
  report: Report;
  workflow: Workflow['reports'][string] | null;
  onChanged: () => void;
  onReproduce: (runId: number) => void;
}) {
  const { config } = useConfig();
  const status = workflow?.status ?? 'Draft';
  const findings = useApi<{ findings: Record<string, string | null>[] }>(`/api/reports/${report.report_id}/findings`);
  const [action, setAction] = useState<null | 'Ready for approval' | 'Issued' | 'Draft'>(null);
  const [comment, setComment] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [findingFilter, setFindingFilter] = useState<'issues' | 'all'>('issues');

  const submitter = [...(workflow?.history ?? [])].reverse().find((e) => e.status === 'Ready for approval')?.changed_by;
  const ownSubmission = Boolean(submitter && config?.user && submitter.toLowerCase() === config.user.toLowerCase());
  const latestReproduction = workflow?.reproductions[0];
  const aiSummary = bool(report.summary_ai_generated);

  async function changeStatus(next: string) {
    setSaving(true);
    setError(null);
    try {
      await api(`/api/reports/${report.report_id}/status`, {
        method: 'POST',
        json: { status: next, comment: comment.trim() || undefined },
      });
      setAction(null);
      setComment('');
      onChanged();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The status was not changed.');
    } finally {
      setSaving(false);
    }
  }

  async function reproduce() {
    setSaving(true);
    setError(null);
    try {
      const { runId } = await api<{ runId: number }>(`/api/reports/${report.report_id}/reproduce`, { method: 'POST' });
      onReproduce(runId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Reproduction could not be started.');
    } finally {
      setSaving(false);
    }
  }

  const allFindings = findings.data?.findings ?? [];
  const shownFindings = findingFilter === 'issues' ? allFindings.filter((f) => f.status !== 'Complete') : allFindings;
  const actionCopy: Record<string, { title: string; button: string; requireComment: boolean; hint: string }> = {
    'Ready for approval': {
      title: 'Submit for approval',
      button: 'Submit for approval',
      requireComment: false,
      hint: 'Another person approves and issues the report.',
    },
    Issued: {
      title: 'Approve and issue',
      button: 'Issue report',
      requireComment: false,
      hint: 'Issuing is final. The report and its evidence snapshot cannot be changed afterwards.',
    },
    Draft: {
      title: 'Return to draft',
      button: 'Return to draft',
      requireComment: true,
      hint: 'Say what needs to change so the preparer can act on it.',
    },
  };

  return (
    <div className="detail">
      <div className="detail-head">
        <div>
          <p className="eyebrow">
            {report.report_id} · version {report.report_version} ·{' '}
            {TYPE_LABELS[report.report_type] ?? report.report_type}
          </p>
          <h2>{report.title}</h2>
        </div>
        <div className="detail-badges">
          <Status value={status} />
        </div>
      </div>

      <dl className="stat-row">
        <div>
          <dt>In scope</dt>
          <dd>{formatNumber(report.obligations_in_scope)}</dd>
        </div>
        <div>
          <dt>Complete</dt>
          <dd>{formatNumber(report.obligations_complete)}</dd>
        </div>
        <div>
          <dt>Expiring</dt>
          <dd>{formatNumber(report.obligations_expiring)}</dd>
        </div>
        <div>
          <dt>Gaps</dt>
          <dd>{formatNumber(report.obligations_gap)}</dd>
        </div>
      </dl>

      <section className="detail-section" aria-labelledby="workflow-title">
        <h3 id="workflow-title">Approval</h3>
        {action ? (
          <form
            className="decision-form"
            onSubmit={(event) => {
              event.preventDefault();
              void changeStatus(action);
            }}
          >
            <p>
              <strong>{actionCopy[action].title}</strong> · {actionCopy[action].hint}
            </p>
            <Label htmlFor="status-comment">
              {actionCopy[action].requireComment ? 'Reason (required)' : 'Comment (optional)'}
            </Label>
            <Textarea
              id="status-comment"
              value={comment}
              maxLength={500}
              onChange={(e) => setComment(e.target.value)}
              required={actionCopy[action].requireComment}
            />
            <div className="inline-actions">
              <Button type="submit" disabled={saving || (actionCopy[action].requireComment && !comment.trim())}>
                {saving ? 'Recording…' : actionCopy[action].button}
              </Button>
              <Button type="button" variant="outline" onClick={() => setAction(null)} disabled={saving}>
                Cancel
              </Button>
            </div>
          </form>
        ) : (
          <div className="inline-actions">
            {status === 'Draft' && <Button onClick={() => setAction('Ready for approval')}>Submit for approval</Button>}
            {status === 'Ready for approval' && (
              <>
                <Button
                  onClick={() => setAction('Issued')}
                  disabled={ownSubmission}
                  title={ownSubmission ? 'You submitted this report. Another person must approve it.' : undefined}
                >
                  Approve and issue
                </Button>
                <Button variant="outline" onClick={() => setAction('Draft')}>
                  Return to draft
                </Button>
              </>
            )}
            {status === 'Issued' && (
              <p className="muted">Issued reports are final. Reproduce one to prove it still matches its evidence.</p>
            )}
          </div>
        )}
        {ownSubmission && status === 'Ready for approval' && !action && (
          <p className="panel-footnote">You submitted this report, so another person must approve and issue it.</p>
        )}
        {error && (
          <Alert variant="destructive" className="inline-alert" role="alert">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {workflow?.history.length ? (
          <ol className="timeline compact">
            {[...workflow.history].reverse().map((event) => (
              <li key={`${event.status}-${event.changed_at}`}>
                <span className="timeline-marker" aria-hidden="true" />
                <div>
                  <p>
                    <Status value={event.status} /> <span className="muted">{formatDateTime(event.changed_at)}</span>
                  </p>
                  <p className="muted">
                    {event.changed_by}
                    {event.comment ? ` · ${event.comment}` : ''}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        ) : null}
      </section>

      <section className="detail-section" aria-labelledby="summary-title">
        <h3 id="summary-title">Executive summary</h3>
        {aiSummary && (
          <p className="ai-label">
            <Sparkles size={14} aria-hidden="true" /> AI-drafted from the findings ({report.model_endpoint}, prompt{' '}
            {report.prompt_version}). Facts only, no ratings. Check it against the findings below.
          </p>
        )}
        <p className="excerpt">{report.executive_summary}</p>
      </section>

      <section className="detail-section" aria-labelledby="findings-title">
        <div className="section-head">
          <h3 id="findings-title">Findings</h3>
          <div className="segmented" role="group" aria-label="Findings shown">
            <button type="button" aria-pressed={findingFilter === 'issues'} onClick={() => setFindingFilter('issues')}>
              Gaps and expiring
            </button>
            <button type="button" aria-pressed={findingFilter === 'all'} onClick={() => setFindingFilter('all')}>
              All {allFindings.length ? `(${allFindings.length})` : ''}
            </button>
          </div>
        </div>
        <QueryState
          loading={findings.loading}
          error={findings.error}
          empty={!shownFindings.length}
          rows={3}
          emptyTitle={
            findingFilter === 'issues' ? 'No gaps or expiring evidence in this report' : 'No findings recorded'
          }
        >
          <ul className="finding-list">
            {shownFindings.map((f) => (
              <li key={`${f.obligation_id}-${f.requirement_id}`}>
                <Status value={f.status} />
                <span className="cell-stack">
                  <span>
                    <Link to={`/obligations?id=${f.obligation_id}`}>{f.obligation_id}</Link> {f.obligation_title} ·{' '}
                    {f.artefact_type}
                  </span>
                  <small>
                    {f.evidence_id
                      ? `${f.evidence_id} v${f.artefact_version} · expires ${formatDate(f.expires_on)}`
                      : (f.gap_reason ?? 'No evidence mapped')}
                  </small>
                </span>
              </li>
            ))}
          </ul>
        </QueryState>
      </section>

      <section className="detail-section" aria-labelledby="package-title">
        <h3 id="package-title">Output package</h3>
        <ul className="file-list">
          <li>
            <a href={`/api/reports/${report.report_id}/files/report.html`} target="_blank" rel="noreferrer">
              <ExternalLink size={14} aria-hidden="true" /> Report (HTML, printable)
            </a>
          </li>
          <li>
            <a href={`/api/reports/${report.report_id}/files/findings.json`} download>
              <FileDown size={14} aria-hidden="true" /> Findings (JSON)
            </a>
          </li>
          <li>
            <a href={`/api/reports/${report.report_id}/files/evidence_manifest.csv`} download>
              <FileDown size={14} aria-hidden="true" /> Evidence manifest (CSV, {formatNumber(report.evidence_items)}{' '}
              items)
            </a>
          </li>
        </ul>
      </section>

      <section className="detail-section" aria-labelledby="repro-title">
        <h3 id="repro-title">Reproducibility</h3>
        <dl className="fields">
          <Field label="Findings digest">
            <CopyValue value={report.findings_digest} display={`${shortHash(report.findings_digest, 16)}…`} />
          </Field>
          <Field label="Register version">{report.register_version_label}</Field>
          <Field label="Evidence snapshot">
            {report.evidence_snapshot_id} · {plural(num(report.evidence_items) ?? 0, 'item')}
          </Field>
          <Field label="Template">{report.template_version}</Field>
          <Field label="Generated">
            {formatDateTime(report.generated_at)} by {report.generated_by}
          </Field>
          <Field label="Last reproduced">
            {latestReproduction ? (
              <>
                <Status
                  value={bool(latestReproduction.matches) ? 'Match' : 'Mismatch'}
                  label={bool(latestReproduction.matches) ? 'Digest matches' : 'Digest differs'}
                />{' '}
                <span className="muted">{formatDateTime(latestReproduction.reproduced_at)}</span>
              </>
            ) : (
              'Not reproduced yet'
            )}
          </Field>
        </dl>
        <div className="inline-actions">
          <Button
            variant="outline"
            onClick={() => void reproduce()}
            disabled={saving || !config?.capabilities.generateReports}
          >
            Reproduce from evidence as at {formatDate(report.as_of_date)}
          </Button>
        </div>
        <p className="panel-footnote">
          Reproduction regenerates the findings from the register and evidence versions that applied on the report date,
          and checks the digest is identical.
        </p>
      </section>
    </div>
  );
}

export function RunBanner({
  run,
  kind,
  onDismiss,
}: {
  run: RunSummary | null;
  kind: 'report' | 'verify';
  onDismiss: () => void;
}) {
  const finished = Boolean(run?.endedAt);
  const ok = isRunSuccessful(run);
  const noun =
    kind === 'verify'
      ? 'Chain verification'
      : run?.params.reproduce_report_id
        ? `Reproduction of ${run.params.reproduce_report_id}`
        : 'Report generation';
  return (
    <Alert
      className={finished ? (ok ? 'info-alert' : '') : 'info-alert'}
      variant={finished && !ok ? 'destructive' : 'default'}
      role="status"
    >
      <FileCheck2 />
      <AlertTitle>
        {!run
          ? `${noun} starting…`
          : !finished
            ? `${noun} is running`
            : ok
              ? `${noun} finished`
              : `${noun} did not complete`}
      </AlertTitle>
      <AlertDescription>
        <p>
          {!finished ? (
            <InlineSpinner
              label={
                run?.startedAt
                  ? `Started ${formatDateTime(run.startedAt)}. This usually takes a few minutes.`
                  : 'Waiting for the job to start.'
              }
            />
          ) : ok ? (
            'The results below have been refreshed.'
          ) : (
            (run?.message ?? 'Open the run to see what failed.')
          )}
        </p>
        <div className="inline-actions">
          {run?.url && (
            <a href={run.url} target="_blank" rel="noreferrer">
              Open the job run <ExternalLink size={12} aria-label="(opens in a new tab)" />
            </a>
          )}
          {finished && (
            <button type="button" className="text-button" onClick={onDismiss}>
              Dismiss
            </button>
          )}
        </div>
      </AlertDescription>
    </Alert>
  );
}

export function GenerateReportButton({
  variant,
  onCreated,
  preflight,
  busy,
}: {
  variant: 'primary' | 'outline';
  onCreated: (runId: number) => void;
  preflight: { gates: Gate[]; overview: Overview | null };
  busy?: boolean;
}) {
  const { config } = useConfig();
  const [open, setOpen] = useState(false);
  const [type, setType] = useState<'monthly_summary' | 'gate_review'>('monthly_summary');
  const [gate, setGate] = useState('');
  const [asOf, setAsOf] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const enabled = Boolean(config?.capabilities.generateReports);

  const scope = useMemo(() => {
    if (type === 'gate_review') {
      const g = preflight.gates.find((item) => item.gate_id === gate);
      return g
        ? {
            gaps: num(g.obligations_gap) ?? 0,
            expiring: num(g.obligations_expiring) ?? 0,
            total: num(g.obligations_total) ?? 0,
          }
        : null;
    }
    const o = preflight.overview;
    return o
      ? {
          gaps: num(o.obligations_gap) ?? 0,
          expiring: num(o.obligations_expiring) ?? 0,
          total: num(o.obligations) ?? 0,
        }
      : null;
  }, [type, gate, preflight]);

  async function create() {
    setSaving(true);
    setError(null);
    try {
      const { runId } = await api<{ runId: number }>('/api/reports/generate', {
        method: 'POST',
        json: { report_type: type, gate_id: type === 'gate_review' ? gate : undefined, as_of_date: asOf || undefined },
      });
      setOpen(false);
      onCreated(runId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Report generation could not be started.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <Button
        variant={variant === 'primary' ? 'default' : 'outline'}
        onClick={() => setOpen(true)}
        disabled={!enabled || busy}
        title={
          !enabled
            ? 'The report job is not bound to this app.'
            : busy
              ? 'A report is already being generated.'
              : undefined
        }
      >
        <FileCheck2 /> Generate report
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Generate assurance report</DialogTitle>
            <DialogDescription>
              Creates a draft from point-in-time obligations and evidence, and preserves the versions used so it can be
              reproduced.
            </DialogDescription>
          </DialogHeader>
          <form
            id="generate-form"
            className="dialog-form"
            onSubmit={(event) => {
              event.preventDefault();
              void create();
            }}
          >
            <fieldset>
              <legend>Report type</legend>
              <RadioGroup value={type} onValueChange={(value) => setType(value as typeof type)}>
                <div className="radio-row">
                  <RadioGroupItem value="monthly_summary" id="type-monthly" />
                  <Label htmlFor="type-monthly">Monthly summary · every obligation in the register</Label>
                </div>
                <div className="radio-row">
                  <RadioGroupItem value="gate_review" id="type-gate" />
                  <Label htmlFor="type-gate">Gate review · obligations for one review gate</Label>
                </div>
              </RadioGroup>
            </fieldset>
            {type === 'gate_review' && (
              <div className="form-row">
                <Label htmlFor="gate">Review gate</Label>
                <FilterSelect
                  label="Review gate"
                  allLabel="Choose a gate"
                  value={gate}
                  onChange={setGate}
                  options={preflight.gates.map((g) => ({
                    value: g.gate_id,
                    label: `${g.gate_label} · ${g.gate_name}`,
                  }))}
                />
              </div>
            )}
            <div className="form-row">
              <Label htmlFor="as-of">Evidence as at</Label>
              <Input
                id="as-of"
                type="date"
                value={asOf}
                max={today()}
                onChange={(e) => setAsOf(e.target.value)}
                aria-describedby="as-of-hint"
              />
              <p id="as-of-hint" className="muted">
                Leave blank for today. A past date uses the register and evidence as they stood on that day.
              </p>
            </div>
            {scope && (
              <div className={`callout ${scope.gaps ? 'warn' : 'good'}`}>
                <strong>Preflight</strong>
                <p>
                  {scope.gaps
                    ? `${plural(scope.gaps, 'obligation')} of ${scope.total} ${scope.gaps === 1 ? 'has' : 'have'} a coverage gap${scope.expiring ? ` and ${scope.expiring} ${scope.expiring === 1 ? 'has' : 'have'} expiring evidence` : ''}. The draft records them as findings; gaps are never hidden.`
                    : `No gaps in scope${scope.expiring ? `; ${plural(scope.expiring, 'obligation')} with expiring evidence` : ''}.`}{' '}
                  Based on coverage as at {formatDate(preflight.overview?.as_of_date)}.
                </p>
              </div>
            )}
            {!scope && type === 'gate_review' && (
              <p className="muted">Choose a gate to see what the draft will report.</p>
            )}
            {error && (
              <Alert variant="destructive" role="alert">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
          </form>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)} disabled={saving}>
              Cancel
            </Button>
            <Button type="submit" form="generate-form" disabled={saving || (type === 'gate_review' && !gate)}>
              {saving ? 'Starting…' : 'Create draft'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

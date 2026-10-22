import { useEffect, useMemo, useState } from 'react';
import { createBrowserRouter, NavLink, Outlet, RouterProvider, useLocation } from 'react-router';
import {
  Alert,
  AlertDescription,
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Empty,
  Input,
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  useAnalyticsQuery,
} from '@databricks/appkit-ui/react';
import { sql } from '@databricks/appkit-ui/js';
import {
  Activity,
  AlertTriangle,
  BarChart3,
  BookOpenCheck,
  CheckCircle2,
  Database,
  FileCheck2,
  FileText,
  Fingerprint,
  Menu,
  Search,
  ShieldCheck,
} from 'lucide-react';

interface RuntimeConfig {
  catalog: string;
  schema: string;
  user: string;
}

function useConfig() {
  const [config, setConfig] = useState<RuntimeConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    fetch('/api/config')
      .then((response) => {
        if (!response.ok) throw new Error('Application configuration is unavailable');
        return response.json() as Promise<RuntimeConfig>;
      })
      .then(setConfig)
      .catch((reason: Error) => setError(reason.message));
  }, []);
  const parameters = useMemo(
    () => ({
      catalog: sql.string(config?.catalog ?? ''),
      schema: sql.string(config?.schema ?? ''),
    }),
    [config]
  );
  return { config, parameters, ready: Boolean(config?.catalog && config?.schema), error };
}

const nav = [
  ['/', 'Overview', BarChart3],
  ['/obligations', 'Obligations', BookOpenCheck],
  ['/evidence', 'Evidence', Database],
  ['/reports', 'Reports', FileText],
  ['/audit', 'Audit trail', Fingerprint],
] as const;

function Shell() {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const current = nav.find(([to]) => to === location.pathname)?.[1] ?? 'Overview';
  const links = (
    <>
      {nav.map(([to, label], index) => (
        <NavLink
          key={to}
          to={to}
          end={to === '/'}
          onClick={() => setOpen(false)}
          className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
        >
          <span>{label}</span>
          <span className="nav-index">0{index + 1}</span>
        </NavLink>
      ))}
    </>
  );
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">NBA</span>
          <strong>Nation Building Authority</strong>
        </div>
        <div className="nav-group">
          <p className="nav-label">Workspace</p>
          <nav>{links}</nav>
        </div>
        <p className="sidebar-note">
          Wireframe data is synthetic. This product supports assurance workflows; it does not interpret regulation.
        </p>
      </aside>
      <div className="main-column">
        <header className="topbar">
          <Sheet open={open} onOpenChange={setOpen}>
            <Button className="mobile-menu" variant="ghost" size="icon" onClick={() => setOpen(true)}>
              <Menu />
              <span className="sr-only">Open navigation</span>
            </Button>
            <SheetContent side="left">
              <SheetHeader>
                <SheetTitle>NBA Assurance</SheetTitle>
              </SheetHeader>
              <nav className="mobile-nav">{links}</nav>
            </SheetContent>
          </Sheet>
          <div className="breadcrumbs">
            Nation Building Authority / <strong>{current}</strong>
          </div>
          <div className="top-actions">
            <Button className="export-button" variant="outline">
              Export register
            </Button>
            <NavLink to="/reports">
              <Button className="generate-button">Generate report</Button>
            </NavLink>
          </div>
        </header>
        <main>
          <Outlet />
        </main>
      </div>
    </div>
  );
}

function PageTitle({
  eyebrow,
  title,
  detail,
  action,
}: {
  eyebrow: string;
  title: string;
  detail: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="page-title">
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        <p>{detail}</p>
      </div>
      {action}
    </div>
  );
}

function QueryState({
  loading,
  error,
  empty,
  children,
}: {
  loading: boolean;
  error: string | null;
  empty: boolean;
  children: React.ReactNode;
}) {
  if (loading)
    return (
      <div className="skeleton-stack">
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="h-28 w-full" />
      </div>
    );
  if (error)
    return (
      <Alert variant="destructive">
        <AlertTriangle />
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  if (empty)
    return (
      <Empty>
        <FileText />
        <h3>No records available</h3>
        <p>Run the compliance pipeline to populate this view.</p>
      </Empty>
    );
  return <>{children}</>;
}

function StatusBadge({ value }: { value: string }) {
  const tone = /complete|online|verified|approved|mapped/i.test(value)
    ? 'good'
    : /gap|offline|failed|high/i.test(value)
      ? 'bad'
      : /expir|review|degraded|draft/i.test(value)
        ? 'warn'
        : 'neutral';
  return <span className={`status ${tone}`}>{value}</span>;
}

function OverviewPage() {
  const { config, parameters, ready, error: configError } = useConfig();
  const overview = useAnalyticsQuery('overview', parameters, { autoStart: ready });
  const gates = useAnalyticsQuery('gate_coverage', parameters, { autoStart: ready });
  const attention = useAnalyticsQuery('attention', parameters, { autoStart: ready });
  const obligations = useAnalyticsQuery('overview_obligations', parameters, { autoStart: ready });
  const row = overview.data?.[0];
  return (
    <div className="page">
      <PageTitle
        eyebrow=""
        title="Compliance assurance"
        detail="Track Nation Building Authority evidence coverage before gaps become reporting blockers."
      />
      <QueryState loading={!ready || overview.loading} error={configError ?? overview.error} empty={!row}>
        {row && (
          <>
            <div className="freshness">
              <Activity size={15} /> Evidence as at {row.as_of_date} · refreshed{' '}
              {new Date(row.refreshed_at).toLocaleString()} · source {config?.catalog}.{config?.schema}
            </div>
            <section className="kpi-grid">
              <Kpi
                label="Obligations"
                value={row.obligations}
                detail={`${row.requirements_total} evidence requirements`}
                tone="teal"
              />
              <Kpi
                label="Covered"
                value={row.obligations_complete}
                detail={`${row.evidence_coverage_pct}% evidence coverage`}
                tone="navy"
              />
              <Kpi
                label="Expiring soon"
                value={row.obligations_expiring}
                detail={`Within ${row.expiry_warning_days} days`}
                tone="amber"
              />
              <Kpi
                label="Open gaps"
                value={row.obligations_gap}
                detail={`${row.open_high_alerts} high-priority alerts`}
                tone="red"
              />
            </section>
          </>
        )}
      </QueryState>
      <section className="coverage-layout">
        <Card className="panel coverage-table-panel">
          <CardHeader>
            <div>
              <CardTitle>Obligation coverage</CardTitle>
              <p className="card-note">Select a row to inspect its latest evidence mapping.</p>
            </div>
            <Input className="panel-search" placeholder="Search obligations" aria-label="Search obligations" />
          </CardHeader>
          <CardContent>
            <QueryState loading={obligations.loading} error={obligations.error} empty={!obligations.data?.length}>
              <DataTable
                headers={['Obligation', 'Gate', 'Owner', 'Evidence', 'Status', 'Review date']}
                rows={(obligations.data ?? []).map((item) => [
                  <span key="obligation">
                    <strong>{item.obligation_title}</strong>
                    <small>{item.obligation_id}</small>
                  </span>,
                  item.gate_id,
                  item.owner_role,
                  `${item.evidence_mapped} mapped`,
                  <StatusBadge key="status" value={item.status} />,
                  item.review_date ?? 'Not set',
                ])}
              />
            </QueryState>
          </CardContent>
        </Card>
        <div className="side-stack">
          <Card className="panel coverage-panel">
            <CardHeader>
              <CardTitle>Coverage by gate</CardTitle>
              <p className="card-note">Current evidence status</p>
            </CardHeader>
            <CardContent>
              <QueryState loading={gates.loading} error={gates.error} empty={!gates.data?.length}>
                <div className="coverage-bars">
                  {gates.data?.map((gate, index) => (
                    <div key={gate.gate_id} className={`bar-row series-${(index % 3) + 1}`}>
                      <div>
                        <span>{gate.gate_label}</span>
                        <code>
                          {gate.obligations_complete} / {gate.obligations_total}
                        </code>
                      </div>
                      <div className="bar">
                        <span style={{ width: `${gate.coverage_pct}%` }} />
                      </div>
                    </div>
                  ))}
                </div>
              </QueryState>
            </CardContent>
          </Card>
          <Card className="panel attention-panel">
            <CardHeader>
              <CardTitle>Needs attention</CardTitle>
              <p className="card-note">Missing or time-sensitive evidence</p>
            </CardHeader>
            <CardContent>
              <QueryState loading={attention.loading} error={attention.error} empty={!attention.data?.length}>
                <div className="wire-alerts">
                  {attention.data?.slice(0, 5).map((item) => (
                    <div key={item.alert_id}>
                      <strong>{item.headline}</strong>
                      <p>
                        {item.obligation_id} · {item.due_date ?? 'No due date'}
                      </p>
                    </div>
                  ))}
                </div>
              </QueryState>
            </CardContent>
          </Card>
        </div>
      </section>
    </div>
  );
}

function Kpi({ label, value, detail, tone }: { label: string; value: string | number; detail: string; tone: string }) {
  return (
    <Card className={`kpi ${tone}`}>
      <CardContent>
        <span>{label}</span>
        <strong>{value}</strong>
        <p>{detail}</p>
      </CardContent>
    </Card>
  );
}

function ObligationsPage() {
  const { parameters, ready, error: configError } = useConfig();
  const query = useAnalyticsQuery('obligations', parameters, { autoStart: ready });
  const [search, setSearch] = useState('');
  const rows =
    query.data?.filter((row) =>
      `${row.obligation_id} ${row.title} ${row.framework}`.toLowerCase().includes(search.toLowerCase())
    ) ?? [];
  const selected = rows[0];
  return (
    <div className="page">
      <PageTitle
        eyebrow="Governed register"
        title="Obligation register"
        detail="Govern versioned obligations, evidence requirements, ownership, and review gates."
      />
      <section className="split-detail">
        <Card className="panel detail-table-panel">
          <CardHeader>
            <div>
              <CardTitle>Register entries</CardTitle>
              <p className="card-note">Current governed obligation register.</p>
            </div>
            <div className="toolbar">
              <Search size={17} />
              <Input
                aria-label="Search obligations"
                placeholder="Search register"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </div>
          </CardHeader>
          <CardContent>
            <QueryState loading={!ready || query.loading} error={configError ?? query.error} empty={!rows.length}>
              <DataTable
                headers={['Obligation', 'Gate', 'Framework', 'Owner', 'Requirements', 'State']}
                rows={rows.map((row) => [
                  <span key="obligation">
                    <strong>{row.obligation_id}</strong>
                    <small>{row.title}</small>
                  </span>,
                  row.gate_label,
                  row.framework,
                  row.owner_role,
                  row.requirement_count,
                  <StatusBadge key="state" value={row.register_state} />,
                ])}
              />
            </QueryState>
          </CardContent>
        </Card>
        <Card className="panel detail-panel">
          <CardHeader>
            <div>
              <CardTitle>{selected?.obligation_id ?? 'Obligation detail'}</CardTitle>
              <p className="card-note">Current version · effective {selected?.effective_from ?? '—'}</p>
            </div>
            {selected && <Badge variant="outline">{selected.gate_label}</Badge>}
          </CardHeader>
          <CardContent>
            {selected ? (
              <div className="detail-body">
                <div>
                  <span className="detail-label">Obligation</span>
                  <p>{selected.title}</p>
                </div>
                <div>
                  <span className="detail-label">Framework</span>
                  <p>{selected.framework}</p>
                </div>
                <div>
                  <span className="detail-label">Owner</span>
                  <p>{selected.owner_role}</p>
                </div>
                <div>
                  <span className="detail-label">Evidence requirements</span>
                  <p>{selected.requirement_count} required artefact types</p>
                </div>
                <div className="inline-actions">
                  <Button variant="outline">View history</Button>
                  <Button variant="outline">Propose revision</Button>
                </div>
              </div>
            ) : (
              <p className="card-note">Select an obligation to inspect its requirements.</p>
            )}
          </CardContent>
        </Card>
      </section>
    </div>
  );
}

function EvidencePage() {
  const { parameters, ready, error: configError } = useConfig();
  const evidence = useAnalyticsQuery('evidence', parameters, { autoStart: ready });
  const sources = useAnalyticsQuery('sources', parameters, { autoStart: ready });
  const [search, setSearch] = useState('');
  const rows =
    evidence.data?.filter((row) =>
      `${row.evidence_id} ${row.title} ${row.source_name}`.toLowerCase().includes(search.toLowerCase())
    ) ?? [];
  const selected = rows[0];
  return (
    <div className="page">
      <PageTitle
        eyebrow="Evidence operations"
        title="Evidence mapping"
        detail="Review collected artefacts, confirm obligation links, and resolve freshness gaps."
      />
      <div className="source-strip">
        {sources.data?.map((source) => (
          <div key={source.source_id}>
            <StatusBadge value={source.health} />
            <span>{source.source_name}</span>
            <small>{source.records_last_30d} records / 30d</small>
          </div>
        ))}
      </div>
      <section className="split-detail">
        <Card className="panel detail-table-panel">
          <CardHeader>
            <div>
              <CardTitle>Evidence inbox</CardTitle>
              <p className="card-note">Automated collections awaiting validation or mapping.</p>
            </div>
            <div className="toolbar">
              <Search size={17} />
              <Input
                aria-label="Search evidence"
                placeholder="Search evidence"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </div>
          </CardHeader>
          <CardContent>
            <QueryState loading={!ready || evidence.loading} error={configError ?? evidence.error} empty={!rows.length}>
              <DataTable
                headers={['Evidence', 'Source', 'Type', 'Mapping', 'Freshness', 'Integrity']}
                rows={rows.map((row) => [
                  <span key="evidence">
                    <strong>{row.evidence_id}</strong>
                    <small>{row.title}</small>
                  </span>,
                  row.source_name,
                  row.artefact_type ?? row.file_format,
                  <StatusBadge key="mapping" value={row.mapping_state} />,
                  <StatusBadge key="freshness" value={row.freshness_status} />,
                  row.integrity_verified ? (
                    <CheckCircle2 className="icon-good" size={18} />
                  ) : (
                    <AlertTriangle className="icon-bad" size={18} />
                  ),
                ])}
              />
            </QueryState>
          </CardContent>
        </Card>
        <Card className="panel detail-panel">
          <CardHeader>
            <div>
              <CardTitle>Mapping review</CardTitle>
              <p className="card-note">
                {selected ? `${selected.evidence_id} · ${selected.title}` : 'Select an artefact'}
              </p>
            </div>
            {selected && <StatusBadge value={selected.freshness_status} />}
          </CardHeader>
          <CardContent>
            {selected ? (
              <div className="detail-body">
                <div>
                  <span className="detail-label">Suggested mapping</span>
                  <p>
                    <strong>{selected.mapping_state}</strong> · {selected.artefact_type ?? selected.file_format}
                  </p>
                </div>
                <div>
                  <span className="detail-label">Provenance</span>
                  <p>
                    {selected.source_name} · collected {new Date(selected.collected_at).toLocaleDateString()}
                  </p>
                </div>
                <div>
                  <span className="detail-label">Integrity</span>
                  <p>{selected.integrity_verified ? 'Checksum verified' : 'Integrity check required'}</p>
                </div>
                <div className="notice">
                  Evidence expires {selected.expires_on ?? 'on its configured freshness threshold'}.
                </div>
                <div className="inline-actions">
                  <Button>Confirm mapping</Button>
                  <Button variant="outline">Request replacement</Button>
                </div>
              </div>
            ) : (
              <p className="card-note">Select evidence to review its mapping.</p>
            )}
          </CardContent>
        </Card>
      </section>
    </div>
  );
}

function ReportsPage() {
  const { config, parameters, ready, error: configError } = useConfig();
  const query = useAnalyticsQuery('reports', parameters, { autoStart: ready });
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState('');
  async function generate() {
    setRunning(true);
    setMessage('');
    try {
      const response = await fetch('/api/jobs/default/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ report_type: 'monthly_summary', requested_by: config?.user ?? 'app.user' }),
      });
      if (!response.ok) throw new Error(await response.text());
      setMessage('Report generation started. Refresh after the run completes.');
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : 'Unable to start report');
    } finally {
      setRunning(false);
    }
  }
  return (
    <div className="page">
      <PageTitle
        eyebrow="Reproducible outputs"
        title="Assurance reports"
        detail="Generate, review, approve, and reproduce reports from point-in-time evidence."
        action={
          <Button onClick={() => void generate()} disabled={running}>
            <FileCheck2 size={16} />
            {running ? 'Starting…' : 'Generate report'}
          </Button>
        }
      />
      {message && (
        <Alert>
          <AlertDescription>{message}</AlertDescription>
        </Alert>
      )}
      <section className="reports-layout">
        <div className="report-grid">
          <QueryState loading={!ready || query.loading} error={configError ?? query.error} empty={!query.data?.length}>
            {query.data?.map((report) => (
              <Card key={report.report_id} className="report-card">
                <CardHeader>
                  <div>
                    <Badge variant="outline">
                      {report.report_id} · v{report.report_version}
                    </Badge>
                    <span>{report.as_of_date}</span>
                  </div>
                  <CardTitle>{report.title}</CardTitle>
                </CardHeader>
                <CardContent>
                  <p>{report.executive_summary}</p>
                  <div className="report-stats">
                    <span>
                      <b>{report.obligations_complete}</b> complete
                    </span>
                    <span>
                      <b>{report.obligations_gap}</b> gaps
                    </span>
                    <span>
                      <b>{report.evidence_items}</b> evidence
                    </span>
                  </div>
                  <small>
                    {report.summary_ai_generated
                      ? 'AI-drafted summary · verify against deterministic findings'
                      : 'Deterministic summary'}{' '}
                    · digest {report.findings_digest.slice(0, 12)}
                  </small>
                </CardContent>
              </Card>
            ))}
          </QueryState>
        </div>
        <div className="side-stack">
          <Card className="panel">
            <CardHeader>
              <CardTitle>Generation preflight</CardTitle>
              <p className="card-note">Latest assurance package</p>
            </CardHeader>
            <CardContent>
              <div className="checklist">
                <div>
                  <CheckCircle2 />
                  <span>
                    <strong>Register version locked</strong>
                    <small>Point-in-time obligations retained</small>
                  </span>
                </div>
                <div>
                  <CheckCircle2 />
                  <span>
                    <strong>Evidence snapshot created</strong>
                    <small>Versions and checksums preserved</small>
                  </span>
                </div>
                <div>
                  <AlertTriangle />
                  <span>
                    <strong>Coverage gaps retained</strong>
                    <small>Blockers remain visible in findings</small>
                  </span>
                </div>
              </div>
            </CardContent>
          </Card>
          <Card className="panel">
            <CardHeader>
              <CardTitle>Output package</CardTitle>
              <p className="card-note">Generated together for traceability</p>
            </CardHeader>
            <CardContent>
              <div className="output-list">
                <span>
                  Human-readable report <strong>HTML</strong>
                </span>
                <span>
                  Machine-readable findings <strong>JSON</strong>
                </span>
                <span>
                  Evidence manifest <strong>CSV</strong>
                </span>
              </div>
            </CardContent>
          </Card>
        </div>
      </section>
    </div>
  );
}

function AuditPage() {
  const { parameters, ready, error: configError } = useConfig();
  const query = useAnalyticsQuery('audit', parameters, { autoStart: ready });
  const head = query.data?.[0];
  return (
    <div className="page">
      <PageTitle
        eyebrow="Immutable provenance"
        title="Audit trail"
        detail="Hash-chained events connect every report to its register version, evidence and actor."
      />
      <QueryState loading={!ready || query.loading} error={configError ?? query.error} empty={!head}>
        {head && (
          <Card className="verification">
            <CardContent>
              <ShieldCheck size={28} />
              <div>
                <span>Chain verification</span>
                <strong>{head.chain_status}</strong>
                <p>
                  {head.events_checked} events checked · head #{head.head_seq} · verified{' '}
                  {new Date(head.verified_at).toLocaleString()}
                </p>
              </div>
              <StatusBadge value={head.chain_status} />
            </CardContent>
          </Card>
        )}
      </QueryState>
      <Card>
        <CardContent>
          <QueryState loading={query.loading} error={query.error} empty={!query.data?.length}>
            <DataTable
              headers={['Sequence', 'Event', 'Entity', 'Summary', 'Actor', 'Occurred', 'Hash']}
              rows={(query.data ?? []).map((row) => [
                row.event_seq,
                row.event_type,
                row.entity_id,
                row.summary,
                row.actor,
                new Date(row.occurred_at).toLocaleString(),
                <code key="hash">{row.event_hash.slice(0, 10)}…</code>,
              ])}
            />
          </QueryState>
        </CardContent>
      </Card>
    </div>
  );
}

function DataTable({ headers, rows }: { headers: string[]; rows: React.ReactNode[][] }) {
  return (
    <div className="table-wrap">
      <Table>
        <TableHeader>
          <TableRow>
            {headers.map((header) => (
              <TableHead key={header}>{header}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => (
            <TableRow key={index}>
              {row.map((cell, cellIndex) => (
                <TableCell key={cellIndex}>{cell}</TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

const router = createBrowserRouter([
  {
    element: <Shell />,
    children: [
      { path: '/', element: <OverviewPage /> },
      { path: '/obligations', element: <ObligationsPage /> },
      { path: '/evidence', element: <EvidencePage /> },
      { path: '/reports', element: <ReportsPage /> },
      { path: '/audit', element: <AuditPage /> },
    ],
  },
]);

export default function App() {
  return <RouterProvider router={router} />;
}

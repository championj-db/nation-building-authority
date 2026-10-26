import { createBrowserRouter, NavLink, Outlet, RouterProvider, useNavigate } from 'react-router';
import { useEffect, useMemo, useState } from 'react';
import {
  Alert, AlertDescription, Badge, BarChart, Button, Card, CardContent, CardHeader, CardTitle,
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
  Empty, EmptyDescription, EmptyHeader, EmptyTitle, GenieChat, Input, Label, Sheet,
  SheetContent, SheetHeader, SheetTitle, Skeleton, Table, TableBody, TableCell,
  TableHead, TableHeader, TableRow, Tabs, TabsContent, TabsList, TabsTrigger, Textarea,
  useAnalyticsQuery,
} from '@databricks/appkit-ui/react';
import { Bot, LockKeyhole, Menu, Search, ShieldCheck, X } from 'lucide-react';
import type { QueryRegistry } from '@databricks/appkit-ui/react';

type WhoAmI = { email: string | null; authenticated: boolean };
type CaseSelection = { caseId: string; constituentId: string; purpose: string; name: string };
type ActionKind = 'Add case note' | 'Assign case owner' | 'Update case status' | 'Correct contact details' | 'Record consent change';
type QueryKey = keyof QueryRegistry;
type QueryResult<K extends QueryKey> = QueryRegistry[K]['result'];
type AnalyticsResult<K extends QueryKey> = { data: QueryResult<K> | null; loading: boolean; error: string | null };

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, headers: { 'Content-Type': 'application/json', ...init?.headers } });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ error: 'Request failed' })) as { error?: string };
    throw new Error(body.error ?? 'Request failed');
  }
  return response.status === 204 ? undefined as T : response.json() as Promise<T>;
}

function QueryState({ loading, error, empty, children }: { loading: boolean; error: string | null; empty: boolean; children: React.ReactNode }) {
  if (loading) return <div className="state"><Skeleton className="h-5 w-2/3"/><Skeleton className="h-16 w-full"/><Skeleton className="h-16 w-full"/></div>;
  if (error) return <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>;
  if (empty) return <Empty><EmptyHeader><EmptyTitle>No permitted records</EmptyTitle><EmptyDescription>No data is available for your current identity, purpose, and access scope.</EmptyDescription></EmptyHeader></Empty>;
  return children;
}

const workspaceNav = [['/', 'Overview'], ['/constituents', 'Constituents'], ['/interactions', 'Interactions'], ['/insights', 'Service insights']] as const;
const governanceNav = [['/consent', 'Consent & access'], ['/lineage', 'Data lineage']] as const;

function Layout() {
  const [mobile, setMobile] = useState(false);
  const [policy, setPolicy] = useState(false);
  const [identity, setIdentity] = useState<WhoAmI>({ email: null, authenticated: false });
  useEffect(() => { void api<WhoAmI>('/api/whoami').then(setIdentity).catch(() => undefined); }, []);
  const links = <>{[['Workspace', workspaceNav], ['Governance', governanceNav]].map(([group, items]) => <nav className="nav" key={group as string}><span className="nav-label">{group as string}</span>{(items as typeof workspaceNav).map(([to,label]) => <NavLink key={to} to={to} end={to === '/'} onClick={() => setMobile(false)}>{label}</NavLink>)}</nav>)}</>;
  return <div className="app-shell">
    <aside className="sidebar"><div className="brand"><span className="mark">NBA</span><span>Nation Building Authority<small>Constituent intelligence</small></span></div>{links}<div className="security"><LockKeyhole size={16}/><span><strong>Protected · OFFICIAL</strong><small>Unity Catalog policies apply to every field shown.</small></span></div></aside>
    <main><header className="topbar"><Button aria-label="Open navigation" className="mobile-menu" variant="ghost" size="icon" onClick={() => setMobile(true)}><Menu/></Button><span className="crumb">Citizen services / <strong>Constituent 360</strong></span><div className="user"><Button variant="outline" onClick={() => setPolicy(true)}>View access policy</Button><span className="avatar">{identity.email?.slice(0,2).toUpperCase() ?? 'JC'}</span><span><strong>{identity.email?.split('@')[0].replace('.', ' ') ?? 'Signed-in officer'}</strong><small>{identity.authenticated ? 'OBO identity verified' : 'Identity pending'}</small></span></div></header><Outlet/></main>
    <Sheet open={mobile} onOpenChange={setMobile}><SheetContent side="left"><SheetHeader><SheetTitle>Constituent 360</SheetTitle></SheetHeader>{links}</SheetContent></Sheet>
    <Dialog open={policy} onOpenChange={setPolicy}><DialogContent><DialogHeader><DialogTitle>Purpose-based access policy</DialogTitle><DialogDescription>Every protected query runs on behalf of your signed-in Databricks identity. Row filters, masks, consent and purpose-of-use policies are evaluated in Unity Catalog.</DialogDescription></DialogHeader><Alert><ShieldCheck/><AlertDescription>Access is minimum-necessary, audited, and expires with the active purpose session.</AlertDescription></Alert></DialogContent></Dialog>
  </div>;
}

function PageHeading({ eyebrow, title, children, action }: { eyebrow: string; title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return <section className="page-heading"><div><p>{eyebrow}</p><h1>{title}</h1><span>{children}</span></div>{action}</section>;
}

function Overview() {
  const queue = useAnalyticsQuery('priority_queue', {});
  const kpis = useAnalyticsQuery('service_kpis', {});
  const profile = useAnalyticsQuery('constituent_profile', {});
  const journey = useAnalyticsQuery('journey', {});
  const signals = useAnalyticsQuery('need_signals', {});
  const graph = useAnalyticsQuery('identity_graph', {});
  const audit = useAnalyticsQuery('access_audit', {});
  const scope = useAnalyticsQuery('access_scope', {});
  const [selected, setSelected] = useState<CaseSelection | null>(() => {
    const saved = sessionStorage.getItem('c360:selected-case');
    return saved ? JSON.parse(saved) as CaseSelection : null;
  });
  const [search, setSearch] = useState('');
  const [assistant, setAssistant] = useState(false);
  const [action, setAction] = useState<ActionKind | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const filtered = useMemo(() => (queue.data ?? []).filter(row => `${row.display_name} ${row.case_id} ${row.service_type}`.toLowerCase().includes(search.toLowerCase())), [queue.data, search]);
  const selectedRow = (queue.data ?? []).find(row => row.case_id === selected?.caseId);
  const openCase = async (row: NonNullable<typeof queue.data>[number]) => {
    try {
      setSessionError(null);
      await api('/api/access-sessions', { method: 'POST', body: JSON.stringify({ purpose: row.case_purpose, caseId: row.case_id, constituentId: row.constituent_id, justification: 'Case workbench review and constituent support' }) });
      const selection = { caseId: row.case_id ?? '', constituentId: row.constituent_id ?? '', purpose: row.case_purpose ?? '', name: row.display_name ?? 'Constituent' } satisfies CaseSelection;
      sessionStorage.setItem('c360:selected-case', JSON.stringify(selection));
      setSelected(selection);
      window.location.reload();
    } catch (error) { setSessionError(error instanceof Error ? error.message : 'Could not start a purpose session'); }
  };
  useEffect(() => {
    const row = queue.data?.find(item => item.display_name === 'Amara Okafor') ?? queue.data?.[0];
    if (!selected && row) {
      void api('/api/access-sessions', { method: 'POST', body: JSON.stringify({ purpose: row.case_purpose, caseId: row.case_id, constituentId: row.constituent_id, justification: 'Default case workbench review and constituent support' }) })
        .then(() => {
          sessionStorage.setItem('c360:selected-case', JSON.stringify({ caseId: row.case_id ?? '', constituentId: row.constituent_id ?? '', purpose: row.case_purpose ?? '', name: row.display_name ?? 'Constituent' } satisfies CaseSelection));
          window.location.reload();
        })
        .catch(error => setSessionError(error instanceof Error ? error.message : 'Could not start a purpose session'));
    }
  }, [queue.data, selected]);
  const metric = kpis.data?.[0];
  const pct = (value: number | null | undefined) => value == null ? '—' : `${(value * 100).toFixed(1)}%`;
  return <div className="page"><PageHeading eyebrow="Operations overview" title="Constituent service overview" action={<span className="freshness">Live governed data · refreshed {metric?.snapshot_date ?? 'pending'}</span>}>Review active cases, cross-channel interactions, identity resolution and purpose-based access controls.</PageHeading>
    {sessionError && <Alert variant="destructive"><AlertDescription>{sessionError}</AlertDescription></Alert>}
    <section className="kpis">
      {[['Open service journeys', metric?.open_journeys ?? '—', `${metric?.opened_today ?? '—'} opened today`], ['Repeat contact within 7 days', pct(metric?.repeat_contact_7d_rate), `Target ${pct(metric?.repeat_contact_target)}`], ['High-need cases awaiting action', metric?.high_need_awaiting ?? '—', `${metric?.high_need_consent_restricted ?? '—'} consent-restricted`], ['Resolved identity confidence', pct(metric?.identity_confidence), `${metric?.multi_source_constituents ?? '—'} multi-source constituents`]].map(([label,value,meta]) => <Card key={label}><CardContent className="kpi"><span>{label}</span><strong>{value}</strong><small>{meta} · refreshed {metric?.snapshot_date ?? 'pending'}</small></CardContent></Card>)}
    </section>
    <section className="workbench">
      <Card className="queue"><CardHeader><div className="queue-title"><span><CardTitle>Priority queue</CardTitle><small>Needs attention · governed</small></span><Badge variant="outline">{filtered.length} cases</Badge></div><div className="search"><Search size={16}/><Input aria-label="Search cases" placeholder="Search name or case" value={search} onChange={event => setSearch(event.target.value)}/></div></CardHeader><CardContent><QueryState loading={queue.loading} error={queue.error} empty={!filtered.length}>{filtered.map(row => <button className={`case-row ${selected?.caseId === row.case_id ? 'active' : ''}`} key={row.case_id ?? ''} onClick={() => void openCase(row)}><span className="initial">{row.initials}</span><span><strong>{row.display_name}</strong><small>{row.service_type} · {row.recommended_action}</small></span><Badge variant="outline">{row.priority_band}</Badge></button>)}</QueryState></CardContent></Card>
      <Card className="profile"><QueryState loading={profile.loading} error={profile.error} empty={!selected}>{selected && profile.data?.[0] ? <Profile profile={profile.data[0]} journey={journey} signals={signals} graph={graph} audit={audit} onAction={setAction}/> : selectedRow ? <ProfileFallback row={selectedRow} journey={journey} onAction={setAction}/> : <Empty><EmptyHeader><EmptyTitle>Select a case</EmptyTitle><EmptyDescription>Opening a case starts an audited purpose-of-use session.</EmptyDescription></EmptyHeader></Empty>}</QueryState></Card>
      <aside className="rail"><Card><CardHeader><div className="rail-heading"><span><CardTitle>Needs & signals</CardTitle><small>Databricks AI Functions</small></span><Badge variant="outline">Explain</Badge></div></CardHeader><CardContent><QueryState loading={signals.loading} error={signals.error} empty={!signals.data?.length}><div className="signal-summary"><strong>{signals.data?.[0]?.need_label ?? 'Permitted need signal'}</strong><p>{signals.data?.[0]?.evidence_count ?? 0} evidence items · urgency {signals.data?.[0]?.avg_urgency ?? '—'}</p>{signals.data?.slice(0,2).map(item => <div className="rail-row" key={item.need_code ?? item.need_label}><span>{item.need_label}</span><strong>{item.avg_urgency}</strong></div>)}</div></QueryState></CardContent></Card><Card><CardHeader><div className="rail-heading"><span><CardTitle>Current access scope</CardTitle><small>{selected ? `Purpose: ${selected.purpose}` : 'No active purpose'}</small></span><Badge variant={selected ? 'default' : 'outline'}>{selected ? 'Policy passed' : 'No session'}</Badge></div></CardHeader><CardContent>{(scope.data ?? []).slice(0,3).map(item => <div className="access-row" key={item.data_domain ?? item.domain_name}><strong>{item.visible ? '✓' : '—'} {item.domain_name}</strong><small>{item.visible ? 'Visible' : 'Restricted'} · {item.reason}</small></div>)}</CardContent></Card><Card className="assistant-card"><CardHeader><CardTitle><Bot size={18}/> Case briefing assistant</CardTitle><small>Permitted records only</small></CardHeader><CardContent>{['What changed since the last contact?','Draft a plain-language callback brief','Why is this case marked urgent?'].map(prompt => <Button className="prompt-button" key={prompt} variant="outline" onClick={() => setAssistant(true)} disabled={!selected}>{prompt}</Button>)}<p>AI-generated answers show sources, SQL and execution identity.</p></CardContent></Card></aside>
    </section>
    <ActionDialog action={action} onClose={() => setAction(null)} onSuccess={setNotice}/>
    <Sheet open={assistant} onOpenChange={setAssistant}><SheetContent className="assistant-sheet"><SheetHeader><SheetTitle>Constituent 360 Case Assistant</SheetTitle></SheetHeader><div className="trust"><Badge>Signed in</Badge><span>Runs OBO as the current user · AI-generated — verify against source records.</span></div><div className="chat"><GenieChat alias="constituent360" placeholder="Ask for a case briefing or unresolved actions…"/></div></SheetContent></Sheet>
    {notice && <div className="toast" role="status">{notice}<button onClick={() => setNotice(null)}><X size={15}/></button></div>}
  </div>;
}

function Profile({ profile, journey, signals, graph, audit, onAction }: { profile: QueryResult<'constituent_profile'>[number]; journey: AnalyticsResult<'journey'>; signals: AnalyticsResult<'need_signals'>; graph: AnalyticsResult<'identity_graph'>; audit: AnalyticsResult<'access_audit'>; onAction: (action: ActionKind) => void }) {
  const actions: Array<[string, ActionKind]> = [['Add note','Add case note'],['Assign case','Assign case owner'],['Update status','Update case status'],['Edit details','Correct contact details']];
  const openServices = Array.isArray(profile.open_services) ? profile.open_services.map(String).join(', ') : String(profile.open_services ?? 'Restricted');
  return <><CardHeader className="profile-head"><div className="person"><span className="avatar large">{profile.initials}</span><div><CardTitle>{profile.display_name}</CardTitle><small>Synthetic constituent · {profile.constituent_id}</small></div><Badge>Identity resolved · {(Number(profile.identity_confidence) * 100).toFixed(1)}%</Badge></div><div className="actions">{actions.map(([label,action]) => <Button key={action} variant="outline" size="sm" onClick={() => onAction(action)}>{label}</Button>)}</div><div className="facts"><span><small>Preferred channel</small><strong>{profile.last_channel ?? 'Masked'}</strong></span><span><small>Primary intent</small><strong>{openServices}</strong></span><span><small>Current sentiment</small><strong>{profile.latest_sentiment ?? 'Masked'}</strong></span></div></CardHeader><CardContent><Tabs defaultValue="journey"><TabsList><TabsTrigger value="journey">Journey</TabsTrigger><TabsTrigger value="signals">Needs & signals</TabsTrigger><TabsTrigger value="identity">Identity graph</TabsTrigger><TabsTrigger value="audit">Access audit</TabsTrigger></TabsList><TabsContent value="journey"><Timeline query={journey}/></TabsContent><TabsContent value="signals"><SignalList query={signals}/></TabsContent><TabsContent value="identity"><IdentityGraph query={graph}/></TabsContent><TabsContent value="audit"><SimpleTable query={audit} columns={['event_ts','officer_name','event_type','decision','detail']}/></TabsContent></Tabs></CardContent></>;
}

function ProfileFallback({ row, journey, onAction }: { row: QueryResult<'priority_queue'>[number]; journey: AnalyticsResult<'journey'>; onAction: (action: ActionKind) => void }) {
  return <><CardHeader className="profile-head"><div className="person"><span className="avatar large">{row.initials}</span><div><CardTitle>{row.display_name}</CardTitle><small>Governed constituent · {row.constituent_id}</small></div><Badge>{row.priority_band} priority</Badge></div><div className="actions">{(['Add case note','Assign case owner','Update case status','Correct contact details'] as ActionKind[]).map(item => <Button key={item} variant="outline" size="sm" onClick={() => onAction(item)}>{item}</Button>)}</div><div className="facts"><span><small>Service journey</small><strong>{row.service_type}</strong></span><span><small>Recommended follow-up</small><strong>{row.recommended_action ?? 'Restricted'}</strong></span><span><small>Case status</small><strong>{row.case_status} · {row.sla_status}</strong></span></div></CardHeader><CardContent><Tabs defaultValue="journey"><TabsList><TabsTrigger value="journey">Journey</TabsTrigger><TabsTrigger value="signals">Needs & signals</TabsTrigger><TabsTrigger value="identity">Identity graph</TabsTrigger><TabsTrigger value="audit">Access audit</TabsTrigger></TabsList><TabsContent value="journey"><div className="recommendation"><Badge variant="outline">Recommended follow-up</Badge><h3>{row.recommended_action}</h3><p>Review the governed journey events and confirm the next action with the constituent.</p></div><Timeline query={journey}/></TabsContent><TabsContent value="signals"><Empty><EmptyHeader><EmptyTitle>Signals restricted</EmptyTitle><EmptyDescription>No additional permitted signals are available for this purpose.</EmptyDescription></EmptyHeader></Empty></TabsContent></Tabs></CardContent></>;
}

function Timeline({ query }: { query: AnalyticsResult<'journey'> }) { return <QueryState loading={query.loading} error={query.error} empty={!query.data?.length}><div className="timeline">{query.data?.map(row => <article key={row.interaction_id ?? ''}><span className="event-icon">{row.channel === 'phone' ? '☎' : '↗'}</span><div><strong>{row.channel_label} · {row.subject ?? row.intent ?? 'Interaction'}</strong><time>{row.event_ts}</time><p>{row.summary ?? 'Summary masked for this purpose.'}</p><Badge variant="outline">{row.data_domain}</Badge></div></article>)}</div></QueryState>; }
function SignalList({ query }: { query: AnalyticsResult<'need_signals'> }) { return <QueryState loading={query.loading} error={query.error} empty={!query.data?.length}><div className="signal-grid">{query.data?.map(row => <Card key={`${row.data_domain}-${row.need_code}`}><CardContent><Badge>{row.strength}</Badge><h3>{row.need_label}</h3><p>{row.evidence_count} permitted evidence items · urgency {row.avg_urgency}</p></CardContent></Card>)}</div></QueryState>; }
function IdentityGraph({ query }: { query: AnalyticsResult<'identity_graph'> }) { const nodes = query.data ?? []; return <QueryState loading={query.loading} error={query.error} empty={!nodes.length}><svg className="identity-svg" viewBox="0 0 760 360" role="img" aria-label="Identity source graph"><line x1="380" y1="180" x2="120" y2="80"/><line x1="380" y1="180" x2="120" y2="280"/><line x1="380" y1="180" x2="640" y2="80"/><line x1="380" y1="180" x2="640" y2="280"/><circle className="root" cx="380" cy="180" r="72"/><text x="380" y="177">Resolved person</text><text x="380" y="199">{nodes.length} source records</text>{nodes.slice(0,4).map((row,index) => { const point = [[120,80],[120,280],[640,80],[640,280]][index]; return <g key={row.source_record_id ?? `${index}`}><circle cx={point[0]} cy={point[1]} r="56"/><text x={point[0]} y={point[1]}>{row.source_system}</text><text x={point[0]} y={point[1]+20}>{row.link_state} · {row.link_probability}</text></g>; })}</svg></QueryState>; }

function ActionDialog({ action, onClose, onSuccess }: { action: ActionKind | null; onClose: () => void; onSuccess: (message: string) => void }) {
  const [details, setDetails] = useState(''); const [error, setError] = useState<string | null>(null); const [saving, setSaving] = useState(false);
  const submit = async () => { if (!action) return; try { setSaving(true); setError(null); await api('/api/record-change-requests', { method: 'POST', body: JSON.stringify({ changeType: action, details, reasonCode: action === 'Record consent change' ? 'consent_update' : 'case_management' }) }); onClose(); setDetails(''); onSuccess('Change staged for review · audit event created'); } catch (caught) { setError(caught instanceof Error ? caught.message : 'Change not staged'); } finally { setSaving(false); } };
  return <Dialog open={Boolean(action)} onOpenChange={open => !open && onClose()}><DialogContent><DialogHeader><DialogTitle>{action}</DialogTitle><DialogDescription>Changes are staged through a governed procedure and never edit source records directly.</DialogDescription></DialogHeader><Label htmlFor="details">Details and justification</Label><Textarea id="details" value={details} onChange={event => setDetails(event.target.value)} placeholder="Describe the requested change…"/>{error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}<DialogFooter><Button variant="outline" onClick={onClose}>Cancel</Button><Button onClick={() => void submit()} disabled={saving || details.length < 3}>{saving ? 'Staging…' : 'Stage for review'}</Button></DialogFooter></DialogContent></Dialog>;
}

function Directory() { const query = useAnalyticsQuery('constituent_directory', {}); const navigate = useNavigate(); return <DataPage eyebrow="Governed directory" title="Constituents" description="Browse minimum-necessary directory attributes for constituents within your authorised purposes."><SimpleTable query={query} columns={['display_name','constituent_id','suburb','open_cases','priority_band','source_record_count']} onRow={() => { void navigate('/'); }}/></DataPage>; }
function Interactions() { const query = useAnalyticsQuery('journey', {}); return <DataPage eyebrow="Cross-channel history" title="Interactions" description="An active case session is required; restricted domains and AI-derived fields remain masked."><Timeline query={query}/></DataPage>; }
function Insights() { const query = useAnalyticsQuery('service_insights', {}); const data = (query.data ?? []).map(row => ({ service: row.service_line ?? 'Other', rate: Number(row.repeat_contact_rate ?? 0) * 100 })); return <DataPage eyebrow="Suppressed aggregates" title="Service insights" description="Compare repeat-contact patterns without exposing small cells."><QueryState loading={query.loading} error={query.error} empty={!data.length}><Card><CardHeader><CardTitle>Repeat contact by service</CardTitle></CardHeader><CardContent className="chart"><BarChart data={data} xKey="service" yKey="rate"/></CardContent></Card></QueryState></DataPage>; }
function Consent() { const scope = useAnalyticsQuery('access_scope', {}); const consent = useAnalyticsQuery('consent_decisions', {}); const [action,setAction] = useState<ActionKind|null>(null); return <DataPage eyebrow="Purpose-aware governance" title="Consent & access" description="Inspect policy outcomes, recorded consent and restricted access." action={<Button onClick={() => setAction('Record consent change')}>Record consent change</Button>}><div className="two-column"><Card><CardHeader><CardTitle>Current access scope</CardTitle></CardHeader><CardContent><SimpleTable query={scope} columns={['domain_name','access_rule','visible','reason','session_expires_at']}/></CardContent></Card><Card><CardHeader><CardTitle>Consent decisions</CardTitle></CardHeader><CardContent><SimpleTable query={consent} columns={['data_domain','decision','is_active','expires_at','source_system']}/></CardContent></Card></div><ActionDialog action={action} onClose={() => setAction(null)} onSuccess={() => undefined}/></DataPage>; }
function Lineage() { const query = useAnalyticsQuery('lineage', {}); return <DataPage eyebrow="Unity Catalog lineage" title="From channel event to governed 360 view." description="Trace each insight to its source, transformation and serving policy."><QueryState loading={query.loading} error={query.error} empty={!query.data?.length}><Card><CardContent><svg className="lineage-svg" viewBox="0 0 980 360" role="img" aria-label="Data lineage graph"><line x1="150" y1="90" x2="420" y2="180"/><line x1="150" y1="180" x2="420" y2="180"/><line x1="150" y1="270" x2="420" y2="180"/><line x1="480" y1="180" x2="700" y2="180"/><line x1="760" y1="180" x2="910" y2="180"/>{[['Phone',150,90],['Web',150,180],['Email',150,270],['Lakeflow',450,180],['Gold 360',730,180],['App',910,180]].map(([label,x,y]) => <g key={label}><circle cx={Number(x)} cy={Number(y)} r="54"/><text x={Number(x)} y={Number(y)}>{label}</text></g>)}</svg><p className="muted">{query.data?.length} observed table lineage edges in the last 90 days.</p></CardContent></Card></QueryState></DataPage>; }

function DataPage({ eyebrow,title,description,action,children }: { eyebrow:string; title:string; description:string; action?:React.ReactNode; children:React.ReactNode }) { return <div className="page"><PageHeading eyebrow={eyebrow} title={title} action={action}>{description}</PageHeading>{children}</div>; }
function displayCell(value: unknown): string { if (value == null) return '—'; if (typeof value === 'string') return value; if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') return value.toString(); if (typeof value === 'object') return JSON.stringify(value); return '—'; }
function SimpleTable<K extends 'constituent_directory'|'access_audit'|'access_scope'|'consent_decisions'>({ query, columns, onRow }: { query: AnalyticsResult<K>; columns: string[]; onRow?: () => void }) { return <QueryState loading={query.loading} error={query.error} empty={!query.data?.length}><div className="table-wrap"><Table><TableHeader><TableRow>{columns.map(column => <TableHead key={column}>{column.split('_').join(' ')}</TableHead>)}</TableRow></TableHeader><TableBody>{query.data?.map(row => { const record = row as Record<string, unknown>; const key = columns.map(column => displayCell(record[column])).join('|'); return <TableRow key={key} onClick={onRow}>{columns.map(column => <TableCell key={column}>{displayCell(record[column])}</TableCell>)}</TableRow>; })}</TableBody></Table></div></QueryState>; }

const router = createBrowserRouter([{ element: <Layout/>, children: [{path:'/',element:<Overview/>},{path:'/constituents',element:<Directory/>},{path:'/interactions',element:<Interactions/>},{path:'/insights',element:<Insights/>},{path:'/consent',element:<Consent/>},{path:'/lineage',element:<Lineage/>}]}]);
export default function App() { return <RouterProvider router={router}/>; }

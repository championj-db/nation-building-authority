import { useState } from 'react';
import { Skeleton } from '@databricks/appkit-ui/react';
import { sql } from '@databricks/appkit-ui/js';
import { useQuery } from '../lib/query';
import { Loader2, Lock, Sparkles } from 'lucide-react';
import { Empty, Modal, QueryError, StatusBadge, statusTone } from '../components/common';
import { postJson } from '../lib/api';
import { bn, dateTime, money, num, personName, tone, yes } from '../lib/format';
import { useAppState } from '../lib/state';

type Action = { programId: string; programName: string; status: 'Submitted' | 'Approved' | 'Returned' | 'Locked'; forecast: number };

function cycleOf(actualsThrough: unknown): { key: string; label: string; due: string } {
  const d = actualsThrough ? new Date(`${String(actualsThrough).slice(0, 10)}T00:00:00`) : new Date();
  const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
  const label = new Intl.DateTimeFormat('en-AU', { month: 'long', year: 'numeric' }).format(d);
  // Forecasts are due on the fifth business day after the ledger closes the month.
  const due = new Date(d.getFullYear(), d.getMonth() + 1, 1);
  let business = 0;
  while (business < 5) {
    due.setDate(due.getDate() + 1);
    if (due.getDay() !== 0 && due.getDay() !== 6) business += 1;
  }
  return { key, label, due: new Intl.DateTimeFormat('en-AU', { weekday: 'short', day: 'numeric', month: 'short' }).format(due) };
}

export function CyclePage({ actualsThrough }: { actualsThrough: unknown }) {
  const { dataVersion, role, setDrill } = useAppState();
  const cycle = cycleOf(actualsThrough);
  const programs = useQuery('forecast_cycle', { cycle: sql.string(cycle.key), data_version: sql.string(dataVersion) });
  const [action, setAction] = useState<Action | null>(null);
  const rows = programs.data ?? [];
  const count = (s: string) => rows.filter((r) => r.status === s).length;
  const done = count('Approved') + count('Locked');
  const allApproved = rows.length > 0 && rows.every((r) => r.status === 'Approved' || r.status === 'Locked');

  return (
    <section className="page active" aria-labelledby="cycle-title">
      <div className="page-head">
        <div>
          <p className="eyebrow">Monthly forecast cycle</p>
          <h1 id="cycle-title">{cycle.label} forecast</h1>
          <p className="subtitle">Program offices confirm their forecast and explain movements once the month's actuals land. The portfolio office reviews, returns or approves, then locks the cycle so the published figures have a traceable basis.</p>
        </div>
        <div className="freshness"><strong>Submissions due {cycle.due}</strong>Acting as {role}</div>
      </div>
      <div className="cycle-progress card">
        <div><span>Not submitted</span><strong>{count('Not submitted')}</strong></div>
        <div><span>Awaiting review</span><strong>{count('Submitted')}</strong></div>
        <div><span>Returned</span><strong className={count('Returned') ? 'delta bad' : ''}>{count('Returned')}</strong></div>
        <div><span>Approved</span><strong className="delta good">{count('Approved')}</strong></div>
        <div><span>Locked</span><strong>{count('Locked')}</strong></div>
        <div className="progress-track" aria-label={`${done} of ${rows.length} programs approved`}><div style={{ width: `${rows.length ? (done / rows.length) * 100 : 0}%` }} /></div>
      </div>
      <article className="card">
        <div className="card-head">
          <div><h2>Program submissions</h2><p>{role === 'Program office' ? 'Submit your program forecast with commentary.' : 'Review each submission; return with a reason or approve.'} Switch role in the top bar.</p></div>
          {role === 'Portfolio office' && allApproved && count('Approved') > 0 && (
            <button className="button primary" onClick={() => setAction({ programId: '*', programName: 'all approved programs', status: 'Locked', forecast: 0 })}><Lock size={15} /> Lock cycle</button>
          )}
        </div>
        {programs.loading && rows.length === 0 && <Skeleton className="table-skeleton" />}
        {programs.error && <QueryError message={`Cycle could not load: ${programs.error}`} />}
        {!programs.loading && !programs.error && rows.length === 0 && <Empty>No programs in the portfolio.</Empty>}
        {rows.length > 0 && (
          <div className="table-wrap"><table><thead><tr><th>Program</th><th>Status</th><th className="num">Forecast FY27–31</th><th className="num">vs plan</th><th>Latest commentary</th><th /></tr></thead><tbody>
            {rows.map((r) => {
              const status = String(r.status);
              const base = { programId: String(r.program_id), programName: String(r.program_name), forecast: num(r.forecast_aud_m) };
              return (
                <tr key={String(r.program_id)}>
                  <td><button className="link-button strong" onClick={() => setDrill({ kind: 'program', id: String(r.program_id), name: String(r.program_name) })}>{r.program_name}</button><small className="table-subtitle">{r.delivery_agency}</small></td>
                  <td><StatusBadge tone={statusTone(status === 'Not submitted' ? '' : status)}>{status}</StatusBadge>{r.status_at && <small className="table-subtitle">{personName(String(r.status_actor))} · {dateTime(r.status_at)}</small>}</td>
                  <td className="num">{bn(r.forecast_aud_m)}{r.submitted_forecast_aud_m !== null && Math.abs(num(r.submitted_forecast_aud_m) - num(r.forecast_aud_m)) > 1 && <small className="table-subtitle">submitted {bn(r.submitted_forecast_aud_m)}</small>}</td>
                  <td className="num"><span className={`delta ${tone(r.variance_aud_m)}`}>{bn(r.variance_aud_m, true)}</span>{yes(r.outside_tolerance) && <small className="table-subtitle">outside tolerance</small>}</td>
                  <td className="cause">{status === 'Returned' ? <><strong>Returned:</strong> {String(r.status_note ?? '')}</> : String(r.submission_commentary ?? '—')}</td>
                  <td className="row-actions">
                    {role === 'Program office' && ['Not submitted', 'Returned'].includes(status) && <button className="button small primary" onClick={() => setAction({ ...base, status: 'Submitted' })}>Submit</button>}
                    {role === 'Portfolio office' && status === 'Submitted' && (
                      <><button className="button small" onClick={() => setAction({ ...base, status: 'Returned' })}>Return</button><button className="button small primary" onClick={() => setAction({ ...base, status: 'Approved' })}>Approve</button></>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody></table></div>
        )}
      </article>
      {action && <SubmissionModal cycle={cycle.key} action={action} programs={rows.filter((r) => r.status === 'Approved').map((r) => ({ id: String(r.program_id), forecast: num(r.forecast_aud_m) }))} onClose={() => setAction(null)} />}
    </section>
  );
}

function SubmissionModal({ cycle, action, programs, onClose }: { cycle: string; action: Action; programs: Array<{ id: string; forecast: number }>; onClose: () => void }) {
  const { role, notify, refresh } = useAppState();
  const [text, setText] = useState('');
  const [drafting, setDrafting] = useState(false);
  const [saving, setSaving] = useState(false);
  const verb = { Submitted: 'Submit forecast', Approved: 'Approve', Returned: 'Return to program office', Locked: 'Lock cycle' }[action.status];
  const needsText = action.status === 'Returned' || action.status === 'Submitted';

  const draft = async () => {
    setDrafting(true);
    try {
      const r = await postJson<{ draft: string }>('/api/ai/variance-draft', { period: 'HORIZON', scope_level: 'program', scope_id: action.programId });
      setText(r.draft);
    } catch (e) {
      notify(e instanceof Error ? e.message : 'Draft failed', 'bad');
    } finally {
      setDrafting(false);
    }
  };

  const save = async () => {
    setSaving(true);
    try {
      const targets = action.programId === '*' ? programs : [{ id: action.programId, forecast: action.forecast }];
      for (const t of targets) {
        await postJson('/api/submissions', { cycle, program_id: t.id, status: action.status, forecast_aud_m: t.forecast, commentary: text, role });
      }
      notify(`${verb}: ${action.programName}`, 'good');
      refresh(3000);
      onClose();
    } catch (e) {
      notify(e instanceof Error ? e.message : 'Could not save', 'bad');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title={`${verb} · ${action.programName}`} eyebrow={`${cycle} cycle · acting as ${role}`} onClose={onClose}>
      {action.forecast > 0 && <p className="muted-small">Program horizon forecast at {money(action.forecast)} from the latest forecast run.</p>}
      <div className="field">
        <div className="field-row">
          <label htmlFor="sub-text">{action.status === 'Returned' ? 'Reason for return' : action.status === 'Submitted' ? 'Forecast commentary' : 'Note (optional)'}</label>
          {action.status === 'Submitted' && <button className="button small" onClick={draft} disabled={drafting}>{drafting ? <><Loader2 size={14} className="spin" /> Drafting</> : <><Sparkles size={14} /> Draft from the data</>}</button>}
        </div>
        <textarea id="sub-text" className="textarea" rows={6} value={text} onChange={(e) => setText(e.target.value)} />
      </div>
      <div className="modal-actions"><button className="button" onClick={onClose}>Cancel</button><button className="button primary" onClick={save} disabled={saving || (needsText && !text.trim())}>{saving ? 'Saving…' : verb}</button></div>
    </Modal>
  );
}

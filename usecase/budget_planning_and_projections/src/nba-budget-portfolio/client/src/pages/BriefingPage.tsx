import { Fragment, useState } from 'react';

import { sql } from '@databricks/appkit-ui/js';
import { useQuery } from '../lib/query';
import { Check, FileText, Loader2, Printer, Sparkles } from 'lucide-react';
import { Empty, ListSkeleton, QueryError, StatusBadge, statusTone } from '../components/common';
import { postJson } from '../lib/api';
import { dateTime, personName } from '../lib/format';
import { useAppState } from '../lib/state';
import type { ScenarioRow } from './ScenariosPage';

type Pack = { pack_id?: string; version?: number; title: string; scenario_id: string; narrative: string; status: string; model?: string | null; forecast_run_id?: string | null; sources?: unknown };

function inline(text: string) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith('**') && part.endsWith('**') ? <strong key={i}>{part.slice(2, -2)}</strong> : <Fragment key={i}>{part}</Fragment>,
  );
}

/** Minimal Markdown (headings, bullets, numbered lists, tables, bold) rendered as React elements: model output is never injected as HTML. */
export function Markdown({ text }: { text: string }) {
  const blocks: React.ReactNode[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  const flush = () => {
    if (!list) return;
    const items = list.items.map((item, i) => <li key={i}>{inline(item)}</li>);
    blocks.push(list.ordered ? <ol key={blocks.length}>{items}</ol> : <ul key={blocks.length}>{items}</ul>);
    list = null;
  };
  let table: string[][] | null = null;
  const flushTable = () => {
    if (!table) return;
    const [head, ...body] = table;
    blocks.push(
      <div className="table-wrap" key={blocks.length}><table className="compact"><thead><tr>{head.map((c, i) => <th key={i}>{inline(c)}</th>)}</tr></thead>
        <tbody>{body.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} className={j > 0 ? 'num' : ''}>{inline(c)}</td>)}</tr>)}</tbody></table></div>,
    );
    table = null;
  };
  for (const raw of text.split('\n')) {
    const line = raw.trimEnd();
    if (line.trim().startsWith('|')) {
      flush();
      const cells = line.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
      if (cells.every((c) => /^:?-{2,}:?$/.test(c))) continue;
      (table ??= []).push(cells);
      continue;
    }
    flushTable();
    const bullet = /^\s*[-*]\s+(.*)$/.exec(line);
    const numbered = /^\s*\d+\.\s+(.*)$/.exec(line);
    if (bullet || numbered) {
      const ordered = Boolean(numbered);
      if (!list || list.ordered !== ordered) { flush(); list = { ordered, items: [] }; }
      list.items.push((bullet ?? numbered)![1]);
      continue;
    }
    flush();
    if (!line.trim()) continue;
    if (line.startsWith('### ')) blocks.push(<h4 key={blocks.length}>{inline(line.slice(4))}</h4>);
    else if (line.startsWith('## ')) blocks.push(<h3 key={blocks.length}>{inline(line.slice(3))}</h3>);
    else if (line.startsWith('# ')) blocks.push(<h2 key={blocks.length}>{inline(line.slice(2))}</h2>);
    else blocks.push(<p key={blocks.length}>{inline(line)}</p>);
  }
  flush();
  flushTable();
  return <div className="markdown">{blocks}</div>;
}

export function BriefingPage({ scenarios }: { scenarios: ScenarioRow[] }) {
  const { dataVersion, scenarioId, notify, refresh, identity } = useAppState();
  const packs = useQuery('briefing_packs', { data_version: sql.string(dataVersion) });
  const [pack, setPack] = useState<Pack | null>(null);
  const [picked, setPicked] = useState(scenarioId);
  const ready = scenarios.filter((s) => s.computed_version !== null && s.computed_version !== undefined);
  const scenario = ready.some((s) => s.scenario_id === picked) ? picked : 'BASE';
  const setScenario = setPicked;
  const [drafting, setDrafting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(true);

  const draft = async () => {
    setDrafting(true);
    try {
      const r = await postJson<{ draft: string; sources: unknown; model: string; forecast_run_id: string | null }>('/api/ai/briefing-draft', { scenario_id: scenario });
      const name = scenarios.find((s) => s.scenario_id === scenario)?.scenario_name ?? scenario;
      setPack({ title: `Portfolio briefing · ${name}`, scenario_id: scenario, narrative: r.draft, status: 'Draft', model: r.model, forecast_run_id: r.forecast_run_id, sources: r.sources });
      setEditing(false);
    } catch (e) {
      notify(e instanceof Error ? e.message : 'Draft failed', 'bad');
    } finally {
      setDrafting(false);
    }
  };

  const save = async (status: 'Draft' | 'Approved') => {
    if (!pack) return;
    setSaving(true);
    try {
      const r = await postJson<{ pack_id: string; version: number; status: string }>('/api/briefings', { ...pack, status });
      setPack({ ...pack, pack_id: r.pack_id, version: r.version, status: r.status });
      notify(status === 'Approved' ? `Briefing approved (v${r.version})` : `Draft saved (v${r.version})`, 'good');
      refresh(3000);
    } catch (e) {
      notify(e instanceof Error ? e.message : 'Could not save', 'bad');
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="page active" aria-labelledby="briefing-title">
      <div className="page-head no-print">
        <div>
          <p className="eyebrow">Briefing packs</p>
          <h1 id="briefing-title">Executive briefing</h1>
          <p className="subtitle">A first draft written from the governed figures you can see — KPIs, scenarios, capacity, exceptions, the variance bridge and recorded commentary — for you to edit, approve and export. Every pack records the forecast run and model behind it.</p>
        </div>
      </div>
      <div className="grid two-one detail-grid">
        <article className="card briefing-card">
          {!pack && (
            <div className="briefing-start no-print">
              <FileText size={28} />
              <h2>Draft a new briefing</h2>
              <div className="filters">
                <select className="select" aria-label="Scenario" value={scenario} onChange={(e) => setScenario(e.target.value)}>
                  {ready.map((s) => <option key={s.scenario_id} value={s.scenario_id}>{s.scenario_name}</option>)}
                </select>
                <button className="button primary" onClick={draft} disabled={drafting}>{drafting ? <><Loader2 size={15} className="spin" /> Drafting — about 20 seconds</> : <><Sparkles size={15} /> Draft from current figures</>}</button>
              </div>
              <p className="muted-small">Drafts run as {identity?.email ?? 'you'}: only figures you are permitted to read are sent to the model{identity?.draftingModel ? ` (${identity.draftingModel})` : ''}.</p>
            </div>
          )}
          {pack && (
            <>
              <div className="card-head no-print">
                <div><input className="title-input" aria-label="Briefing title" value={pack.title} onChange={(e) => setPack({ ...pack, title: e.target.value })} disabled={pack.status === 'Approved'} />
                  <p>{pack.pack_id ? `${pack.pack_id} v${pack.version}` : 'Unsaved draft'} · forecast run {pack.forecast_run_id ?? '—'} · {pack.model ? `first draft by ${pack.model}` : 'written by hand'}</p></div>
                <StatusBadge tone={statusTone(pack.status)}>{pack.status}</StatusBadge>
              </div>
              <div className="actions wrap no-print briefing-actions">
                {pack.status !== 'Approved' && <button className="button" onClick={() => setEditing(!editing)}>{editing ? 'Preview' : 'Edit'}</button>}
                {pack.status !== 'Approved' && <button className="button" onClick={() => save('Draft')} disabled={saving}>Save draft</button>}
                {pack.status !== 'Approved' && <button className="button primary" onClick={() => save('Approved')} disabled={saving}><Check size={15} /> Approve</button>}
                <button className="button" onClick={() => window.print()}><Printer size={15} /> Print / PDF</button>
                <button className="button" onClick={() => setPack(null)}>New briefing</button>
              </div>
              {editing && pack.status !== 'Approved'
                ? <textarea className="textarea briefing-editor" value={pack.narrative} onChange={(e) => setPack({ ...pack, narrative: e.target.value })} aria-label="Briefing text (Markdown)" />
                : (
                  <div className="briefing-print">
                    <div className="print-only print-head"><strong>Nation Building Authority · {pack.title}</strong><span>PROTECTED · Working figures · synthetic demonstration</span></div>
                    <Markdown text={pack.narrative} />
                    <p className="print-foot">Forecast run {pack.forecast_run_id ?? '—'} · {pack.status}{pack.version ? ` v${pack.version}` : ''} · prepared by {identity?.email ?? '—'} · first draft generated by {pack.model ?? 'n/a'} from governed Unity Catalog figures and reviewed by the author.</p>
                  </div>
                )}
            </>
          )}
        </article>
        <article className="card no-print">
          <div className="card-head"><div><h2>Recent packs</h2><p>Latest version of each</p></div></div>
          {packs.loading && !packs.data && <ListSkeleton rows={3} />}
          {packs.error && <QueryError message={`Packs could not load: ${packs.error}`} />}
          {packs.data?.length === 0 && <Empty>No briefing packs yet.</Empty>}
          <ol className="history">
            {packs.data?.map((p) => (
              <li key={String(p.pack_id)}>
                <button className="link-button strong" onClick={() => { setPack({ pack_id: String(p.pack_id), version: Number(p.version), title: String(p.title), scenario_id: String(p.scenario_id), narrative: String(p.narrative), status: String(p.status), model: p.model as string | null, forecast_run_id: p.forecast_run_id as string | null }); setEditing(false); }}>{p.title}</button>
                <small><StatusBadge tone={statusTone(String(p.status))}>{p.status}</StatusBadge> v{Number(p.version)} · {personName(String(p.actor))} · {dateTime(p.created_at)}</small>
              </li>
            ))}
          </ol>
        </article>
      </div>
    </section>
  );
}

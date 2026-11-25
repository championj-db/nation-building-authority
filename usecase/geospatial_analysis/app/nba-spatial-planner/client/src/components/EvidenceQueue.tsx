import { useEffect, useMemo, useState } from 'react';
import { EVIDENCE_STATUSES } from '../../../shared/contracts';
import type { Analysis } from '../lib/analysis';
import { postJson, sql, useBaseParams, useRows, useScope } from '../lib/data';
import { dateTime, km, officerName, people, pct } from '../lib/format';
import {
  ACCESS_CLASS_LABEL,
  EVIDENCE_LABEL,
  defaultEvidence,
  recommendedStep,
  type EvidenceStatus,
  type RegionAccess,
} from '../lib/model';
import { GEO_LEVEL_LABELS, GEO_LEVEL_NOUN, type AnalysisSettings } from '../lib/settings';
import { ClassLabel, Dialog, ErrorNotice, PanelSkeleton, useToast } from './primitives';

type Filter = 'all' | 'beyond' | 'near' | 'within';
const PAGE = 12;

interface Props {
  analysis: Analysis;
  settings: AnalysisSettings;
  serviceLabel: string;
  selected: string | null;
  onSelect: (code: string) => void;
  noteFor: RegionAccess | null;
  onNoteFor: (row: RegionAccess | null) => void;
}

export function EvidenceQueue({ analysis, settings, serviceLabel, selected, onSelect, noteFor, onNoteFor }: Props) {
  const { access, notes, minCount } = analysis;
  const [filter, setFilter] = useState<Filter>('all');
  const [showAll, setShowAll] = useState(false);
  const pageKey = `${settings.geoLevel}|${settings.scope}|${filter}`;
  const [shownKey, setShownKey] = useState(pageKey);
  if (shownKey !== pageKey) {
    setShownKey(pageKey);
    setShowAll(false);
  }

  const counts = useMemo(() => {
    const c: Record<Filter, number> = { all: 0, beyond: 0, near: 0, within: 0 };
    for (const r of access.rows) {
      if (r.access_class === 'no_population') continue;
      c.all += 1;
      if (r.access_class === 'beyond' || r.access_class === 'near' || r.access_class === 'within')
        c[r.access_class] += 1;
    }
    return c;
  }, [access.rows]);
  const rows = useMemo(
    () =>
      access.rows.filter((r) => r.access_class !== 'no_population' && (filter === 'all' || r.access_class === filter)),
    [access.rows, filter]
  );
  // Keep the selected region visible even when it falls past the first page.
  const visible = showAll ? rows : rows.slice(0, PAGE);
  const selectedRow =
    selected && !visible.some((r) => r.region_code === selected)
      ? rows.find((r) => r.region_code === selected)
      : undefined;
  const display = selectedRow ? [...visible, selectedRow] : visible;

  const exportCsv = () => {
    const header = [
      'Region',
      'State',
      'Access class',
      'Residents',
      `Beyond ${settings.threshold} km`,
      'Share beyond',
      'Median km',
      'Aged 65+ beyond',
      'Households without a car beyond',
      'Evidence status',
      'Next step',
    ];
    const lines = rows.map((r) => {
      const note = notes.byRegion.get(r.region_code);
      return [
        r.region_name,
        r.state_abbr,
        ACCESS_CLASS_LABEL[r.access_class],
        people(r.persons, minCount).replace(/,/g, ''),
        people(r.persons_beyond, minCount, r.persons_beyond == null).replace(/,/g, ''),
        pct(r.share_beyond),
        r.median_km ?? '',
        people(r.persons_65_beyond, minCount).replace(/,/g, ''),
        people(r.households_no_vehicle_beyond, minCount).replace(/,/g, ''),
        EVIDENCE_LABEL[note?.evidence_status ?? defaultEvidence(r.access_class)],
        note?.next_step || recommendedStep(r),
      ];
    });
    const csv = [header, ...lines].map((l) => l.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(',')).join('\n');
    const notice = `"SYNTHETIC household data - not for operational use. ${minCount ? `Counts under ${minCount} suppressed.` : 'UNSUPPRESSED - internal analysis only.'}"`;
    const blob = new Blob([`${notice}\n${csv}\n`], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `evidence-queue-${settings.service}-${settings.geoLevel}-${settings.scope}-${settings.threshold}km.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <section className="panel table-panel" aria-labelledby="queue-title">
      <div className="panel-head">
        <div>
          <h2 id="queue-title">Evidence queue</h2>
          <span className="sub">
            Prepared for briefing, subject to officer review · {GEO_LEVEL_LABELS[settings.geoLevel]}
          </span>
        </div>
        <div className="table-toolbar">
          {(['all', 'beyond', 'near', 'within'] as const).map((f) => (
            <button key={f} type="button" className="chip" aria-pressed={filter === f} onClick={() => setFilter(f)}>
              {f === 'all' ? 'All' : ACCESS_CLASS_LABEL[f]}
              {access.loading ? '' : ` · ${counts[f]}`}
            </button>
          ))}
          <button type="button" className="button small" onClick={exportCsv} disabled={!rows.length}>
            Export CSV
          </button>
          <button
            type="button"
            className="button small"
            onClick={() => {
              const target = access.rows.find((r) => r.region_code === selected) ?? rows[0];
              if (target) onNoteFor(target);
            }}
            disabled={!rows.length}
          >
            Add review note
          </button>
        </div>
      </div>
      {access.error ? (
        <div className="panel-body">
          <ErrorNotice title="The evidence queue did not load" message={access.error} />
        </div>
      ) : access.loading ? (
        <div className="panel-body">
          <PanelSkeleton lines={5} />
        </div>
      ) : (
        <div className={`table-wrap${access.refreshing ? ' refreshing' : ''}`}>
          <table>
            <caption className="sr-only">
              {GEO_LEVEL_LABELS[settings.geoLevel]} by access to {serviceLabel.toLowerCase()} at a {settings.threshold}{' '}
              km threshold
            </caption>
            <thead>
              <tr>
                <th scope="col">Planning region</th>
                <th scope="col">Access class</th>
                <th scope="col" className="number">
                  Nearest service
                </th>
                <th scope="col" className="number">
                  Beyond {settings.threshold} km
                </th>
                <th scope="col">Evidence status</th>
                <th scope="col">Recommended next step</th>
                <th scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {display.map((r) => {
                const note = notes.byRegion.get(r.region_code);
                const status = note?.evidence_status ?? defaultEvidence(r.access_class);
                return (
                  <tr
                    key={r.region_code}
                    className={r.region_code === selected ? 'selected' : undefined}
                    aria-selected={r.region_code === selected}
                    onClick={() => onSelect(r.region_code)}
                  >
                    <td>
                      <button
                        type="button"
                        className="button ghost small"
                        style={{ padding: 0, minHeight: 0, fontWeight: 600, letterSpacing: 0 }}
                        onClick={(e) => {
                          e.stopPropagation();
                          onSelect(r.region_code);
                        }}
                      >
                        {r.region_name}
                      </button>
                      {settings.scope === 'AUS' && <span className="xs muted"> · {r.state_abbr}</span>}
                    </td>
                    <td>
                      <ClassLabel value={r.access_class} />
                    </td>
                    <td className="number">{km(r.median_km)}</td>
                    <td className="number">
                      {people(r.persons_beyond, minCount, r.persons_beyond == null)}
                      <span className="xs muted"> · {pct(r.share_beyond, 0)}</span>
                    </td>
                    <td>
                      <span className={note ? '' : 'muted'}>{EVIDENCE_LABEL[status]}</span>
                      {note && (
                        <div className="xs muted">
                          {officerName(note.officer)} ·{' '}
                          {note.note_count > 1 ? `${note.note_count} notes` : dateTime(note.created_ts)}
                        </div>
                      )}
                    </td>
                    <td>{note?.next_step || recommendedStep(r)}</td>
                    <td>
                      <button
                        type="button"
                        className="button small"
                        onClick={(e) => {
                          e.stopPropagation();
                          onNoteFor(r);
                        }}
                        aria-label={`Add review note for ${r.region_name}`}
                      >
                        Note
                      </button>
                    </td>
                  </tr>
                );
              })}
              {display.length === 0 && (
                <tr>
                  <td colSpan={7} className="muted">
                    No {GEO_LEVEL_NOUN[settings.geoLevel]} in this class.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      <div className="table-foot">
        <span>
          Sorted by people beyond the threshold.{' '}
          {minCount ? `Counts under ${minCount} shown as <${minCount}.` : 'Small counts are not suppressed.'}
        </span>
        {rows.length > PAGE && (
          <button type="button" className="button small" onClick={() => setShowAll((v) => !v)}>
            {showAll ? 'Show fewer' : `Show all ${rows.length}`}
          </button>
        )}
      </div>
      <NoteDialog row={noteFor} settings={settings} analysis={analysis} onClose={() => onNoteFor(null)} />
    </section>
  );
}

function NoteDialog({
  row,
  settings,
  analysis,
  onClose,
}: {
  row: RegionAccess | null;
  settings: AnalysisSettings;
  analysis: Analysis;
  onClose: () => void;
}) {
  const toast = useToast();
  const { writes, bumpWrites } = useScope();
  const base = useBaseParams();
  const current = row ? analysis.notes.byRegion.get(row.region_code) : undefined;
  const [status, setStatus] = useState<EvidenceStatus>('needs_validation');
  const [nextStep, setNextStep] = useState('');
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!row) return;
    setStatus(current?.evidence_status ?? defaultEvidence(row.access_class));
    setNextStep(current?.next_step || recommendedStep(row));
    setNote('');
    setError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [row?.region_code]);

  const historyParams = useMemo(
    () => ({
      ...base,
      service: sql.string(settings.service),
      geo_level: sql.string(settings.geoLevel),
      region_code: sql.string(row?.region_code ?? ''),
      refresh: sql.string(writes),
    }),
    [base, settings.service, settings.geoLevel, row?.region_code, writes]
  );
  const history = useRows('region_notes', historyParams, { autoStart: Boolean(row) });
  const historyRows = (row ? (history.data ?? []) : []) as {
    note_id: string;
    created_ts: string;
    officer: string;
    evidence_status: EvidenceStatus;
    next_step: string | null;
    note: string | null;
    threshold_km: number | null;
  }[];

  const save = async () => {
    if (!row) return;
    setSaving(true);
    setError(null);
    try {
      await postJson('/api/notes', {
        service: settings.service,
        geoLevel: settings.geoLevel,
        regionCode: row.region_code,
        regionName: row.region_name,
        thresholdKm: settings.threshold,
        evidenceStatus: status,
        nextStep,
        note,
      });
      bumpWrites();
      toast(`Review note recorded for ${row.region_name}.`);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The note was not saved');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog
      open={Boolean(row)}
      onClose={onClose}
      title="Add review note"
      subtitle={
        row ? `${row.region_name} · ${ACCESS_CLASS_LABEL[row.access_class]} at ${settings.threshold} km` : undefined
      }
      footer={
        <>
          <button type="button" className="button" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="button primary" onClick={() => void save()} disabled={saving}>
            {saving ? 'Saving…' : 'Record note'}
          </button>
        </>
      }
    >
      <div className="field">
        <span className="label" id="status-label">
          Evidence status
        </span>
        <div className="radio-row" role="radiogroup" aria-labelledby="status-label">
          {EVIDENCE_STATUSES.map((s) => (
            <label key={s}>
              <input
                type="radio"
                name="evidence-status"
                value={s}
                checked={status === s}
                onChange={() => setStatus(s)}
              />
              {EVIDENCE_LABEL[s]}
            </label>
          ))}
        </div>
      </div>
      <div className="field">
        <label htmlFor="next-step">Recommended next step</label>
        <input
          id="next-step"
          type="text"
          value={nextStep}
          maxLength={160}
          onChange={(e) => setNextStep(e.target.value)}
        />
      </div>
      <div className="field">
        <label htmlFor="note-text">Note</label>
        <textarea
          id="note-text"
          value={note}
          maxLength={1000}
          placeholder="What did you check, and what should the next reviewer know?"
          onChange={(e) => setNote(e.target.value)}
        />
        <small>Recorded against your identity with the threshold and geography shown. Notes are append-only.</small>
      </div>
      {error && <ErrorNotice title="Not saved" message={error} />}
      {historyRows.length > 0 && (
        <>
          <h3 className="section-title">History</h3>
          <ul className="history">
            {historyRows.map((h) => (
              <li key={h.note_id}>
                <div className="meta">
                  {officerName(h.officer)} · {dateTime(h.created_ts)} · {EVIDENCE_LABEL[h.evidence_status]}
                  {h.threshold_km ? ` · at ${h.threshold_km} km` : ''}
                </div>
                {h.next_step && <div>Next: {h.next_step}</div>}
                {h.note && <div className="muted">{h.note}</div>}
              </li>
            ))}
          </ul>
        </>
      )}
    </Dialog>
  );
}

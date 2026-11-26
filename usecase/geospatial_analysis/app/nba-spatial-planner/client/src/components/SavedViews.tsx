import { useMemo, useState } from 'react';
import { Bookmark, X } from 'lucide-react';
import { postJson, sql, useBaseParams, useRows, useScope } from '../lib/data';
import { officerName, relativeDay } from '../lib/format';
import {
  GEO_LEVEL_LABELS,
  SCOPE_LABELS,
  SERVICE_LABELS,
  parseStoredSettings,
  type AnalysisSettings,
} from '../lib/settings';
import { useOutsideClose, useToast } from './primitives';

interface SavedViewRow {
  view_id: string;
  created_ts: string;
  officer: string;
  name: string;
  settings: unknown;
  is_mine: boolean;
}

export function SavedViews({
  current,
  onApply,
}: {
  current: AnalysisSettings;
  onApply: (s: AnalysisSettings, name: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const { writes, bumpWrites } = useScope();
  const base = useBaseParams();
  const params = useMemo(() => ({ ...base, refresh: sql.string(writes) }), [base, writes]);
  const views = useRows('saved_views', params, { autoStart: open });
  const rows = (views.data ?? []) as SavedViewRow[];
  const ref = useOutsideClose(open, () => setOpen(false));

  const save = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      await postJson('/api/views', { name: name.trim(), settings: current });
      bumpWrites();
      setName('');
      toast('View saved. Officers with access to this workspace can open it.');
    } catch (e) {
      toast(e instanceof Error ? e.message : 'The view was not saved', 'error');
    } finally {
      setBusy(false);
    }
  };
  const remove = async (row: SavedViewRow) => {
    try {
      await postJson(`/api/views/${row.view_id}`, undefined, 'DELETE');
      bumpWrites();
      toast(`Removed “${row.name}”.`);
    } catch (e) {
      toast(e instanceof Error ? e.message : 'The view was not removed', 'error');
    }
  };

  return (
    <div className="popover-anchor" ref={ref}>
      <button
        type="button"
        className="button"
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((v) => !v)}
      >
        <Bookmark className="icon" aria-hidden="true" />
        <span className="label">Saved views</span>
      </button>
      {open && (
        <div className="popover" role="dialog" aria-label="Saved views">
          <div className="panel-head">
            <h2>Saved views</h2>
            <button
              type="button"
              className="button small"
              onClick={() =>
                void navigator.clipboard?.writeText(window.location.href).then(() => toast('Link to this view copied.'))
              }
            >
              Copy link
            </button>
          </div>
          <form
            className="panel-body"
            style={{ borderBottom: '1px solid var(--line-soft)' }}
            onSubmit={(e) => {
              e.preventDefault();
              void save();
            }}
          >
            <label className="xs muted" htmlFor="view-name">
              Save the current settings
            </label>
            <div className="row" style={{ marginTop: 6 }}>
              <input
                id="view-name"
                type="text"
                value={name}
                maxLength={80}
                placeholder="e.g. NSW hospitals, 45 km"
                onChange={(e) => setName(e.target.value)}
              />
              <button type="submit" className="button primary" disabled={busy || !name.trim()}>
                Save
              </button>
            </div>
          </form>
          {views.loading ? (
            <div className="panel-body muted small">
              <span className="spinner" aria-hidden="true" />
              Loading…
            </div>
          ) : views.error ? (
            <div className="panel-body small">Saved views did not load. {views.error}</div>
          ) : rows.length === 0 ? (
            <div className="panel-body muted small">No saved views yet.</div>
          ) : (
            <ul className="view-list">
              {rows.map((row) => {
                const settings = parseStoredSettings(row.settings);
                return (
                  <li key={row.view_id}>
                    <button
                      type="button"
                      className="apply"
                      disabled={!settings}
                      onClick={() => {
                        if (settings) onApply(settings, row.name);
                        setOpen(false);
                      }}
                    >
                      <span style={{ fontWeight: 600 }}>{row.name}</span>
                      <span className="xs muted">
                        {settings
                          ? `${SERVICE_LABELS[settings.service]} · ${SCOPE_LABELS[settings.scope]} · ${GEO_LEVEL_LABELS[settings.geoLevel]} · ${settings.threshold} km`
                          : 'Settings no longer valid'}
                      </span>
                      <span className="xs muted">
                        {row.is_mine ? 'You' : officerName(row.officer)} · {relativeDay(row.created_ts)}
                      </span>
                    </button>
                    {row.is_mine && (
                      <button
                        type="button"
                        className="button small icon-button ghost"
                        aria-label={`Remove ${row.name}`}
                        onClick={() => void remove(row)}
                      >
                        <X className="icon" aria-hidden="true" />
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

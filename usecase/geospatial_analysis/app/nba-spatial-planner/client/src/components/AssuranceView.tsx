import { briefForSettings, type BriefRow } from '../lib/briefs';
import { dateTime, officerName } from '../lib/format';
import { SCOPE_LABELS, SERVICE_LABELS, parseStoredSettings, type AnalysisSettings } from '../lib/settings';
import { ErrorNotice, PanelSkeleton } from './primitives';

interface Props {
  settings: AnalysisSettings;
  minCount: number;
  briefs: { rows: BriefRow[]; loading: boolean; error: string | null };
  onPrepare: () => void;
  onView: (briefId: string) => void;
}

export function AssuranceView({ settings, minCount, briefs, onPrepare, onView }: Props) {
  const current = briefForSettings(briefs.rows, settings);
  const checks = [
    { label: 'Synthetic data label', note: 'Visible in analysis, exports and briefs.', done: true, auto: true },
    {
      label: 'Small-count suppression',
      note: settings.suppress
        ? `Enabled for this view (under ${minCount} people hidden).`
        : 'Off. Briefs cannot be prepared until it is on.',
      done: settings.suppress,
      auto: true,
    },
    {
      label: 'Purpose recorded',
      note: current
        ? `“${current.policy_question.slice(0, 80)}${current.policy_question.length > 80 ? '…' : ''}”`
        : 'Add to the decision brief for this analysis.',
      done: Boolean(current),
    },
    {
      label: 'Officer sign-off',
      note:
        current?.status === 'signed_off'
          ? `${officerName(current.signed_off_by)}, ${dateTime(current.signed_off_ts)}`
          : 'Required before external circulation.',
      done: current?.status === 'signed_off',
    },
  ];

  return (
    <div className="empty-view">
      <div className="assurance-stack">
        <div className="panel">
          <div className="panel-head">
            <h2>Privacy by aggregation</h2>
            <span className="tag">Required</span>
          </div>
          <div className="panel-body">
            <p style={{ maxWidth: '65ch', color: 'var(--fg-muted)' }}>
              Precise location can identify a person even when other fields are masked. This workspace keeps household
              locations out of the interface and presents spatial aggregates for policy review.
            </p>
            <ol className="process">
              <li>
                <span className="step">1</span>
                <div>
                  <strong>Minimise precision</strong>
                  <p>
                    Use the least precise geography necessary for the decision. Household rows never leave the governed
                    silver layer.
                  </p>
                </div>
              </li>
              <li>
                <span className="step">2</span>
                <div>
                  <strong>Suppress small counts</strong>
                  <p>
                    Prevent disclosure through fine-grained aggregates. Counts under {minCount} are replaced before
                    results leave the warehouse.
                  </p>
                </div>
              </li>
              <li>
                <span className="step">3</span>
                <div>
                  <strong>Record purpose</strong>
                  <p>Capture the policy question, access basis, and intended audience with every brief.</p>
                </div>
              </li>
            </ol>
          </div>
        </div>

        <section className="panel" aria-labelledby="brief-history">
          <div className="panel-head">
            <h2 id="brief-history">Decision briefs</h2>
            <button type="button" className="button small primary" onClick={onPrepare} disabled={!settings.suppress}>
              Prepare brief
            </button>
          </div>
          {briefs.loading ? (
            <div className="panel-body">
              <PanelSkeleton lines={3} />
            </div>
          ) : briefs.error ? (
            <div className="panel-body">
              <ErrorNotice title="Briefs did not load" message={briefs.error} />
            </div>
          ) : briefs.rows.length === 0 ? (
            <div className="panel-body muted small">No briefs have been prepared yet.</div>
          ) : (
            <div className="table-wrap">
              <table style={{ minWidth: 560 }}>
                <thead>
                  <tr>
                    <th>Brief</th>
                    <th>Prepared</th>
                    <th>Status</th>
                    <th>
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {briefs.rows.map((b) => {
                    const s = parseStoredSettings(b.settings);
                    return (
                      <tr key={b.brief_id} onClick={() => onView(b.brief_id)}>
                        <td>
                          <strong>{b.title}</strong>
                          {s && (
                            <div className="xs muted">
                              {SERVICE_LABELS[s.service]} · {SCOPE_LABELS[s.scope]} · {s.threshold} km
                            </div>
                          )}
                        </td>
                        <td className="small">
                          {officerName(b.prepared_by)}
                          <div className="xs muted">{dateTime(b.prepared_ts)}</div>
                        </td>
                        <td>
                          <span className={`tag${b.status === 'signed_off' ? ' ok' : ''}`}>
                            {b.status === 'signed_off' ? 'Signed off' : 'Draft'}
                          </span>
                        </td>
                        <td>
                          <button
                            type="button"
                            className="button small"
                            onClick={(e) => {
                              e.stopPropagation();
                              onView(b.brief_id);
                            }}
                          >
                            Open
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>

      <aside className="panel">
        <div className="panel-head">
          <h2>Before publication</h2>
        </div>
        <div className="panel-body">
          <p className="xs muted" style={{ marginBottom: 8 }}>
            For the current analysis: {SERVICE_LABELS[settings.service]}, {SCOPE_LABELS[settings.scope]},{' '}
            {settings.threshold} km.
          </p>
          {checks.map((c) => (
            <div className="check readonly" key={c.label}>
              <input
                type="checkbox"
                checked={c.done}
                readOnly
                disabled
                aria-label={`${c.label}: ${c.done ? 'complete' : 'outstanding'}`}
              />
              <span>
                <strong>{c.label}</strong>
                <br />
                <small>{c.note}</small>
              </span>
            </div>
          ))}
          <div className="row" style={{ marginTop: 12, flexWrap: 'wrap' }}>
            {current ? (
              <button type="button" className="button" onClick={() => onView(current.brief_id)}>
                {current.status === 'signed_off' ? 'Open signed-off brief' : 'Review and sign off'}
              </button>
            ) : (
              <button type="button" className="button primary" onClick={onPrepare} disabled={!settings.suppress}>
                Record purpose
              </button>
            )}
          </div>
        </div>
      </aside>
    </div>
  );
}

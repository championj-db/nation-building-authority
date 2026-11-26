import { GEO_LEVELS, SCOPES, SERVICES } from '../../../shared/contracts';
import type { CatalogRow } from '../lib/model';
import {
  GEO_LEVEL_LABELS,
  SCOPE_LABELS,
  SERVICE_LABELS,
  THRESHOLD_SLIDER,
  samePolicy,
  type AnalysisSettings,
  type ServiceType,
} from '../lib/settings';

interface Props {
  draft: AnalysisSettings;
  applied: AnalysisSettings;
  catalog: CatalogRow[];
  minCount: number;
  running: boolean;
  onChange: (patch: Partial<AnalysisSettings>) => void;
  onRun: () => void;
  onDiscard: () => void;
}

export function PolicySettings({ draft, applied, catalog, minCount, running, onChange, onRun, onDiscard }: Props) {
  const dirty = !samePolicy(draft, applied);
  const service = catalog.find((c) => c.service_type === draft.service);
  return (
    <aside className="panel" aria-labelledby="settings-title">
      <div className="panel-head">
        <h2 id="settings-title">Policy settings</h2>
        <span className={`tag${dirty ? '' : ' neutral'}`}>{dirty ? 'Draft' : 'Applied'}</span>
      </div>
      <form
        className="panel-body"
        onSubmit={(event) => {
          event.preventDefault();
          onRun();
        }}
      >
        <div className="field">
          <label htmlFor="serviceType">Essential service</label>
          <select
            id="serviceType"
            value={draft.service}
            onChange={(e) => {
              const next = e.target.value as ServiceType;
              const def = catalog.find((c) => c.service_type === next)?.default_threshold_km;
              onChange({ service: next, ...(def ? { threshold: def } : {}) });
            }}
          >
            {SERVICES.map((s) => {
              const row = catalog.find((c) => c.service_type === s);
              return (
                <option key={s} value={s}>
                  {row?.label ?? SERVICE_LABELS[s]}
                  {row ? ` (${row.sites.toLocaleString('en-AU')})` : ''}
                </option>
              );
            })}
          </select>
          {service && <small>{service.description}</small>}
        </div>

        <div className="field">
          <label htmlFor="scope">Area</label>
          <select
            id="scope"
            value={draft.scope}
            onChange={(e) => onChange({ scope: e.target.value as AnalysisSettings['scope'] })}
          >
            {SCOPES.map((s) => (
              <option key={s} value={s}>
                {SCOPE_LABELS[s]}
              </option>
            ))}
          </select>
        </div>

        <div className="field">
          <label htmlFor="geography">Analysis geography</label>
          <select
            id="geography"
            value={draft.geoLevel}
            onChange={(e) => onChange({ geoLevel: e.target.value as AnalysisSettings['geoLevel'] })}
          >
            {GEO_LEVELS.map((g) => (
              <option key={g} value={g}>
                {GEO_LEVEL_LABELS[g]}
              </option>
            ))}
          </select>
          {draft.geoLevel === 'sa2' && draft.scope === 'AUS' && (
            <small>About 2,400 areas nationally. Choose a state for a closer view.</small>
          )}
        </div>

        <div className="field">
          <label htmlFor="distance">Reasonable access threshold</label>
          <input
            id="distance"
            type="range"
            min={THRESHOLD_SLIDER.min}
            max={THRESHOLD_SLIDER.max}
            step={THRESHOLD_SLIDER.step}
            value={draft.threshold}
            aria-valuetext={`${draft.threshold} kilometres`}
            onChange={(e) => onChange({ threshold: Number(e.target.value) })}
          />
          <div className="range-line">
            <span>{THRESHOLD_SLIDER.min} km</span>
            <strong>{draft.threshold} km</strong>
            <span>{THRESHOLD_SLIDER.max} km</span>
          </div>
          {service && draft.threshold !== service.default_threshold_km && (
            <small>
              Planning default for this service is {service.default_threshold_km} km.{' '}
              <button
                type="button"
                className="button small ghost"
                style={{ minHeight: 0, padding: 0, textDecoration: 'underline' }}
                onClick={() => onChange({ threshold: service.default_threshold_km })}
              >
                Use default
              </button>
            </small>
          )}
        </div>

        <label className="check">
          <input type="checkbox" checked={draft.suppress} onChange={(e) => onChange({ suppress: e.target.checked })} />
          <span>
            <strong>Suppress small counts</strong>
            <br />
            <small>Hide aggregates below the disclosure threshold ({minCount} people).</small>
          </span>
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={draft.boundaries}
            onChange={(e) => onChange({ boundaries: e.target.checked })}
          />
          <span>
            <strong>Show boundaries</strong>
            <br />
            <small>Compare results by standard geography.</small>
          </span>
        </label>

        <button
          className="button primary"
          type="submit"
          style={{ width: '100%', marginTop: 16 }}
          disabled={running && !dirty}
        >
          {running ? (
            <>
              <span className="spinner" aria-hidden="true" />
              Running analysis…
            </>
          ) : (
            'Run analysis'
          )}
        </button>
        {dirty && (
          <button
            type="button"
            className="button ghost small"
            style={{ width: '100%', marginTop: 8 }}
            onClick={onDiscard}
          >
            Discard changes
          </button>
        )}
      </form>
    </aside>
  );
}

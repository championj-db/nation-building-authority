import { useMemo } from 'react';
import { X } from 'lucide-react';
import type { Analysis } from '../lib/analysis';
import { sql, useBaseParams, useRows } from '../lib/data';
import { km, people, pct, plural } from '../lib/format';
import {
  EVIDENCE_LABEL,
  defaultEvidence,
  priorities,
  priorityRationale,
  recommendedStep,
  type DistributionRow,
  type RegionAccess,
} from '../lib/model';
import { GEO_LEVEL_NOUN, SCOPE_LABELS, type AnalysisSettings } from '../lib/settings';
import { ClassLabel, ErrorNotice, PanelSkeleton, Skeleton } from './primitives';

interface Props {
  analysis: Analysis;
  settings: AnalysisSettings;
  serviceLabel: string;
  status: 'ready' | 'updating' | 'updated' | 'draft';
  selected: RegionAccess | null;
  placing: boolean;
  onFocusRegion: (code: string) => void;
  onClearSelection: () => void;
  onAddNote: (row: RegionAccess) => void;
  onStartPlacing: () => void;
  onRemoveSite: (index: number) => void;
  onClearSites: () => void;
}

const STATUS_LABEL = { ready: 'Ready', updating: 'Updating', updated: 'Updated', draft: 'Draft settings' } as const;

export function DecisionSignals(props: Props) {
  const { analysis, settings, serviceLabel, status, selected } = props;
  const { summary, access, remoteness, notes, minCount } = analysis;
  const row = summary.row;
  const beyondRegions = access.rows.filter((r) => r.access_class === 'beyond').length;
  const top = useMemo(() => priorities(access.rows, 3), [access.rows]);
  const share = row?.persons && row.persons_beyond != null ? row.persons_beyond / row.persons : null;
  const refreshing = summary.refreshing || access.refreshing;

  return (
    <aside className="panel results" aria-labelledby="signals-title">
      <div className="panel-head">
        <h2 id="signals-title">Decision signals</h2>
        <span className={`tag${status === 'ready' ? ' neutral' : ''}`} aria-live="polite">
          {STATUS_LABEL[status]}
        </span>
      </div>
      <div className={`panel-body${refreshing ? ' refreshing' : ''}`}>
        {selected && <SelectedRegion {...props} row={selected} />}

        {summary.error ? (
          <ErrorNotice title="Headline figures did not load" message={summary.error} />
        ) : summary.loading || !row ? (
          <PanelSkeleton lines={6} />
        ) : (
          <>
            <div className="metric">
              <div className="metric-label">People beyond threshold</div>
              <div className="metric-value">{people(row.persons_beyond, minCount)}</div>
              <span className="metric-note">
                {pct(share)} of {people(row.persons, minCount)} modelled residents in {SCOPE_LABELS[settings.scope]}
              </span>
            </div>
            <div className="metric">
              <div className="metric-label">{capitalise(GEO_LEVEL_NOUN[settings.geoLevel])} beyond threshold</div>
              {access.loading ? (
                <Skeleton width={112} height={30} style={{ marginTop: 6 }} />
              ) : (
                <div className="metric-value">
                  {beyondRegions} of {access.rows.filter((r) => r.access_class !== 'no_population').length}
                </div>
              )}
              <span className="metric-note">Where the median resident lives further than {settings.threshold} km</span>
            </div>
            <div className="metric">
              <div className="metric-label">Threshold tested</div>
              <div className="metric-value">{settings.threshold} km</div>
              <span className="metric-note">
                Straight-line proximity, not road travel · median resident {km(row.median_km)}
              </span>
            </div>
            <div className="metric">
              <div className="metric-label">Priority cohorts beyond threshold</div>
              <dl className="kv" style={{ marginTop: 8, fontSize: 'var(--text-sm)' }}>
                <dt>People aged 65+</dt>
                <dd>{people(row.persons_65_beyond, minCount)}</dd>
                <dt>Households without a car</dt>
                <dd>{people(row.households_no_vehicle_beyond, minCount)}</dd>
              </dl>
              <span className="metric-note">Vehicle access is modelled from remoteness, not measured.</span>
            </div>
          </>
        )}

        {remoteness.rows.length > 0 && (
          <>
            <h3 className="section-title">
              By remoteness <span className="xs muted">share beyond {settings.threshold} km</span>
            </h3>
            <div className="bars">
              {remoteness.rows.map((r) => (
                <div className="bar-row" key={r.ra_class}>
                  <span>{r.ra_label}</span>
                  <div className="bar-track" aria-hidden="true">
                    <div className="bar-fill" style={{ width: `${Math.round((r.share_beyond ?? 0) * 100)}%` }} />
                  </div>
                  <span className="mono" style={{ textAlign: 'right' }}>
                    {r.persons == null ? `<${minCount}` : pct(r.share_beyond, 0)}
                  </span>
                </div>
              ))}
            </div>
          </>
        )}

        <Scenario {...props} />

        <h3 className="section-title">Review priorities</h3>
        {access.loading ? (
          <PanelSkeleton lines={3} />
        ) : top.length === 0 ? (
          <p className="muted small" style={{ marginTop: 8 }}>
            No {GEO_LEVEL_NOUN[settings.geoLevel]} are beyond or near the {settings.threshold} km threshold. Try a lower
            threshold or a finer geography.
          </p>
        ) : (
          top.map((r) => {
            const note = notes.byRegion.get(r.region_code);
            const status = note?.evidence_status ?? defaultEvidence(r.access_class);
            return (
              <button
                type="button"
                className="priority"
                key={r.region_code}
                onClick={() => props.onFocusRegion(r.region_code)}
              >
                <div className="priority-top">
                  <strong>{r.region_name}</strong>
                  <span className={`tag${status === 'validated' ? ' ok' : ''}`}>
                    {note ? EVIDENCE_LABEL[status] : 'Review'}
                  </span>
                </div>
                <p>
                  {priorityRationale(r, serviceLabel, settings.threshold, minCount)}{' '}
                  {note?.next_step || recommendedStep(r)}.
                </p>
              </button>
            );
          })
        )}
      </div>
    </aside>
  );
}

function gainText(value: number | null, minCount: number) {
  if (value == null) return `<${minCount}`;
  return value === 0 ? '0' : `+${people(value, minCount)}`;
}

function capitalise(s: string) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function SelectedRegion({
  analysis,
  settings,
  row,
  onClearSelection,
  onAddNote,
  onStartPlacing,
  placing,
}: Props & { row: RegionAccess }) {
  const base = useBaseParams();
  const params = useMemo(
    () => ({
      ...base,
      geo_level: sql.string(settings.geoLevel),
      region_code: sql.string(row.region_code),
      service: sql.string(settings.service),
      min_count: sql.int(analysis.minCount),
    }),
    [base, settings.geoLevel, row.region_code, settings.service, analysis.minCount]
  );
  const dist = useRows('region_distribution', params);
  // Every 10 km band from 0 to 150+, so the axis reads to scale even where a band is empty.
  const buckets = useMemo(() => {
    const rows = (dist.data ?? []) as DistributionRow[];
    if (!rows.length) return [];
    const byKm = new Map(rows.map((r) => [r.bucket_km, r]));
    return Array.from(
      { length: 16 },
      (_, i) => byKm.get(i * 10) ?? { bucket_km: i * 10, persons: 0, suppressed: false }
    );
  }, [dist.data]);
  const max = Math.max(1, ...buckets.map((b) => b.persons ?? 0));
  const note = analysis.notes.byRegion.get(row.region_code);
  return (
    <section className="selected-card" aria-label={`Selected: ${row.region_name}`} style={{ marginBottom: 16 }}>
      <div className="priority-top">
        <div>
          <strong>{row.region_name}</strong>
          <div className="xs muted">{row.state_abbr}</div>
        </div>
        <button
          type="button"
          className="button small icon-button ghost"
          aria-label="Clear selection"
          onClick={onClearSelection}
        >
          <X className="icon" aria-hidden="true" />
        </button>
      </div>
      <div style={{ marginTop: 8 }}>
        <ClassLabel value={row.access_class} />
      </div>
      <dl className="kv" style={{ marginTop: 8 }}>
        <dt>Residents</dt>
        <dd>{people(row.persons, analysis.minCount)}</dd>
        <dt>Beyond {settings.threshold} km</dt>
        <dd>
          {people(row.persons_beyond, analysis.minCount, row.persons_beyond == null)} ({pct(row.share_beyond)})
        </dd>
        <dt>Median · 90th percentile</dt>
        <dd>
          {km(row.median_km)} · {km(row.p90_km)}
        </dd>
        <dt>Evidence status</dt>
        <dd>{EVIDENCE_LABEL[note?.evidence_status ?? defaultEvidence(row.access_class)]}</dd>
      </dl>
      {buckets.length > 0 && (
        <figure style={{ margin: '12px 0 0' }}>
          <figcaption className="xs muted">Residents by distance to nearest site (10 km bands)</figcaption>
          <div className="histogram" role="img" aria-label={`Distance distribution for ${row.region_name}`}>
            {buckets.map((b) => (
              <div
                key={b.bucket_km}
                className={`col${b.suppressed ? ' hidden' : b.bucket_km >= settings.threshold ? ' over' : ''}`}
                style={{ height: `${b.suppressed ? 8 : Math.max(2, ((b.persons ?? 0) / max) * 100)}%` }}
                title={`${b.bucket_km}${b.bucket_km >= 150 ? '+' : `–${b.bucket_km + 10}`} km: ${people(b.persons, analysis.minCount, b.suppressed)}`}
              />
            ))}
          </div>
          <div className="histogram-axis">
            <span>0</span>
            <span>75</span>
            <span>150+ km</span>
          </div>
        </figure>
      )}
      <div className="row">
        <button type="button" className="button small" onClick={() => onAddNote(row)}>
          Add review note
        </button>
        {row.access_class !== 'within' && row.access_class !== 'no_population' && (
          <button
            type="button"
            className="button small"
            onClick={onStartPlacing}
            disabled={placing || settings.sites.length >= 5}
          >
            Test a site here
          </button>
        )}
      </div>
    </section>
  );
}

function Scenario({ analysis, settings, onStartPlacing, onRemoveSite, onClearSites, placing }: Props) {
  const { scenario, summary, minCount } = analysis;
  if (!settings.sites.length) {
    return (
      <>
        <h3 className="section-title">New-site scenario</h3>
        <p className="muted small" style={{ marginTop: 8 }}>
          Propose up to five sites on the map to see how many people would move within {settings.threshold} km.
        </p>
        <button
          type="button"
          className="button small"
          style={{ marginTop: 12 }}
          onClick={onStartPlacing}
          disabled={placing}
        >
          {placing ? 'Click the map…' : 'Propose a site'}
        </button>
      </>
    );
  }
  const gained = scenario.total?.persons_gained ?? null;
  const beyond = summary.row?.persons_beyond ?? null;
  const reduction = gained != null && beyond ? gained / beyond : null;
  return (
    <section className="scenario-card" aria-labelledby="scenario-title">
      <div className="priority-top">
        <strong id="scenario-title">New-site scenario · {plural(settings.sites.length, 'site')}</strong>
        <button type="button" className="button small ghost" onClick={onClearSites}>
          Clear
        </button>
      </div>
      {scenario.error ? (
        <div style={{ marginTop: 8 }}>
          <ErrorNotice title="Scenario did not run" message={scenario.error} />
        </div>
      ) : scenario.loading ? (
        <div style={{ marginTop: 8 }}>
          <PanelSkeleton lines={2} />
        </div>
      ) : (
        <>
          <div className="metric-value" style={{ fontSize: 'var(--text-xl)', marginTop: 8 }}>
            {gained == null ? `Fewer than ${minCount}` : `+${people(gained, minCount)}`}
          </div>
          <span className="metric-note">
            people brought within {settings.threshold} km
            {reduction != null ? ` · ${pct(reduction)} fewer beyond the threshold` : ''}
          </span>
          {scenario.total && (
            <dl className="kv" style={{ marginTop: 8 }}>
              <dt>Aged 65+</dt>
              <dd>{gainText(scenario.total.persons_65_gained, minCount)}</dd>
              <dt>Households without a car</dt>
              <dd>{gainText(scenario.total.households_no_vehicle_gained, minCount)}</dd>
            </dl>
          )}
          {scenario.regions.length > 0 && (
            <p className="xs muted" style={{ marginTop: 8 }}>
              Most gain in{' '}
              {scenario.regions
                .slice(0, 3)
                .map((r) => r.region_name)
                .join(', ')}
              .
            </p>
          )}
        </>
      )}
      <ul className="site-list">
        {settings.sites.map((s, i) => (
          <li key={`${s.lon},${s.lat}`}>
            <span className="mono">
              {i + 1}. {s.lat.toFixed(3)}, {s.lon.toFixed(3)}
            </span>
            <button
              type="button"
              className="button small ghost"
              aria-label={`Remove proposed site ${i + 1}`}
              onClick={() => onRemoveSite(i)}
            >
              Remove
            </button>
          </li>
        ))}
      </ul>
      {settings.sites.length < 5 && (
        <button
          type="button"
          className="button small"
          style={{ marginTop: 8 }}
          onClick={onStartPlacing}
          disabled={placing}
        >
          {placing ? 'Click the map…' : 'Add another site'}
        </button>
      )}
      <p className="xs muted" style={{ marginTop: 8 }}>
        Estimated per H3 cell (~0.7 km²), straight-line. A test of reach, not a siting recommendation.
      </p>
    </section>
  );
}

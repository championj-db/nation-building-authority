import { useBaseParams, useRows } from '../lib/data';
import { dateTime } from '../lib/format';
import { ErrorNotice, PanelSkeleton } from './primitives';

export interface MetricRow {
  step_order: number;
  step: string;
  metric: string;
  value: number | null;
  detail: string | null;
}
interface SourceRow {
  dataset: string;
  step: string;
  publisher: string;
  source_url: string;
  attribution: string;
  licence: string;
  features: number | null;
  from_cache: boolean;
  fetch_error: string | null;
  fetched_at: string;
}

const STEPS = [
  {
    key: 'ingest',
    title: 'Spatial ingest',
    body: 'Conform geometries and projections from approved public sources: ABS boundaries and population, national service registers.',
  },
  {
    key: 'index',
    title: 'Spatial index',
    body: 'Apply H3 indexing so large-scale joins remain tractable. Synthetic households are placed inside real SA1s with ST_Contains.',
  },
  {
    key: 'analysis',
    title: 'Proximity and containment',
    body: 'Calculate nearest service and point-in-boundary relationships, pruned with H3 so the nearest site is exact, not approximate.',
  },
  {
    key: 'aggregate',
    title: 'Governed aggregates',
    body: 'Aggregate to standard geographies in 1 km distance bands. Suppression controls apply when results are served.',
  },
  {
    key: 'serve',
    title: 'Map-ready serving',
    body: 'Publish reviewable outputs for analysis and briefing, queried on behalf of each officer under Unity Catalog.',
  },
];

const compact = new Intl.NumberFormat('en-AU', { notation: 'compact', maximumFractionDigits: 1 });
function show(m: MetricRow) {
  if (m.value == null) return '–';
  if (m.metric === 'Refreshed') return dateTime(m.value * 1000);
  if (m.value > 0 && m.value < 1) return `${(m.value * 100).toFixed(1)}%`;
  return m.value >= 100_000 ? compact.format(m.value) : m.value.toLocaleString('en-AU');
}

export function PipelineView() {
  const base = useBaseParams();
  const metrics = useRows('pipeline_metrics', base);
  const sources = useRows('data_sources', base);
  const rows = (metrics.data ?? []) as MetricRow[];
  const src = (sources.data ?? []) as SourceRow[];
  const allPairs = rows.find((m) => m.metric === 'All-pairs distance calculations')?.value ?? null;
  const pruned = rows.find((m) => m.metric === 'Calculations after H3 pruning')?.value ?? null;
  const cached = src.filter((s) => s.from_cache);

  return (
    <div className="empty-view">
      <div className="panel">
        <div className="panel-head">
          <h2>From source to map-ready evidence</h2>
          <span className="status">Serverless pattern</span>
        </div>
        <div className="panel-body">
          {metrics.error && <ErrorNotice title="Pipeline metrics did not load" message={metrics.error} />}
          <ol className="process">
            {STEPS.map((step, i) => {
              const stepMetrics = rows.filter((m) => m.step === step.key);
              return (
                <li key={step.key}>
                  <span className="step">{i + 1}</span>
                  <div>
                    <strong>{step.title}</strong>
                    <p>{step.body}</p>
                    {metrics.loading ? (
                      <div style={{ marginTop: 8 }}>
                        <PanelSkeleton lines={1} />
                      </div>
                    ) : (
                      stepMetrics.length > 0 && (
                        <div className="stat-row">
                          {stepMetrics.map((m) => (
                            <span key={m.metric} title={m.detail ?? undefined}>
                              {m.metric} <strong>{show(m)}</strong>
                            </span>
                          ))}
                        </div>
                      )
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
          {allPairs != null && pruned != null && (
            <div className="highlight">
              <div className="metric-label">H3 pruning for nearest-service search</div>
              <div className="metric-value">
                {((pruned / allPairs) * 100).toFixed(pruned / allPairs < 0.01 ? 3 : 1)}% of all-pairs work
              </div>
              <span className="metric-note">
                {compact.format(pruned)} distance calculations instead of {compact.format(allPairs)}, with the same
                exact answer.
              </span>
            </div>
          )}
        </div>
      </div>
      <div className="assurance-stack">
        <aside className="panel">
          <div className="panel-head">
            <h2>Platform pattern</h2>
          </div>
          <div className="panel-body">
            {[
              ['Ingest', 'Lakeflow Jobs'],
              ['Analysis', 'SQL + H3'],
              ['Governance', 'Unity Catalog'],
              ['Presentation', 'Databricks Apps'],
            ].map(([label, value]) => (
              <div className="metric" key={label}>
                <div className="metric-label">{label}</div>
                <div className="platform-value">{value}</div>
              </div>
            ))}
          </div>
        </aside>
        <aside className="panel">
          <div className="panel-head">
            <h2>Public sources</h2>
            <span className={`status${cached.length ? ' warn' : ''}`}>
              {cached.length ? `${cached.length} from cache` : 'All live'}
            </span>
          </div>
          <div className="panel-body">
            {sources.loading ? (
              <PanelSkeleton lines={4} />
            ) : sources.error ? (
              <ErrorNotice title="Sources did not load" message={sources.error} />
            ) : (
              <ul className="source-list">
                {dedupe(src).map((s) => (
                  <li key={s.dataset}>
                    <strong>{sourceTitle(s)}</strong>
                    <div className="xs muted">
                      {s.publisher} · {s.licence}
                      {s.features != null ? ` · ${s.features.toLocaleString('en-AU')} features` : ''}
                    </div>
                    <div className="xs muted">
                      Fetched {dateTime(s.fetched_at)}
                      {s.from_cache ? ' · source unreachable, last good copy used' : ''}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}

const TITLES: Record<string, string> = {
  asgs2021: 'ASGS Edition 3 boundaries (SA1–SA4, LGA, Remoteness Area, state)',
  abs_erp_sa2_age: 'Estimated resident population by SA2 and age',
  service_public_hospital: 'Declared Public Hospitals',
  service_urgent_care: 'Medicare Urgent Care Clinics',
  service_residential_aged_care: 'Australian Aged Care Services (residential)',
  service_ambulance_station: 'Emergency Management Facilities: ambulance stations',
};
function sourceTitle(s: SourceRow) {
  return TITLES[s.dataset] ?? s.attribution.split(',')[0];
}

/** Boundary layers are fetched per level; show one row per ABS product rather than eleven. */
function dedupe(rows: SourceRow[]) {
  const boundaries = rows.filter((r) => r.step === 'boundaries');
  const others = rows.filter((r) => r.step !== 'boundaries');
  if (!boundaries.length) return others;
  const first = boundaries[0];
  return [
    {
      ...first,
      dataset: 'asgs2021',
      attribution: 'ABS ASGS Edition 3 boundaries: SA1 to SA4, LGA, Remoteness Area and state',
      features: boundaries.reduce((n, b) => n + (b.features ?? 0), 0),
      from_cache: boundaries.some((b) => b.from_cache),
    },
    ...others,
  ];
}

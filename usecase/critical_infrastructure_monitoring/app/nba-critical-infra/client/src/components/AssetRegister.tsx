import { formatInt, formatPeople, formatTime } from '../lib/format';
import { FACTOR_LABELS, type Factor } from '../lib/model';
import type { IncidentRow, RegisterRow } from '../lib/rows';
import { SectorBadge } from './icons';
import { EmptyState, ErrorState, Skeleton } from './primitives';

interface Props {
  rows: RegisterRow[] | null;
  incidentsByAsset: Map<string, IncidentRow>;
  loading: boolean;
  error: string | null;
  onReview: (incident: IncidentRow) => void;
}

/** Highest-risk assets across every sector, with what drives each score. */
export function AssetRegister({ rows, incidentsByAsset, loading, error, onReview }: Props) {
  const runTs = rows?.[0]?.run_ts;
  return (
    <section className="section" id="assets" aria-labelledby="assets-heading">
      <div className="container">
        <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
          <div className="row-between panel-head">
            <div>
              <h2 id="assets-heading">Asset risk register</h2>
              <p className="lead">The highest-risk assets across all sectors and operators, and the factor driving each score.</p>
            </div>
            <span className="tag">{runTs ? `Updated ${formatTime(runTs)}` : 'Updating…'}</span>
          </div>
          {error && !rows ? (
            <div style={{ padding: 20 }}>
              <ErrorState title="The asset register could not load" message={error} />
            </div>
          ) : loading ? (
            <div style={{ padding: 20, display: 'grid', gap: 12 }} aria-busy="true">
              {[0, 1, 2, 3, 4].map((i) => (
                <Skeleton key={i} height={22} />
              ))}
            </div>
          ) : !rows || rows.length === 0 ? (
            <div style={{ padding: 20 }}>
              <EmptyState title="No scored assets yet">Run the pipeline job to score the network.</EmptyState>
            </div>
          ) : (
            <div className="ds-table-wrap">
              <table className="ds-table">
                <caption className="sr-only">Highest-risk assets. Select a row to review its incident.</caption>
                <thead>
                  <tr>
                    <th scope="col">Asset</th>
                    <th scope="col">Sector</th>
                    <th scope="col">Operator</th>
                    <th scope="col">Driving factor</th>
                    <th scope="col" className="num-col">People relying</th>
                    <th scope="col" className="num-col">Risk</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => {
                    const incident = incidentsByAsset.get(String(row.asset_id));
                    const sev = row.risk_rating === 'extreme' ? 'critical' : String(row.risk_rating);
                    const factor = FACTOR_LABELS[String(row.dominant_factor) as Factor] ?? row.dominant_factor;
                    const open = () => incident && onReview(incident);
                    return (
                      <tr
                        key={String(row.asset_id)}
                        tabIndex={incident ? 0 : -1}
                        className={incident ? undefined : 'inert-row'}
                        aria-label={incident ? `Review ${row.asset_name}, risk ${row.risk_score}` : `${row.asset_name}, risk ${row.risk_score}, below the incident threshold`}
                        onClick={open}
                        onKeyDown={(e) => {
                          if (incident && (e.key === 'Enter' || e.key === ' ')) {
                            e.preventDefault();
                            open();
                          }
                        }}
                      >
                        <td>
                          <strong>{row.asset_name}</strong>
                          <div className="meta">
                            {row.asset_code} · {row.locality}, {row.state}
                          </div>
                        </td>
                        <td>
                          <SectorBadge sector={String(row.sector)} />
                        </td>
                        <td>{row.operator_name}</td>
                        <td>
                          {factor}
                          {row.dominant_factor === 'limit_exceedance' || row.dominant_factor === 'anomaly' ? <div className="meta">{row.trigger_metric_label}</div> : null}
                        </td>
                        <td className="num-col">{formatPeople(row.people_affected)}</td>
                        <td className="num-col">
                          <span className="risk-score">{formatInt(row.risk_score)}</span>
                          <div className={`sev ${sev}`} style={{ justifyContent: 'flex-end', display: 'flex' }}>
                            {row.risk_rating}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

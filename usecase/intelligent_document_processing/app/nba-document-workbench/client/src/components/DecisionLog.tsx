import { CHECK_LABELS, DOC_TYPES } from '../../../shared/contracts';
import { useDecisionsContext } from '../lib/data';
import { timeOfDay, weekday } from '../lib/format';
import { Empty, ErrorNotice, PanelHead, SkeletonRows } from './primitives';

const LABEL: Record<string, string> = {
  accepted: 'Accepted',
  returned: 'Returned to supplier',
  reclassified: 'Reclassified',
  actioned: 'Actioned',
};

export function DecisionLog({ onOpen }: { onOpen: (id: string) => void }) {
  const d = useDecisionsContext();
  return (
    <div className="content">
      <div className="page-head">
        <div>
          <h1>Decision log</h1>
          <p className="page-intro">
            Every decision recorded in this workbench: who made it, when, what the machine said at the time, and what
            they changed. Decisions are final and are copied into Unity Catalog by the feedback job.
          </p>
        </div>
      </div>
      {d.error && <ErrorNotice message={d.error} onRetry={d.reload} />}
      <section className="card" aria-labelledby="log-title">
        <PanelHead id="log-title" title={`${d.decisions.length} decisions`} copy="Newest first." />
        {d.loading && !d.decisions.length ? (
          <SkeletonRows rows={6} height={30} />
        ) : !d.enabled ? (
          <Empty title="The review store is not connected">
            Decisions are kept in Lakebase. Connect it to record and see them.
          </Empty>
        ) : !d.decisions.length ? (
          <Empty title="No decisions yet">Open an invoice from the review queue to record the first one.</Empty>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th scope="col">When</th>
                  <th scope="col">Document</th>
                  <th scope="col">Decision</th>
                  <th scope="col">Machine status then</th>
                  <th scope="col" className="num">
                    Fields corrected
                  </th>
                  <th scope="col" className="num">
                    Handling
                  </th>
                  <th scope="col">By</th>
                </tr>
              </thead>
              <tbody>
                {d.decisions.map((r) => (
                  <tr key={r.decision_id}>
                    <td style={{ whiteSpace: 'nowrap' }}>
                      {weekday(r.decided_at)} {timeOfDay(r.decided_at)}
                    </td>
                    <td>
                      <button className="link-button mono" onClick={() => onOpen(r.doc_id)}>
                        {r.doc_id}
                      </button>
                      <div className="doc-meta">{DOC_TYPES[r.doc_type as keyof typeof DOC_TYPES] ?? r.doc_type}</div>
                    </td>
                    <td>
                      {LABEL[r.decision] ?? r.decision}
                      {r.reason_codes.length > 0 && (
                        <div className="doc-meta">{r.reason_codes.map((c) => CHECK_LABELS[c] ?? c).join(', ')}</div>
                      )}
                      {r.note && <div className="doc-meta">&ldquo;{r.note}&rdquo;</div>}
                    </td>
                    <td>
                      {r.status_seen.replace('_', ' ')}
                      {r.lowest_confidence_seen != null && (
                        <div className="doc-meta">lowest field {Math.round(r.lowest_confidence_seen * 100)}%</div>
                      )}
                    </td>
                    <td className="num mono">{r.fields_corrected}</td>
                    <td className="num mono">
                      {r.handling_seconds < 60 ? `${r.handling_seconds}s` : `${Math.round(r.handling_seconds / 60)}m`}
                    </td>
                    <td>{r.decided_by}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

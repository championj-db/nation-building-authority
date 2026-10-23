import { useState } from 'react';
import { Skeleton } from '@databricks/appkit-ui/react';
import { sql } from '@databricks/appkit-ui/js';
import { useQuery } from '../lib/query';
import { Empty, Modal, QueryError, Segmented, StatusBadge, statusTone } from '../components/common';
import { postJson } from '../lib/api';
import { date, dateTime, personName } from '../lib/format';
import { useAppState } from '../lib/state';

type ActionKind = 'Attested' | 'Comment' | 'Action raised' | 'Closed';
type Filter = 'open' | 'all';

export function AssurancePage() {
  const { dataVersion } = useAppState();
  const register = useQuery('assurance_register', { data_version: sql.string(dataVersion) });
  const [filter, setFilter] = useState<Filter>('open');
  const [action, setAction] = useState<{ recordId: string; record: string; kind: ActionKind } | null>(null);
  const rows = register.data ?? [];
  const open = rows.filter((r) => ['Action required', 'Awaiting attestation', 'Working'].includes(String(r.approval_status)));
  const shown = filter === 'open' ? open : rows;
  const today = new Date();
  const overdue = rows.filter((r) => r.next_review_due && new Date(String(r.next_review_due)) < today).length;

  return (
    <section className="page active" aria-labelledby="assurance-title">
      <div className="page-head">
        <div>
          <p className="eyebrow">Assurance register</p>
          <h1 id="assurance-title">Forecast assumptions and Gateway assurance</h1>
          <p className="subtitle">Every material input to the forecast, with its owner, evidence and approval state. Owners attest assumptions here; attestations are recorded against the record and the person.</p>
        </div>
        <div className="freshness"><strong>{rows.length} records · {open.length} open</strong>{overdue} past review date</div>
      </div>
      <div className="filters"><Segmented label="Show" value={filter} onChange={setFilter} options={[['open', `Needs action (${open.length})`], ['all', `All records (${rows.length})`]]} /></div>
      <article className="card">
        {register.loading && rows.length === 0 && <Skeleton className="table-skeleton" />}
        {register.error && <QueryError message={`Assurance records could not load: ${register.error}`} />}
        {!register.loading && !register.error && shown.length === 0 && <Empty>Nothing needs action.</Empty>}
        {shown.length > 0 && (
          <div className="table-wrap"><table><thead><tr><th>Record</th><th>Type</th><th>Owner</th><th>Confidence</th><th>Status</th><th>Review due</th><th /></tr></thead><tbody>
            {shown.map((r) => {
              const status = String(r.approval_status);
              const due = r.next_review_due ? new Date(String(r.next_review_due)) : null;
              return (
                <tr key={String(r.record_id)}>
                  <td><strong>{r.record}</strong><small className="table-subtitle">{r.evidence_reference} · {r.value_summary}</small>
                    {r.last_action && <small className="table-subtitle activity">{r.last_action}: {r.last_action_comment ? `"${String(r.last_action_comment)}" ` : ''}— {personName(String(r.last_action_actor))}, {dateTime(r.last_action_at)}</small>}</td>
                  <td>{r.record_type}</td>
                  <td>{r.owner}</td>
                  <td>{r.confidence}</td>
                  <td><StatusBadge tone={statusTone(status)}>{status}</StatusBadge></td>
                  <td><span className={due && due < today ? 'delta bad' : ''}>{date(r.next_review_due)}</span></td>
                  <td className="row-actions">
                    {status === 'Awaiting attestation' && <button className="button small primary" onClick={() => setAction({ recordId: String(r.record_id), record: String(r.record), kind: 'Attested' })}>Attest</button>}
                    {status === 'Action required' && <button className="button small" onClick={() => setAction({ recordId: String(r.record_id), record: String(r.record), kind: r.last_action === 'Action raised' ? 'Closed' : 'Action raised' })}>{r.last_action === 'Action raised' ? 'Close action' : 'Raise action'}</button>}
                    <button className="button small" onClick={() => setAction({ recordId: String(r.record_id), record: String(r.record), kind: 'Comment' })}>Comment</button>
                  </td>
                </tr>
              );
            })}
          </tbody></table></div>
        )}
      </article>
      {action && <ActionModal {...action} onClose={() => setAction(null)} />}
    </section>
  );
}

function ActionModal({ recordId, record, kind, onClose }: { recordId: string; record: string; kind: ActionKind; onClose: () => void }) {
  const { notify, refresh, identity } = useAppState();
  const [comment, setComment] = useState('');
  const [saving, setSaving] = useState(false);
  const title = { Attested: 'Attest assumption', Comment: 'Add comment', 'Action raised': 'Raise remediation action', Closed: 'Close action' }[kind];
  const save = async () => {
    setSaving(true);
    try {
      await postJson('/api/assurance-actions', { record_id: recordId, action: kind, comment });
      notify(`${title}: ${record}`, 'good');
      refresh(3000);
      onClose();
    } catch (e) {
      notify(e instanceof Error ? e.message : 'Could not save', 'bad');
    } finally {
      setSaving(false);
    }
  };
  return (
    <Modal title={title} eyebrow={record} onClose={onClose}>
      {kind === 'Attested' && <p className="muted-small">I, {identity?.email ?? 'the owner'}, confirm this assumption is current, supported by the referenced evidence, and appropriate for the forecast.</p>}
      <div className="field"><label htmlFor="as-comment">{kind === 'Attested' ? 'Comment (optional)' : 'Comment'}</label><textarea id="as-comment" className="textarea" rows={4} value={comment} onChange={(e) => setComment(e.target.value)} /></div>
      <div className="modal-actions"><button className="button" onClick={onClose}>Cancel</button><button className="button primary" onClick={save} disabled={saving || (kind !== 'Attested' && !comment.trim())}>{saving ? 'Saving…' : title}</button></div>
    </Modal>
  );
}

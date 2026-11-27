import { ChevronRight } from 'lucide-react';
import { DOC_TYPES } from '../../../shared/contracts';
import { list } from '../lib/data';
import { money, received } from '../lib/format';
import { clockText, dueText } from '../lib/queue';
import type { QueueRow } from '../lib/types';
import { scoreTitle } from '../lib/confidence';
import { Empty, StatusText } from './primitives';

const CHECK_SHORT: Record<string, string> = {
  addressed_to_buyer: 'wrong addressee',
  tax_invoice_label: 'not a tax invoice',
  supplier_abn_valid: 'invalid ABN',
  supplier_abn_matches_vendor: 'ABN mismatch',
  recipient_identity: 'no recipient',
  po_quoted: 'no PO',
  po_matches: 'PO mismatch',
  gst_calculated: 'GST error',
  within_po_value: 'over order value',
  not_duplicate: 'duplicate',
  delivery_acknowledged: 'no receipt',
};

function lowestField(r: QueueRow) {
  const held = list(r.held_fields).length;
  if (r.status === 'exception') {
    const failed = list(r.failed_checks).map((c) => CHECK_SHORT[c] ?? c);
    return {
      value: failed[0] ?? 'failed',
      note: failed.length > 1 ? `+${failed.length - 1} more` : 'failed check',
      low: true,
      title: 'A correctly rendered check failed',
    };
  }
  const c = r.lowest_required_confidence;
  return {
    value: held ? `${held} held` : c == null ? '-' : 'Confident',
    note: '',
    low: held > 0,
    title: scoreTitle(c),
  };
}

export function QueueList({
  rows,
  onOpen,
  limit,
  showHead = false,
}: {
  rows: QueueRow[];
  onOpen: (docId: string) => void;
  limit?: number;
  showHead?: boolean;
}) {
  const shown = limit ? rows.slice(0, limit) : rows;
  if (!rows.length) {
    return <Empty title="Nothing waiting here">New invoices appear here as soon as they are parsed and checked.</Empty>;
  }
  return (
    <div className="queue-list" role="list">
      {showHead && (
        <div className="queue-head" aria-hidden="true">
          <span>Document</span>
          <span>Status</span>
          <span>Fields</span>
          <span>Payment clock</span>
          <span />
        </div>
      )}
      {shown.map((r) => {
        const lf = lowestField(r);
        const clock = clockText(r);
        const type = DOC_TYPES[r.doc_type as keyof typeof DOC_TYPES] ?? r.doc_type;
        return (
          <button key={r.doc_id} className="queue-row" role="listitem" onClick={() => onOpen(r.doc_id)}>
            <span style={{ minWidth: 0 }}>
              <span className="doc-title">{r.supplier_name ?? 'Unidentified supplier'}</span>
              <span className="doc-meta">
                {type} <span className="mono">{r.invoice_number ?? ''}</span> ·{' '}
                <span className="mono">{money(r.total_inc_gst)}</span>
                <span className="received"> · received {received(r.arrival_ts)}</span>
              </span>
            </span>
            <StatusText status={r.status} label={r.status_label} />
            <span className={`confidence${lf.low ? ' low' : ''}`} title={lf.title}>
              {lf.value}
              {lf.note && <small>{lf.note}</small>}
            </span>
            <span className={`clock ${r.clock_state}`} title={clock.long}>
              {clock.short}
              <small>{dueText(r)}</small>
            </span>
            <ChevronRight className="arrow" aria-hidden="true" />
            <span className="sr-only">{clock.long}</span>
          </button>
        );
      })}
    </div>
  );
}

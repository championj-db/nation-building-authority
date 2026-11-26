import { useMemo } from 'react';
import { BadgeCheck, Building2, ClipboardCheck, Landmark, Mail, MapPin, Phone, User, UserRound, type LucideIcon } from 'lucide-react';
import { edgePath, layoutGraph, type GraphEdge, type GraphNode } from '../lib/graphLayout';

const KIND_ICON: Record<string, LucideIcon> = {
  supplier: Building2,
  claimant: User,
  bank_account: Landmark,
  address: MapPin,
  phone: Phone,
  email: Mail,
  director: UserRound,
  officer: BadgeCheck,
  assessor: ClipboardCheck,
};

/**
 * The case's linked records, drawn from gold_case_graph_node/edge: the subject on the left, the
 * shared attributes in the middle, and the other entities they lead to on the right. The same
 * links are listed as text underneath, so the view never depends on reading the drawing.
 */
export function EntityGraph({ nodes, edges }: { nodes: GraphNode[]; edges: GraphEdge[] }) {
  const g = useMemo(() => layoutGraph(nodes, edges), [nodes, edges]);
  const byId = useMemo(() => new Map(g.nodes.map((n) => [n.node_id, n])), [g.nodes]);
  const subject = g.nodes.find((n) => n.role === 'subject');

  if (g.nodes.length === 0) {
    return (
      <div className="graph">
        <div className="empty" style={{ padding: 32 }}>
          <p>No linked records were retained for this case.</p>
        </div>
      </div>
    );
  }

  const description = `Relationship graph linking ${subject?.label ?? 'the case subject'} to ${g.nodes
    .filter((n) => n !== subject)
    .map((n) => `${n.label} (${n.sub_label.toLowerCase()})`)
    .join(', ')}`;

  return (
    <figure className="graph" style={{ margin: '16px 0 0' }}>
      <svg viewBox={`0 0 ${g.width} ${g.height}`} role="img" aria-label={description}>
        <g>
          {g.edges.map((e) => {
            const a = byId.get(e.src)!;
            const b = byId.get(e.dst)!;
            const p = edgePath(a, b);
            return (
              <line key={`${e.src}-${e.dst}`} className="graph-edge" x1={p.x1} y1={p.y1} x2={p.x2} y2={p.y2}>
                <title>{`${a.label} ${e.relation} ${b.label}`}</title>
              </line>
            );
          })}
        </g>
        {g.nodes.map((n) => {
          const Icon = KIND_ICON[n.kind] ?? Building2;
          return (
            <g key={n.node_id} className={`graph-node ${n.role}`} transform={`translate(${n.x} ${n.y})`}>
              <rect width={n.w} height={n.h} rx={12} />
              <Icon className="node-icon" x={10} y={(n.h - 16) / 2} width={16} height={16} strokeWidth={1.75} aria-hidden="true" />
              <text className="node-label" x={34} y={20}>
                {n.label}
              </text>
              <text className="node-sub" x={34} y={35}>
                {n.sub_label}
              </text>
            </g>
          );
        })}
      </svg>
      <ul className="graph-links" aria-label="Links">
        {g.edges.map((e) => (
          <li key={`${e.src}-${e.dst}`}>
            <strong>{byId.get(e.src)?.label}</strong> {e.relation} <strong>{byId.get(e.dst)?.label}</strong>
          </li>
        ))}
      </ul>
    </figure>
  );
}

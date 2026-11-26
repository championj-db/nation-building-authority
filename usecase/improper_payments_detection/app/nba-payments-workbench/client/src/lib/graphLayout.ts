/** Rows of gold_case_graph_node / gold_case_graph_edge for one case. */
export interface GraphNode {
  node_id: string;
  label: string;
  kind: string;
  sub_label: string;
  /** subject | link | related */
  role: string;
}
export interface GraphEdge {
  src: string;
  dst: string;
  relation: string;
}
export interface PlacedNode extends GraphNode {
  x: number;
  y: number;
  w: number;
  h: number;
}

export const NODE_H = 46;
const CHAR_W = 6.9;
export const nodeWidth = (n: GraphNode) => Math.round(Math.min(156, Math.max(104, 40 + CHAR_W * Math.max(n.label.length, n.sub_label.length))));

/**
 * Deterministic three-column layout: the case subject on the left, the shared attributes that
 * link it (accounts, addresses, officers) in the middle, and the other entities those attributes
 * lead to on the right. Each column is spread vertically and ordered so that related entities sit
 * beside the attribute that connects them, which keeps edges short and uncrossed.
 */
export function layoutGraph(nodes: readonly GraphNode[], edges: readonly GraphEdge[], width = 560, minHeight = 220) {
  const subject = nodes.find((n) => n.role === 'subject') ?? nodes[0];
  if (!subject) return { nodes: [] as PlacedNode[], edges: [] as GraphEdge[], width, height: minHeight };
  const neighbours = (id: string) =>
    edges.flatMap((e) => (e.src === id ? [e.dst] : e.dst === id ? [e.src] : [])).filter((x) => x !== id);

  const byId = new Map(nodes.map((n) => [n.node_id, n]));
  const middle = nodes
    .filter((n) => n !== subject && n.role !== 'related')
    .sort((a, b) => a.node_id.localeCompare(b.node_id));
  const placedRight = new Set<string>();
  const right: GraphNode[] = [];
  for (const m of middle) {
    for (const id of neighbours(m.node_id).sort()) {
      const n = byId.get(id);
      if (n && n.role === 'related' && !placedRight.has(id)) {
        placedRight.add(id);
        right.push(n);
      }
    }
  }
  for (const n of nodes) if (n.role === 'related' && !placedRight.has(n.node_id)) right.push(n);

  const rows = Math.max(middle.length, right.length, 1);
  const gap = 16;
  const height = Math.max(minHeight, rows * NODE_H + (rows - 1) * gap + 48);
  const column = (list: GraphNode[], cx: number): PlacedNode[] => {
    const total = list.length * NODE_H + Math.max(0, list.length - 1) * gap;
    const top = (height - total) / 2;
    return list.map((n, i) => {
      const w = nodeWidth(n);
      return { ...n, w, h: NODE_H, x: cx - w / 2, y: top + i * (NODE_H + gap) };
    });
  };
  const hasRight = right.length > 0;
  const cols = hasRight ? [0.17, 0.5, 0.83] : [0.25, 0.7];
  const placed = [
    ...column([subject], width * cols[0]),
    ...column(middle, width * cols[1]),
    ...(hasRight ? column(right, width * cols[2]) : []),
  ];
  const ids = new Set(placed.map((p) => p.node_id));
  return { nodes: placed, edges: edges.filter((e) => ids.has(e.src) && ids.has(e.dst)), width, height };
}

/** Where an edge leaves one box and enters another: the facing sides' midpoints. */
export function edgePath(a: PlacedNode, b: PlacedNode) {
  const [left, right] = a.x <= b.x ? [a, b] : [b, a];
  const sameColumn = Math.abs(left.x - right.x) < 4;
  if (sameColumn) {
    const [top, bottom] = a.y <= b.y ? [a, b] : [b, a];
    return { x1: top.x + top.w / 2, y1: top.y + top.h, x2: bottom.x + bottom.w / 2, y2: bottom.y };
  }
  return { x1: left.x + left.w, y1: left.y + left.h / 2, x2: right.x, y2: right.y + right.h / 2 };
}

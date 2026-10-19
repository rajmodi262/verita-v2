/**
 * Deterministic layout for the money-flow graph: time flows left → right.
 *
 * Each account sits at the median time of the payments touching it, so upstream senders land on
 * the left and onward receivers on the right. Accounts that share a time column are stacked,
 * alternating above and below the centre line, with the alerted account pinned to the middle.
 */
import type { GraphEdge, GraphNode } from "../../api/alerts";

export interface Position {
  x: number;
  y: number;
}

export const WIDTH = 900;
export const ROW = 70;
const COLUMNS = 12;

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  if (sorted.length === 0) return 0;
  return sorted.length % 2 ? (sorted[mid] ?? 0) : ((sorted[mid - 1] ?? 0) + (sorted[mid] ?? 0)) / 2;
}

export function layoutGraph(nodes: GraphNode[], edges: GraphEdge[]): Map<string, Position> {
  const times = new Map<string, number[]>();
  for (const e of edges) {
    const t = Date.parse(e.ts);
    for (const id of [e.from, e.to]) {
      const list = times.get(id) ?? [];
      list.push(t);
      times.set(id, list);
    }
  }
  const all = edges.map((e) => Date.parse(e.ts));
  const lo = all.length ? Math.min(...all) : 0;
  const hi = all.length ? Math.max(...all) : 1;
  const span = Math.max(hi - lo, 1);

  const columnOf = (id: string): number => {
    const t = median(times.get(id) ?? [lo]);
    return Math.round(((t - lo) / span) * (COLUMNS - 1));
  };

  const columns = new Map<number, GraphNode[]>();
  for (const node of [...nodes].sort(
    (a, b) => b.max_score - a.max_score || a.id.localeCompare(b.id),
  )) {
    const col = columnOf(node.id);
    const list = columns.get(col) ?? [];
    list.push(node);
    columns.set(col, list);
  }

  const positions = new Map<string, Position>();
  for (const [col, list] of columns) {
    const x = (col / (COLUMNS - 1)) * WIDTH;
    let slot = 0;
    const center = list.find((n) => n.is_center);
    if (center) positions.set(center.id, { x, y: 0 });
    for (const node of list) {
      if (node.is_center) continue;
      slot += 1;
      const level = Math.ceil(slot / 2);
      const sign = slot % 2 ? -1 : 1;
      positions.set(node.id, { x, y: sign * level * ROW });
    }
  }
  return positions;
}

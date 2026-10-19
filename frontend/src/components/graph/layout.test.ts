import { subgraph } from "../../test/alertFixtures";

import { layoutGraph, ROW, WIDTH } from "./layout";

it("places the centre on the middle line and time left to right", () => {
  const g = subgraph(1);
  const pos = layoutGraph(g.nodes, g.edges);
  expect(pos.get("11:800000001")?.y).toBe(0);
  const sender = pos.get("11:800000002")!;
  const receiver = pos.get("12:800000003")!;
  expect(sender.x).toBeLessThan(receiver.x); // paid earlier → further left
  expect(receiver.x).toBe(WIDTH);
});

it("stacks accounts that share a column without overlapping", () => {
  const g = subgraph(1);
  const many = Array.from({ length: 5 }, (_, i) => ({
    id: `x:${String(i)}`,
    is_center: false,
    max_score: 0.5,
    degree: 1,
  }));
  const edges = many.map((n, i) => ({
    ...g.edges[0]!,
    txn_id: i,
    from: n.id,
    to: "11:800000001",
  }));
  const pos = layoutGraph([g.nodes[0]!, ...many], edges);
  const ys = many.map((n) => pos.get(n.id)!.y).sort((a, b) => a - b);
  expect(new Set(ys).size).toBe(5);
  expect(ys.every((y) => Math.abs(y) % ROW === 0 && y !== 0)).toBe(true);
});

it("handles an empty graph", () => {
  expect(layoutGraph([], []).size).toBe(0);
});

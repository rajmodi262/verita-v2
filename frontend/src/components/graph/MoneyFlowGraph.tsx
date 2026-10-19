import type { Core, EventObject } from "cytoscape";
import { useEffect, useRef } from "react";

import type { Subgraph } from "../../api/alerts";
import { money, score } from "../../lib/format";

import { layoutGraph } from "./layout";
import styles from "./MoneyFlowGraph.module.css";

export interface MoneyFlowGraphProps {
  graph: Subgraph;
  selectedTxn: number | null;
  onSelectTxn: (txnId: number) => void;
}

function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/**
 * Canvas rendering of the evidence subgraph (Cytoscape, loaded with this route only). It is a
 * visual aid; the same data is always available as a table beside it.
 */
export function MoneyFlowGraph({ graph, selectedTxn, onSelectTxn }: MoneyFlowGraphProps) {
  const container = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const select = useRef(onSelectTxn);
  useEffect(() => {
    select.current = onSelectTxn;
  }, [onSelectTxn]);

  useEffect(() => {
    let cancelled = false;
    const node = container.current;
    if (!node) return undefined;
    void import("cytoscape").then(({ default: cytoscape }) => {
      if (cancelled) return;
      const positions = layoutGraph(graph.nodes, graph.edges);
      const ink = token("--color-ink");
      const cy = cytoscape({
        container: node,
        boxSelectionEnabled: false,
        wheelSensitivity: 0.2,
        elements: [
          ...graph.nodes.map((n) => ({
            data: { id: n.id, label: n.id.split(":")[1] ?? n.id, center: n.is_center ? 1 : 0 },
            position: positions.get(n.id) ?? { x: 0, y: 0 },
          })),
          ...graph.edges.map((e) => ({
            data: {
              id: String(e.txn_id),
              source: e.from,
              target: e.to,
              path: e.on_dominant_path ? 1 : 0,
              flagged: e.flagged ? 1 : 0,
              label: `${money(e.amount_paid, e.currency_paid)} · ${score(e.score)}`,
            },
          })),
        ],
        layout: { name: "preset", fit: true, padding: 30 },
        style: [
          {
            selector: "node",
            style: {
              "background-color": token("--color-node"),
              "border-color": ink,
              "border-width": 2,
              shape: "rectangle",
              width: 18,
              height: 18,
              label: "data(label)",
              color: ink,
              "font-family": "JetBrains Mono Variable, monospace",
              "font-size": 10,
              "text-valign": "bottom",
              "text-margin-y": 4,
            },
          },
          {
            selector: "node[center = 1]",
            style: {
              "border-color": token("--color-alert"),
              "border-width": 4,
              width: 26,
              height: 26,
            },
          },
          {
            selector: "edge",
            style: {
              "line-color": token("--color-edge"),
              "target-arrow-color": token("--color-edge"),
              "target-arrow-shape": "triangle",
              "curve-style": "bezier",
              width: 1.5,
              opacity: 0.7,
            },
          },
          { selector: "edge[flagged = 1]", style: { width: 2.5, opacity: 0.9 } },
          {
            selector: "edge[path = 1]",
            style: {
              "line-color": token("--color-path"),
              "target-arrow-color": token("--color-path"),
              width: 4,
              opacity: 1,
              "z-index": 10,
            },
          },
          {
            selector: "edge:selected",
            style: {
              label: "data(label)",
              "font-size": 10,
              color: ink,
              "text-background-color": token("--color-surface"),
              "text-background-opacity": 1,
              "line-style": "dashed",
            },
          },
        ],
      });
      cy.on("tap", "edge", (event: EventObject) => {
        const target = event.target as { id: () => string };
        select.current(Number(target.id()));
      });
      cyRef.current = cy;
    });
    return () => {
      cancelled = true;
      cyRef.current?.destroy();
      cyRef.current = null;
    };
  }, [graph]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.edges().unselect();
    if (selectedTxn !== null) cy.getElementById(String(selectedTxn)).select();
  }, [selectedTxn]);

  return (
    <figure className={styles.figure}>
      <div
        ref={container}
        className={styles.canvas}
        role="img"
        aria-label={`Money-flow graph: ${String(graph.nodes.length)} accounts and ${String(graph.edges.length)} payments. The table view lists every payment.`}
      />
      <figcaption className={styles.legend}>
        <span className={styles.keyPath}>Dominant path</span>
        <span className={styles.keyCenter}>Alerted account</span>
        <span>Time flows left → right · scroll to zoom · drag to pan</span>
      </figcaption>
    </figure>
  );
}

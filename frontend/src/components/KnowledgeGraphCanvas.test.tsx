import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";

import type { GraphEdge, GraphNode } from "../types";
import { KnowledgeGraphCanvas } from "./KnowledgeGraphCanvas";

beforeEach(() => {
  document.documentElement.dataset.theme = "light";
  vi.stubGlobal(
    "ResizeObserver",
    class ResizeObserver {
      constructor(private readonly callback: ResizeObserverCallback) {}
      observe(target: Element) {
        this.callback(
          [{ target, contentRect: target.getBoundingClientRect() } as ResizeObserverEntry],
          this,
        );
      }
      unobserve() {}
      disconnect() {}
    },
  );

  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(() => ({
    bottom: 720,
    height: 720,
    left: 0,
    right: 1200,
    top: 0,
    width: 1200,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  }));
});

const nodes: GraphNode[] = [
  {
    aliases: ["allocative efficiency"],
    code: "KG-0001",
    confidence: 0.99,
    description: "A firm is efficient where $P = MC$.",
    evidence: [],
    id: "node-1",
    metadata: {},
    node_type: "concept",
    parent_key: null,
    review_status: "accepted",
    stable_key: "concept:allocative-efficiency",
    title: "Allocative efficiency",
    unit_code: "U1",
  },
  {
    aliases: ["P = MC"],
    code: "KG-0002",
    confidence: 0.97,
    description: "The condition $P = MC$ identifies allocative efficiency.",
    evidence: [],
    id: "node-2",
    metadata: {},
    node_type: "formula",
    parent_key: null,
    review_status: "pending",
    stable_key: "formula:price-equals-marginal-cost",
    title: "Price equals marginal cost",
    unit_code: "U1",
  },
];

const edges: GraphEdge[] = [
  {
    confidence: 0.96,
    evidence: [],
    id: "edge-1",
    relation_type: "expressed_by",
    review_status: "pending",
    source_key: nodes[0].stable_key,
    target_key: nodes[1].stable_key,
  },
];

describe("KnowledgeGraphCanvas", () => {
  test("lays out connected nodes and exposes node selection", () => {
    const onSelectNode = vi.fn();

    render(
      <div style={{ height: 720, width: 1200 }}>
        <KnowledgeGraphCanvas
          edges={edges}
          nodes={nodes}
          onSelectEdge={() => undefined}
          onSelectNode={onSelectNode}
          selectedEdgeId={null}
          selectedNodeId={nodes[0].id}
        />
      </div>,
    );

    expect(screen.getByText("Allocative efficiency")).toBeInTheDocument();
    expect(screen.getAllByText("1 条关系")).toHaveLength(2);
    expect(screen.getByText("公式").closest(".knowledge-graph-node")?.querySelector(".katex"))
      .toBeInTheDocument();

    fireEvent.click(screen.getByText("Allocative efficiency").closest(".react-flow__node")!);
    expect(onSelectNode).toHaveBeenCalledWith(nodes[0].id);
  });

  test("tracks document theme changes while mounted", async () => {
    const { container } = render(
      <div style={{ height: 720, width: 1200 }}>
        <KnowledgeGraphCanvas
          edges={edges}
          nodes={nodes}
          onSelectEdge={() => undefined}
          onSelectNode={() => undefined}
          selectedEdgeId={null}
          selectedNodeId={null}
        />
      </div>,
    );

    expect(container.querySelector(".react-flow")).toHaveClass("light");
    document.documentElement.dataset.theme = "dark";
    await waitFor(() => expect(container.querySelector(".react-flow")).toHaveClass("dark"));
  });

  test("renders Markdown and KaTeX in the hover detail card", async () => {
    render(
      <div style={{ height: 720, width: 1200 }}>
        <KnowledgeGraphCanvas
          edges={edges}
          nodes={nodes}
          onSelectEdge={() => undefined}
          onSelectNode={() => undefined}
          selectedEdgeId={null}
          selectedNodeId={null}
        />
      </div>,
    );

    const formulaNode = screen.getByText("公式").closest(".react-flow__node")!;
    fireEvent.mouseEnter(formulaNode, { clientX: 600, clientY: 300 });

    const tooltip = await screen.findByRole("tooltip");
    expect(within(tooltip).getByText("KG-0002")).toBeInTheDocument();
    expect(tooltip).toHaveTextContent("identifies allocative efficiency");
    expect(tooltip.querySelectorAll(".katex").length).toBeGreaterThanOrEqual(2);

    fireEvent.mouseLeave(formulaNode);
    await waitFor(() => expect(screen.queryByRole("tooltip")).not.toBeInTheDocument());
  });
});

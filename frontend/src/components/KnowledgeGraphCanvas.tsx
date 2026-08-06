import Dagre from "@dagrejs/dagre";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent } from "react";

import { InlineMarkdown, Markdown } from "./Markdown";
import type { GraphEdge, GraphNode } from "../types";

const NODE_WIDTH = 224;
const NODE_HEIGHT = 88;

const nodeColors: Record<string, string> = {
  unit: "#2563eb",
  topic: "#0891b2",
  learning_objective: "#7c3aed",
  concept: "#0f766e",
  subconcept: "#0f766e",
  skill: "#c2410c",
  method: "#b45309",
  formula: "#be185d",
  term: "#475569",
};

type KnowledgeNodeData = {
  node: GraphNode;
  relationCount: number;
  [key: string]: unknown;
};

type KnowledgeFlowNode = Node<KnowledgeNodeData, "knowledge">;
type KnowledgeFlowEdge = Edge<{ edge: GraphEdge }>;

type HoveredNode = {
  node: GraphNode;
  relationCount: number;
  left: number;
  top: number;
};

function nodeTypeLabel(type: string) {
  const labels: Record<string, string> = {
    unit: "Unit",
    topic: "章节",
    learning_objective: "学习目标",
    concept: "概念",
    subconcept: "子概念",
    skill: "技能",
    method: "方法",
    formula: "公式",
    term: "术语",
  };
  return labels[type] ?? type;
}

function KnowledgeNodeCard({ data, selected }: NodeProps<KnowledgeFlowNode>) {
  const { node, relationCount } = data;
  return (
    <article
      className={`knowledge-graph-node type-${node.node_type} status-${node.review_status} ${selected ? "is-selected" : ""}`}
    >
      <Handle isConnectable={false} position={Position.Left} type="target" />
      <div className="knowledge-graph-node-topline">
        <span>{node.code}</span>
        <em>{nodeTypeLabel(node.node_type)}</em>
      </div>
      <strong><InlineMarkdown>{node.title}</InlineMarkdown></strong>
      <div className="knowledge-graph-node-meta">
        <span>{Math.round(node.confidence * 100)}% 置信度</span>
        <span>{relationCount} 条关系</span>
      </div>
      <Handle isConnectable={false} position={Position.Right} type="source" />
    </article>
  );
}

const nodeTypes = { knowledge: KnowledgeNodeCard };

function layoutGraph(nodes: GraphNode[], edges: GraphEdge[]) {
  const graph = new Dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}));
  graph.setGraph({
    rankdir: "LR",
    align: "UL",
    nodesep: 34,
    ranksep: 90,
    edgesep: 18,
    marginx: 32,
    marginy: 32,
  });

  const keys = new Set(nodes.map((node) => node.stable_key));
  const relationCounts = new Map<string, number>();
  for (const edge of edges) {
    if (!keys.has(edge.source_key) || !keys.has(edge.target_key)) continue;
    graph.setEdge(edge.source_key, edge.target_key);
    relationCounts.set(edge.source_key, (relationCounts.get(edge.source_key) ?? 0) + 1);
    relationCounts.set(edge.target_key, (relationCounts.get(edge.target_key) ?? 0) + 1);
  }
  for (const node of nodes) {
    graph.setNode(node.stable_key, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  Dagre.layout(graph);

  const flowNodes: KnowledgeFlowNode[] = nodes.map((node) => {
    const position = graph.node(node.stable_key) as { x: number; y: number };
    return {
      id: node.stable_key,
      type: "knowledge",
      width: NODE_WIDTH,
      height: NODE_HEIGHT,
      data: { node, relationCount: relationCounts.get(node.stable_key) ?? 0 },
      position: {
        x: position.x - NODE_WIDTH / 2,
        y: position.y - NODE_HEIGHT / 2,
      },
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
    };
  });

  const flowEdges: KnowledgeFlowEdge[] = edges.flatMap((edge) => {
    if (!keys.has(edge.source_key) || !keys.has(edge.target_key)) return [];
    return [{
      id: edge.id,
      source: edge.source_key,
      target: edge.target_key,
      type: "smoothstep",
      data: { edge },
      className: `graph-flow-edge status-${edge.review_status}`,
      markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
    }];
  });

  return { nodes: flowNodes, edges: flowEdges };
}

export function KnowledgeGraphCanvas({
  nodes,
  edges,
  selectedNodeId,
  selectedEdgeId,
  onSelectNode,
  onSelectEdge,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  selectedNodeId: string | null;
  selectedEdgeId: string | null;
  onSelectNode: (id: string) => void;
  onSelectEdge: (id: string) => void;
}) {
  const [hovered, setHovered] = useState<HoveredNode | null>(null);
  const [colorMode, setColorMode] = useState<"dark" | "light">(
    () => document.documentElement.dataset.theme === "dark" ? "dark" : "light",
  );
  const hoverLeaveTimer = useRef<number | null>(null);
  const layout = useMemo(() => layoutGraph(nodes, edges), [edges, nodes]);
  const flowNodes = useMemo(
    () => layout.nodes.map((node) => ({
      ...node,
      selected: node.data.node.id === selectedNodeId,
    })),
    [layout.nodes, selectedNodeId],
  );
  const flowEdges = useMemo(
    () => layout.edges.map((edge) => ({
      ...edge,
      selected: edge.id === selectedEdgeId,
      animated: edge.data?.edge.review_status === "pending",
    })),
    [layout.edges, selectedEdgeId],
  );
  const focusNodes = useMemo(() => {
    const selected = flowNodes.find((node) => node.data.node.id === selectedNodeId);
    if (!selected) return flowNodes.slice(0, 6);
    const connectedKeys = new Set<string>([selected.id]);
    for (const edge of flowEdges) {
      if (edge.source === selected.id) connectedKeys.add(edge.target);
      if (edge.target === selected.id) connectedKeys.add(edge.source);
      if (connectedKeys.size >= 8) break;
    }
    return flowNodes.filter((node) => connectedKeys.has(node.id)).slice(0, 8);
  }, [flowEdges, flowNodes, selectedNodeId]);
  useEffect(() => {
    const observer = new MutationObserver(() => {
      setColorMode(document.documentElement.dataset.theme === "dark" ? "dark" : "light");
    });
    observer.observe(document.documentElement, {
      attributeFilter: ["data-theme"],
      attributes: true,
    });
    return () => {
      observer.disconnect();
      if (hoverLeaveTimer.current !== null) window.clearTimeout(hoverLeaveTimer.current);
    };
  }, []);

  function cancelHoverHide() {
    if (hoverLeaveTimer.current === null) return;
    window.clearTimeout(hoverLeaveTimer.current);
    hoverLeaveTimer.current = null;
  }

  function hideHoverSoon() {
    cancelHoverHide();
    hoverLeaveTimer.current = window.setTimeout(() => setHovered(null), 100);
  }


  function showHover(event: ReactMouseEvent, node: KnowledgeFlowNode) {
    const width = 360;
    const height = 360;
    cancelHoverHide();
    setHovered({
      node: node.data.node,
      relationCount: node.data.relationCount,
      left: Math.max(12, Math.min(event.clientX + 18, window.innerWidth - width - 12)),
      top: Math.max(12, Math.min(event.clientY + 18, window.innerHeight - height - 12)),
    });
  }

  return (
    <div className="knowledge-graph-viewport">
      <ReactFlow
        colorMode={colorMode}
        defaultEdgeOptions={{ interactionWidth: 18 }}
        edges={flowEdges}
        elementsSelectable
        fitView
        fitViewOptions={{ maxZoom: 0.9, nodes: focusNodes, padding: 0.5 }}
        minZoom={0.08}
        nodeTypes={nodeTypes}
        nodes={flowNodes}
        nodesConnectable={false}
        nodesDraggable={false}
        onEdgeClick={(_event, edge) => onSelectEdge(edge.id)}
        onNodeClick={(_event, node) => onSelectNode(node.data.node.id)}
        onNodeMouseEnter={showHover}
        onNodeMouseLeave={hideHoverSoon}
        onNodeMouseMove={showHover}
        onlyRenderVisibleElements
        panOnScroll
        selectionOnDrag={false}
        zoomOnDoubleClick={false}
      >
        <Background color="var(--graph-grid)" gap={24} size={1.3} variant={BackgroundVariant.Dots} />
        <MiniMap
          ariaLabel="知识图谱小地图"
          maskColor="color-mix(in srgb, var(--surface) 72%, transparent)"
          nodeColor={(node) => {
            const data = node.data as KnowledgeNodeData | undefined;
            return nodeColors[data?.node.node_type ?? ""] ?? "#64748b";
          }}
          pannable
          zoomable
        />
        <Controls position="bottom-left" showInteractive={false} />
      </ReactFlow>
      {hovered && (
        <aside
          className={`knowledge-graph-hover type-${hovered.node.node_type}`}
          onMouseEnter={cancelHoverHide}
          onMouseLeave={hideHoverSoon}
          tabIndex={0}
          role="tooltip"
          style={{ left: hovered.left, top: hovered.top }}
        >
          <div className="knowledge-graph-hover-head">
            <span>{hovered.node.code}</span>
            <em>{nodeTypeLabel(hovered.node.node_type)}</em>
          </div>
          <h3><InlineMarkdown>{hovered.node.title}</InlineMarkdown></h3>
          {hovered.node.description && (
            <div className="knowledge-graph-hover-description">
              <Markdown>{hovered.node.description}</Markdown>
            </div>
          )}
          <dl>
            <div><dt>置信度</dt><dd>{Math.round(hovered.node.confidence * 100)}%</dd></div>
            <div><dt>直接关系</dt><dd>{hovered.relationCount}</dd></div>
            <div><dt>审核状态</dt><dd>{hovered.node.review_status}</dd></div>
          </dl>
          {hovered.node.aliases.length > 0 && (
            <p className="knowledge-graph-hover-aliases">
              {hovered.node.aliases.slice(0, 4).map((alias) => <span key={alias}>{alias}</span>)}
            </p>
          )}
        </aside>
      )}
    </div>
  );
}

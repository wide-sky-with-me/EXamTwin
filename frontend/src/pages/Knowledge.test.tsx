import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";

import type { GraphNode, SubjectPack } from "../types";
import { Knowledge } from "./Knowledge";

vi.mock("../components/KnowledgeGraphCanvas", () => ({
  GraphNodeFormula: () => null,
  KnowledgeGraphCanvas: ({
    nodes,
    onSelectNode,
    selectedNodeId,
  }: {
    nodes: GraphNode[];
    onSelectNode: (id: string) => void;
    selectedNodeId: string | null;
  }) => (
    <div aria-label="测试图谱画布">
      {nodes.map((node) => (
        <button
          aria-pressed={selectedNodeId === node.id}
          key={node.id}
          onClick={() => onSelectNode(node.id)}
          type="button"
        >
          {node.title}
        </button>
      ))}
    </div>
  ),
}));

const subject: SubjectPack = {
  id: "oxfordaqa-economics-9640",
  subject_code: "9640",
  title: "OxfordAQA Economics",
  board_name: "OxfordAQA",
  version: "1",
  digest: "test",
  capability_profile_id: "oxfordaqa-economics-9640",
  generic_qa_enabled: true,
  answering_enabled: true,
  answering_disabled_reason: null,
  active_graph_version_id: "graph-a",
  knowledge_bases: [],
  units: [],
};

const baseNode: GraphNode = {
  aliases: [],
  code: "KG-0001",
  confidence: 0.99,
  description: "First definition",
  evidence: [],
  id: "node-1",
  metadata: {},
  node_type: "concept",
  parent_key: null,
  review_status: "pending",
  stable_key: "concept:first",
  title: "First node",
  unit_code: "U1",
};

function response(payload: unknown) {
  return Promise.resolve(new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  }));
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Knowledge graph workbench", () => {
  test("ignores stale graph loads and preserves the edited node after refresh", async () => {
    const graphA = {
      id: "graph-a",
      subject_id: subject.id,
      knowledge_base_version_id: null,
      version_number: 1,
      status: "draft",
      extraction_model: "test",
      extraction_prompt_version: "test",
      nodes: [{ ...baseNode, id: "node-a", title: "Slow graph node" }],
      edges: [],
      created_at: "2026-08-05T00:00:00Z",
      published_at: null,
    };
    const graphB = {
      ...graphA,
      id: "graph-b",
      version_number: 2,
      nodes: [
        baseNode,
        {
          ...baseNode,
          code: "KG-0002",
          id: "node-2",
          stable_key: "concept:second",
          title: "Second node",
        },
      ],
    };
    let requestedA = false;
    let graphBRequests = 0;
    let patchRequests = 0;
    let resolveA: ((value: Response) => void) | undefined;
    const slowA = new Promise<Response>((resolve) => {
      resolveA = resolve;
    });
    const fetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : null;
      const url = new URL(String(request?.url ?? input));
      const method = request?.method ?? init?.method ?? "GET";
      if (url.pathname === "/api/v1/knowledge-graphs" && method === "GET") {
        return response([
          { id: "graph-a", version_number: 1, status: "draft" },
          { id: "graph-b", version_number: 2, status: "draft" },
        ]);
      }
      if (url.pathname === "/api/v1/knowledge-graphs/graph-a") {
        requestedA = true;
        return slowA;
      }
      if (url.pathname === "/api/v1/knowledge-graphs/graph-b" && method === "GET") {
        graphBRequests += 1;
        return response(graphB);
      }
      if (url.pathname.includes("/api/v1/knowledge-graphs/graph-b/nodes/") && method === "PATCH") {
        patchRequests += 1;
        return response(graphB.nodes[1]);
      }
      return response([]);
    });
    vi.stubGlobal("fetch", fetch);

    const user = userEvent.setup();
    render(<Knowledge points={[]} relations={[]} subject={subject} refresh={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "图谱生产" }));
    await waitFor(() => expect(requestedA).toBe(true));
    await user.click(await screen.findByRole("button", { name: "选择图谱 v2 · draft" }));
    expect(await screen.findByRole("button", { name: "Second node" })).toBeInTheDocument();

    await act(async () => {
      resolveA?.(new Response(JSON.stringify(graphA), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }));
      await slowA;
    });
    expect(screen.queryByRole("button", { name: "Slow graph node" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Second node" }));
    expect(screen.getByRole("button", { name: "Second node" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("标题")).toHaveValue("Second node");
    await user.click(screen.getByRole("button", { name: "保存并接受" }));

    await waitFor(() => expect(patchRequests).toBe(1));
    await waitFor(() => expect(graphBRequests).toBe(2));
    expect(screen.getByRole("button", { name: "Second node" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("标题")).toHaveValue("Second node");
  });
  test("fullscreens only the graph canvas and deletes one coexisting version", async () => {
    const graphA = {
      id: "graph-a",
      subject_id: subject.id,
      knowledge_base_version_id: null,
      version_number: 1,
      status: "published",
      extraction_model: "test",
      extraction_prompt_version: "test",
      nodes: [{ ...baseNode, id: "node-a", title: "Version one node" }],
      edges: [],
      created_at: "2026-08-05T00:00:00Z",
      published_at: "2026-08-05T00:00:00Z",
    };
    const graphB = {
      ...graphA,
      id: "graph-b",
      version_number: 2,
      status: "draft",
      nodes: [{ ...baseNode, id: "node-b", title: "Version two node" }],
      published_at: null,
    };
    let versions = [
      { id: "graph-b", version_number: 2, status: "draft" },
      { id: "graph-a", version_number: 1, status: "published" },
    ];
    let deletedVersion: string | null = null;
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const request = input instanceof Request ? input : null;
      const url = new URL(String(request?.url ?? input));
      const method = request?.method ?? init?.method ?? "GET";
      if (url.pathname === "/api/v1/knowledge-graphs" && method === "GET") {
        return response(versions);
      }
      if (url.pathname === "/api/v1/knowledge-graphs/graph-a" && method === "GET") {
        return response(graphA);
      }
      if (url.pathname === "/api/v1/knowledge-graphs/graph-b" && method === "GET") {
        return response(graphB);
      }
      if (url.pathname === "/api/v1/knowledge-graphs/graph-b" && method === "DELETE") {
        deletedVersion = "graph-b";
        versions = versions.filter((item) => item.id !== "graph-b");
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      return response([]);
    }));

    const user = userEvent.setup();
    const { container } = render(
      <Knowledge points={[]} relations={[]} subject={subject} refresh={vi.fn()} />,
    );
    await user.click(screen.getByRole("button", { name: "图谱生产" }));

    expect(await screen.findByRole("button", { name: "选择图谱 v2 · draft" }))
      .toBeInTheDocument();
    expect(screen.getByRole("button", { name: "选择图谱 v1 · published · 当前使用" }))
      .toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "选择图谱 v2 · draft" }));
    expect(await screen.findByRole("button", { name: "Version two node" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "全屏预览图谱" }));
    expect(container.querySelector(".graph-canvas")).toHaveClass("is-fullscreen");
    expect(container.querySelector(".knowledge-page")).not.toHaveClass("is-fullscreen");
    expect(screen.getByRole("heading", { name: "知识图谱生产与发布" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "退出图谱全屏" }));

    await user.click(screen.getByRole("button", { name: "删除当前图谱" }));
    await waitFor(() => expect(deletedVersion).toBe("graph-b"));
    expect(screen.queryByRole("button", { name: "选择图谱 v2 · draft" }))
      .not.toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Version one node" })).toBeInTheDocument();
  });
});

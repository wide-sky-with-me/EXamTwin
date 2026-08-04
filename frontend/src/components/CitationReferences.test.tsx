import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";

import type { Citation } from "../types";
import { CitationMarkdown } from "./CitationReferences";

const citation: Citation = {
  source: "licensed-textbook/chapter-1.md",
  document_id: "doc-1",
  page: 22,
  section: "Sequences",
  source_type: "textbook",
  evidence_role: "explanation",
  excerpt: "A sequence may be specified by a recurrence relation.",
  authority_tier: null,
  content_url: null,
  index_build_id: null,
  knowledge_code: null,
  pair_key: null,
  score: null,
  section_path: [],
};

describe("CitationMarkdown", () => {
  test("turns S markers into hover previews and focus-managed source dialogs", async () => {
    const user = userEvent.setup();
    const citations = [citation];
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
        document_id: "doc-1",
        source: citation.source,
        page: 22,
        content_markdown: "## Full source\n\nComplete recurrence explanation.",
        truncated: false,
      }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })));
    const { rerender } = render(
      <CitationMarkdown citations={citations} query="recurrence">
        The recurrence follows the textbook definition [S1].
      </CitationMarkdown>,
    );

    const marker = screen.getByRole("button", { name: "查看参考文献 1" });
    await user.hover(marker);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Sequences");

    await user.click(marker);
    expect(screen.getByRole("dialog", { name: "Sequences" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "关闭参考文献详情" })).toHaveFocus();
    await waitFor(() => {
      expect(screen.getByText("Complete recurrence explanation.")).toBeInTheDocument();
    });

    rerender(
      <CitationMarkdown citations={citations} query="recurrence">
        The recurrence follows the textbook definition [S1].
      </CitationMarkdown>,
    );
    expect(screen.getByRole("dialog", { name: "Sequences" })).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Sequences" })).not.toBeInTheDocument();
    expect(marker).toHaveFocus();
  });
});

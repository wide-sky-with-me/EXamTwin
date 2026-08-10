import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";

import type { PlatformStatus, SubjectStatus } from "../types";
import { Overview } from "./Overview";

const stats = {
  documents_by_status: {},
  documents_by_type: {},
  documents_total: 0,
  exam_identity_incomplete: 0,
  knowledge_points: 0,
  orphan_mark_schemes: 0,
  orphan_question_papers: 0,
  pending_reviews: 0,
  question_difficulty_rows: 0,
  relations: 0,
  strict_pairs: 0,
};

function subject(
  id: string,
  subjectCode: string,
  title: string,
  capabilityProfileId: string | null,
): SubjectStatus {
  return {
    active_graph_version_id: null,
    answering_disabled_reason: null,
    answering_enabled: false,
    board_name: capabilityProfileId ? "OxfordAQA" : "Test board",
    capability_profile_id: capabilityProfileId,
    digest: id,
    generic_qa_enabled: true,
    id,
    knowledge_bases: [],
    stats,
    subject_code: subjectCode,
    title,
    units: [],
    vector_alias: `subject_${subjectCode}`,
    vector_index_ready: false,
    vector_points: 0,
    version: "1",
  };
}

const builtInSubject = subject(
  "oxfordaqa-mathematics-9660",
  "9660",
  "OxfordAQA International Mathematics",
  "oxfordaqa-mathematics-9660",
);
const customSubject = subject(
  "subject-test",
  "ATEST",
  "Graph subject",
  null,
);
const platform: PlatformStatus = {
  infrastructure: {
    object_storage: true,
    postgresql: true,
    qdrant: true,
  },
  subjects: [builtInSubject, customSubject],
};

describe("Overview subject management", () => {
  test("selects only custom subjects and confirms batch deletion", async () => {
    const user = userEvent.setup();
    const refresh = vi.fn().mockResolvedValue(undefined);
    const fetch = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ deleted_ids: [customSubject.id], deleted_count: 1 }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ));
    vi.stubGlobal("fetch", fetch);

    render(
      <Overview
        loading={false}
        platform={platform}
        refresh={refresh}
        selected={builtInSubject}
        selectSubject={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "管理科目" }));
    expect(screen.getByRole("button", {
      name: /9660 .*内置科目不可删除/,
    })).toBeDisabled();

    await user.click(screen.getByRole("button", {
      name: /选择 ATEST Graph subject/,
    }));
    await user.click(screen.getByRole("button", { name: "删除所选" }));

    const dialog = screen.getByRole("alertdialog", {
      name: "删除 1 个科目工作区？",
    });
    expect(within(dialog).getByText("Graph subject")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "永久删除" }));

    await waitFor(() => expect(refresh).toHaveBeenCalledOnce());
    const request = fetch.mock.calls[0][0] as Request;
    expect(new URL(request.url).pathname).toBe(
      "/api/v1/subject-workspaces/batch-delete",
    );
    expect(await request.clone().json()).toEqual({
      subject_ids: [customSubject.id],
    });
    expect(screen.getByRole("status")).toHaveTextContent("已删除 1 个科目工作区");
  });
});

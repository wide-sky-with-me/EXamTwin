import { LoaderCircle } from "lucide-react";
import { useState } from "react";

import { getSourceContext } from "../lib/api";
import { sourceLabels } from "../lib/evidence";
import type {
  Citation,
  SourceContextResult,
} from "../types";
import { ErrorBanner } from "./Feedback";
import { Markdown } from "./Markdown";

const evidenceRoleLabels: Record<string, string> = {
  definition: "知识定义",
  explanation: "教材讲解",
  worked_example: "教材例题",
  assessment: "考题证据",
  marking: "评分依据",
};

export function SourceEvidence({
  citation,
  index,
  query,
  marker,
}: {
  citation: Citation;
  index: number;
  query: string;
  marker?: string;
}) {
  const [context, setContext] = useState<SourceContextResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadContext() {
    if (!citation.document_id || loading || context) return;
    setLoading(true);
    setError(null);
    try {
      const result = await getSourceContext(
        citation.document_id,
        citation.page ?? null,
        query,
        citation.content_url,
      );
      setContext(result);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "完整原文加载失败");
    } finally {
      setLoading(false);
    }
  }

  const filename = citation.source.split("/").pop() ?? citation.source;
  const sourceLabel = sourceLabels[citation.source_type ?? "other"] ?? citation.source_type ?? "资料";
  const roleLabel = evidenceRoleLabels[citation.evidence_role ?? ""] ?? citation.evidence_role;
  const location =
    citation.page
      ? `p.${citation.page}`
      : citation.section
        ? "定位到章节"
        : "定位到相关内容";
  return (
    <details
      className="source-evidence"
      onToggle={(event) => {
        if (event.currentTarget.open) void loadContext();
      }}
    >
      <summary>
        <span>{marker ?? `[S${index + 1}]`} · {sourceLabel}{roleLabel ? ` · ${roleLabel}` : ""}</span>
        <strong>{citation.section ?? filename}</strong>
        <em>{location}</em>
      </summary>
      <div className="source-evidence-body" aria-busy={loading}>
        {loading && <p className="source-loading"><LoaderCircle className="spin" size={14} />正在读取知识库原文…</p>}
        {error && <ErrorBanner message={error} />}
        <p className="source-provenance">
          {filename}
          {citation.section_path?.length ? ` · ${citation.section_path.join(" › ")}` : ""}
        </p>
        <div className="source-original">
          <Markdown>{context?.content_markdown ?? citation.excerpt}</Markdown>
        </div>
        {!citation.document_id && <small>当前引用没有文档 ID，只能展示检索片段。</small>}
        {context?.truncated && <small>该章节很长，界面已按服务端上限截断。</small>}
      </div>
    </details>
  );
}

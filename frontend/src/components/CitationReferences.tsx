import { FileText, LoaderCircle, X } from "lucide-react";
import {
  type ComponentPropsWithoutRef,
  type Dispatch,
  type SetStateAction,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

import { getSourceContext } from "../lib/api";
import { sourceLabels } from "../lib/evidence";
import { useModalFocus } from "../lib/use-modal-focus";
import type { Citation, SourceContextResult } from "../types";
import { ErrorBanner } from "./Feedback";
import { Markdown } from "./Markdown";

const evidenceRoleLabels: Record<string, string> = {
  definition: "知识定义",
  explanation: "教材讲解",
  worked_example: "教材例题",
  assessment: "考题证据",
  marking: "评分依据",
};

function citationLabels(citation: Citation) {
  const filename = citation.source.split("/").pop() ?? citation.source;
  const sourceType = sourceLabels[citation.source_type ?? "other"]
    ?? citation.source_type
    ?? "资料";
  const role = evidenceRoleLabels[citation.evidence_role ?? ""]
    ?? citation.evidence_role;
  const location = citation.page
    ? `p.${citation.page}`
    : citation.section
      ? "章节定位"
      : "相关内容";
  return {
    filename,
    sourceType,
    role,
    location,
    title: citation.section ?? filename,
  };
}

function useSourceContext(citation: Citation, query: string, open: boolean) {
  const [context, setContext] = useState<SourceContextResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !citation.document_id || context) return;
    let active = true;
    setLoading(true);
    setError(null);
    void getSourceContext(
      citation.document_id,
      citation.page ?? null,
      query,
      citation.content_url,
    )
      .then((result) => {
        if (active) setContext(result);
      })
      .catch((cause) => {
        if (active) {
          setError(cause instanceof Error ? cause.message : "完整原文加载失败");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [citation, context, open, query]);

  return { context, loading, error };
}

function CitationDialog({
  citation,
  index,
  query,
  open,
  setOpen,
}: {
  citation: Citation;
  index: number;
  query: string;
  open: boolean;
  setOpen: Dispatch<SetStateAction<boolean>>;
}) {
  const labels = citationLabels(citation);
  const modalRef = useModalFocus(open, setOpen);
  const { context, loading, error } = useSourceContext(citation, query, open);
  if (!open) return null;
  return createPortal(
    <div
      className="citation-dialog-overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) setOpen(false);
      }}
    >
      <article
        aria-labelledby={`citation-dialog-title-${index}`}
        aria-modal="true"
        className="citation-dialog"
        ref={modalRef}
        role="dialog"
        tabIndex={-1}
      >
        <header>
          <div>
            <span>参考文献 [{index + 1}] · {labels.sourceType}</span>
            <h2 id={`citation-dialog-title-${index}`}>{labels.title}</h2>
            <p>
              {labels.filename} · {labels.location}
              {citation.section_path?.length
                ? ` · ${citation.section_path.join(" › ")}`
                : ""}
            </p>
          </div>
          <button
            aria-label="关闭参考文献详情"
            data-modal-close
            onClick={() => setOpen(false)}
            type="button"
          >
            <X size={19} />
          </button>
        </header>
        <div className="citation-dialog-meta">
          {labels.role && <span>{labels.role}</span>}
          {citation.authority_tier && <span>来源层级 {citation.authority_tier}</span>}
          {citation.knowledge_code && <span>知识点 {citation.knowledge_code}</span>}
          {citation.score != null && <span>相关度 {citation.score.toFixed(3)}</span>}
        </div>
        <div className="citation-dialog-body" aria-busy={loading}>
          {loading && (
            <p className="source-loading">
              <LoaderCircle className="spin" size={15} />正在读取知识库完整原文…
            </p>
          )}
          {error && <ErrorBanner message={error} />}
          <div className="citation-dialog-original">
            <Markdown>{context?.content_markdown ?? citation.excerpt}</Markdown>
          </div>
          {!citation.document_id && (
            <small>当前引用没有文档 ID，只能展示检索片段。</small>
          )}
          {context?.truncated && <small>原章节很长，已按服务端安全上限展示。</small>}
        </div>
        <footer>
          <span><FileText size={14} />来源原文</span>
          <button onClick={() => setOpen(false)} type="button">关闭</button>
        </footer>
      </article>
    </div>,
    document.body,
  );
}

type TooltipPosition = { left: number; top: number };

export function CitationReference({
  citation,
  index,
  query,
  variant = "list",
}: {
  citation: Citation;
  index: number;
  query: string;
  variant?: "inline" | "list";
}) {
  const labels = citationLabels(citation);
  const tooltipId = `citation-tooltip-${useId().replaceAll(":", "")}`;
  const buttonRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [preview, setPreview] = useState(false);
  const [tooltipPosition, setTooltipPosition] = useState<TooltipPosition | null>(null);

  useLayoutEffect(() => {
    if (!preview) return;
    const update = () => {
      const rect = buttonRef.current?.getBoundingClientRect();
      if (!rect) return;
      const width = Math.min(360, window.innerWidth - 24);
      const left = Math.max(12, Math.min(rect.left - 12, window.innerWidth - width - 12));
      const useBelow = rect.bottom + 188 < window.innerHeight;
      setTooltipPosition({
        left,
        top: useBelow ? rect.bottom + 8 : Math.max(12, rect.top - 176),
      });
    };
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [preview]);

  const previewCard = preview && tooltipPosition
    ? createPortal(
        <div
          className="citation-hover-card"
          id={tooltipId}
          role="tooltip"
          style={tooltipPosition}
        >
          <span>[{index + 1}] {labels.sourceType}{labels.role ? ` · ${labels.role}` : ""}</span>
          <strong>{labels.title}</strong>
          <em>{labels.location} · 点击查看完整原文</em>
          <p>{citation.excerpt}</p>
        </div>,
        document.body,
      )
    : null;

  const shared = {
    "aria-describedby": preview ? tooltipId : undefined,
    "aria-haspopup": "dialog" as const,
    onBlur: () => setPreview(false),
    onClick: () => setOpen(true),
    onFocus: () => setPreview(true),
    onMouseEnter: () => setPreview(true),
    onMouseLeave: () => setPreview(false),
    ref: buttonRef,
    type: "button" as const,
  };

  return (
    <>
      {variant === "inline" ? (
        <sup className="citation-inline-reference">
          <button {...shared} aria-label={`查看参考文献 ${index + 1}`}>
            {index + 1}
          </button>
        </sup>
      ) : (
        <button className="citation-reference-row" {...shared}>
          <span>[{index + 1}]</span>
          <span>
            <strong>{labels.title}</strong>
            <small>{labels.sourceType}{labels.role ? ` · ${labels.role}` : ""} · {labels.location}</small>
          </span>
          <em>查看原文</em>
        </button>
      )}
      {previewCard}
      <CitationDialog
        citation={citation}
        index={index}
        open={open}
        query={query}
        setOpen={setOpen}
      />
    </>
  );
}

function linkCitationMarkers(markdown: string) {
  return markdown.replace(/\[S(\d+)\]/gi, (_match, value: string) => (
    `[${value}](#citation-s${value})`
  ));
}

export function CitationMarkdown({
  children,
  citations,
  query,
}: {
  children: string;
  citations: Citation[];
  query: string;
}) {
  const components = useMemo(
    () => ({
      a({ href, children: linkChildren, title }: ComponentPropsWithoutRef<"a">) {
        const match = /^#citation-s(\d+)$/i.exec(href ?? "");
        if (!match) return <a href={href} title={title}>{linkChildren}</a>;
        const index = Number(match[1]) - 1;
        const citation = citations[index];
        if (!citation) {
          return <sup className="citation-inline-reference invalid">?</sup>;
        }
        return (
          <CitationReference
            citation={citation}
            index={index}
            query={query}
            variant="inline"
          />
        );
      },
    }),
    [citations, query],
  );

  return (
    <Markdown components={components}>
      {linkCitationMarkers(children)}
    </Markdown>
  );
}

export function CitationReferenceList({
  citations,
  query,
}: {
  citations: Citation[];
  query: string;
}) {
  return (
    <div className="citation-reference-list">
      {citations.map((citation, index) => (
        <CitationReference
          citation={citation}
          index={index}
          key={`${citation.source}-${citation.page ?? citation.section ?? "section"}-${index}`}
          query={query}
        />
      ))}
    </div>
  );
}

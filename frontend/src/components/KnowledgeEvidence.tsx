import { FileText, X } from "lucide-react";
import { forwardRef, useState } from "react";

import { apiUrl } from "../lib/api";
import type { PaperKnowledgeReference } from "../types";
import { SourceEvidence } from "./Evidence";
import { difficultyOf, relationLabels } from "../lib/evidence";
import { InlineMarkdown, Markdown } from "./Markdown";

export function KnowledgeEvidenceCard({
  point,
  index,
}: {
  point: PaperKnowledgeReference;
  index: number;
}) {
  const difficulty = difficultyOf(point);
  return (
    <article className="knowledge-evidence-card">
      <header>
        <div>
          <code>{point.code}</code>
          <span>知识点 {index + 1}</span>
        </div>
        <strong><InlineMarkdown>{point.title}</InlineMarkdown></strong>
        {(point.breadcrumb || point.path?.length) && (
          <p className="knowledge-card-breadcrumb">
            <InlineMarkdown>
              {point.breadcrumb ?? point.path?.map((item) => item.title).join(" › ") ?? ""}
            </InlineMarkdown>
          </p>
        )}
      </header>
      {point.definition && (
        <div className="knowledge-definition-block">
          <span>这是什么</span>
          <p><InlineMarkdown>{point.definition}</InlineMarkdown></p>
        </div>
      )}
      <div className="knowledge-difficulty-block">
        <div>
          <span>难度 {difficulty.score.toFixed(2)} · {difficulty.label}</span>
          <em>{difficulty.evidence_level} 级 · 置信度 {Math.round(difficulty.confidence * 100)}%</em>
        </div>
        <div className="difficulty"><span><i style={{ width: `${difficulty.score * 100}%` }} /></span></div>
        <p>{difficulty.rationale}</p>
      </div>
      {(point.relations ?? []).length > 0 && (
        <div className="knowledge-relation-chips">
          {(point.relations ?? []).map((relation) => (
            <div
              className="knowledge-relation-chip"
              key={`${relation.direction}-${relation.relation_type}-${relation.code}`}
            >
              <span>{relationLabels[relation.relation_type] ?? relation.relation_type}</span>
              <b aria-hidden="true">{relation.direction === "outgoing" ? "→" : "←"}</b>
              <div><Markdown>{relation.title}</Markdown></div>
            </div>
          ))}
        </div>
      )}
      <div className="knowledge-card-evidence">
        <h4>支撑这一知识点的原文</h4>
        {point.references.length === 0 && <p>当前没有可定位的教材或大纲原文。</p>}
        {point.references.map((reference, referenceIndex) => (
          <SourceEvidence
            citation={reference}
            index={referenceIndex}
            marker={`证据 ${referenceIndex + 1}`}
            query={point.title}
            key={`${reference.source}-${reference.page ?? reference.section ?? "section"}-${referenceIndex}`}
          />
        ))}
      </div>
    </article>
  );
}

type SourcePreviewDialogProps = {
  jobId: string;
  questionNumber: string;
  pages: number[];
  onClose: () => void;
};

export const SourcePreviewDialog = forwardRef<HTMLDivElement, SourcePreviewDialogProps>(
  function SourcePreviewDialog(
    { jobId, questionNumber, pages, onClose },
    ref,
  ) {
    const [activePage, setActivePage] = useState(pages[0] ?? 1);
    const activePageUrl = apiUrl(
      `/papers/jobs/${jobId}/source/pages/${activePage}`,
    );

    return (
      <div
        className="source-preview-overlay"
        onMouseDown={(event) => {
          if (event.target === event.currentTarget) onClose();
        }}
      >
        <div
          aria-describedby="source-preview-description"
          aria-labelledby="source-preview-title"
          aria-modal="true"
          className="source-preview-dialog"
          ref={ref}
          role="dialog"
        >
          <header>
            <div>
              <span>上传试卷原始证据</span>
              <h2 id="source-preview-title">Question {questionNumber} · 原卷题面</h2>
              <p id="source-preview-description">
                共 {pages.length} 页；图形、表格与版式来自上传 PDF。
              </p>
            </div>
            <button
              aria-label="关闭原卷预览"
              className="source-preview-close"
              onClick={onClose}
              type="button"
            >
              <X size={20} />
            </button>
          </header>
          <div className="source-preview-body">
            <div className="source-preview-pages">
              {pages.length > 1 && (
                <nav aria-label={`Question ${questionNumber} 原卷页码`}>
                  {pages.map((page) => (
                    <button
                      aria-current={activePage === page ? "page" : undefined}
                      className={activePage === page ? "active" : ""}
                      key={page}
                      onClick={() => setActivePage(page)}
                      type="button"
                    >
                      第 {page} 页
                    </button>
                  ))}
                </nav>
              )}
              <figure>
                <figcaption>
                  <span>原卷第 {activePage} 页</span>
                  <a href={activePageUrl} target="_blank" rel="noreferrer">
                    查看原尺寸
                  </a>
                </figcaption>
                <a
                  className="source-preview-image-link"
                  href={activePageUrl}
                  target="_blank"
                  rel="noreferrer"
                >
                  <img
                    src={activePageUrl}
                    alt={`Question ${questionNumber} 所在原卷第 ${activePage} 页`}
                  />
                </a>
              </figure>
            </div>
          </div>
          <footer>
            <a
              href={apiUrl(`/papers/jobs/${jobId}/source`)}
              target="_blank"
              rel="noreferrer"
            >
              <FileText size={15} />
              在新窗口打开完整 PDF
            </a>
            <button onClick={onClose} type="button">关闭</button>
          </footer>
        </div>
      </div>
    );
  },
);

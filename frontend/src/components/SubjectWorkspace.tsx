import {
  BookOpen,
  CheckCircle2,
  FileText,
  FolderOpen,
  LoaderCircle,
  RefreshCw,
  Sparkles,
  Trash2,
  UploadCloud,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { apiClient, setApiSubject, unwrapApi, uploadWorkspaceDocument } from "../lib/api";
import { sourceLabels } from "../lib/evidence";
import type { SourceDocument, SubjectPack } from "../types";
import { ErrorBanner } from "./Feedback";
import { AppConfirmDialog } from "./ui/AppConfirmDialog";

const CORE_SOURCE_TYPES = ["syllabus", "textbook"];
const SUPPLEMENTARY_SOURCE_TYPES = ["textbook", "slide", "revision_note", "topic_practice"];
const ASSESSMENT_SOURCE_TYPES = ["question_paper", "mark_scheme", "insert", "examiner_report"];

type WorkspaceTarget = "assessment" | string;

export function SubjectWorkspace({
  subject,
  view,
  onChanged,
}: {
  subject: SubjectPack;
  view: "documents" | "knowledge";
  onChanged: () => Promise<void>;
}) {
  const [documents, setDocuments] = useState<SourceDocument[]>([]);
  const [target, setTarget] = useState<WorkspaceTarget>(
    view === "knowledge" ? (subject.knowledge_bases[0]?.id ?? "") : "assessment",
  );
  const [sourceType, setSourceType] = useState(
    view === "knowledge" ? "syllabus" : "question_paper",
  );
  const [licenseConfirmed, setLicenseConfirmed] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [busy, setBusy] = useState<"load" | "upload" | "build" | "delete" | null>("load");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<SourceDocument | null>(null);

  const selectedBase = subject.knowledge_bases.find((base) => base.id === target) ?? null;
  const availableTypes = target === "assessment"
    ? ASSESSMENT_SOURCE_TYPES
    : selectedBase?.kind === "core"
      ? CORE_SOURCE_TYPES
      : SUPPLEMENTARY_SOURCE_TYPES;
  const visibleDocuments = useMemo(() => {
    if (target === "assessment") {
      return documents.filter((document) => ASSESSMENT_SOURCE_TYPES.includes(document.source_type));
    }
    return documents.filter((document) => document.knowledge_base_id === target);
  }, [documents, target]);

  const loadDocuments = useCallback(async () => {
    setApiSubject(subject.id);
    setBusy("load");
    try {
      const rows = await unwrapApi(
        apiClient.GET("/api/v1/subject-workspaces/{workspace_id}/documents", {
          params: { path: { workspace_id: subject.id } },
        }),
      );
      setDocuments(rows);
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "资料加载失败");
    } finally {
      setBusy(null);
    }
  }, [subject.id]);

  useEffect(() => {
    void loadDocuments();
  }, [loadDocuments]);

  function selectTarget(nextTarget: WorkspaceTarget) {
    const base = subject.knowledge_bases.find((item) => item.id === nextTarget);
    setTarget(nextTarget);
    setSourceType(nextTarget === "assessment" ? "question_paper" : base?.kind === "core" ? "syllabus" : "textbook");
    setLicenseConfirmed(false);
    setFile(null);
    setFileInputKey((value) => value + 1);
    setNotice("");
    setError(null);
  }

  async function uploadDocument() {
    if (!file) return;
    if (sourceType === "textbook" && !licenseConfirmed) {
      setError("教材进入知识库前必须确认已获得使用授权。");
      return;
    }
    setApiSubject(subject.id);
    setBusy("upload");
    setNotice("");
    setError(null);
    try {
      const uploaded = await uploadWorkspaceDocument(subject.id, file, sourceType, {
        knowledgeBaseId: selectedBase?.id,
        licenseConfirmed,
      });
      await unwrapApi(
        apiClient.POST("/api/v1/corpus/convert", {
          body: {
            document_ids: [uploaded.id],
            source_types: [],
            authority_tiers: [],
            limit: null,
            workers: 2,
            force: false,
          },
        }),
      );
      setNotice(`${file.name} 已上传并完成转换。`);
      setFile(null);
      setFileInputKey((value) => value + 1);
      await Promise.all([loadDocuments(), onChanged()]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "资料上传或转换失败");
    } finally {
      setBusy(null);
    }
  }

  async function deleteDocument(document: SourceDocument) {
    setApiSubject(subject.id);
    setBusy("delete");
    setNotice("");
    setError(null);
    try {
      await unwrapApi(
        apiClient.DELETE("/api/v1/subject-workspaces/{workspace_id}/documents/{document_id}", {
          params: { path: { workspace_id: subject.id, document_id: document.id } },
        }),
      );
      setNotice(`${document.filename} 已删除。`);
      setPendingDelete(null);
      await Promise.all([loadDocuments(), onChanged()]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "资料删除失败");
    } finally {
      setBusy(null);
    }
  }

  async function buildVersion() {
    if (!selectedBase) return;
    setApiSubject(subject.id);
    setBusy("build");
    setNotice("");
    setError(null);
    try {
      const result = await unwrapApi(
        apiClient.POST("/api/v1/knowledge-bases/{knowledge_base_id}/build", {
          params: { path: { knowledge_base_id: selectedBase.id } },
        }),
      );
      setNotice(`${selectedBase.name} v${result.version.version_number} 已构建并发布。`);
      await onChanged();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "知识库版本构建失败");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="subject-workspace">
      <div className="subject-workspace-targets" aria-label={view === "documents" ? "资料分类" : "知识库"}>
        {view === "documents" && (
          <button
            aria-pressed={target === "assessment"}
            className={target === "assessment" ? "active" : ""}
            onClick={() => selectTarget("assessment")}
            type="button"
          >
            <FileText size={18} />
            <span><strong>考试材料</strong><small>试卷、答案标准与配套资料</small></span>
          </button>
        )}
        {subject.knowledge_bases.map((base) => (
          <button
            aria-pressed={target === base.id}
            className={target === base.id ? "active" : ""}
            key={base.id}
            onClick={() => selectTarget(base.id)}
            type="button"
          >
            {base.kind === "core" ? <BookOpen size={18} /> : <FolderOpen size={18} />}
            <span>
              <strong>{base.kind === "core" ? "核心知识库" : "补充知识库"}</strong>
              <small>{base.active_version_number ? `已发布 v${base.active_version_number}` : "尚未发布"} · {base.vector_points} 向量</small>
            </span>
          </button>
        ))}
      </div>

      <ErrorBanner message={error} />
      {notice && <div className="notice" role="status">{notice}</div>}

      <div className="subject-workspace-grid">
        <section className="subject-workspace-upload">
          <header>
            <div>
              <span>{target === "assessment" ? "上传考试材料" : `上传到${selectedBase?.kind === "core" ? "核心" : "补充"}知识库`}</span>
              <h3>添加资料</h3>
            </div>
            <button aria-label="刷新资料" className="icon-button" disabled={busy !== null} onClick={() => void loadDocuments()} type="button">
              <RefreshCw className={busy === "load" ? "spin" : ""} size={17} />
            </button>
          </header>
          {selectedBase?.kind === "core" && (
            <div className="inline-policy"><CheckCircle2 size={16} />核心知识库只接收课程大纲和已授权教材。</div>
          )}
          <label>
            资料类型
            <select value={sourceType} onChange={(event) => {
              setSourceType(event.target.value);
              setLicenseConfirmed(false);
            }}>
              {availableTypes.map((type) => <option key={type} value={type}>{sourceLabels[type] ?? type}</option>)}
            </select>
          </label>
          <label>
            文件
            <input
              accept=".pdf,.ppt,.pptx,.doc,.docx,.md,.txt"
              key={fileInputKey}
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              type="file"
            />
          </label>
          {sourceType === "textbook" && (
            <label className="checkbox-row">
              <input checked={licenseConfirmed} onChange={(event) => setLicenseConfirmed(event.target.checked)} type="checkbox" />
              我确认该教材已获得当前项目使用授权
            </label>
          )}
          <button
            className="primary"
            disabled={!file || busy !== null || (sourceType === "textbook" && !licenseConfirmed)}
            onClick={() => void uploadDocument()}
            type="button"
          >
            {busy === "upload" ? <LoaderCircle className="spin" size={16} /> : <UploadCloud size={16} />}
            上传并转换
          </button>
        </section>

        <section className="subject-workspace-list">
          <header>
            <div><span>当前资料</span><h3>{visibleDocuments.length} 份文件</h3></div>
            {view === "knowledge" && selectedBase && (
              <button className="primary" disabled={!visibleDocuments.length || busy !== null} onClick={() => void buildVersion()} type="button">
                {busy === "build" ? <LoaderCircle className="spin" size={16} /> : <Sparkles size={16} />}
                重新构建并发布
              </button>
            )}
          </header>
          <div className="subject-document-list">
            {visibleDocuments.map((document) => (
              <div key={document.id}>
                <FileText size={17} />
                <span><strong>{document.filename}</strong><small>{sourceLabels[document.source_type] ?? document.source_type} · {document.page_count ?? "—"} 页</small></span>
                <em className={document.status}>{document.status}</em>
                <button aria-label={`删除 ${document.filename}`} className="icon-button danger" disabled={busy !== null} onClick={() => setPendingDelete(document)} type="button"><Trash2 size={16} /></button>
              </div>
            ))}
            {!visibleDocuments.length && <div className="empty compact-empty"><FolderOpen size={28} /><p>还没有资料。</p></div>}
          </div>
        </section>
      </div>
      <AppConfirmDialog
        busy={busy === "delete"}
        confirmLabel="删除资料"
        danger
        description={pendingDelete
          ? `将删除“${pendingDelete.filename}”。已发布的历史知识版本不会被删除。`
          : ""}
        onConfirm={() => pendingDelete ? deleteDocument(pendingDelete) : undefined}
        onOpenChange={(open) => { if (!open) setPendingDelete(null); }}
        open={pendingDelete !== null}
        title="确认删除资料"
      />
    </div>
  );
}

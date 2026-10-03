import { Button, Checkbox, Empty, Select, Tag, Tooltip, Upload } from "antd";
import {
  BookOpen,
  FileText,
  FolderOpen,
  Paperclip,
  RefreshCw,
  ScanText,
  Sparkles,
  Trash2,
  UploadCloud,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { apiClient, subjectHeaders, unwrapApi, uploadWorkspaceDocument } from "../lib/api";
import { useConversionQueue } from "../lib/conversion-queue";
import { sourceLabels } from "../lib/evidence";
import type { SourceDocument, SubjectPack } from "../types";
import { ErrorBanner } from "./Feedback";
import { useToast } from "./toast-context";
import { AppConfirmDialog } from "./ui/AppConfirmDialog";

const CORE_SOURCE_TYPES = ["syllabus", "textbook"];
const SUPPLEMENTARY_SOURCE_TYPES = ["textbook", "slide", "revision_note", "topic_practice"];
const ASSESSMENT_SOURCE_TYPES = ["question_paper", "mark_scheme", "insert", "examiner_report"];

type WorkspaceTarget = "assessment" | string;

const DOCUMENT_STATUS: Record<string, { label: string; color: string }> = {
  discovered: { label: "待解析", color: "warning" },
  queued: { label: "排队中", color: "processing" },
  converting: { label: "解析中", color: "processing" },
  converted: { label: "已解析", color: "success" },
  indexed: { label: "已索引", color: "success" },
  failed: { label: "解析失败", color: "error" },
};

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
  const [busy, setBusy] = useState<"load" | "upload" | "build" | "delete" | null>("load");
  const [error, setError] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const { notify } = useToast();
  const {
    queue: conversionQueue,
    snapshot: { states: conversionStates, finished: finishedConversions },
  } = useConversionQueue(notify);
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
    setBusy("load");
    try {
      const rows = await unwrapApi(
        apiClient.GET("/api/v1/subject-workspaces/{workspace_id}/documents", {
          headers: subjectHeaders(subject.id),
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

  const onChangedRef = useRef(onChanged);
  const handledConversionsRef = useRef(finishedConversions);
  useEffect(() => {
    onChangedRef.current = onChanged;
  }, [onChanged]);
  useEffect(() => {
    if (handledConversionsRef.current === finishedConversions) return;
    handledConversionsRef.current = finishedConversions;
    void Promise.all([loadDocuments(), onChangedRef.current()]);
  }, [finishedConversions, loadDocuments]);

  function selectTarget(nextTarget: WorkspaceTarget) {
    const base = subject.knowledge_bases.find((item) => item.id === nextTarget);
    setTarget(nextTarget);
    setSourceType(nextTarget === "assessment" ? "question_paper" : base?.kind === "core" ? "syllabus" : "textbook");
    setLicenseConfirmed(false);
    setFile(null);
    setError(null);
  }

  async function uploadDocument() {
    if (!file) return;
    if (sourceType === "textbook" && !licenseConfirmed) {
      setError("教材进入知识库前必须确认已获得使用授权。");
      return;
    }
    setBusy("upload");
    setError(null);
    try {
      const uploaded = await uploadWorkspaceDocument(subject.id, file, sourceType, {
        knowledgeBaseId: selectedBase?.id,
        licenseConfirmed,
      });
      setFile(null);
      const queued = conversionQueue.enqueue([uploaded], subject.id);
      notify(queued ? `${file.name} 已上传，正在解析。` : `${file.name} 已上传。`);
      await Promise.all([loadDocuments(), onChanged()]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "资料上传失败");
    } finally {
      setBusy(null);
    }
  }

  async function deleteDocument(document: SourceDocument) {
    setBusy("delete");
    setDeleteError(null);
    try {
      await unwrapApi(
        apiClient.DELETE("/api/v1/subject-workspaces/{workspace_id}/documents/{document_id}", {
          headers: subjectHeaders(subject.id),
          params: { path: { workspace_id: subject.id, document_id: document.id } },
        }),
      );
      notify(`${document.filename} 已删除。`);
      setPendingDelete(null);
      await Promise.all([loadDocuments(), onChanged()]);
    } catch (cause) {
      setDeleteError(cause instanceof Error ? cause.message : "资料删除失败");
    } finally {
      setBusy(null);
    }
  }

  async function buildVersion() {
    if (!selectedBase) return;
    setBusy("build");
    setError(null);
    try {
      const result = await unwrapApi(
        apiClient.POST("/api/v1/knowledge-bases/{knowledge_base_id}/build", {
          headers: subjectHeaders(subject.id),
          params: { path: { knowledge_base_id: selectedBase.id } },
        }),
      );
      notify(`${selectedBase.name} v${result.version.version_number} 已构建并发布。`);
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
            <span><strong>考试材料</strong></span>
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

      <div className="subject-workspace-grid">
        <section className="subject-workspace-upload">
          <header>
            <h3>添加资料</h3>
          </header>
          <div className="subject-workspace-field">
            <span>资料类型</span>
            <Select
              aria-label="资料类型"
              onChange={(value) => {
                setSourceType(value);
                setLicenseConfirmed(false);
              }}
              options={availableTypes.map((type) => ({ label: sourceLabels[type] ?? type, value: type }))}
              value={sourceType}
            />
          </div>
          <div className="subject-workspace-field">
            <span>文件</span>
            <Upload
              accept=".pdf,.ppt,.pptx,.doc,.docx,.md,.txt"
              beforeUpload={(nextFile) => {
                setFile(nextFile);
                return false;
              }}
              maxCount={1}
              showUploadList={false}
            >
              <Button block className="subject-workspace-file" icon={file ? <Paperclip size={15} /> : <UploadCloud size={15} />}>
                <span>{file ? file.name : "选择文件"}</span>
              </Button>
            </Upload>
          </div>
          {sourceType === "textbook" && (
            <Checkbox checked={licenseConfirmed} onChange={(event) => setLicenseConfirmed(event.target.checked)}>
              我确认该教材已获得当前项目使用授权
            </Checkbox>
          )}
          <Button
            block
            disabled={!file || (busy !== null && busy !== "upload") || (sourceType === "textbook" && !licenseConfirmed)}
            icon={<UploadCloud size={16} />}
            loading={busy === "upload"}
            onClick={() => void uploadDocument()}
            type="primary"
          >
            上传并转换
          </Button>
        </section>

        <section className="subject-workspace-list">
          <header>
            <h3>{visibleDocuments.length} 份资料</h3>
            <span className="subject-workspace-list-actions">
              <Tooltip title="刷新">
                <Button
                  aria-label="刷新资料"
                  disabled={busy !== null && busy !== "load"}
                  icon={<RefreshCw className={busy === "load" ? "spin" : ""} size={16} />}
                  onClick={() => void loadDocuments()}
                  type="text"
                />
              </Tooltip>
              {view === "knowledge" && selectedBase && (
                <Button
                  disabled={!visibleDocuments.length || (busy !== null && busy !== "build")}
                  icon={<Sparkles size={16} />}
                  loading={busy === "build"}
                  onClick={() => void buildVersion()}
                  type="primary"
                >
                  重新构建并发布
                </Button>
              )}
            </span>
          </header>
          <div className="subject-document-list">
            {visibleDocuments.map((document) => {
              const statusKey = conversionStates[document.id] ?? document.status;
              const status = DOCUMENT_STATUS[statusKey];
              const canConvert = statusKey === "discovered" || statusKey === "failed";
              return (
                <div key={document.id}>
                  <FileText size={17} />
                  <span>
                    <Tooltip placement="topLeft" title={document.filename}><strong>{document.filename}</strong></Tooltip>
                    <small>{sourceLabels[document.source_type] ?? document.source_type} · {document.page_count ?? "—"} 页</small>
                  </span>
                  <Tag color={status?.color}>{status?.label ?? statusKey}</Tag>
                  {canConvert ? (
                    <Tooltip title={statusKey === "failed" ? "重新解析" : "解析"}>
                      <Button
                        aria-label={`解析 ${document.filename}`}
                        icon={<ScanText size={15} />}
                        onClick={() => {
                          if (conversionQueue.enqueue([document], subject.id)) notify(`${document.filename} 已加入解析队列。`);
                        }}
                        type="text"
                      />
                    </Tooltip>
                  ) : <span aria-hidden="true" />}
                  <Tooltip title="删除">
                    <Button
                      aria-label={`删除 ${document.filename}`}
                      danger
                      disabled={busy !== null}
                      icon={<Trash2 size={15} />}
                      onClick={() => { setDeleteError(null); setPendingDelete(document); }}
                      type="text"
                    />
                  </Tooltip>
                </div>
              );
            })}
            {!visibleDocuments.length && busy !== "load" && (
              <Empty description="暂无资料" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
          </div>
        </section>
      </div>
      <AppConfirmDialog
        busy={busy === "delete"}
        confirmLabel="删除资料"
        danger
        description={pendingDelete
          ? `将删除“${pendingDelete.filename}”。已绑定到试卷的资料需先在试卷中替换；已发布的历史知识版本不会被删除。`
          : ""}
        error={deleteError}
        onConfirm={() => pendingDelete ? deleteDocument(pendingDelete) : undefined}
        onOpenChange={(open) => { if (!open && busy !== "delete") setPendingDelete(null); }}
        open={pendingDelete !== null}
        title="确认删除资料"
      />
    </div>
  );
}

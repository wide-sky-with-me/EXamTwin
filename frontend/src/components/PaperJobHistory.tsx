import {
  FileClock,
  Check,
  LoaderCircle,
  Pencil,
  RefreshCw,
  Trash2,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";

import {
  deletePaperJobs,
  listPaperJobs,
  renamePaperJob,
  replacePaperJob,
} from "../lib/api";
import { PAPER_JOB_STATUS_LABELS } from "../lib/paper-job";
import type {
  PaperJobHistoryStatus,
  PaperJobList,
  PaperJobSummary,
  SubjectPack,
} from "../types";
import { ErrorBanner } from "./Feedback";
import { useToast } from "./toast-context";
import {
  ListFilterBar,
  ListFilterSelect,
  ListPagination,
} from "./ui/ListControls";
import { AppConfirmDialog } from "./ui/AppConfirmDialog";

const DEFAULT_PAGE_SIZE = 10;
const PAGE_SIZES = [10, 20, 50] as const;
const TERMINAL_STATUSES = new Set<PaperJobSummary["status"]>([
  "completed",
  "partial_failed",
  "failed",
]);
const DATE_FORMATTER = new Intl.DateTimeFormat("zh-CN", {
  dateStyle: "medium",
  timeStyle: "short",
});
type HistoryRange = "all" | "7" | "30" | "90";


function createdAfter(range: HistoryRange): string | undefined {
  if (range === "all") return undefined;
  const date = new Date();
  date.setDate(date.getDate() - Number(range));
  return date.toISOString();
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : DATE_FORMATTER.format(date);
}

export function PaperJobHistory({
  subject,
  subjects = subject ? [subject] : [],
  currentJobId,
  refreshKey,
  onOpen,
  onDeleted,
  onSubjectChange = () => undefined,
  paperUnitId,
  embedded = false,
}: {
  subject: SubjectPack | null;
  subjects?: SubjectPack[];
  currentJobId: string | null;
  refreshKey: number;
  onOpen: (jobId: string, paperUnitId?: string | null) => void;
  onDeleted: (jobId: string) => void;
  onSubjectChange?: (subjectId: string) => void;
  paperUnitId?: string;
  embedded?: boolean;
}) {
  const [history, setHistory] = useState<PaperJobList | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [queryDraft, setQueryDraft] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<PaperJobHistoryStatus | "">("");
  const [answerMode, setAnswerMode] = useState<"generated" | "uploaded" | "">("");
  const [unitCode, setUnitCode] = useState("");
  const [range, setRange] = useState<HistoryRange>("all");
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [localRefresh, setLocalRefresh] = useState(0);
  const [deleteCandidate, setDeleteCandidate] = useState<PaperJobSummary | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [bulkConfirming, setBulkConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [repairingId, setRepairingId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftName, setDraftName] = useState("");
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const { notify } = useToast();
  const subjectId = subject?.id ?? null;

  useEffect(() => {
    if (!subjectId) {
      setHistory(null);
      return;
    }
    let active = true;
    setLoading(true);
    setError(null);
    void listPaperJobs(subjectId, {
      status: status || undefined,
      answerMode: answerMode || undefined,
      unitCode: unitCode || undefined,
      paperUnitId,
      query: query || undefined,
      createdAfter: createdAfter(range),
      limit: pageSize,
      offset: page * pageSize,
    })
      .then((result) => {
        if (active) setHistory(result);
      })
      .catch((cause) => {
        if (active) {
          setError(cause instanceof Error ? cause.message : "作答记录加载失败");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [answerMode, localRefresh, page, pageSize, paperUnitId, query, range, refreshKey, status, subjectId, unitCode]);

  useEffect(() => {
    setSelectedIds(new Set());
    setBulkConfirming(false);
    setDeleteCandidate(null);
  }, [answerMode, query, range, status, subjectId, unitCode]);

  function applyQuery() {
    setPage(0);
    setQuery(queryDraft.trim());
  }

  function resetFilters() {
    setQueryDraft("");
    setQuery("");
    setStatus("");
    setAnswerMode("");
    setUnitCode("");
    setRange("all");
    setPage(0);
  }

  function refreshAfterDelete(deletedCount: number) {
    const remaining = Math.max(0, (history?.total ?? deletedCount) - deletedCount);
    const lastPage = Math.max(0, Math.ceil(remaining / pageSize) - 1);
    if (page > lastPage) setPage(lastPage);
    else setLocalRefresh((value) => value + 1);
  }

  async function confirmDelete() {
    if (!deleteCandidate || !subjectId) return;
    const deletingId = deleteCandidate.job_id;
    setDeleting(true);
    setError(null);
    try {
      await deletePaperJobs(subjectId, [deletingId]);
      setDeleteCandidate(null);
      setSelectedIds((current) => {
        const next = new Set(current);
        next.delete(deletingId);
        return next;
      });
      if (deletingId === currentJobId) onDeleted(deletingId);
      refreshAfterDelete(1);
      notify("试卷作答记录已删除。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "作答记录删除失败");
    } finally {
      setDeleting(false);
    }
  }

  async function confirmBulkDelete() {
    const jobIds = [...selectedIds];
    if (!jobIds.length || !subjectId) return;
    setDeleting(true);
    setError(null);
    try {
      const result = await deletePaperJobs(subjectId, jobIds);
      setSelectedIds(new Set());
      setBulkConfirming(false);
      setDeleteCandidate(null);
      if (currentJobId && jobIds.includes(currentJobId)) onDeleted(currentJobId);
      refreshAfterDelete(result.deleted_count);
      notify(`已删除 ${result.deleted_count} 条试卷作答记录。`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "批量删除作答记录失败");
    } finally {
      setDeleting(false);
    }
  }

  async function repairJob(item: PaperJobSummary) {
    if (!subjectId) return;
    setRepairingId(item.job_id);
    setError(null);
    try {
      const replacement = await replacePaperJob(subjectId, item.job_id);
      notify("已创建替代任务；旧记录将保留用于审计。");
      setLocalRefresh((value) => value + 1);
      onOpen(replacement.job_id, item.paper_unit_id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "替代任务创建失败");
    } finally {
      setRepairingId(null);
    }
  }

  async function confirmRename(item: PaperJobSummary) {
    if (!subjectId) return;
    const normalized = draftName.trim();
    if (!normalized) {
      setError("显示名称不能为空");
      return;
    }
    setRenamingId(item.job_id);
    setError(null);
    try {
      await renamePaperJob(subjectId, item.job_id, normalized);
      setEditingId(null);
      setLocalRefresh((value) => value + 1);
      notify("作答记录名称已更新。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "作答记录名称保存失败");
    } finally {
      setRenamingId(null);
    }
  }

  function toggleSelection(jobId: string) {
    setDeleteCandidate(null);
    setBulkConfirming(false);
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(jobId)) next.delete(jobId);
      else next.add(jobId);
      return next;
    });
  }

  const selectableIds =
    history?.items
      .filter((item) => !item.replacement_for_job_id && !item.replaced_by_job_id)
      .map((item) => item.job_id) ?? [];
  const allPageSelected =
    selectableIds.length > 0 && selectableIds.every((jobId) => selectedIds.has(jobId));
  const somePageSelected = selectableIds.some((jobId) => selectedIds.has(jobId));

  function toggleCurrentPage() {
    setDeleteCandidate(null);
    setBulkConfirming(false);
    setSelectedIds((current) => {
      const next = new Set(current);
      for (const jobId of selectableIds) {
        if (allPageSelected) next.delete(jobId);
        else next.add(jobId);
      }
      return next;
    });
  }


  return (
    <article aria-busy={loading} className={`panel paper-history${embedded ? " paper-history-embedded" : ""}`}>
      <header>
        <div>
          <FileClock size={19} />
          <div>
            <h2>{embedded ? "作答记录" : "全部作答记录"}</h2>
          </div>
        </div>
        <button
          aria-label="刷新试卷作答记录"
          className="secondary"
          disabled={loading || !subject}
          onClick={() => setLocalRefresh((value) => value + 1)}
          type="button"
        >
          {loading ? <LoaderCircle className="spin" size={15} /> : <RefreshCw size={15} />}
          刷新
        </button>
      </header>

      <ListFilterBar
        ariaLabel="作答记录搜索与筛选"
        onQueryChange={setQueryDraft}
        onReset={resetFilters}
        onSearch={applyQuery}
        query={queryDraft}
        queryLabel="按名称或文件名筛选"
        queryPlaceholder="搜索作答名称或文件名"
        resetDisabled={!queryDraft && !query && !status && !answerMode && !unitCode && range === "all"}
      >
        {!embedded && (
          <ListFilterSelect
            ariaLabel="按科目筛选"
            onValueChange={(value) => {
              setPage(0);
              setUnitCode("");
              onSubjectChange(value);
            }}
            options={subjects.map((item) => ({
              label: `${item.title} · ${item.subject_code}`,
              value: item.id,
            }))}
            value={subject?.id ?? ""}
          />
        )}
        <ListFilterSelect
          ariaLabel="按状态筛选"
          onValueChange={(value) => {
            setPage(0);
            setStatus(value as PaperJobHistoryStatus | "");
          }}
          options={[
            { label: "全部状态", value: "" },
            { label: "处理中", value: "active" },
            { label: "处理完成", value: "completed" },
            { label: "部分题目失败", value: "partial_failed" },
            { label: "处理失败", value: "failed" },
          ]}
          value={status}
        />
        <ListFilterSelect
          ariaLabel="按来源筛选"
          onValueChange={(value) => {
            setPage(0);
            setAnswerMode(value as "generated" | "uploaded" | "");
          }}
          options={[
            { label: "全部来源", value: "" },
            { label: "AI 作答", value: "generated" },
            { label: "外部答卷", value: "uploaded" },
          ]}
          value={answerMode}
        />
        {!embedded && (
          <ListFilterSelect
            ariaLabel="按单元筛选"
            onValueChange={(value) => {
              setPage(0);
              setUnitCode(value);
            }}
            options={[
              { label: "全部单元", value: "" },
              ...(subject?.units.map((item) => ({
                label: item.code,
                value: item.code,
              })) ?? []),
            ]}
            value={unitCode}
          />
        )}
        <ListFilterSelect
          ariaLabel="按时间筛选"
          onValueChange={(value) => {
            setPage(0);
            setRange(value as HistoryRange);
          }}
          options={[
            { label: "全部时间", value: "all" },
            { label: "最近 7 天", value: "7" },
            { label: "最近 30 天", value: "30" },
            { label: "最近 90 天", value: "90" },
          ]}
          value={range}
        />
      </ListFilterBar>

      <ErrorBanner message={error} />
      {selectedIds.size > 0 && (
        <div aria-label="批量删除操作" className="paper-history-bulk" role="region">
          <strong>已选择 {selectedIds.size} 条</strong>
          <button onClick={() => setSelectedIds(new Set())} type="button">取消选择</button>
          <button className="danger" onClick={() => setBulkConfirming(true)} type="button">
            <Trash2 size={14} />
            批量删除
          </button>
        </div>
      )}
      {loading && !history ? (
        <p className="paper-history-loading"><LoaderCircle className="spin" size={16} />正在加载作答记录…</p>
      ) : history?.items.length ? (
        <>
        <div className="paper-history-select-all">
          <label>
            <input
              aria-label="全选当前页可删除记录"
              checked={allPageSelected}
              disabled={!selectableIds.length}
              onChange={toggleCurrentPage}
              ref={(element) => {
                if (element) element.indeterminate = somePageSelected && !allPageSelected;
              }}
              type="checkbox"
            />
            选择当前页
          </label>
          {selectedIds.size > 0 && <span>跨页保留选择</span>}
        </div>
        <ul className="paper-history-list">
          {history.items.map((item) => {
            const selectable = !item.replacement_for_job_id && !item.replaced_by_job_id;
            const unverified = item.source_integrity_status === "legacy_unverified"
              || item.source_integrity_status === "replacement_queued";
            const repairingThis = repairingId === item.job_id;
            return (
              <li aria-current={item.job_id === currentJobId ? "true" : undefined} key={item.job_id}>
                <input
                  aria-label={`选择记录 ${item.display_name || item.filename}`}
                  checked={selectedIds.has(item.job_id)}
                  className="paper-history-checkbox"
                  disabled={!selectable || deleting}
                  onChange={() => toggleSelection(item.job_id)}
                  title={selectable ? "选择记录" : "具有替代审计关系的记录不能删除"}
                  type="checkbox"
                />
                <div className="paper-history-main">
                  {editingId === item.job_id ? (
                    <input
                      aria-label={`修改 ${item.display_name || item.filename} 的显示名称`}
                      autoFocus
                      className="paper-history-rename-input"
                      disabled={renamingId === item.job_id}
                      maxLength={200}
                      onChange={(event) => setDraftName(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") void confirmRename(item);
                        if (event.key === "Escape") setEditingId(null);
                      }}
                      value={draftName}
                    />
                  ) : (
                    <div className="paper-history-title-row">
                      <strong>{item.display_name || item.filename}</strong>
                      <span className={`paper-history-mode ${item.answer_mode === "uploaded" ? "uploaded" : "generated"}`}>
                        {item.answer_mode === "uploaded" ? "外部答卷" : "AI 作答"}
                      </span>
                    </div>
                  )}
                  <small>
                    {formatDate(item.created_at)} · {item.unit_code || "未限定单元"}
                  </small>
                  {item.display_name && <small>原文件：{item.filename}</small>}
                  {unverified && (
                    <small className="paper-history-integrity">
                      {item.replaced_by_job_id
                        ? "旧版未验证结果 · 已创建替代任务"
                        : "旧版未验证结果 · 不应作为可信答案"}
                    </small>
                  )}
                </div>
                <span className={`paper-history-status ${item.status}`}>
                  {PAPER_JOB_STATUS_LABELS[item.status]}
                </span>
                <span className="paper-history-counts">
                  {item.total_questions > 0
                    ? `${item.completed_questions}/${item.total_questions} 题已处理`
                    : "等待识别题目"}
                  {item.failed_questions > 0 ? ` · ${item.failed_questions} 题处理失败` : ""}
                </span>
                <div className="paper-history-actions">
                    {editingId === item.job_id ? (
                      <>
                        <button
                          aria-label="取消修改名称"
                          className="paper-history-icon-action"
                          disabled={renamingId === item.job_id}
                          onClick={() => setEditingId(null)}
                          title="取消"
                          type="button"
                        ><X size={15} /></button>
                        <button
                          aria-label="保存显示名称"
                          className="paper-history-icon-action save"
                          disabled={renamingId === item.job_id || !draftName.trim()}
                          onClick={() => void confirmRename(item)}
                          title="保存名称"
                          type="button"
                        >
                          {renamingId === item.job_id
                            ? <LoaderCircle className="spin" size={15} />
                            : <Check size={15} />}
                        </button>
                      </>
                    ) : (
                      <>
                    <button className="secondary" onClick={() => onOpen(item.job_id, item.paper_unit_id)} type="button">
                      查看
                    </button>
                    {item.replaced_by_job_id ? (
                      <button
                        className="secondary"
                        onClick={() => onOpen(item.replaced_by_job_id!, item.paper_unit_id)}
                        type="button"
                      >
                        查看替代任务
                      </button>
                    ) : unverified && selectable ? (
                      <button
                        className="secondary"
                        disabled={repairingThis}
                        onClick={() => void repairJob(item)}
                        type="button"
                      >
                        {repairingThis
                          ? <LoaderCircle className="spin" size={14} />
                          : <RefreshCw size={14} />}
                        修复并重跑
                      </button>
                    ) : null}
                    <button
                      aria-label={`修改 ${item.display_name || item.filename} 的显示名称`}
                      className="paper-history-icon-action"
                      onClick={() => {
                        setEditingId(item.job_id);
                        setDraftName(item.display_name || item.filename);
                        setError(null);
                      }}
                      title="修改显示名称"
                      type="button"
                    >
                      <Pencil size={15} />
                    </button>
                    {selectable && (
                      <button
                        aria-label={`删除记录 ${item.display_name || item.filename}`}
                        className="paper-history-delete"
                        onClick={() => {
                          setBulkConfirming(false);
                          setDeleteCandidate(item);
                        }}
                        title={TERMINAL_STATUSES.has(item.status) ? "删除记录" : "取消并删除任务"}
                        type="button"
                      >
                        <Trash2 size={15} />
                      </button>
                    )}
                      </>
                    )}
                  </div>
              </li>
            );
          })}
        </ul>
        </>
      ) : (
        <p className="paper-history-empty">没有符合当前条件的作答记录。</p>
      )}

      {history && (
        <ListPagination
          ariaLabel="作答记录分页"
          disabled={loading}
          itemName="作答记录"
          itemUnit="条"
          onPageChange={setPage}
          onPageSizeChange={(size) => {
            setPage(0);
            setPageSize(size);
          }}
          page={page}
          pageSize={pageSize}
          pageSizes={PAGE_SIZES}
          total={history.total}
          pageSizeLabel="每页显示条数"
          visibleCount={history.items.length}
        />
      )}

      <AppConfirmDialog
        busy={deleting}
        confirmLabel="删除作答记录"
        danger
        description={deleteCandidate
          ? `将永久删除“${deleteCandidate.display_name || deleteCandidate.filename}”的作答结果、关联评分、复核记录和作答文件。此操作无法恢复。`
          : ""}
        onConfirm={confirmDelete}
        onOpenChange={(open) => {
          if (!open) setDeleteCandidate(null);
        }}
        open={deleteCandidate !== null}
        title="确认删除作答记录"
      />
      <AppConfirmDialog
        busy={deleting}
        confirmLabel={`删除 ${selectedIds.size} 条记录`}
        danger
        description={`将永久删除选中的 ${selectedIds.size} 条作答记录，以及关联评分、复核记录和作答文件。此操作无法恢复。`}
        onConfirm={confirmBulkDelete}
        onOpenChange={setBulkConfirming}
        open={bulkConfirming}
        title="确认批量删除"
      />
    </article>
  );
}

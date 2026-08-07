import {
  ChevronLeft,
  ChevronRight,
  FileClock,
  LoaderCircle,
  RefreshCw,
  Search,
  Trash2,
} from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";

import { deletePaperJobs, listPaperJobs, replacePaperJob } from "../lib/api";
import { PAPER_JOB_STATUS_LABELS } from "../lib/paper-job";
import type {
  PaperJobHistoryStatus,
  PaperJobList,
  PaperJobSummary,
  SubjectPack,
} from "../types";
import { ErrorBanner } from "./Feedback";
import { useToast } from "./toast-context";

const DEFAULT_PAGE_SIZE = 10;
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


function canDeleteJob(item: PaperJobSummary): boolean {
  return TERMINAL_STATUSES.has(item.status)
    && !item.replacement_for_job_id
    && !item.replaced_by_job_id;
}
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
  currentJobId,
  refreshKey,
  onOpen,
  onDeleted,
}: {
  subject: SubjectPack | null;
  currentJobId: string | null;
  refreshKey: number;
  onOpen: (jobId: string) => void;
  onDeleted: (jobId: string) => void;
}) {
  const [history, setHistory] = useState<PaperJobList | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [queryDraft, setQueryDraft] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<PaperJobHistoryStatus | "">("");
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
    void listPaperJobs({
      status: status || undefined,
      unitCode: unitCode || undefined,
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
  }, [localRefresh, page, pageSize, query, range, refreshKey, status, subjectId, unitCode]);

  useEffect(() => {
    setSelectedIds(new Set());
    setBulkConfirming(false);
    setDeleteCandidate(null);
  }, [query, range, status, subjectId, unitCode]);

  function applyQuery(event: FormEvent) {
    event.preventDefault();
    setPage(0);
    setQuery(queryDraft.trim());
  }

  function refreshAfterDelete(deletedCount: number) {
    const remaining = Math.max(0, (history?.total ?? deletedCount) - deletedCount);
    const lastPage = Math.max(0, Math.ceil(remaining / pageSize) - 1);
    if (page > lastPage) setPage(lastPage);
    else setLocalRefresh((value) => value + 1);
  }

  async function confirmDelete() {
    if (!deleteCandidate) return;
    const deletingId = deleteCandidate.job_id;
    setDeleting(true);
    setError(null);
    try {
      await deletePaperJobs([deletingId]);
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
    if (!jobIds.length) return;
    setDeleting(true);
    setError(null);
    try {
      const result = await deletePaperJobs(jobIds);
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
    setRepairingId(item.job_id);
    setError(null);
    try {
      const replacement = await replacePaperJob(item.job_id);
      notify("已创建替代任务；旧记录将保留用于审计。");
      setLocalRefresh((value) => value + 1);
      onOpen(replacement.job_id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "替代任务创建失败");
    } finally {
      setRepairingId(null);
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
      .filter(canDeleteJob)
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

  const firstItem = history && history.total > 0 ? history.offset + 1 : 0;
  const lastItem = history ? history.offset + history.items.length : 0;
  const hasPrevious = page > 0;
  const hasNext = history ? lastItem < history.total : false;
  const totalPages = Math.max(1, Math.ceil((history?.total ?? 0) / pageSize));

  return (
    <article aria-busy={loading} className="panel paper-history">
      <header>
        <div>
          <FileClock size={19} />
          <div>
            <h2>试卷作答记录</h2>
            <p>查看历史结果，按条件筛选，或删除不再需要的记录。</p>
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

      <form className="paper-history-filters" onSubmit={applyQuery}>
        <label>
          <span>文件名</span>
          <div className="paper-history-search">
            <Search size={15} />
            <input
              aria-label="按文件名筛选"
              onChange={(event) => setQueryDraft(event.target.value)}
              placeholder="搜索试卷文件名"
              type="search"
              value={queryDraft}
            />
          </div>
        </label>
        <label>
          <span>状态</span>
          <select
            aria-label="按状态筛选"
            onChange={(event) => {
              setPage(0);
              setStatus(event.target.value as PaperJobHistoryStatus | "");
            }}
            value={status}
          >
            <option value="">全部状态</option>
            <option value="active">处理中</option>
            <option value="completed">处理完成</option>
            <option value="partial_failed">部分题目失败</option>
            <option value="failed">处理失败</option>
          </select>
        </label>
        <label>
          <span>单元</span>
          <select
            aria-label="按单元筛选"
            onChange={(event) => {
              setPage(0);
              setUnitCode(event.target.value);
            }}
            value={unitCode}
          >
            <option value="">全部单元</option>
            {subject?.units.map((item) => (
              <option key={item.code} value={item.code}>{item.code}</option>
            ))}
          </select>
        </label>
        <label>
          <span>时间</span>
          <select
            aria-label="按时间筛选"
            onChange={(event) => {
              setPage(0);
              setRange(event.target.value as HistoryRange);
            }}
            value={range}
          >
            <option value="all">全部时间</option>
            <option value="7">最近 7 天</option>
            <option value="30">最近 30 天</option>
            <option value="90">最近 90 天</option>
          </select>
        </label>
        <button className="secondary" type="submit">筛选</button>
      </form>

      <ErrorBanner message={error} />
      {selectedIds.size > 0 && (
        <div aria-label="批量删除操作" className="paper-history-bulk" role="region">
          {bulkConfirming ? (
            <>
              <strong role="alert">确认删除选中的 {selectedIds.size} 条记录？</strong>
              <button disabled={deleting} onClick={() => setBulkConfirming(false)} type="button">
                取消
              </button>
              <button
                className="danger"
                disabled={deleting}
                onClick={() => void confirmBulkDelete()}
                type="button"
              >
                {deleting ? <LoaderCircle className="spin" size={14} /> : <Trash2 size={14} />}
                确认批量删除
              </button>
            </>
          ) : (
            <>
              <strong>已选择 {selectedIds.size} 条</strong>
              <button onClick={() => setSelectedIds(new Set())} type="button">取消选择</button>
              <button className="danger" onClick={() => setBulkConfirming(true)} type="button">
                <Trash2 size={14} />
                批量删除
              </button>
            </>
          )}
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
            const deletingThis = deleteCandidate?.job_id === item.job_id;
            const selectable = canDeleteJob(item);
            const unverified = item.source_integrity_status === "legacy_unverified"
              || item.source_integrity_status === "replacement_queued";
            const repairingThis = repairingId === item.job_id;
            return (
              <li aria-current={item.job_id === currentJobId ? "true" : undefined} key={item.job_id}>
                <input
                  aria-label={`选择记录 ${item.filename}`}
                  checked={selectedIds.has(item.job_id)}
                  className="paper-history-checkbox"
                  disabled={!selectable || deleting}
                  onChange={() => toggleSelection(item.job_id)}
                  title={selectable ? "选择记录" : "处理中记录不能删除"}
                  type="checkbox"
                />
                <div className="paper-history-main">
                  <strong>{item.filename}</strong>
                  <small>
                    {formatDate(item.created_at)} · {item.unit_code || "未限定单元"}
                  </small>
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
                {deletingThis ? (
                  <div className="paper-history-confirm" role="alert">
                    <span>确认删除？</span>
                    <button disabled={deleting} onClick={() => setDeleteCandidate(null)} type="button">
                      取消
                    </button>
                    <button className="danger" disabled={deleting} onClick={() => void confirmDelete()} type="button">
                      {deleting ? <LoaderCircle className="spin" size={14} /> : <Trash2 size={14} />}
                      确认删除
                    </button>
                  </div>
                ) : (
                  <div className="paper-history-actions">
                    <button className="secondary" onClick={() => onOpen(item.job_id)} type="button">
                      查看
                    </button>
                    {item.replaced_by_job_id ? (
                      <button
                        className="secondary"
                        onClick={() => onOpen(item.replaced_by_job_id!)}
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
                    {selectable && (
                      <button
                        aria-label={`删除记录 ${item.filename}`}
                        className="paper-history-delete"
                        onClick={() => {
                          setBulkConfirming(false);
                          setDeleteCandidate(item);
                        }}
                        title="删除记录"
                        type="button"
                      >
                        <Trash2 size={15} />
                      </button>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
        </>
      ) : (
        <p className="paper-history-empty">没有符合当前条件的作答记录。</p>
      )}

      {history && history.total > 0 && (
        <footer>
          <span>共 {history.total} 条 · 当前显示 {firstItem}–{lastItem}</span>
          <div className="paper-history-pagination">
            <label>
              每页
              <select
                aria-label="每页显示条数"
                disabled={loading}
                onChange={(event) => {
                  setPage(0);
                  setPageSize(Number(event.target.value));
                }}
                value={pageSize}
              >
                <option value={10}>10 条</option>
                <option value={20}>20 条</option>
                <option value={50}>50 条</option>
              </select>
            </label>
            <span>第 {page + 1} / {totalPages} 页</span>
            <button
              aria-label="上一页作答记录"
              disabled={!hasPrevious || loading}
              onClick={() => setPage((value) => value - 1)}
              type="button"
            >
              <ChevronLeft size={15} />
            </button>
            <button
              aria-label="下一页作答记录"
              disabled={!hasNext || loading}
              onClick={() => setPage((value) => value + 1)}
              type="button"
            >
              <ChevronRight size={15} />
            </button>
          </div>
        </footer>
      )}
    </article>
  );
}

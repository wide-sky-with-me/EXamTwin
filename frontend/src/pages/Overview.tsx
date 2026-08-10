import {
  BookOpenCheck,
  CheckCircle2,
  CheckSquare2,
  CircleGauge,
  Database,
  FileCheck2,
  HardDrive,
  Layers3,
  LoaderCircle,
  LockKeyhole,
  Network,
  Plus,
  RefreshCw,
  ShieldCheck,
  Square,
  Trash2,
  X,
} from "lucide-react";
import { type FormEvent, useState } from "react";
import { createPortal } from "react-dom";

import { apiClient, unwrapApi } from "../lib/api";
import { sourceLabels } from "../lib/evidence";
import { useModalFocus } from "../lib/use-modal-focus";
import type { PlatformStatus, SubjectStatus } from "../types";

export function Overview({
  platform,
  selected,
  selectSubject,
  refresh,
  loading,
}: {
  platform: PlatformStatus | null;
  selected: SubjectStatus | null;
  selectSubject: (packageId: string | null) => void;
  refresh: () => Promise<void>;
  loading: boolean;
}) {
  const [inventorying, setInventorying] = useState(false);
  const [notice, setNotice] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [managingSubjects, setManagingSubjects] = useState(false);
  const [selectedSubjectIds, setSelectedSubjectIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deletingSubjects, setDeletingSubjects] = useState(false);
  const deleteDialogRef = useModalFocus(confirmingDelete, setConfirmingDelete);
  const [subjectDraft, setSubjectDraft] = useState({
    id: "",
    subject_code: "",
    title: "",
    board_name: "",
  });

  async function createSubject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreating(true);
    setNotice("");
    try {
      const created = await unwrapApi(
        apiClient.POST("/api/v1/subject-workspaces", {
          body: {
            ...subjectDraft,
            capability_profile_id: null,
            language: "en",
          },
        }),
      );
      await refresh();
      selectSubject(created.id);
      setSubjectDraft({ id: "", subject_code: "", title: "", board_name: "" });
      setShowCreate(false);
      setNotice(`已创建 ${created.subject_code} 科目工作区。`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "科目工作区创建失败");
    } finally {
      setCreating(false);
    }
  }

  async function inventory() {
    if (!selected) return;
    setInventorying(true);
    setNotice("");
    try {
      const result = await unwrapApi(
        apiClient.POST("/api/v1/corpus/inventory", { body: { refresh: true } }),
      );
      const failureSummary = Object.entries(result.identity_failures)
        .map(([reason, count]) => `${reason} ${count} 份`)
        .join("；");
      setNotice(
        result.exam_identity_incomplete
          ? `已核验 ${result.scanned} 份资料；${result.exam_identity_incomplete} 份考试资料身份不完整${failureSummary ? `（${failureSummary}）` : ""}。`
          : `已核验 ${result.scanned} 份资料，全部考试资料身份均可判定。`,
      );
      await refresh();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "清点失败");
    } finally {
      setInventorying(false);
    }
  }

  const subjects = platform?.subjects ?? [];
  const deletableSubjects = subjects.filter((item) => !item.capability_profile_id);
  const selectedForDeletion = deletableSubjects.filter((item) =>
    selectedSubjectIds.has(item.id),
  );
  const allDeletableSelected =
    deletableSubjects.length > 0
    && deletableSubjects.every((item) => selectedSubjectIds.has(item.id));

  function stopManagingSubjects() {
    setManagingSubjects(false);
    setSelectedSubjectIds(new Set());
    setConfirmingDelete(false);
  }

  function toggleSubjectSelection(subjectId: string) {
    setSelectedSubjectIds((current) => {
      const next = new Set(current);
      if (next.has(subjectId)) next.delete(subjectId);
      else next.add(subjectId);
      return next;
    });
  }

  async function deleteSelectedSubjects() {
    if (!selectedForDeletion.length) return;
    setDeletingSubjects(true);
    setNotice("");
    try {
      const result = await unwrapApi(
        apiClient.POST("/api/v1/subject-workspaces/batch-delete", {
          body: { subject_ids: selectedForDeletion.map((item) => item.id) },
        }),
      );
      stopManagingSubjects();
      await refresh();
      setNotice(`已删除 ${result.deleted_count} 个科目工作区。`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "科目工作区删除失败");
      setConfirmingDelete(false);
    } finally {
      setDeletingSubjects(false);
    }
  }

  const infrastructure = platform?.infrastructure;
  const infrastructureItems = [
    ["PostgreSQL", infrastructure?.postgresql, Database],
    ["Qdrant", infrastructure?.qdrant, Network],
    ["对象存储", infrastructure?.object_storage, HardDrive],
  ] as const;
  const statusLabel = (ready: boolean | undefined) =>
    ready === undefined ? "检查中" : ready ? "正常" : "异常";
  const statusClass = (ready: boolean | undefined) =>
    ready === undefined ? "checking" : ready ? "ready" : "offline";
  const metricValue = (value: number | null | undefined) => value ?? "—";
  const stats = selected?.stats;
  const metrics = [
    ["资料总数", stats?.documents_total ?? "—", Database],
    ["严格 QP/MS 配对", stats?.strict_pairs ?? "—", FileCheck2],
    ["知识节点", stats?.knowledge_points ?? "—", Network],
    ["待人工复核", stats?.pending_reviews ?? "—", ShieldCheck],
  ] as const;

  return (
    <section>
      <div className="page-heading status-heading">
        <div>
          <h1>所有科目，一套可验证的工作流。</h1>
          <p>在这里选择科目上下文，并检查资料、知识索引、答题能力与基础设施是否就绪。</p>
        </div>
        <div className="page-heading-actions">
          <button
            className={managingSubjects ? "secondary active" : "secondary"}
            onClick={() => {
              if (managingSubjects) stopManagingSubjects();
              else {
                setShowCreate(false);
                setManagingSubjects(true);
              }
            }}
            type="button"
          >
            {managingSubjects ? <X size={17} /> : <Trash2 size={17} />}
            {managingSubjects ? "完成管理" : "管理科目"}
          </button>
          <button
            className="secondary"
            disabled={managingSubjects}
            onClick={() => setShowCreate((value) => !value)}
            type="button"
          >
            <Plus size={17} />
            新建科目
          </button>
          <button
            className="secondary"
            onClick={() => void refresh()}
            disabled={loading || managingSubjects}
          >
            {loading ? <LoaderCircle className="spin" size={17} /> : <RefreshCw size={17} />}
            刷新状态
          </button>
        </div>
      </div>
      {showCreate && (
        <form className="panel subject-create-panel" onSubmit={(event) => void createSubject(event)}>
          <div>
            <span className="kicker">新科目工作区</span>
            <h2>建立隔离的资料、知识与评测边界</h2>
            <p>新科目会自动获得核心知识库和补充知识库；能力模板可在服务端后续绑定。</p>
          </div>
          <div className="subject-create-fields">
            <label>
              科目标识
              <input
                required
                pattern="[a-z0-9][a-z0-9-]{1,62}"
                placeholder="例如 international-physics"
                value={subjectDraft.id}
                onChange={(event) => setSubjectDraft((draft) => ({ ...draft, id: event.target.value }))}
              />
            </label>
            <label>
              科目代码
              <input
                required
                placeholder="例如 9630"
                value={subjectDraft.subject_code}
                onChange={(event) => setSubjectDraft((draft) => ({ ...draft, subject_code: event.target.value }))}
              />
            </label>
            <label>
              科目名称
              <input
                required
                placeholder="例如 International A-level Physics"
                value={subjectDraft.title}
                onChange={(event) => setSubjectDraft((draft) => ({ ...draft, title: event.target.value }))}
              />
            </label>
            <label>
              课程体系
              <input
                required
                placeholder="例如 OxfordAQA International Qualifications"
                value={subjectDraft.board_name}
                onChange={(event) => setSubjectDraft((draft) => ({ ...draft, board_name: event.target.value }))}
              />
            </label>
          </div>
          <div className="subject-create-actions">
            <button className="secondary" onClick={() => setShowCreate(false)} type="button">取消</button>
            <button className="primary" disabled={creating} type="submit">
              {creating ? <LoaderCircle className="spin" size={16} /> : <Plus size={16} />}
              创建工作区
            </button>
          </div>
        </form>
      )}
      {notice && <div className="notice" role="status">{notice}</div>}

      <div className="infrastructure-strip" aria-label="基础设施状态">
        {infrastructureItems.map(([label, ready, Icon]) => (
          <div key={label} className={statusClass(ready)}>
            <Icon size={17} />
            <span>{label}</span>
            <b>{statusLabel(ready)}</b>
          </div>
        ))}
      </div>

      {managingSubjects && (
        <div className="subject-management-toolbar">
          <div>
            <strong>
              {selectedForDeletion.length
                ? `已选择 ${selectedForDeletion.length} 个自建科目`
                : "选择要删除的自建科目"}
            </strong>
            <span>内置科目受保护，不会进入删除范围。</span>
          </div>
          <button
            className="secondary"
            disabled={!deletableSubjects.length}
            onClick={() => {
              setSelectedSubjectIds(
                allDeletableSelected
                  ? new Set()
                  : new Set(deletableSubjects.map((item) => item.id)),
              );
            }}
            type="button"
          >
            {allDeletableSelected ? "取消全选" : "全选自建科目"}
          </button>
          <button
            className="danger"
            disabled={!selectedForDeletion.length}
            onClick={() => setConfirmingDelete(true)}
            type="button"
          >
            <Trash2 size={16} />
            删除所选
          </button>
        </div>
      )}

      <div className={`subject-status-grid ${managingSubjects ? "is-managing" : ""}`}>
        {subjects.map((item) => {
          const active = item.id === selected?.id;
          const converted = item.stats?.documents_by_status.converted;
          const protectedSubject = Boolean(item.capability_profile_id);
          const selectedForDelete = selectedSubjectIds.has(item.id);
          return (
            <button
              type="button"
              key={item.id}
              className={[
                "subject-status-card",
                !managingSubjects && active ? "active" : "",
                selectedForDelete ? "selected-for-delete" : "",
                managingSubjects && protectedSubject ? "protected" : "",
              ].filter(Boolean).join(" ")}
              disabled={managingSubjects && protectedSubject}
              onClick={() => {
                if (managingSubjects) toggleSubjectSelection(item.id);
                else selectSubject(item.id);
              }}
              aria-label={
                managingSubjects
                  ? protectedSubject
                    ? `${item.subject_code} ${item.title}，内置科目不可删除`
                    : `${selectedForDelete ? "取消选择" : "选择"} ${item.subject_code} ${item.title}`
                  : undefined
              }
              aria-pressed={managingSubjects ? selectedForDelete : active}
            >
              {managingSubjects && (
                <span className="subject-manage-indicator" aria-hidden="true">
                  {protectedSubject
                    ? <LockKeyhole size={18} />
                    : selectedForDelete
                      ? <CheckSquare2 size={19} />
                      : <Square size={19} />}
                </span>
              )}
              <span className="subject-code">{item.subject_code}</span>
              <div>
                <strong>{item.title.replace(/^OxfordAQA International /, "")}</strong>
                <small>{item.board_name} · {item.units.length} 个 Unit</small>
              </div>
              <dl>
                <div><dt>资料</dt><dd>{metricValue(item.stats?.documents_total)}</dd></div>
                <div><dt>已转换</dt><dd>{metricValue(converted)}</dd></div>
                <div><dt>知识点</dt><dd>{metricValue(item.stats?.knowledge_points)}</dd></div>
                <div><dt>向量</dt><dd>{item.vector_points}</dd></div>
              </dl>
              <footer>
                <span className={item.answering_enabled ? "ready" : "pending"}>
                  <BookOpenCheck size={14} /> {item.answering_enabled ? "答题 Skill 已启用" : "答题 Skill 未启用"}
                </span>
                <span className={item.vector_index_ready ? "ready" : "pending"}>
                  <CheckCircle2 size={14} /> {item.vector_index_ready ? "检索可用" : "索引待发布"}
                </span>
              </footer>
            </button>
          );
        })}
      </div>

      {!selected ? (
        <div className="panel context-empty">
          <Layers3 size={28} />
          <h2>选择一个科目，进入对应工作区</h2>
          <p>切换后，Unit、资料统计、知识图谱、RAG 索引、试卷任务和评分复核会同步切换。</p>
        </div>
      ) : (
        <>
          <div className="selected-context-bar">
            <div>
              <span>当前上下文</span>
              <strong>{selected.subject_code} · {selected.title}</strong>
            </div>
            <button className="secondary" onClick={inventory} disabled={inventorying}>
              {inventorying ? <LoaderCircle className="spin" size={17} /> : <RefreshCw size={17} />}
              重新清点该科资料
            </button>
          </div>

          <div className="metric-grid">
            {metrics.map(([label, value, Icon]) => (
              <article className="metric-card" key={label}>
                <div className="metric-icon"><Icon size={19} /></div>
                <span>{label}</span>
                <strong>{loading ? "…" : value}</strong>
              </article>
            ))}
          </div>

          <div className="overview-grid">
            <article className="panel">
              <div className="panel-title">
                <div><span className="kicker">当前资料库</span><h2>资料构成</h2></div>
                <span className={`status ${infrastructure?.postgresql ? "" : "offline"}`}>
                  <span /> {infrastructure?.postgresql ? "资料服务正常" : "资料服务不可用"}
                </span>
              </div>
              <div className="source-list">
                {Object.entries(stats?.documents_by_type ?? {})
                  .sort((a, b) => b[1] - a[1])
                  .map(([type, count]) => {
                    const total = Math.max(stats?.documents_total ?? 1, 1);
                    return (
                      <div className="source-row" key={type}>
                        <span>{sourceLabels[type] ?? type}</span>
                        <div className="bar"><i style={{ width: `${(count / total) * 100}%` }} /></div>
                        <b>{count}</b>
                      </div>
                    );
                  })}
              </div>
              {(stats?.exam_identity_incomplete ?? 0) > 0 && (
                <div className="notice warning">
                  {stats?.exam_identity_incomplete} 份考试资料缺少年份、考季或 Unit，已从严格配对中排除。
                </div>
              )}
            </article>

            <article className="panel evidence-panel">
              <div className="panel-title">
                <div><span className="kicker">难度状态</span><h2>证据等级</h2></div>
                <CircleGauge size={22} />
              </div>
              <div className="evidence-level"><b>A</b><div><strong>官方量化证据</strong><span>facility、mean mark、discrimination</span></div></div>
              <div className="evidence-level"><b>B</b><div><strong>官方定性证据</strong><span>考官报告中的常见错误与表现描述</span></div></div>
              <div className="evidence-level"><b>C</b><div><strong>历史估计</strong><span>经验证的题目表现代理量</span></div></div>
              <div className="evidence-level"><b>D</b><div><strong>冷启动推断</strong><span>知识深度、AO、解题步数；必须可被覆盖</span></div></div>
            </article>
          </div>
        </>
      )}

      <div className="guardrail">
        <ShieldCheck size={26} />
        <div>
          <strong>科目上下文隔离，自动评分仍需确认</strong>
          <p>检索只访问当前科目的向量别名；评分建议只进入该科目的人工复核队列。</p>
        </div>
        <span>教师最终确认</span>
      </div>
      {confirmingDelete && createPortal(
        <div
          className="subject-delete-overlay"
          onMouseDown={(event) => {
            if (!deletingSubjects && event.target === event.currentTarget) {
              setConfirmingDelete(false);
            }
          }}
        >
          <article
            aria-describedby="subject-delete-description"
            aria-labelledby="subject-delete-title"
            aria-modal="true"
            className="subject-delete-dialog"
            ref={deleteDialogRef}
            role="alertdialog"
            tabIndex={-1}
          >
            <div className="subject-delete-icon" aria-hidden="true">
              <Trash2 size={22} />
            </div>
            <div>
              <span className="kicker">不可撤销</span>
              <h2 id="subject-delete-title">
                删除 {selectedForDeletion.length} 个科目工作区？
              </h2>
              <p id="subject-delete-description">
                将删除这些科目的资料索引、知识图谱、试卷任务和评分记录。
                存储对象继续遵循现有保留与回收策略。
              </p>
              <ul>
                {selectedForDeletion.slice(0, 5).map((item) => (
                  <li key={item.id}>
                    <strong>{item.subject_code}</strong>
                    <span>{item.title}</span>
                  </li>
                ))}
              </ul>
              {selectedForDeletion.length > 5 && (
                <small>另有 {selectedForDeletion.length - 5} 个科目工作区</small>
              )}
            </div>
            <footer>
              <button
                className="secondary"
                data-modal-close
                disabled={deletingSubjects}
                onClick={() => setConfirmingDelete(false)}
                type="button"
              >
                取消
              </button>
              <button
                className="danger"
                disabled={deletingSubjects}
                onClick={() => void deleteSelectedSubjects()}
                type="button"
              >
                {deletingSubjects
                  ? <LoaderCircle className="spin" size={16} />
                  : <Trash2 size={16} />}
                {deletingSubjects ? "正在删除…" : "永久删除"}
              </button>
            </footer>
          </article>
        </div>,
        document.body,
      )}
    </section>
  );
}

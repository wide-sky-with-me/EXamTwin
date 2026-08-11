import {
  Atom,
  BookOpen,
  BookOpenText,
  Calculator,
  ChartNoAxesCombined,
  Database,
  FileText,
  FlaskConical,
  GraduationCap,
  Languages,
  Landmark,
  LoaderCircle,
  Plus,
  Search,
  Settings2,
  Trash2,
  X,
} from "lucide-react";
import { type CSSProperties, type FormEvent, useEffect, useMemo, useState } from "react";

import { ErrorBanner } from "../components/Feedback";
import { SubjectWorkspace } from "../components/SubjectWorkspace";
import { AppConfirmDialog } from "../components/ui/AppConfirmDialog";
import { AppDialog } from "../components/ui/AppDialog";
import { apiClient, setApiSubject, unwrapApi } from "../lib/api";
import type { SubjectStatus } from "../types";

const ICONS = {
  "book-open": BookOpen,
  calculator: Calculator,
  "chart-no-axes-combined": ChartNoAxesCombined,
  "flask-conical": FlaskConical,
  languages: Languages,
  landmark: Landmark,
  atom: Atom,
  "graduation-cap": GraduationCap,
} as const;

type SubjectIcon = keyof typeof ICONS;
type SubjectTab = "basic" | "documents" | "knowledge";
type CapabilityProfile = {
  id: string;
  subject_code: string;
  title: string;
  version: string;
  answering_enabled: boolean;
};
type CreateForm = {
  id: string;
  subject_code: string;
  title: string;
  board_name: string;
  capability_profile_id: string;
  icon: SubjectIcon;
  color: string;
};

const emptyCreateForm: CreateForm = {
  id: "",
  subject_code: "",
  title: "",
  board_name: "",
  capability_profile_id: "",
  icon: "book-open",
  color: "#2F6FED",
};

function IconPicker({
  icon,
  color,
  onChange,
}: {
  icon: SubjectIcon;
  color: string;
  onChange: (next: { icon: SubjectIcon; color: string }) => void;
}) {
  return (
    <fieldset className="subject-appearance full-field">
      <legend>图标与颜色</legend>
      <div className="icon-picker">
        {(Object.keys(ICONS) as SubjectIcon[]).map((value) => {
          const Icon = ICONS[value];
          return (
            <button aria-label={value} aria-pressed={icon === value} key={value} onClick={() => onChange({ icon: value, color })} type="button">
              <Icon size={19} />
            </button>
          );
        })}
        <input aria-label="科目颜色" onChange={(event) => onChange({ icon, color: event.target.value.toUpperCase() })} type="color" value={color} />
      </div>
    </fieldset>
  );
}

export function SubjectManagement({
  subjects,
  refresh,
  loading,
}: {
  subjects: SubjectStatus[];
  refresh: () => Promise<void>;
  loading: boolean;
}) {
  const [query, setQuery] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [manageOpen, setManageOpen] = useState(false);
  const [managedSubjectId, setManagedSubjectId] = useState<string | null>(null);
  const [tab, setTab] = useState<SubjectTab>("basic");
  const [profiles, setProfiles] = useState<CapabilityProfile[]>([]);
  const [createForm, setCreateForm] = useState<CreateForm>(emptyCreateForm);
  const [editForm, setEditForm] = useState({ title: "", icon: "book-open" as SubjectIcon, color: "#2F6FED" });
  const [busy, setBusy] = useState<"create" | "save" | "delete" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<SubjectStatus | null>(null);

  const managedSubject = subjects.find((subject) => subject.id === managedSubjectId) ?? null;
  const filteredSubjects = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return subjects;
    return subjects.filter((subject) =>
      [subject.title, subject.subject_code, subject.board_name]
        .some((value) => value.toLowerCase().includes(normalized)),
    );
  }, [query, subjects]);

  useEffect(() => {
    if (!createOpen) return;
    void unwrapApi(apiClient.GET("/api/v1/capability-profiles"))
      .then((rows) => setProfiles(rows as CapabilityProfile[]))
      .catch((cause) => setError(cause instanceof Error ? cause.message : "课程模板加载失败"));
  }, [createOpen]);

  function openManager(subject: SubjectStatus, initialTab: SubjectTab = "basic") {
    setApiSubject(subject.id);
    setManagedSubjectId(subject.id);
    setManageOpen(true);
    setTab(initialTab);
    setEditForm({
      title: subject.title,
      icon: subject.icon && subject.icon in ICONS ? subject.icon as SubjectIcon : "book-open",
      color: subject.color ?? "#2F6FED",
    });
    setError(null);
  }

  function closeManager() {
    setManageOpen(false);
    setManagedSubjectId(null);
    setApiSubject(null);
    setError(null);
  }

  function chooseProfile(profileId: string) {
    const profile = profiles.find((item) => item.id === profileId);
    setCreateForm((current) => ({
      ...current,
      capability_profile_id: profileId,
      subject_code: profile?.subject_code ?? current.subject_code,
      id: current.id || profile?.id || "",
      title: current.title || profile?.title || "",
    }));
  }

  async function createSubject(event: FormEvent) {
    event.preventDefault();
    setBusy("create");
    setError(null);
    try {
      await unwrapApi(apiClient.POST("/api/v1/subject-workspaces", {
        body: {
          id: createForm.id,
          subject_code: createForm.subject_code,
          title: createForm.title,
          board_name: createForm.board_name,
          language: "en",
          capability_profile_id: createForm.capability_profile_id || null,
          icon: createForm.icon,
          color: createForm.color,
        },
      }));
      setCreateOpen(false);
      setCreateForm(emptyCreateForm);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "科目创建失败");
    } finally {
      setBusy(null);
    }
  }

  async function saveSubject() {
    if (!managedSubject) return;
    setBusy("save");
    setError(null);
    try {
      setApiSubject(managedSubject.id);
      await unwrapApi(apiClient.PATCH("/api/v1/subject-workspaces/{workspace_id}", {
        params: { path: { workspace_id: managedSubject.id } },
        body: editForm,
      }));
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "科目保存失败");
    } finally {
      setBusy(null);
    }
  }

  async function deleteSubject(subject: SubjectStatus) {
    setBusy("delete");
    setError(null);
    try {
      await unwrapApi(apiClient.POST("/api/v1/subject-workspaces/batch-delete", {
        body: { subject_ids: [subject.id] },
      }));
      closeManager();
      setPendingDelete(null);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "科目删除失败");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="subject-page">
      <header className="page-heading subject-heading">
        <div><h1>科目管理</h1><p>管理课程资料与知识库。</p></div>
        <button className="primary" onClick={() => { setCreateOpen(true); setError(null); }} type="button"><Plus size={17} />新增科目</button>
      </header>

      <div className="subject-toolbar">
        <label className="search-field"><Search size={17} /><input aria-label="搜索科目" onChange={(event) => setQuery(event.target.value)} placeholder="搜索科目名称或代码" value={query} /></label>
        <span>{filteredSubjects.length} 个科目</span>
      </div>

      <ErrorBanner message={!createOpen && !manageOpen ? error : null} />
      {loading && !subjects.length ? (
        <div className="empty"><LoaderCircle className="spin" size={28} /><p>正在加载科目…</p></div>
      ) : (
        <div className="subject-card-grid">
          {filteredSubjects.map((subject) => {
            const icon = subject.icon && subject.icon in ICONS ? subject.icon as SubjectIcon : "book-open";
            const Icon = ICONS[icon];
            return (
              <article className="subject-card" key={subject.id} style={{ "--subject-color": subject.color ?? "#2F6FED" } as CSSProperties}>
                <header>
                  <span className="subject-card-icon"><Icon size={23} /></span>
                  <button aria-label={`管理 ${subject.title}`} className="icon-button" onClick={() => openManager(subject)} type="button"><Settings2 size={18} /></button>
                </header>
                <button className="subject-card-main" onClick={() => openManager(subject)} type="button">
                  <strong>{subject.title}</strong><span>{subject.subject_code} · {subject.board_name}</span>
                </button>
                <dl>
                  <div><dt><FileText size={15} />资料</dt><dd>{subject.stats?.documents_total ?? 0}</dd></div>
                  <div><dt><Database size={15} />向量</dt><dd>{subject.vector_points}</dd></div>
                </dl>
                <footer>
                  <span className={subject.answering_enabled ? "status-dot success" : "status-dot warning"}>{subject.answering_enabled ? "可用" : "需配置"}</span>
                  <button onClick={() => openManager(subject, "documents")} type="button">管理资料</button>
                </footer>
              </article>
            );
          })}
          {!filteredSubjects.length && <div className="empty subject-empty"><BookOpenText size={32} /><p>{query ? "没有匹配的科目。" : "还没有科目，先创建一个。"}</p></div>}
        </div>
      )}

      {createOpen && (
        <AppDialog
          contentClassName="modal-card subject-create-modal"
          dismissible={busy === null}
          initialFocusSelector="#create-subject-title"
          onOpenChange={setCreateOpen}
          open
          title="新增科目"
        >
            <header className="modal-header"><div><span>科目管理</span><h2 id="create-subject-title">新增科目</h2></div><button aria-label="关闭" className="icon-button" data-modal-close onClick={() => setCreateOpen(false)} type="button"><X size={19} /></button></header>
            <form className="subject-form" onSubmit={(event) => void createSubject(event)}>
              <ErrorBanner message={error} />
              <label className="full-field">课程模板（可选）<select onChange={(event) => chooseProfile(event.target.value)} value={createForm.capability_profile_id}><option value="">不使用模板</option>{profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.title} · {profile.subject_code}</option>)}</select></label>
              <label>科目名称<input maxLength={200} onChange={(event) => setCreateForm({ ...createForm, title: event.target.value })} required value={createForm.title} /></label>
              <label>科目代码<input maxLength={32} onChange={(event) => setCreateForm({ ...createForm, subject_code: event.target.value })} pattern="[A-Za-z0-9._-]{2,32}" required value={createForm.subject_code} /></label>
              <label>科目标识<input maxLength={63} onChange={(event) => setCreateForm({ ...createForm, id: event.target.value.toLowerCase() })} pattern="[a-z0-9][a-z0-9-]{1,62}" required value={createForm.id} /></label>
              <label>考试局 / 课程体系<input maxLength={200} onChange={(event) => setCreateForm({ ...createForm, board_name: event.target.value })} required value={createForm.board_name} /></label>
              <IconPicker color={createForm.color} icon={createForm.icon} onChange={(next) => setCreateForm({ ...createForm, ...next })} />
              <footer className="modal-actions"><button className="secondary" onClick={() => setCreateOpen(false)} type="button">取消</button><button className="primary" disabled={busy !== null} type="submit">{busy === "create" && <LoaderCircle className="spin" size={16} />}创建科目</button></footer>
            </form>
        </AppDialog>
      )}

      {manageOpen && managedSubject && (
        <AppDialog
          contentClassName="modal-card subject-manage-modal"
          dismissible={busy === null}
          initialFocusSelector="#manage-subject-title"
          onOpenChange={(open) => { if (!open) closeManager(); }}
          open
          title={managedSubject.title}
        >
            <header className="modal-header"><div><span>{managedSubject.subject_code}</span><h2 id="manage-subject-title">{managedSubject.title}</h2></div><button aria-label="关闭" className="icon-button" data-modal-close onClick={closeManager} type="button"><X size={19} /></button></header>
            <nav className="modal-tabs" aria-label="科目设置"><button aria-current={tab === "basic" ? "page" : undefined} onClick={() => setTab("basic")} type="button">基本信息</button><button aria-current={tab === "documents" ? "page" : undefined} onClick={() => setTab("documents")} type="button">资料管理</button><button aria-current={tab === "knowledge" ? "page" : undefined} onClick={() => setTab("knowledge")} type="button">知识库</button></nav>
            <div className="subject-modal-body">
              <ErrorBanner message={error} />
              {tab === "basic" && (
                <section className="subject-form subject-edit-form">
                  <label className="full-field">科目名称<input maxLength={200} onChange={(event) => setEditForm({ ...editForm, title: event.target.value })} required value={editForm.title} /></label>
                  <IconPicker color={editForm.color} icon={editForm.icon} onChange={(next) => setEditForm({ ...editForm, ...next })} />
                  <div className="readonly-subject-fields"><div><span>科目标识</span><strong>{managedSubject.id}</strong></div><div><span>科目代码</span><strong>{managedSubject.subject_code}</strong></div><div><span>课程体系</span><strong>{managedSubject.board_name}</strong></div></div>
                  <footer className="modal-actions"><button className="danger-button" disabled={busy !== null} onClick={() => setPendingDelete(managedSubject)} type="button"><Trash2 size={16} />删除科目</button><button className="primary" disabled={!editForm.title.trim() || busy !== null} onClick={() => void saveSubject()} type="button">{busy === "save" && <LoaderCircle className="spin" size={16} />}保存修改</button></footer>
                </section>
              )}
              {tab === "documents" && <SubjectWorkspace key={`${managedSubject.id}-documents`} onChanged={refresh} subject={managedSubject} view="documents" />}
              {tab === "knowledge" && <SubjectWorkspace key={`${managedSubject.id}-knowledge`} onChanged={refresh} subject={managedSubject} view="knowledge" />}
            </div>
        </AppDialog>
      )}
      <AppConfirmDialog
        busy={busy === "delete"}
        confirmLabel="永久删除科目"
        danger
        description={pendingDelete
          ? `将删除“${pendingDelete.title}”的资料、知识库、作答和评分记录。此操作不可恢复。`
          : ""}
        onConfirm={() => pendingDelete ? deleteSubject(pendingDelete) : undefined}
        onOpenChange={(open) => { if (!open) setPendingDelete(null); }}
        open={pendingDelete !== null}
        title="确认删除科目"
      />
    </div>
  );
}

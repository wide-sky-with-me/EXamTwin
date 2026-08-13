import {
  Button,
  Card,
  Col,
  ColorPicker,
  Descriptions,
  Drawer,
  Empty,
  Flex,
  Form,
  Input,
  Modal,
  Row,
  Select,
  Skeleton,
  Space,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from "antd";
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
  Plus,
  RotateCcw,
  Search,
  Settings2,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";

import { ErrorBanner } from "../components/Feedback";
import { SubjectWorkspace } from "../components/SubjectWorkspace";
import { AppConfirmDialog } from "../components/ui/AppConfirmDialog";
import { ListPagination } from "../components/ui/ListControls";
import { apiClient, subjectHeaders, unwrapApi } from "../lib/api";
import type { SubjectStatus } from "../types";

const { Text } = Typography;
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
type SubjectAvailability = "" | "enabled" | "disabled";
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

const PAGE_SIZES = [10, 20, 50] as const;
const EMPTY_CREATE_FORM: CreateForm = {
  id: "",
  subject_code: "",
  title: "",
  board_name: "",
  capability_profile_id: "",
  icon: "book-open",
  color: "#2F6FED",
};

function subjectIcon(subject: SubjectStatus): SubjectIcon {
  return subject.icon && subject.icon in ICONS ? subject.icon as SubjectIcon : "book-open";
}

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
    <Form.Item label="图标与颜色">
      <Flex align="center" gap="small" wrap>
        {(Object.keys(ICONS) as SubjectIcon[]).map((value) => {
          const Icon = ICONS[value];
          return (
            <Button
              aria-label={value}
              aria-pressed={icon === value}
              icon={<Icon size={18} />}
              key={value}
              onClick={() => onChange({ icon: value, color })}
              shape="circle"
              type={icon === value ? "primary" : "default"}
            />
          );
        })}
        <ColorPicker
          aria-label="科目颜色"
          onChange={(nextColor) => onChange({ icon, color: nextColor.toHexString().toUpperCase() })}
          value={color}
        />
      </Flex>
    </Form.Item>
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
  const [queryDraft, setQueryDraft] = useState("");
  const [query, setQuery] = useState("");
  const [availability, setAvailability] = useState<SubjectAvailability>("");
  const [board, setBoard] = useState("");
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState<number>(PAGE_SIZES[0]);
  const [createOpen, setCreateOpen] = useState(false);
  const [manageOpen, setManageOpen] = useState(false);
  const [managedSubjectId, setManagedSubjectId] = useState<string | null>(null);
  const [tab, setTab] = useState<SubjectTab>("basic");
  const [profiles, setProfiles] = useState<CapabilityProfile[]>([]);
  const [createForm, setCreateForm] = useState<CreateForm>(EMPTY_CREATE_FORM);
  const [editForm, setEditForm] = useState({ title: "", icon: "book-open" as SubjectIcon, color: "#2F6FED" });
  const [busy, setBusy] = useState<"create" | "save" | "delete" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<SubjectStatus | null>(null);

  const managedSubject = subjects.find((subject) => subject.id === managedSubjectId) ?? null;
  const boards = useMemo(() => [...new Set(subjects.map((subject) => subject.board_name))].sort(), [subjects]);
  const filteredSubjects = useMemo(() => {
    const normalized = query.toLowerCase();
    return subjects.filter((subject) => {
      const matchesQuery = !normalized || [subject.title, subject.subject_code, subject.board_name]
        .some((value) => value.toLowerCase().includes(normalized));
      const matchesAvailability = !availability || subject.answering_enabled === (availability === "enabled");
      return matchesQuery && matchesAvailability && (!board || subject.board_name === board);
    });
  }, [availability, board, query, subjects]);
  const totalPages = Math.max(1, Math.ceil(filteredSubjects.length / pageSize));
  const currentPage = Math.min(page, totalPages - 1);
  const pageSubjects = filteredSubjects.slice(currentPage * pageSize, (currentPage + 1) * pageSize);

  useEffect(() => {
    if (!createOpen) return;
    void unwrapApi(apiClient.GET("/api/v1/capability-profiles"))
      .then((rows) => setProfiles(rows as CapabilityProfile[]))
      .catch((cause) => setError(cause instanceof Error ? cause.message : "课程模板加载失败"));
  }, [createOpen]);

  function openManager(subject: SubjectStatus, initialTab: SubjectTab = "basic") {
    setManagedSubjectId(subject.id);
    setManageOpen(true);
    setTab(initialTab);
    setEditForm({ title: subject.title, icon: subjectIcon(subject), color: subject.color ?? "#2F6FED" });
    setError(null);
  }

  function closeManager() {
    setManageOpen(false);
    setManagedSubjectId(null);
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

  async function createSubject() {
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
      setCreateForm(EMPTY_CREATE_FORM);
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
      await unwrapApi(apiClient.PATCH("/api/v1/subject-workspaces/{workspace_id}", {
        headers: subjectHeaders(managedSubject.id),
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
      await unwrapApi(apiClient.POST("/api/v1/subject-workspaces/batch-delete", { body: { subject_ids: [subject.id] } }));
      closeManager();
      setPendingDelete(null);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "科目删除失败");
    } finally {
      setBusy(null);
    }
  }

  function resetFilters() {
    setQueryDraft("");
    setQuery("");
    setAvailability("");
    setBoard("");
    setPage(0);
  }

  return (
    <div aria-label="科目管理" className="subject-management-page">
      <form
        aria-label="科目搜索与筛选"
        className="subject-management-toolbar"
        onSubmit={(event) => {
          event.preventDefault();
          setPage(0);
          setQuery(queryDraft.trim());
        }}
      >
        <Input
          allowClear
          aria-label="搜索科目"
          autoComplete="off"
          onChange={(event) => setQueryDraft(event.target.value)}
          placeholder="搜索名称、代码或考试局"
          prefix={<Search aria-hidden="true" size={16} />}
          value={queryDraft}
        />
        <Select
          aria-label="按科目状态筛选"
          className="subject-status-filter"
          onChange={(value) => { setPage(0); setAvailability(value as SubjectAvailability); }}
          options={[{ label: "全部状态", value: "" }, { label: "可用", value: "enabled" }, { label: "需配置", value: "disabled" }]}
          value={availability}
        />
        <Select
          aria-label="按考试局筛选"
          className="subject-board-filter"
          onChange={(value) => { setPage(0); setBoard(value); }}
          options={[{ label: "全部考试局", value: "" }, ...boards.map((item) => ({ label: item, value: item }))]}
          value={board}
        />
        <Tooltip title="搜索">
          <Button aria-label="搜索" htmlType="submit" icon={<Search size={16} />} type="primary" />
        </Tooltip>
        <Tooltip title="重置筛选">
          <Button
            aria-label="重置"
            disabled={!queryDraft && !query && !availability && !board}
            icon={<RotateCcw size={16} />}
            onClick={resetFilters}
          />
        </Tooltip>
        <Tooltip title="新增科目">
          <Button
            aria-label="新增科目"
            icon={<Plus size={17} />}
            onClick={() => { setCreateOpen(true); setError(null); }}
            type="primary"
          />
        </Tooltip>
      </form>

      <ErrorBanner message={!createOpen && !manageOpen ? error : null} />
      {loading && subjects.length === 0 ? (
        <div className="subject-management-grid">{Array.from({ length: 6 }, (_, index) => <Card key={index}><Skeleton active /></Card>)}</div>
      ) : pageSubjects.length === 0 ? (
        <Card className="subject-management-empty"><Empty description={query || availability || board ? "没有符合当前条件的科目" : "还没有科目，先创建一个"} image={<BookOpenText size={48} />} /></Card>
      ) : (
        <div className="subject-management-grid">
          {pageSubjects.map((subject) => {
            const Icon = ICONS[subjectIcon(subject)];
            const color = subject.color ?? "#2F6FED";
            return (
              <article className="subject-management-card" key={subject.id} style={{ "--subject-color": color } as CSSProperties}>
                <header>
                  <span className="subject-management-card-icon" style={{ color }}><Icon size={22} /></span>
                  <span className="subject-management-card-title">
                    <Tooltip placement="topLeft" title={subject.title}>
                      <strong>{subject.title}</strong>
                    </Tooltip>
                    <small>
                      <b>{subject.subject_code}</b>
                      <span aria-hidden="true">·</span>
                      <Tooltip placement="bottomLeft" title={subject.board_name}>
                        <span className="subject-management-card-board">{subject.board_name}</span>
                      </Tooltip>
                      <Tag color={subject.answering_enabled ? "success" : "warning"}>{subject.answering_enabled ? "可用" : "需配置"}</Tag>
                    </small>
                  </span>
                </header>
                <dl className="subject-management-card-overview">
                  <div><dt><FileText size={14} />资料</dt><dd>{subject.stats?.documents_total ?? 0}</dd></div>
                  <div><dt><Database size={14} />向量</dt><dd>{subject.vector_points.toLocaleString()}</dd></div>
                  <div><dt><BookOpenText size={14} />版本</dt><dd>{subject.knowledge_bases.length}</dd></div>
                </dl>
                <footer>
                  <Tooltip title="科目设置">
                    <Button aria-label={`设置 ${subject.title}`} icon={<Settings2 size={16} />} onClick={() => openManager(subject)} type="text">设置</Button>
                  </Tooltip>
                  <Tooltip title="删除科目">
                    <Button aria-label={`删除 ${subject.title}`} danger icon={<Trash2 size={16} />} onClick={() => setPendingDelete(subject)} type="text">删除</Button>
                  </Tooltip>
                </footer>
              </article>
            );
          })}
        </div>
      )}

      <ListPagination
        ariaLabel="科目分页"
        disabled={loading}
        itemName="科目"
        itemUnit="个"
        onPageChange={setPage}
        onPageSizeChange={(size) => { setPage(0); setPageSize(size); }}
        page={currentPage}
        pageSize={pageSize}
        pageSizes={PAGE_SIZES}
        total={filteredSubjects.length}
        visibleCount={pageSubjects.length}
      />

      <Modal destroyOnHidden footer={null} onCancel={() => setCreateOpen(false)} open={createOpen} title="新增科目" width={720}>
        <Form layout="vertical" onFinish={() => void createSubject()}>
          <ErrorBanner message={error} />
          <Form.Item label="课程模板（可选）">
            <Select
              onChange={chooseProfile}
              options={[{ label: "不使用模板", value: "" }, ...profiles.map((profile) => ({ label: `${profile.title} · ${profile.subject_code}`, value: profile.id }))]}
              value={createForm.capability_profile_id}
            />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}><Form.Item label="科目名称" required><Input maxLength={200} onChange={(event) => setCreateForm({ ...createForm, title: event.target.value })} value={createForm.title} /></Form.Item></Col>
            <Col span={12}><Form.Item label="科目代码" required><Input maxLength={32} onChange={(event) => setCreateForm({ ...createForm, subject_code: event.target.value })} value={createForm.subject_code} /></Form.Item></Col>
            <Col span={12}><Form.Item label="科目标识" required><Input maxLength={63} onChange={(event) => setCreateForm({ ...createForm, id: event.target.value.toLowerCase() })} value={createForm.id} /></Form.Item></Col>
            <Col span={12}><Form.Item label="考试局 / 课程体系" required><Input maxLength={200} onChange={(event) => setCreateForm({ ...createForm, board_name: event.target.value })} value={createForm.board_name} /></Form.Item></Col>
          </Row>
          <IconPicker color={createForm.color} icon={createForm.icon} onChange={(next) => setCreateForm({ ...createForm, ...next })} />
          <Flex gap="small" justify="flex-end"><Button onClick={() => setCreateOpen(false)}>取消</Button><Button disabled={!createForm.id || !createForm.subject_code || !createForm.title || !createForm.board_name} htmlType="submit" loading={busy === "create"} type="primary">创建科目</Button></Flex>
        </Form>
      </Modal>

      <Drawer
        destroyOnHidden
        onClose={closeManager}
        open={manageOpen && managedSubject !== null}
        size="large"
        title={managedSubject ? `${managedSubject.title} · ${managedSubject.subject_code}` : "科目设置"}
      >
        {managedSubject && (
          <Space orientation="vertical" size="large" style={{ width: "100%" }}>
            <ErrorBanner message={error} />
            <Tabs
              activeKey={tab}
              items={[
                {
                  key: "basic",
                  label: "基本信息",
                  children: (
                    <Form layout="vertical">
                      <Form.Item label="科目名称" required><Input maxLength={200} onChange={(event) => setEditForm({ ...editForm, title: event.target.value })} value={editForm.title} /></Form.Item>
                      <IconPicker color={editForm.color} icon={editForm.icon} onChange={(next) => setEditForm({ ...editForm, ...next })} />
                      <Descriptions bordered column={1} size="small">
                        <Descriptions.Item label="科目标识"><Text code>{managedSubject.id}</Text></Descriptions.Item>
                        <Descriptions.Item label="科目代码">{managedSubject.subject_code}</Descriptions.Item>
                        <Descriptions.Item label="课程体系">{managedSubject.board_name}</Descriptions.Item>
                      </Descriptions>
                      <Flex gap="small" justify="flex-end" style={{ marginTop: 24 }}>
                        <Button disabled={!editForm.title.trim()} loading={busy === "save"} onClick={() => void saveSubject()} type="primary">保存修改</Button>
                      </Flex>
                    </Form>
                  ),
                },
                { key: "documents", label: "资料管理", children: <SubjectWorkspace key={`${managedSubject.id}-documents`} onChanged={refresh} subject={managedSubject} view="documents" /> },
                { key: "knowledge", label: "知识库", children: <SubjectWorkspace key={`${managedSubject.id}-knowledge`} onChanged={refresh} subject={managedSubject} view="knowledge" /> },
              ]}
              onChange={(key) => setTab(key as SubjectTab)}
            />
          </Space>
        )}
      </Drawer>

      <AppConfirmDialog
        busy={busy === "delete"}
        confirmLabel="永久删除科目"
        danger
        description={pendingDelete ? `将删除“${pendingDelete.title}”的资料、知识库、作答和评分记录。此操作不可恢复。` : ""}
        onConfirm={() => pendingDelete ? deleteSubject(pendingDelete) : undefined}
        onOpenChange={(open) => { if (!open) setPendingDelete(null); }}
        open={pendingDelete !== null}
        title="确认删除科目"
      />
    </div>
  );
}

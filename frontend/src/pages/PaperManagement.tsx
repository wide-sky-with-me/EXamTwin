import {
  Button,
  Card,
  Checkbox,
  Col,
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
  Tag,
  Typography,
  Upload,
} from "antd";
import {
  BookOpenCheck,
  FileText,
  ChevronRight,
  Layers3,
  Pencil,
  Play,
  Plus,
  ShieldCheck,
  Trash2,
  UploadCloud,
} from "lucide-react";
import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { ErrorBanner } from "../components/Feedback";
import { useToast } from "../components/toast-context";
import { AppConfirmDialog } from "../components/ui/AppConfirmDialog";
import { ListPagination } from "../components/ui/ListControls";
import {
  answerPaperUnit,
  apiClient,
  archivePaperUnit,
  createPaperUnit,
  listPaperUnits,
  subjectHeaders,
  unwrapApi,
  updatePaperUnit,
  uploadWorkspaceDocument,
} from "../lib/api";
import type {
  PaperJobResult,
  PaperUnitDocument,
  PaperUnitList,
  PaperUnitSummary,
  SourceDocument,
  SubjectStatus,
} from "../types";

const { Paragraph, Text, Title } = Typography;
const PAGE_SIZE = 12;
const EMPTY_LIST: PaperUnitList = {
  items: [],
  total: 0,
  limit: PAGE_SIZE,
  offset: 0,
  available_units: [],
  available_years: [],
  available_sessions: [],
};

type Detail =
  | { kind: "paper"; id: string }
  | { kind: "document"; id: string }
  | { kind: "job"; id: string }
  | null;

type PaperManagementProps = {
  subjects: SubjectStatus[];
  subjectId?: string;
  detail?: Detail;
  onSubjectChange?: (subjectId: string) => void;
  onOpenPaper?: (subjectId: string, paperUnitId: string) => void;
  onOpenDocument?: (subjectId: string, documentId: string) => void;
  onOpenJob?: (subjectId: string, paperUnitId: string, jobId: string) => void;
  onCloseDetail?: (subjectId: string) => void;
  onStartAnswering?: (subjectId: string, paperUnitId: string, jobId: string) => void;
  onStartGrading?: (subjectId: string, paperUnitId: string) => void;
};

type BindingDraft = {
  displayName: string;
  questionPaperId: string;
  markSchemeId: string;
  sourceBookletId: string;
};

const EMPTY_DRAFT: BindingDraft = {
  displayName: "",
  questionPaperId: "",
  markSchemeId: "",
  sourceBookletId: "",
};

function documentLabel(document: Pick<SourceDocument | PaperUnitDocument, "display_name" | "filename">) {
  return document.display_name || document.filename;
}

function sessionLabel(session: string) {
  return { JAN: "一月", MAR: "三月", JUN: "六月", NOV: "十一月" }[session] ?? session;
}

function PaperDocumentRow({
  document,
  onOpen,
}: {
  document: PaperUnitDocument;
  onOpen: () => void;
}) {
  const labels = {
    question_paper: "Question Paper",
    mark_scheme: "Mark Scheme",
    source_booklet: "Source Booklet",
  } as const;
  const icons = {
    question_paper: FileText,
    mark_scheme: ShieldCheck,
    source_booklet: Layers3,
  } as const;
  const Icon = icons[document.role];
  return (
    <button className="paper-binding-row" onClick={onOpen} type="button">
      <Icon size={18} />
      <span><strong>{labels[document.role]}</strong><small>{documentLabel(document)}</small></span>
      <em>{document.page_count ? `${document.page_count} 页` : document.status}</em>
      <ChevronRight size={16} />
    </button>
  );
}

export function PaperManagement({
  subjects,
  subjectId: controlledSubjectId,
  detail = null,
  onSubjectChange,
  onOpenPaper,
  onOpenDocument,
  onOpenJob,
  onCloseDetail,
  onStartAnswering,
  onStartGrading,
}: PaperManagementProps) {
  const [localSubjectId, setLocalSubjectId] = useState(controlledSubjectId ?? subjects[0]?.id ?? "");
  const subjectId = controlledSubjectId ?? localSubjectId;
  const subject = subjects.find((item) => item.id === subjectId) ?? null;
  const [papers, setPapers] = useState<PaperUnitList>(EMPTY_LIST);
  const [documents, setDocuments] = useState<SourceDocument[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [unitCode, setUnitCode] = useState("");
  const [examYear, setExamYear] = useState("");
  const [examSession, setExamSession] = useState("");
  const [page, setPage] = useState(0);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<PaperUnitSummary | null>(null);
  const [draft, setDraft] = useState<BindingDraft>(EMPTY_DRAFT);
  const [files, setFiles] = useState<Record<string, File | null>>({
    question_paper: null,
    mark_scheme: null,
    insert: null,
  });
  const [licenseConfirmed, setLicenseConfirmed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [archiving, setArchiving] = useState<PaperUnitSummary | null>(null);
  const [starting, setStarting] = useState(false);
  const [job, setJob] = useState<PaperJobResult | null>(null);
  const [detailPaper, setDetailPaper] = useState<PaperUnitSummary | null>(null);
  const { notify } = useToast();

  useEffect(() => {
    if (!subjectId && subjects[0]) setLocalSubjectId(subjects[0].id);
  }, [subjectId, subjects]);

  const loadDocuments = useCallback(async () => {
    if (!subjectId) return;
    const rows = await unwrapApi(
      apiClient.GET("/api/v1/subject-workspaces/{workspace_id}/documents", {
        headers: subjectHeaders(subjectId),
        params: { path: { workspace_id: subjectId } },
      }),
    );
    setDocuments(rows);
  }, [subjectId]);

  const loadPapers = useCallback(async () => {
    if (!subjectId) {
      setPapers(EMPTY_LIST);
      return;
    }
    setLoading(true);
    try {
      const next = await listPaperUnits(subjectId, {
        query: query.trim() || undefined,
        unitCode: unitCode || undefined,
        examYear: examYear ? Number(examYear) : undefined,
        examSession: examSession || undefined,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      });
      setPapers(next);
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "试卷列表加载失败");
    } finally {
      setLoading(false);
    }
  }, [examSession, examYear, page, query, subjectId, unitCode]);

  useEffect(() => {
    setPage(0);
    setQuery("");
    setUnitCode("");
    setExamYear("");
    setExamSession("");
    void loadDocuments().catch((cause: unknown) => {
      setError(cause instanceof Error ? cause.message : "试卷资料加载失败");
    });
  }, [loadDocuments, subjectId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadPapers(), 180);
    return () => window.clearTimeout(timer);
  }, [loadPapers]);

  useEffect(() => {
    if (detail?.kind !== "paper" || !subjectId) {
      setDetailPaper(null);
      return;
    }
    const listed = papers.items.find((item) => item.id === detail.id);
    if (listed) {
      setDetailPaper(listed);
      return;
    }
    let current = true;
    void unwrapApi(apiClient.GET(
      "/api/v1/subject-workspaces/{workspace_id}/paper-units/{paper_unit_id}",
      {
        headers: subjectHeaders(subjectId),
        params: { path: { workspace_id: subjectId, paper_unit_id: detail.id } },
      },
    )).then((result) => {
      if (current) setDetailPaper(result);
    }).catch((cause: unknown) => {
      if (current) setError(cause instanceof Error ? cause.message : "试卷详情加载失败");
    });
    return () => { current = false; };
  }, [detail, papers.items, subjectId]);

  useEffect(() => {
    if (detail?.kind !== "job" || !subjectId) {
      setJob(null);
      return;
    }
    let current = true;
    void unwrapApi(apiClient.GET("/api/v1/papers/jobs/{job_id}", {
      headers: subjectHeaders(subjectId),
      params: { path: { job_id: detail.id } },
    })).then((result) => {
      if (current) setJob(result as unknown as PaperJobResult);
    }).catch((cause: unknown) => {
      if (current) setError(cause instanceof Error ? cause.message : "作答记录加载失败");
    });
    return () => { current = false; };
  }, [detail, subjectId]);

  const selectedPaper = detail?.kind === "paper" ? detailPaper : null;
  const selectedDocument = detail?.kind === "document"
    ? documents.find((item) => item.id === detail.id) ?? null
    : null;

  const candidates = useMemo(() => {
    const usable = documents.filter((item) => item.status !== "deleted" && item.identity_status === "complete");
    return {
      question_paper: usable.filter((item) => item.source_type === "question_paper"),
      mark_scheme: usable.filter((item) => item.source_type === "mark_scheme"),
      insert: usable.filter((item) => item.source_type === "insert"),
    };
  }, [documents]);

  function chooseSubject(nextSubjectId: string) {
    if (nextSubjectId === subjectId) return;
    setLocalSubjectId(nextSubjectId);
    onSubjectChange?.(nextSubjectId);
  }

  function openCreate() {
    setEditing(null);
    setDraft(EMPTY_DRAFT);
    setFiles({ question_paper: null, mark_scheme: null, insert: null });
    setLicenseConfirmed(false);
    setEditorOpen(true);
  }

  function openEdit(paper: PaperUnitSummary) {
    setEditing(paper);
    setDraft({
      displayName: paper.display_name ?? "",
      questionPaperId: paper.documents.find((item) => item.role === "question_paper")?.id ?? "",
      markSchemeId: paper.documents.find((item) => item.role === "mark_scheme")?.id ?? "",
      sourceBookletId: paper.documents.find((item) => item.role === "source_booklet")?.id ?? "",
    });
    setFiles({ question_paper: null, mark_scheme: null, insert: null });
    setLicenseConfirmed(false);
    setEditorOpen(true);
  }

  async function uploadCandidate(role: "question_paper" | "mark_scheme" | "insert") {
    const file = files[role];
    if (!file || !subjectId) return "";
    const uploaded = await uploadWorkspaceDocument(subjectId, file, role, { licenseConfirmed });
    return uploaded.id;
  }

  async function savePaper(event: FormEvent) {
    event.preventDefault();
    if (!subjectId) return;
    if (Object.values(files).some(Boolean) && !licenseConfirmed) {
      setError("上传文件前请确认你有权使用这些考试资料。");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const uploadedIds = await Promise.all([
        uploadCandidate("question_paper"),
        uploadCandidate("mark_scheme"),
        uploadCandidate("insert"),
      ]);
      const documentIds = [
        uploadedIds[0] || draft.questionPaperId,
        uploadedIds[1] || draft.markSchemeId,
        uploadedIds[2] || draft.sourceBookletId,
      ].filter(Boolean);
      if (!documentIds[0]) throw new Error("必须选择或上传 Question Paper。");
      if (editing) {
        await updatePaperUnit(subjectId, editing.id, documentIds, draft.displayName.trim() || null);
        notify("试卷信息与资料绑定已更新。");
      } else {
        await createPaperUnit(subjectId, documentIds, draft.displayName.trim() || null);
        notify("试卷已加入管理库。");
      }
      setEditorOpen(false);
      await Promise.all([loadDocuments(), loadPapers()]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "试卷保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function confirmArchive() {
    if (!archiving || !subjectId) return;
    try {
      await archivePaperUnit(subjectId, archiving.id);
      notify("试卷已归档，历史作答与评分记录保留。");
      setArchiving(null);
      onCloseDetail?.(subjectId);
      await loadPapers();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "试卷归档失败");
    }
  }

  async function startAnswering(paper: PaperUnitSummary) {
    const questionPaper = paper.documents.find((item) => item.role === "question_paper");
    const sourceBooklet = paper.documents.find((item) => item.role === "source_booklet");
    if (!questionPaper || !subjectId) return;
    setStarting(true);
    try {
      const created = await answerPaperUnit(subjectId, paper.id, questionPaper.id, sourceBooklet?.id);
      notify("已使用当前试卷及绑定资料创建作答任务。");
      onStartAnswering?.(subjectId, paper.id, created.job_id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "作答任务创建失败");
    } finally {
      setStarting(false);
    }
  }

  function openDocument(documentId: string) {
    if (subjectId) onOpenDocument?.(subjectId, documentId);
  }

  const detailVisible = Boolean(detail);

  return (
    <Space orientation="vertical" size="large" style={{ width: "100%" }}>
      <Flex align="flex-end" justify="space-between" wrap gap="middle">
        <div>
          <Title level={1} style={{ marginBottom: 4 }}>试卷库</Title>
          <Paragraph type="secondary" style={{ margin: 0 }}>Question Paper、Mark Scheme 与 Source Booklet 的唯一绑定入口。</Paragraph>
        </div>
        <Space wrap>
          <Select
            aria-label="选择科目"
            onChange={chooseSubject}
            options={subjects.map((item) => ({ label: `${item.title} · ${item.subject_code}`, value: item.id }))}
            placeholder="选择科目"
            style={{ minWidth: 260 }}
            value={subjectId || undefined}
          />
          <Button disabled={!subject} icon={<Plus size={17} />} onClick={openCreate} size="large" type="primary">添加试卷</Button>
        </Space>
      </Flex>

      {subject ? (
        <>
          <Card size="small">
            <Flex align="center" gap="small" wrap>
              <Input.Search
                allowClear
                aria-label="搜索试卷"
                onChange={(event) => { setQuery(event.target.value); setPage(0); }}
                placeholder="搜索名称、年份或配对键"
                style={{ flex: "1 1 300px" }}
                value={query}
              />
              <Select
                aria-label="按单元筛选"
                onChange={(value) => { setUnitCode(value); setPage(0); }}
                options={[{ label: "全部单元", value: "" }, ...papers.available_units.map((value) => ({ label: value, value }))]}
                style={{ minWidth: 150 }}
                value={unitCode}
              />
              <Select
                aria-label="按年份筛选"
                onChange={(value) => { setExamYear(value); setPage(0); }}
                options={[{ label: "全部年份", value: "" }, ...papers.available_years.map((value) => ({ label: String(value), value: String(value) }))]}
                style={{ minWidth: 140 }}
                value={examYear}
              />
              <Select
                aria-label="按考季筛选"
                onChange={(value) => { setExamSession(value); setPage(0); }}
                options={[{ label: "全部考季", value: "" }, ...papers.available_sessions.map((value) => ({ label: sessionLabel(value), value }))]}
                style={{ minWidth: 140 }}
                value={examSession}
              />
            </Flex>
          </Card>
          <ErrorBanner message={error} />

          {loading ? (
            <Row gutter={[16, 16]}>{Array.from({ length: 6 }, (_, index) => <Col key={index} lg={8} md={12} xs={24}><Card><Skeleton active /></Card></Col>)}</Row>
          ) : papers.items.length > 0 ? (
            <Row gutter={[16, 16]}>
              {papers.items.map((paper) => {
                const markScheme = paper.documents.some((item) => item.role === "mark_scheme");
                const booklet = paper.documents.some((item) => item.role === "source_booklet");
                const name = paper.display_name || paper.pair_key;
                return (
                  <Col key={paper.id} lg={8} md={12} xs={24}>
                    <Card
                      actions={[
                        <Button aria-label={`编辑 ${name}`} icon={<Pencil size={15} />} key="edit" onClick={() => openEdit(paper)} type="link">编辑</Button>,
                        <Button aria-label={`归档 ${name}`} danger icon={<Trash2 size={15} />} key="archive" onClick={() => setArchiving(paper)} type="link">归档</Button>,
                      ]}
                      hoverable
                      title={<Button onClick={() => onOpenPaper?.(subject.id, paper.id)} style={{ fontWeight: 600, paddingInline: 0 }} type="link">{name}</Button>}
                    >
                      <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
                        <Flex justify="space-between" wrap gap="small">
                          <Space><Tag color="blue">{paper.unit_code}</Tag><Text type="secondary">{paper.exam_year} · {sessionLabel(paper.exam_session)}</Text></Space>
                          <Text type="secondary">{paper.paper_job_count} 条作答记录</Text>
                        </Flex>
                        <Space wrap>
                          <Tag color={markScheme ? "success" : "warning"} icon={<ShieldCheck size={13} />}>{markScheme ? "评分标准已绑定" : "待绑定评分标准"}</Tag>
                          <Tag color={booklet ? "success" : "default"} icon={<Layers3 size={13} />}>{booklet ? "支撑材料已绑定" : "无支撑材料"}</Tag>
                        </Space>
                        <Text code copyable>{paper.pair_key}</Text>
                      </Space>
                    </Card>
                  </Col>
                );
              })}
            </Row>
          ) : (
            <Card>
              <Empty description="当前条件下没有试卷">
                <Button icon={<Plus size={16} />} onClick={openCreate} type="primary">添加第一份试卷</Button>
              </Empty>
            </Card>
          )}

          <ListPagination
            ariaLabel="试卷分页"
            itemName="试卷"
            itemUnit="份"
            onPageChange={setPage}
            onPageSizeChange={() => undefined}
            page={page}
            pageSize={PAGE_SIZE}
            pageSizes={[PAGE_SIZE]}
            total={papers.total}
            visibleCount={papers.items.length}
          />
        </>
      ) : (
        <Card><Empty description="先选择科目" /></Card>
      )}

      <Drawer
        destroyOnHidden
        onClose={() => subjectId && onCloseDetail?.(subjectId)}
        open={detailVisible}
        size="large"
        title="试卷详情"
      >
        {selectedPaper && (
          <Space orientation="vertical" size="large" style={{ width: "100%" }}>
            <div>
              <Text type="secondary">{selectedPaper.exam_year} · {sessionLabel(selectedPaper.exam_session)} · {selectedPaper.unit_code}</Text>
              <Title level={2} style={{ margin: "4px 0 8px" }}>{selectedPaper.display_name || selectedPaper.pair_key}</Title>
              <Text code copyable>{selectedPaper.pair_key}</Text>
            </div>
            <Flex gap="small" wrap>
              <Button icon={<Play size={16} />} loading={starting} onClick={() => void startAnswering(selectedPaper)} type="primary">开始作答</Button>
              <Button disabled={!selectedPaper.documents.some((item) => item.role === "mark_scheme")} icon={<BookOpenCheck size={16} />} onClick={() => onStartGrading?.(subjectId, selectedPaper.id)}>进入评分</Button>
              <Button icon={<Pencil size={16} />} onClick={() => openEdit(selectedPaper)}>编辑绑定</Button>
            </Flex>
            <section>
              <Title level={4}>资料绑定</Title>
              <Space orientation="vertical" size="small" style={{ width: "100%" }}>
                {selectedPaper.documents.map((document) => <PaperDocumentRow document={document} key={document.id} onOpen={() => openDocument(document.id)} />)}
              </Space>
            </section>
            <Descriptions bordered column={1} size="small">
              <Descriptions.Item label="作答记录">{selectedPaper.paper_job_count}</Descriptions.Item>
              <Descriptions.Item label="状态"><Tag color={selectedPaper.status === "active" ? "success" : "default"}>{selectedPaper.status === "active" ? "使用中" : "已归档"}</Tag></Descriptions.Item>
              <Descriptions.Item label="更新于">{new Date(selectedPaper.updated_at).toLocaleDateString("zh-CN")}</Descriptions.Item>
            </Descriptions>
          </Space>
        )}
        {selectedDocument && (
          <Space orientation="vertical" size="large" style={{ width: "100%" }}>
            <Title level={2}>{documentLabel(selectedDocument)}</Title>
            <Descriptions bordered column={1} size="small">
              <Descriptions.Item label="类型">{selectedDocument.source_type}</Descriptions.Item>
              <Descriptions.Item label="文件名">{selectedDocument.filename}</Descriptions.Item>
              <Descriptions.Item label="配对键"><Text code>{selectedDocument.pair_key || "未识别"}</Text></Descriptions.Item>
              <Descriptions.Item label="识别状态">{selectedDocument.identity_status}</Descriptions.Item>
              <Descriptions.Item label="页数">{selectedDocument.page_count ?? "—"}</Descriptions.Item>
            </Descriptions>
          </Space>
        )}
        {detail?.kind === "job" && (
          job ? (
            <Space orientation="vertical" size="large" style={{ width: "100%" }}>
              <Title level={2}>{job.display_name || job.filename}</Title>
              <Descriptions bordered column={1} size="small">
                <Descriptions.Item label="状态">{job.status}</Descriptions.Item>
                <Descriptions.Item label="题目">{job.completed_questions}/{job.total_questions}</Descriptions.Item>
                <Descriptions.Item label="单元">{job.unit_code || "—"}</Descriptions.Item>
              </Descriptions>
              {onOpenJob && subjectId && job.paper_unit_id && <Button onClick={() => { if (job.paper_unit_id) onOpenJob(subjectId, job.paper_unit_id, job.job_id); }} type="primary">打开作答结果</Button>}
            </Space>
          ) : <Skeleton active />
        )}
      </Drawer>

      <Modal destroyOnHidden footer={null} onCancel={() => setEditorOpen(false)} open={editorOpen} title={editing ? "编辑试卷" : "添加试卷"} width={760}>
        <form onSubmit={savePaper}>
          <Form component={false} layout="vertical">
            <Form.Item label="显示名称（可选）">
              <Input aria-label="显示名称（可选）" maxLength={200} onChange={(event) => setDraft((value) => ({ ...value, displayName: event.target.value }))} placeholder="例如 2024 June Paper 1" value={draft.displayName} />
            </Form.Item>
            {(["question_paper", "mark_scheme", "insert"] as const).map((role) => {
              const titles = { question_paper: "Question Paper", mark_scheme: "Mark Scheme", insert: "Source Booklet" };
              const valueKey = { question_paper: "questionPaperId", mark_scheme: "markSchemeId", insert: "sourceBookletId" } as const;
              const label = role === "question_paper" ? titles[role] : `${titles[role]}（可选）`;
              return (
                <Card key={role} size="small" style={{ marginBottom: 16 }} title={label}>
                  <Space orientation="vertical" size="small" style={{ width: "100%" }}>
                    <select
                      aria-label={label}
                      onChange={(event) => setDraft((current) => ({ ...current, [valueKey[role]]: event.target.value }))}
                      value={draft[valueKey[role]]}
                    >
                      <option value="">从资料库选择…</option>
                      {candidates[role].map((document) => <option key={document.id} value={document.id}>{documentLabel(document)} · {document.pair_key}</option>)}
                    </select>
                    <Upload
                      accept=".pdf,.md,.markdown,application/pdf,text/markdown"
                      beforeUpload={(file) => {
                        setFiles((current) => ({ ...current, [role]: file }));
                        return false;
                      }}
                      maxCount={1}
                      onRemove={() => {
                        setFiles((current) => ({ ...current, [role]: null }));
                      }}
                    >
                      <Button icon={<UploadCloud size={15} />}>上传新文件</Button>
                    </Upload>
                  </Space>
                </Card>
              );
            })}
            {Object.values(files).some(Boolean) && (
              <Form.Item>
                <Checkbox checked={licenseConfirmed} onChange={(event) => setLicenseConfirmed(event.target.checked)}>我确认有权在本系统中使用以上考试资料。</Checkbox>
              </Form.Item>
            )}
            <ErrorBanner message={error} />
            <Flex gap="small" justify="flex-end">
              <Button onClick={() => setEditorOpen(false)}>取消</Button>
              <Button disabled={!draft.questionPaperId && !files.question_paper} htmlType="submit" loading={saving} type="primary">保存试卷</Button>
            </Flex>
          </Form>
        </form>
      </Modal>

      <AppConfirmDialog
        confirmLabel="归档试卷"
        danger
        description="试卷将从管理列表移除；历史作答与评分记录不会删除。"
        onConfirm={() => void confirmArchive()}
        onOpenChange={(open) => { if (!open) setArchiving(null); }}
        open={Boolean(archiving)}
        title={`归档「${archiving?.display_name || archiving?.pair_key || "试卷"}」？`}
      />
    </Space>
  );
}

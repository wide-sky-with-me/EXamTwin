import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Badge,
  Breadcrumb,
  Button,
  Card,
  Col,
  Drawer,
  Flex,
  Layout,
  Menu,
  Result,
  Row,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import {
  BookOpenCheck,
  FileText,
  Files,
  GraduationCap,
  LibraryBig,
  PanelLeftOpen,
  ShieldCheck,
  X,
} from "lucide-react";
import { lazy, type ReactNode, Suspense, useState } from "react";
import {
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
} from "react-router";

import { SubjectWorkspace } from "./components/SubjectWorkspace";
import { ThemeSwitch } from "./components/ThemeSwitch";
import { apiClient, unwrapApi } from "./lib/api";
import type { PlatformStatus, ReviewItem, SubjectStatus } from "./types";

const SubjectManagement = lazy(() => import("./pages/SubjectManagement").then(({ SubjectManagement: Page }) => ({ default: Page })));
const PaperManagement = lazy(() => import("./pages/PaperManagement").then(({ PaperManagement: Page }) => ({ default: Page })));
const PaperAnswering = lazy(() => import("./pages/PaperAnswering").then(({ PaperAnswering: Page }) => ({ default: Page })));
const Grading = lazy(() => import("./pages/Grading").then(({ Grading: Page }) => ({ default: Page })));
const Reviews = lazy(() => import("./pages/Reviews").then(({ Reviews: Page }) => ({ default: Page })));

const { Content } = Layout;
const { Paragraph, Text, Title } = Typography;

type AppMenuItem = {
  key: string;
  icon: ReactNode;
  label: ReactNode;
  path: string;
};

function SidebarNavigation({
  items,
  onClose,
  onNavigate,
  selectedKey,
}: {
  items: AppMenuItem[];
  onClose?: () => void;
  onNavigate: (path: string) => void;
  selectedKey: string;
}) {
  return (
    <div className="flex h-full min-h-0 flex-col px-4 py-5">
      <div className="mb-6 flex items-center justify-between gap-3 px-1">
        <Button
          className="!h-auto !px-2 !py-1.5"
          icon={<span className="flex size-9 items-center justify-center rounded-xl bg-blue-600 text-white shadow-lg shadow-blue-600/20"><LibraryBig size={19} /></span>}
          onClick={() => onNavigate("/subjects")}
          type="text"
        >
          <span className="flex flex-col items-start leading-tight">
            <Text className="!text-[15px]" strong>ExamTwin</Text>
            <Text className="!text-[10px] !tracking-[0.12em]" type="secondary">ASSESSMENT</Text>
          </span>
        </Button>
        {onClose && <Button aria-label="关闭主导航" icon={<X size={18} />} onClick={onClose} shape="circle" type="text" />}
      </div>
      <nav aria-label="主导航" className="min-h-0 flex-1">
        <Menu
          className="app-side-menu"
          items={items.map(({ key, icon, label }) => ({ key, icon, label }))}
          mode="inline"
          onClick={({ key }) => onNavigate(items.find((item) => item.key === key)?.path ?? "/subjects")}
          selectedKeys={[selectedKey]}
        />
      </nav>
      <div className="mt-5 rounded-2xl border border-[var(--app-glass-border)] bg-[var(--app-content-glass)] p-2.5 shadow-sm backdrop-blur-xl">
        <Text className="mb-2 block px-1 !text-[10px] !font-semibold !tracking-[0.12em]" type="secondary">外观</Text>
        <ThemeSwitch />
      </div>
    </div>
  );
}

function subjectOrFirst(subjects: SubjectStatus[], requested?: string) {
  return subjects.find((item) => item.id === requested)?.id ?? subjects[0]?.id ?? "";
}

function encoded(value: string) {
  return encodeURIComponent(value);
}

function SubjectRedirect({ subjects, task }: { subjects: SubjectStatus[]; task: "papers" | "answering" | "grading" }) {
  const subjectId = subjects[0]?.id;
  if (!subjectId) return <Navigate replace to="/subjects" />;
  return <Navigate replace to={`/subjects/${encoded(subjectId)}/${task}`} />;
}

function SubjectOverview({ subjects }: { subjects: SubjectStatus[] }) {
  const navigate = useNavigate();
  const { subjectId = "" } = useParams();
  const subject = subjects.find((item) => item.id === subjectId);
  if (!subject) {
    return <Result status="404" title="科目不存在" subTitle="该 URL 中的科目标识无效或科目已被删除。" extra={<Button onClick={() => navigate("/subjects")} type="primary">返回科目列表</Button>} />;
  }
  const base = `/subjects/${encoded(subject.id)}`;
  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Breadcrumb items={[{ title: "科目" }, { title: subject.title }]} />
      <Flex align="center" justify="space-between" wrap gap="middle">
        <Space direction="vertical" size={0}>
          <Space wrap>
            <Tag color="blue">{subject.subject_code}</Tag>
            <Text type="secondary">{subject.board_name}</Text>
          </Space>
          <Title level={2} style={{ margin: 0 }}>{subject.title}</Title>
          <Paragraph type="secondary">科目资料、知识库、试卷、作答与评分的统一入口。</Paragraph>
        </Space>
        <Button onClick={() => navigate(`${base}/papers`)} size="large" type="primary">进入试卷库</Button>
      </Flex>
      <Row gutter={[16, 16]}>
        <Col lg={8} md={12} xs={24}>
          <Card actions={[<Button key="documents" onClick={() => navigate(`${base}/documents`)} type="link">管理资料</Button>]}>
            <Card.Meta avatar={<Files size={24} />} title="资料库" description="大纲、教材、Question Paper、Mark Scheme 与 Source Booklet。" />
          </Card>
        </Col>
        <Col lg={8} md={12} xs={24}>
          <Card actions={[<Button key="knowledge" onClick={() => navigate(`${base}/knowledge`)} type="link">查看知识库</Button>]}>
            <Card.Meta avatar={<LibraryBig size={24} />} title="知识库" description="维护授权资料并构建当前科目的可检索知识版本。" />
          </Card>
        </Col>
        <Col lg={8} md={12} xs={24}>
          <Card actions={[<Button key="papers" onClick={() => navigate(`${base}/papers`)} type="link">打开试卷库</Button>]}>
            <Card.Meta avatar={<FileText size={24} />} title="试卷库" description="管理严格配对的试卷、评分标准和支撑材料。" />
          </Card>
        </Col>
        <Col lg={8} md={12} xs={24}>
          <Card actions={[<Button key="answering" onClick={() => navigate(`${base}/answering`)} type="link">进入作答</Button>]}>
            <Card.Meta avatar={<GraduationCap size={24} />} title="作答任务" description="上传试卷或继续该科目已有的作答任务。" />
          </Card>
        </Col>
        <Col lg={8} md={12} xs={24}>
          <Card actions={[<Button key="grading" onClick={() => navigate(`${base}/grading`)} type="link">进入评分</Button>]}>
            <Card.Meta avatar={<BookOpenCheck size={24} />} title="评分任务" description="绑定评分标准，逐题判分并进入人工复核。" />
          </Card>
        </Col>
      </Row>
    </Space>
  );
}

function SubjectWorkspaceRoute({ subjects, refresh, view }: { subjects: SubjectStatus[]; refresh: () => Promise<void>; view: "documents" | "knowledge" }) {
  const navigate = useNavigate();
  const { subjectId = "" } = useParams();
  const subject = subjects.find((item) => item.id === subjectId);
  if (!subject) return <Result status="404" title="科目不存在" extra={<Button onClick={() => navigate("/subjects")}>返回科目列表</Button>} />;
  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Breadcrumb items={[{ title: <Button onClick={() => navigate("/subjects")} type="link">科目</Button> }, { title: <Button onClick={() => navigate(`/subjects/${encoded(subject.id)}`)} type="link">{subject.title}</Button> }, { title: view === "documents" ? "资料库" : "知识库" }]} />
      <Title level={2}>{view === "documents" ? "资料库" : "知识库"}</Title>
      <SubjectWorkspace onChanged={refresh} subject={subject} view={view} />
    </Space>
  );
}

function PaperRoute({ subjects }: { subjects: SubjectStatus[] }) {
  const navigate = useNavigate();
  const params = useParams();
  const selectedSubjectId = subjectOrFirst(subjects, params.subjectId);
  if (!selectedSubjectId) return <Result title="尚未创建科目" subTitle="创建科目后才能管理试卷。" />;
  const jobId = params.jobId ?? "";
  const detail = params.documentId
    ? { kind: "document" as const, id: params.documentId, parentPaperId: params.paperUnitId }
    : params.paperUnitId && jobId
      ? { kind: "job" as const, id: jobId }
      : params.paperUnitId
        ? { kind: "paper" as const, id: params.paperUnitId }
        : null;
  return <PaperManagement
    detail={detail}
    onBackDocument={(subjectId, paperUnitId) => navigate(paperUnitId ? `/subjects/${encoded(subjectId)}/papers/${encoded(paperUnitId)}` : `/subjects/${encoded(subjectId)}/papers`)}
    onCloseDetail={(subjectId) => navigate(detail?.kind === "document" && detail.parentPaperId ? `/subjects/${encoded(subjectId)}/papers/${encoded(detail.parentPaperId)}` : `/subjects/${encoded(subjectId)}/papers`)}
    onOpenDocument={(subjectId, documentId, paperUnitId) => navigate(paperUnitId ? `/subjects/${encoded(subjectId)}/papers/${encoded(paperUnitId)}/documents/${encoded(documentId)}` : `/subjects/${encoded(subjectId)}/documents/${encoded(documentId)}`)}
    onOpenJob={(subjectId, paperUnitId, nextJobId) => navigate(`/subjects/${encoded(subjectId)}/papers/${encoded(paperUnitId)}/jobs/${encoded(nextJobId)}`)}
    onOpenPaper={(subjectId, paperUnitId) => navigate(`/subjects/${encoded(subjectId)}/papers/${encoded(paperUnitId)}`)}
    onStartAnswering={(subjectId, paperUnitId, nextJobId) => navigate(`/subjects/${encoded(subjectId)}/papers/${encoded(paperUnitId)}/jobs/${encoded(nextJobId)}/answering`)}
    onStartGrading={(subjectId, paperUnitId) => navigate(`/subjects/${encoded(subjectId)}/papers/${encoded(paperUnitId)}/grading`)}
    onSubjectChange={(subjectId) => navigate(`/subjects/${encoded(subjectId)}/papers`)}
    subjectId={selectedSubjectId}
    subjects={subjects}
  />;
}

function AnsweringRoute({ subjects }: { subjects: SubjectStatus[] }) {
  const params = useParams();
  const subjectId = subjectOrFirst(subjects, params.subjectId);
  const subject = subjects.find((item) => item.id === subjectId);
  if (!subject) return <Result status="404" title="科目不存在" />;
  return <PaperAnswering enabled={subject.answering_enabled} initialJobId={params.jobId} initialSubjectId={subject.id} subjects={subjects} />;
}

function GradingRoute({ subjects, onCreated }: { subjects: SubjectStatus[]; onCreated: () => Promise<void> }) {
  const params = useParams();
  const subjectId = subjectOrFirst(subjects, params.subjectId);
  if (!subjectId) return <Result status="404" title="科目不存在" />;
  return <Grading initialPaperUnitId={params.paperUnitId} initialSubjectId={subjectId} onCreated={onCreated} subjects={subjects} />;
}

function ReviewRoute({ items, refresh }: { items: ReviewItem[]; refresh: () => Promise<void> }) {
  const { assessmentId } = useParams();
  const visibleItems = assessmentId ? items.filter((item) => item.id === assessmentId) : items;
  if (assessmentId && visibleItems.length === 0) return <Result status="404" title="复核项不存在" />;
  return <Reviews items={visibleItems} refresh={refresh} />;
}

function selectedMenuKey(pathname: string) {
  if (pathname.startsWith("/reviews")) return "reviews";
  if (pathname.includes("/grading")) return "grading";
  if (pathname.includes("/answering")) return "answering";
  if (pathname.includes("/papers") || pathname.includes("/documents/")) return "papers";
  return "subjects";
}

export default function App() {
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const [mobileNavigationOpen, setMobileNavigationOpen] = useState(false);
  const platformQuery = useQuery({
    queryKey: ["platform", "subjects"],
    queryFn: () => unwrapApi(apiClient.GET("/api/v1/subjects/status")),
  });
  const reviewsQuery = useQuery({
    queryKey: ["reviews", "pending"],
    queryFn: () => unwrapApi(apiClient.GET("/api/v1/grading/reviews/all")),
  });
  const platform = platformQuery.data as PlatformStatus | undefined;
  const reviews = (reviewsQuery.data ?? []) as ReviewItem[];
  const subjects = platform?.subjects ?? [];
  const currentSubjectId = location.pathname.match(/^\/subjects\/([^/]+)/)?.[1];
  const navSubjectId = subjectOrFirst(subjects, currentSubjectId ? decodeURIComponent(currentSubjectId) : undefined);
  const subjectBase = navSubjectId ? `/subjects/${encoded(navSubjectId)}` : "/subjects";
  const refreshSubjects = async () => {
    await queryClient.invalidateQueries({ queryKey: ["platform", "subjects"] });
  };
  const refreshReviews = async () => {
    await queryClient.invalidateQueries({ queryKey: ["reviews", "pending"] });
  };
  const loading = platformQuery.isPending;
  const loadError = platformQuery.error ?? reviewsQuery.error;
  const menuItems: AppMenuItem[] = [
    { key: "subjects", icon: <GraduationCap size={17} />, label: "科目", path: "/subjects" },
    { key: "papers", icon: <Files size={17} />, label: "试卷", path: `${subjectBase}/papers` },
    { key: "answering", icon: <FileText size={17} />, label: "作答", path: `${subjectBase}/answering` },
    { key: "grading", icon: <BookOpenCheck size={17} />, label: "评分", path: `${subjectBase}/grading` },
    { key: "reviews", icon: <ShieldCheck size={17} />, label: <Badge count={reviews.length} offset={[10, -3]} size="small">复核</Badge>, path: "/reviews" },
  ];
  const navigateFromSidebar = (path: string) => {
    navigate(path);
    setMobileNavigationOpen(false);
  };
  const selectedKey = selectedMenuKey(location.pathname);

  return (
    <Layout hasSider className="relative min-h-screen overflow-x-clip !bg-[var(--surface-muted)]">
      <div aria-hidden="true" className="pointer-events-none fixed -left-28 -top-32 size-[28rem] rounded-full bg-[var(--app-ambient-one)] blur-3xl" />
      <div aria-hidden="true" className="pointer-events-none fixed -bottom-40 right-[-8rem] size-[32rem] rounded-full bg-[var(--app-ambient-two)] blur-3xl" />
      <aside aria-label="应用侧边栏" className="sticky top-0 z-20 hidden h-screen w-64 shrink-0 border-r border-[var(--app-glass-border)] bg-[var(--app-glass)] shadow-[var(--app-glass-shadow)] backdrop-blur-2xl lg:block">
        <SidebarNavigation items={menuItems} onNavigate={navigateFromSidebar} selectedKey={selectedKey} />
      </aside>
      <Drawer
        className="app-mobile-drawer"
        closable={false}
        onClose={() => setMobileNavigationOpen(false)}
        open={mobileNavigationOpen}
        placement="left"
        rootClassName="lg:!hidden"
        size={272}
        styles={{ body: { padding: 0 } }}
      >
        <div className="h-full border-r border-[var(--app-glass-border)] bg-[var(--app-glass-strong)] shadow-[var(--app-glass-shadow)] backdrop-blur-2xl">
          <SidebarNavigation items={menuItems} onClose={() => setMobileNavigationOpen(false)} onNavigate={navigateFromSidebar} selectedKey={selectedKey} />
        </div>
      </Drawer>
      <Layout className="relative min-w-0 !bg-transparent">
        <header className="sticky top-0 z-10 flex h-16 items-center gap-3 border-b border-[var(--app-glass-border)] bg-[var(--app-glass)] px-4 shadow-sm backdrop-blur-xl lg:hidden">
          <Button aria-label="打开主导航" icon={<PanelLeftOpen size={19} />} onClick={() => setMobileNavigationOpen(true)} shape="circle" size="large" type="text" />
          <span className="flex size-8 items-center justify-center rounded-xl bg-blue-600 text-white shadow-md shadow-blue-600/20"><LibraryBig size={17} /></span>
          <Text strong>ExamTwin</Text>
        </header>
        <Content className="app-page-content w-full p-3 sm:p-4 lg:p-5">
          <div className="app-page-shell min-h-[calc(100vh-2.5rem)]">
            {loadError && <Alert closable message={loadError instanceof Error ? loadError.message : "数据加载失败"} showIcon type="error" />}
            <Suspense fallback={<Flex align="center" justify="center" style={{ minHeight: 320 }}><Spin description="正在加载" size="large" /></Flex>}>
              <Routes>
            <Route element={<Navigate replace to="/subjects" />} path="/" />
            <Route element={<SubjectManagement loading={loading} refresh={refreshSubjects} subjects={subjects} />} path="/subjects" />
            <Route element={<SubjectOverview subjects={subjects} />} path="/subjects/:subjectId" />
            <Route element={<SubjectWorkspaceRoute refresh={refreshSubjects} subjects={subjects} view="documents" />} path="/subjects/:subjectId/documents" />
            <Route element={<SubjectWorkspaceRoute refresh={refreshSubjects} subjects={subjects} view="knowledge" />} path="/subjects/:subjectId/knowledge" />
            <Route element={<SubjectRedirect subjects={subjects} task="papers" />} path="/papers" />
            <Route element={<PaperRoute subjects={subjects} />} path="/subjects/:subjectId/papers" />
            <Route element={<PaperRoute subjects={subjects} />} path="/subjects/:subjectId/papers/:paperUnitId" />
            <Route element={<PaperRoute subjects={subjects} />} path="/subjects/:subjectId/papers/:paperUnitId/documents/:documentId" />
            <Route element={<PaperRoute subjects={subjects} />} path="/subjects/:subjectId/documents/:documentId" />
            <Route element={<SubjectRedirect subjects={subjects} task="answering" />} path="/answering" />
            <Route element={<AnsweringRoute subjects={subjects} />} path="/subjects/:subjectId/answering" />
            <Route element={<PaperRoute subjects={subjects} />} path="/subjects/:subjectId/papers/:paperUnitId/jobs/:jobId" />
            <Route element={<AnsweringRoute subjects={subjects} />} path="/subjects/:subjectId/papers/:paperUnitId/jobs/:jobId/answering" />
            <Route element={<SubjectRedirect subjects={subjects} task="grading" />} path="/grading" />
            <Route element={<GradingRoute onCreated={refreshReviews} subjects={subjects} />} path="/subjects/:subjectId/grading" />
            <Route element={<GradingRoute onCreated={refreshReviews} subjects={subjects} />} path="/subjects/:subjectId/papers/:paperUnitId/grading" />
            <Route element={<ReviewRoute items={reviews} refresh={refreshReviews} />} path="/reviews" />
            <Route element={<ReviewRoute items={reviews} refresh={refreshReviews} />} path="/reviews/:assessmentId" />
            <Route element={<Navigate replace to="/subjects" />} path="*" />
              </Routes>
            </Suspense>
          </div>
        </Content>
      </Layout>
    </Layout>
  );
}
